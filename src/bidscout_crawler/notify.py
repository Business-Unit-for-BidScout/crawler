import argparse
import json
import os
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

SHANGHAI = ZoneInfo("Asia/Shanghai")
WINDOW_LABELS = {
    "noon": "昨晚至今日中午",
    "evening": "今日下午",
}
CLASS_LABELS = {
    "procurement_notice": "采购公告",
    "award_or_result_notice": "中标/结果",
    "procurement_change_notice": "变更公告",
    "contract_notice": "合同公告",
    "other_procurement_related": "其他采购信息",
    "uncertain": "待复核",
    "not_procurement": "非采购信息",
}


def window_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    day = current.date()
    if period == "noon":
        return (
            datetime.combine(day - timedelta(days=1), time(19), SHANGHAI),
            datetime.combine(day, time(12), SHANGHAI),
        )
    if period == "evening":
        return (
            datetime.combine(day, time(12), SHANGHAI),
            datetime.combine(day, time(19), SHANGHAI),
        )
    raise ValueError(f"unsupported period: {period}")


def parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def load_notices(db_path: Path, start: datetime, end: datetime) -> list[dict]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT title, final_url, url, source_id, first_seen_at, classification,
                      confidence, needs_human_review
               FROM documents
               ORDER BY first_seen_at DESC"""
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows if start <= parse_timestamp(row["first_seen_at"]) < end]


def load_latest_notices(db_path: Path, limit: int = 15) -> list[dict]:
    if not db_path.exists():
        return []
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT title, final_url, url, source_id, first_seen_at, classification,
                      confidence, needs_human_review
               FROM documents
               ORDER BY first_seen_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def render_message(period: str, start: datetime, end: datetime, notices: list[dict], report_url: str, test_label: str = "") -> str:
    title = f"【BidScout {WINDOW_LABELS[period]}招采摘要{test_label}】"
    lines = [
        title,
        f"> 数据窗口：{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}（北京时间）",
        f"> 新增信息：{len(notices)} 条",
        "",
    ]
    if notices:
        for index, notice in enumerate(notices[:15], start=1):
            classification = str(notice.get("classification") or "")
            label = CLASS_LABELS.get(classification, classification or "未分类")
            source = notice.get("source_id") or "未知来源"
            url = notice.get("final_url") or notice.get("url") or report_url
            title_text = " ".join((notice.get("title") or "未命名公告").split())
            lines.extend((f"{index}. [{label}] {title_text}", f"   来源：{source} | [原文]({url})"))
        if len(notices) > 15:
            lines.append(f"\n另有 {len(notices) - 15} 条，请查看完整报告。")
    else:
        lines.append("该时段暂未采集到新增招采信息。")
    lines.extend(("", f"[查看完整报告]({report_url})", "建议仅供参考，最终以官方来源及实际招采文件为准。"))
    return "\n".join(lines)


def redact_webhook(webhook: str) -> str:
    parts = urlsplit(webhook)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "key=REDACTED", ""))


def send_message(webhook: str, content: str) -> None:
    response = httpx.post(webhook, json={"msgtype": "markdown", "markdown": {"content": content}}, timeout=20)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(f"WeCom webhook rejected request: {payload}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=sorted(WINDOW_LABELS), required=True)
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--report-url", default="https://bidscout.futurescience.technology/")
    parser.add_argument("--latest-test", action="store_true", help="Send the latest real records as a display test")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    start, end = window_bounds(args.period)
    db_path = Path(args.data_dir) / "bidscout.sqlite3"
    if args.latest_test:
        notices = load_latest_notices(db_path)
        if notices:
            seen = [parse_timestamp(str(item["first_seen_at"])) for item in notices]
            start, end = min(seen), max(seen) + timedelta(microseconds=1)
        message = render_message(args.period, start, end, notices, args.report_url, "｜显示测试")
    else:
        notices = load_notices(db_path, start, end)
        message = render_message(args.period, start, end, notices, args.report_url)
    if args.dry_run:
        print(message)
        return

    webhook = os.environ.get("WECOM_WEBHOOK_URL", "")
    if not webhook:
        raise SystemExit("WECOM_WEBHOOK_URL is required")
    if urlsplit(webhook).netloc != "qyapi.weixin.qq.com":
        raise SystemExit(f"unexpected webhook host: {redact_webhook(webhook)}")
    send_message(webhook, message)
    print(json.dumps({"period": args.period, "notices": len(notices), "status": "sent"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
