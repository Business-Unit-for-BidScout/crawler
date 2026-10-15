import json
from copy import deepcopy
from datetime import date
from unittest.mock import Mock

import httpx
import pytest

from bidscout_crawler.daily import build_daily_payload
from bidscout_crawler.notify_daily import (
    DeliveryRejected, GitHubDeliveryStore, MESSAGE_LIMIT, NotificationError,
    build_message, deliver, main, send_wecom, wait_for_publication,
)

WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-only"


def payload():
    return build_daily_payload([], date(2026, 10, 14), snapshot_updated_at="2026-08-23T11:27:42Z", eligible_sources=0)


class Store:
    def __init__(self):
        self.records = {}
        self.writes = []

    def get(self, key):
        return self.records.get(key), "sha" if key in self.records else None

    def put(self, key, record, sha=None):
        self.records[key] = deepcopy(record)
        self.writes.append(deepcopy(record))
        return "sha"


def test_empty_day_message_includes_coverage_and_dated_report_link():
    message = build_message(payload())
    assert "2026-10-14" in message
    assert "新增信息 **0**" in message
    assert "零新增不代表" in message
    assert "/daily/2026-10-14.html" in message


def test_message_is_utf8_bounded_and_neutralizes_page_markdown():
    documents = [{
        "url": f"https://example.com/{i}", "first_seen_at": "2026-10-14T10:00:00Z",
        "title": "<@all> [点击](evil) " + "中文标题" * 300, "source_id": "来源" * 300,
        "classification": "procurement_notice",
    } for i in range(50)]
    message = build_message(build_daily_payload(documents, date(2026, 10, 14)))
    assert len(message.encode("utf-8")) <= MESSAGE_LIMIT
    assert "<@all>" not in message
    assert "[点击]" not in message
    assert "更多信息" in message
    assert message.endswith("请以原始公告为准。")


def test_duplicate_delivery_is_skipped_even_if_report_is_rebuilt():
    store, sender = Store(), Mock()
    assert deliver(payload(), WEBHOOK, store, sender) == "sent"
    rebuilt = payload()
    rebuilt["generated_at"] = "2026-10-15T05:00:00Z"
    assert deliver(rebuilt, WEBHOOK, store, sender) == "already_sent"
    assert sender.call_count == 1
    assert [x["status"] for x in store.writes] == ["sending", "sent"]
    assert "test-only" not in json.dumps(store.records)
    assert "qyapi" not in json.dumps(store.records)


def test_dates_and_destinations_have_independent_delivery_receipts():
    store, sender = Store(), Mock()
    deliver(payload(), WEBHOOK, store, sender)
    deliver(payload(), WEBHOOK + "-other", store, sender)
    tomorrow = build_daily_payload([], date(2026, 10, 15))
    deliver(tomorrow, WEBHOOK, store, sender)
    assert sender.call_count == 3


def test_timeout_keeps_reservation_and_prevents_automatic_resend():
    store = Store()
    sender = Mock(side_effect=NotificationError("uncertain"))
    with pytest.raises(NotificationError, match="uncertain"):
        deliver(payload(), WEBHOOK, store, sender)
    with pytest.raises(NotificationError, match="earlier delivery"):
        deliver(payload(), WEBHOOK, store, sender)
    assert sender.call_count == 1
    assert store.writes[-1]["status"] == "sending"


def test_explicit_rejection_can_be_retried():
    store = Store()
    with pytest.raises(DeliveryRejected):
        deliver(payload(), WEBHOOK, store, Mock(side_effect=DeliveryRejected("rejected")))
    assert store.writes[-1]["status"] == "rejected"
    assert deliver(payload(), WEBHOOK, store, Mock()) == "sent"


def test_ledger_conflict_prevents_sending():
    store = Store()
    store.put = Mock(side_effect=NotificationError("conflict"))
    sender = Mock()
    with pytest.raises(NotificationError):
        deliver(payload(), WEBHOOK, store, sender)
    sender.assert_not_called()


@pytest.mark.parametrize("url", [
    "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-only",
    "https://example.com/cgi-bin/webhook/send?key=test-only",
    WEBHOOK + "&extra=1",
])
def test_invalid_destination_never_receives_a_request(url):
    post = Mock()
    with pytest.raises(NotificationError):
        send_wecom(url, "message", post)
    post.assert_not_called()


def test_http_errors_are_redacted_and_messages_are_not_retried():
    post = Mock(side_effect=httpx.ReadTimeout(WEBHOOK))
    with pytest.raises(NotificationError) as caught:
        send_wecom(WEBHOOK, "message", post)
    assert WEBHOOK not in str(caught.value)
    assert post.call_count == 1


def test_wecom_checks_application_receipt_and_disables_redirects():
    post = Mock(return_value=httpx.Response(200, json={"errcode": 0}))
    send_wecom(WEBHOOK, "message", post)
    assert post.call_args.kwargs["follow_redirects"] is False
    post.return_value = httpx.Response(200, json={"errcode": 93000, "errmsg": WEBHOOK})
    with pytest.raises(DeliveryRejected) as caught:
        send_wecom(WEBHOOK, "message", post)
    assert WEBHOOK not in str(caught.value)


def test_publication_requires_matching_json_and_available_html():
    data = payload()
    get = Mock(side_effect=[httpx.Response(200, json={}), httpx.Response(200, json=data), httpx.Response(200)])
    wait_for_publication(data, get=get, sleep=Mock(), attempts=2)
    get = Mock(return_value=httpx.Response(404))
    with pytest.raises(NotificationError, match="not yet publicly available"):
        wait_for_publication(data, get=get, sleep=Mock(), attempts=1)


def test_dry_run_needs_no_secrets_or_network(tmp_path, monkeypatch, capsys):
    (tmp_path / "daily").mkdir()
    (tmp_path / "daily/2026-10-14.json").write_text(json.dumps(payload()), encoding="utf-8")
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("bidscout_crawler.notify_daily.GitHubDeliveryStore", Mock(side_effect=AssertionError("network")))
    assert main(["--public-dir", str(tmp_path), "--date", "2026-10-14", "--dry-run"]) == 0
    assert "BidScout 招采日报" in capsys.readouterr().out


def test_github_ledger_uses_optimistic_file_writes_without_credentials_in_content():
    requests = []
    def handler(request):
        requests.append(request)
        if request.method == "GET" and "/git/ref/heads/" in request.url.path:
            return httpx.Response(200, json={"object": {"sha": "head"}})
        if request.method == "GET":
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(201, json={"content": {"sha": "new-sha"}})
    store = GitHubDeliveryStore("owner/repo", "test-token", httpx.Client(transport=httpx.MockTransport(handler)))
    assert store.get("wecom-daily/target/2026-10-14") == (None, None)
    assert store.put("wecom-daily/target/2026-10-14", {"date": "2026-10-14", "status": "sent"}, "old-sha") == "new-sha"
    body = json.loads(requests[-1].content)
    assert body["sha"] == "old-sha"
    assert body["branch"] == "notification-state"
    assert "test-token" not in requests[-1].content.decode()
