from copy import deepcopy
from unittest.mock import Mock
import json

import httpx
import pytest

from bidscout_crawler.notify_daily import NotificationError
from bidscout_crawler.notify_policy import SITE_URL, ReportNotReady, build_message, deliver, load_published, validate_payload

WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=policy-test-only"


def sample():
    return {
        "schema_version": 1, "report_type": "shaanxi-policy-daily", "date": "2026-10-15",
        "count_basis": "discovery_and_changes_on_report_date", "generated_at": "2026-10-15T08:40:00+08:00",
        "report_url": SITE_URL + "/daily/2026-10-15.html",
        "counts": {"total": 1, "discovered": 0, "updated": 0, "baseline": 1, "urgent": 0, "sources": 8, "healthy": 5, "partial": 2, "failed": 1},
        "policies": [{"title": "西安市中小企业数字化改造项目申报通知", "region": "西安市", "category": "申报与征集", "published_date": "2026-09-11", "changes": ["baseline"], "deadline": {"date": "2026-09-25", "status": "已过原文截止日期"}}],
    }


class Store:
    def __init__(self):
        self.records = {}
    def get(self, key):
        return self.records.get(key), "sha" if key in self.records else None
    def put(self, key, record, sha=None):
        self.records[key] = deepcopy(record)
        return "sha"


def test_brief_preserves_baseline_failures_and_expiry():
    message = build_message(sample())
    assert "首次建档 1 条" in message and "新收录 **0**" in message
    assert "1 个失败" in message and "已过原文截止日期 2026-09-25" in message
    assert len(message.encode()) <= 4096


def test_policy_delivery_has_independent_receipt_and_duplicate_is_skipped():
    store, sender = Store(), Mock()
    assert deliver(sample(), WEBHOOK, store, sender) == "sent"
    assert deliver(sample(), WEBHOOK, store, sender) == "already_sent"
    assert sender.call_count == 1
    assert next(iter(store.records)).startswith("wecom-shaanxi-policy/")
    assert WEBHOOK not in json.dumps(store.records)


def test_ambiguous_delivery_stays_reserved():
    store, sender = Store(), Mock(side_effect=NotificationError("uncertain"))
    with pytest.raises(NotificationError):
        deliver(sample(), WEBHOOK, store, sender)
    with pytest.raises(NotificationError, match="earlier delivery"):
        deliver(sample(), WEBHOOK, store, sender)
    assert sender.call_count == 1


def test_reject_stale_snapshot_and_untrusted_report_link():
    p = sample()
    p["generated_at"] = "2026-10-14T08:40:00+08:00"
    with pytest.raises(NotificationError, match="stale"):
        validate_payload(p, p["date"])
    p = sample()
    p["report_url"] = "https://untrusted.example/"
    with pytest.raises(NotificationError):
        build_message(p)


def test_publication_verifies_json_and_html_and_does_not_use_yesterday():
    get = Mock(side_effect=[httpx.Response(200, json=sample()), httpx.Response(200, text="published")])
    assert load_published("2026-10-15", get) == sample()
    assert get.call_count == 2
    with pytest.raises(ReportNotReady):
        load_published("2026-10-15", Mock(return_value=httpx.Response(404)))


def test_markdown_and_multibyte_size_bound():
    p = sample()
    p["policies"] *= 30
    p["counts"]["total"] = 30
    p["policies"][0]["title"] = '<@all> [fake](https://evil.example) ' + '中文政策' * 500
    message = build_message(p)
    assert '<@all>' not in message and '[fake]' not in message
    assert len(message.encode()) <= 4096
