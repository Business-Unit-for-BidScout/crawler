import json
from datetime import date

import pytest

from bidscout_crawler.daily import build_daily_payload, render_daily_html, write_daily_reports


def notice(url, discovered, classification="procurement_notice", **extra):
    return {
        "url": url, "first_seen_at": discovered, "classification": classification,
        "source_id": "hospital", "title": "医疗设备采购公告", **extra,
    }


def test_calendar_day_uses_first_discovery_in_shanghai_and_deduplicates():
    documents = [
        notice("https://example.com/before", "2026-10-13T15:59:59Z"),
        notice("https://example.com/start", "2026-10-13T16:00:00Z", published_at="2020-01-01"),
        notice("https://example.com/end", "2026-10-14T15:59:59Z", "uncertain"),
        notice("https://example.com/end", "2026-10-14T15:59:59Z", "uncertain"),
        notice("https://example.com/next", "2026-10-14T16:00:00Z"),
        notice("https://example.com/other", "2026-10-14T14:00:00+08:00", "not_procurement", source_id="other"),
    ]
    result = build_daily_payload(documents, date(2026, 10, 14))
    assert result["total_count"] == 3
    assert result["procurement_count"] == 1
    assert result["uncertain_count"] == 1
    assert result["non_procurement_count"] == 1
    assert result["source_count"] == 2
    assert result["window_end"] == "2026-10-15T00:00:00+08:00"


@pytest.mark.parametrize("timestamp,eligible,status", [
    ("", None, "unknown"),
    ("2026-08-23T11:27:42Z", 0, "stale"),
    ("2026-10-14T19:00:00+08:00", 3, "stale"),
    ("2026-10-15T02:00:00Z", 0, "no_sources"),
    ("2026-10-15T02:00:00Z", 3, "snapshot_available"),
])
def test_empty_days_distinguish_missing_coverage(timestamp, eligible, status):
    result = build_daily_payload([], date(2026, 10, 14), snapshot_updated_at=timestamp, eligible_sources=eligible)
    assert result["total_count"] == 0
    assert result["coverage"]["status"] == status
    if status == "stale":
        assert "零新增不代表" in result["coverage"]["message"]


def test_daily_export_whitelists_public_fields_and_escapes_page_content():
    result = build_daily_payload([notice(
        "javascript:alert(1)", "2026-10-14T10:00:00+08:00",
        title='<script>alert("page")</script>', excerpt="<img src=x onerror=alert(1)>",
        raw_path="private/raw.bin", text_path="private/text.txt", reason="internal error",
    )], date(2026, 10, 14))
    public = result["notices"][0]
    assert public["url"] == ""
    assert not {"raw_path", "text_path", "reason"} & public.keys()
    page = render_daily_html(result)
    assert "<script>" not in page
    assert "<img src=x" not in page
    assert "javascript:" not in page
    assert "&lt;script&gt;" in page


def test_fresh_snapshot_does_not_hide_source_failures():
    result = build_daily_payload([], date(2026, 10, 14), snapshot_updated_at="2026-10-15T02:00:00Z", eligible_sources=3, collection_incomplete=True)
    assert result["coverage"]["status"] == "partial"
    assert "有来源未完成" in result["coverage"]["message"]


def test_daily_archive_preserves_empty_days_and_creates_yesterday_report(tmp_path, monkeypatch):
    monkeypatch.setattr("bidscout_crawler.daily.yesterday", lambda: date(2026, 10, 14))
    result = write_daily_reports([notice("https://example.com/1", "2026-10-12T10:00:00Z")], tmp_path)
    assert result["date"] == "2026-10-14"
    assert result["total_count"] == 0
    assert json.loads((tmp_path / "daily/2026-10-13.json").read_text(encoding="utf-8"))["total_count"] == 0
    index = (tmp_path / "daily/index.html").read_text(encoding="utf-8")
    assert index.index("2026-10-14.html") < index.index("2026-10-12.html")
    with pytest.raises(ValueError, match="completed"):
        write_daily_reports([], tmp_path, report_date=date(2026, 10, 15))
