import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from bidscout_crawler.notify import main, render_message, window_bounds


def test_noon_window_is_previous_evening_to_noon():
    now = datetime(2026, 7, 20, 14, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    start, end = window_bounds("noon", now)
    assert start.isoformat() == "2026-07-19T19:00:00+08:00"
    assert end.isoformat() == "2026-07-20T12:00:00+08:00"


def test_evening_window_is_noon_to_evening():
    now = datetime(2026, 7, 20, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    start, end = window_bounds("evening", now)
    assert start.isoformat() == "2026-07-20T12:00:00+08:00"
    assert end.isoformat() == "2026-07-20T19:00:00+08:00"


def test_message_includes_time_source_and_original_url():
    start = datetime(2026, 7, 19, 19, tzinfo=ZoneInfo("Asia/Shanghai"))
    end = datetime(2026, 7, 20, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    message = render_message("noon", start, end, [{
        "title": "某采购公告", "source_id": "source-a",
        "final_url": "https://example.com/notice/1",
        "classification": "procurement_notice",
    }], "https://bidscout.futurescience.technology/")
    assert "数据窗口" in message
    assert "source-a" in message
    assert "https://example.com/notice/1" in message


def test_skip_empty_does_not_send_or_require_webhook(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(sys, "argv", [
        "bidscout-notify",
        "--period", "noon",
        "--data-dir", str(tmp_path),
        "--skip-empty",
    ])
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)

    main()

    result = json.loads(capsys.readouterr().out)
    assert result == {
        "period": "noon",
        "notices": 0,
        "status": "skipped",
        "reason": "no_new_notices",
    }


def test_display_test_is_clearly_labelled():
    start = datetime(2026, 7, 11, 12, tzinfo=ZoneInfo("Asia/Shanghai"))
    message = render_message("noon", start, start, [], "https://example.com", "｜显示测试")
    assert "显示测试" in message.splitlines()[0]
