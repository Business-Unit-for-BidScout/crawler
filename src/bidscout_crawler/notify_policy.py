"""Send the independent Shaanxi policy report using this repo's existing bot."""

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone

import httpx
from .notify_daily import GitHubDeliveryStore, MESSAGE_LIMIT, NotificationError, _text, deliver_message, send_wecom

SITE_URL = "https://business-unit-for-enterprise-service.github.io/shaanxi-policy-monitor"
LOCAL_TZ = timezone(timedelta(hours=8))


class ReportNotReady(NotificationError):
    pass


def validate_payload(payload, report_date):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise NotificationError("Invalid policy report date.")
    date.fromisoformat(report_date)
    if (payload.get("schema_version") != 1 or payload.get("report_type") != "shaanxi-policy-daily"
        or payload.get("date") != report_date or payload.get("count_basis") != "discovery_and_changes_on_report_date"
        or payload.get("report_url") != f"{SITE_URL}/daily/{report_date}.html"):
        raise NotificationError("Policy report schema, date or publication URL mismatch.")
    counts = payload.get("counts", {})
    for key in ("discovered", "updated", "baseline", "total", "urgent", "sources", "healthy", "partial", "failed"):
        if type(counts.get(key)) is not int or not 0 <= counts[key] <= 100000:
            raise NotificationError("Invalid policy report counters.")
    if not isinstance(payload.get("policies"), list) or len(payload["policies"]) != counts["total"]:
        raise NotificationError("Policy report records and total disagree.")
    if counts["healthy"] + counts["partial"] + counts["failed"] != counts["sources"]:
        raise NotificationError("Policy source counts disagree.")
    if datetime.fromisoformat(payload["generated_at"]).astimezone(LOCAL_TZ).date().isoformat() != report_date:
        raise NotificationError("Policy snapshot is stale for the requested date.")


def build_message(payload):
    validate_payload(payload, payload["date"])
    c = payload["counts"]
    message = (
        f"**陕西政策日报 · 西安优先 | {payload['date']}**\n"
        f"今日新收录 **{c['discovered']}** 条 · 原文更新 **{c['updated']}** 条\n"
        f"首次建档 {c['baseline']} 条 · 累计 {c['total']} 条\n"
        f"已识别的7天内截止事项 **{c['urgent']}** 条\n"
        f"采集覆盖：{c['healthy']} 个栏目完成，{c['partial']} 个部分完成，{c['failed']} 个失败。\n"
        "新收录按发现时间统计；首次建档包含历史政策。"
    )
    footer = f"\n\n[查看完整政策日报与官方原文]({payload['report_url']})\n仅覆盖已配置栏目；申报条件、截止时点和延期请以官方原文为准。"
    records = sorted(payload["policies"], key=lambda r: (r.get("region") != "西安市", not bool(r.get("changes")), r.get("deadline", {}).get("status") not in {"7天内截止", "今日截止，时点需核实"}))
    count = 0
    for r in records[:5]:
        d = r.get("deadline", {})
        block = f"\n\n{count + 1}. {_text(r['title'], 90)}\n{_text(r['region'], 10)} · {_text(r['category'], 20)} · 发布 {_text(r.get('published_date') or '待核实', 12)}"
        if d.get("status") != "不适用":
            block += f"\n{_text(d.get('status'), 30)} {_text(d.get('date') or '', 12)}"
        if len((message + block + footer).encode("utf-8")) > MESSAGE_LIMIT:
            break
        message += block
        count += 1
    message += footer
    if len(message.encode("utf-8")) > MESSAGE_LIMIT:
        raise NotificationError("Policy message exceeds the WeCom byte limit.")
    return message


def load_published(report_date, get=httpx.get):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise NotificationError("Invalid policy report date.")
    try:
        r = get(f"{SITE_URL}/daily/{report_date}.json", timeout=20, follow_redirects=False, headers={"Cache-Control": "no-cache"})
        if r.status_code == 404:
            raise ReportNotReady("Today's policy report has not been published yet.")
        if r.status_code != 200 or len(r.content) > 10_000_000:
            raise NotificationError("Unable to retrieve the public policy report.")
        payload = r.json()
        validate_payload(payload, report_date)
        page = get(payload["report_url"], timeout=20, follow_redirects=False)
        if page.status_code != 200:
            raise ReportNotReady("The policy report HTML is not yet publicly available.")
        return payload
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
        raise NotificationError("Policy publication verification failed; no report sent.") from None


def deliver(payload, webhook, store, sender=send_wecom):
    return deliver_message(payload["date"], build_message(payload), webhook, store, "wecom-shaanxi-policy", sender)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(LOCAL_TZ).date().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-not-ready", action="store_true")
    args = parser.parse_args(argv)
    try:
        if date.fromisoformat(args.date) != datetime.now(LOCAL_TZ).date():
            raise NotificationError("Only today's policy snapshot may be sent automatically.")
        payload = load_published(args.date)
        if args.dry_run:
            print(build_message(payload))
            return 0
        store = GitHubDeliveryStore(os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", ""))
        result = deliver(payload, os.environ.get("WECOM_WEBHOOK_URL", "").strip(), store)
        print(json.dumps({"date": args.date, "status": result, "product": "shaanxi-policy", "policies": payload["counts"]["total"]}, ensure_ascii=False))
        return 0
    except ReportNotReady as error:
        print(str(error), file=sys.stderr)
        return 0 if args.allow_not_ready else 1
    except NotificationError as error:
        print(f"Policy notification error: {error}", file=sys.stderr)
    except (ValueError, KeyError, TypeError, AttributeError):
        print("Invalid policy report or notification configuration; no automatic resend.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
