"""Send the published daily report once per WeCom destination and report date."""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

from .daily import PROCUREMENT_CLASSES, clean, yesterday

SITE_URL = "https://bidscout.futurescience.technology"
STATE_BRANCH = "notification-state"
MESSAGE_LIMIT = 4096


class NotificationError(Exception):
    """An operational error that contains no credentials or raw HTTP responses."""


class DeliveryRejected(NotificationError):
    """An explicit rejection is safe to retry on a subsequent manual run."""


def validate_payload(payload, report_date):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", report_date):
        raise NotificationError("Report date must use YYYY-MM-DD.")
    date.fromisoformat(report_date)
    if payload.get("schema_version") != 1 or payload.get("date") != report_date or payload.get("count_basis") != "first_seen_at":
        raise NotificationError("Daily report schema or date does not match.")
    if not isinstance(payload.get("notices"), list) or payload.get("total_count") != len(payload["notices"]):
        raise NotificationError("Daily report count does not match its notices.")
    for key in ("total_count", "procurement_count", "uncertain_count", "non_procurement_count", "source_count", "review_count"):
        if type(payload.get(key)) is not int or payload[key] < 0:
            raise NotificationError("Invalid daily report counters.")


def _text(value, limit=100):
    return clean(value, limit).translate(str.maketrans("<>[]*_`!#&@", "＜＞［］＊＿｀！＃＆＠"))


def build_message(payload):
    validate_payload(payload, payload["date"])
    lines = [
        f"**BidScout 招采日报 | {payload['date']}**",
        f"统计：{payload['date']} 00:00 至次日 00:00（北京时间）",
        f"新增信息 **{payload['total_count']}** 条 · 招采相关 **{payload['procurement_count']}** 条 · {payload['source_count']} 个来源",
        f"待分类确认 {payload['uncertain_count']} 条 · 非招采 {payload['non_procurement_count']} 条 · 需人工复核 {payload['review_count']} 条",
        "",
        "分类：" + ("；".join(f"{_text(item['label'], 20)} {item['count']}" for item in payload["classes"] if item["count"]) or "暂无新增分类记录"),
        "",
        _text(payload["coverage"]["message"], 180),
        "数据快照更新：" + _text(payload["snapshot_updated_at"] or "未知", 60),
    ]
    if not payload["total_count"]:
        lines.append("归档中没有该日首次采集的信息。")
    footer = f"\n\n[查看完整日报与原文]({SITE_URL}/daily/{payload['date']}.html)\n按首次采集时间统计，非公告发布日期；请以原始公告为准。"
    message = "\n".join(lines)
    notices = sorted(payload["notices"], key=lambda item: item["classification"] not in PROCUREMENT_CLASSES)
    included = 0
    for item in notices[:5]:
        block = f"\n\n{included + 1}. [{_text(item['class_label'], 20)}] {_text(item['title'], 110)}\n来源：{_text(item['source_id'], 60)}"
        if len((message + block + "\n更多信息见完整日报。" + footer).encode("utf-8")) > MESSAGE_LIMIT:
            break
        message += block
        included += 1
    if included < len(notices):
        message += "\n更多信息见完整日报。"
    message += footer
    if len(message.encode("utf-8")) > MESSAGE_LIMIT:
        raise NotificationError("Daily brief exceeds WeCom's message limit.")
    return message


def validate_webhook(webhook):
    if not re.fullmatch(r"https://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9_-]{1,128}", webhook):
        raise NotificationError("Set WECOM_WEBHOOK_URL to the official HTTPS group-bot endpoint.")


def send_wecom(webhook, message, post=httpx.post):
    validate_webhook(webhook)
    if len(message.encode("utf-8")) > MESSAGE_LIMIT:
        raise NotificationError("WeCom message exceeds the markdown size limit.")
    try:
        response = post(webhook, json={"msgtype": "markdown", "markdown": {"content": message}}, timeout=20, follow_redirects=False)
        body = response.json()
    except (httpx.HTTPError, ValueError):
        raise NotificationError("WeCom delivery is uncertain; check the group before retrying.") from None
    if response.status_code == 200 and isinstance(body, dict) and type(body.get("errcode")) is int:
        if body["errcode"] == 0:
            return
        if body["errcode"] > 0:
            raise DeliveryRejected(f"WeCom rejected the daily brief (code {body['errcode']}).")
    raise NotificationError("WeCom delivery is uncertain; check the group before retrying.")


class GitHubDeliveryStore:
    """Only dates, delivery status and hashes are written; never webhook URLs."""

    def __init__(self, repository, token, client=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not token:
            raise NotificationError("GITHUB_REPOSITORY and GITHUB_TOKEN are required.")
        self.base = f"https://api.github.com/repos/{repository}"
        self.client = client or httpx.Client(timeout=30, follow_redirects=False)
        self.headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        status, _ = self._api("GET", f"/git/ref/heads/{STATE_BRANCH}", allowed=(200, 404))
        if status == 404:
            _, info = self._api("GET", "")
            _, head = self._api("GET", "/git/ref/heads/" + quote(info["default_branch"], safe=""))
            status, _ = self._api("POST", "/git/refs", {"ref": f"refs/heads/{STATE_BRANCH}", "sha": head["object"]["sha"]}, allowed=(201, 422))
            if status == 422:
                self._api("GET", f"/git/ref/heads/{STATE_BRANCH}")

    def _api(self, method, path, body=None, allowed=(200, 201)):
        try:
            response = self.client.request(method, self.base + path, headers=self.headers, json=body)
            if response.status_code not in allowed:
                raise NotificationError(f"Notification ledger request failed (HTTP {response.status_code}); no automatic resend.")
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError
            return response.status_code, result
        except (httpx.HTTPError, ValueError):
            raise NotificationError("Notification ledger unavailable; no automatic resend.") from None

    def get(self, key):
        status, result = self._api("GET", f"/contents/deliveries/{key}.json?ref={STATE_BRANCH}", allowed=(200, 404))
        if status == 404:
            return None, None
        try:
            record = json.loads(base64.b64decode(result["content"]))
            if record.get("status") not in {"sending", "sent", "rejected"}:
                raise ValueError
            return record, result["sha"]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise NotificationError("Invalid notification ledger; inspect it before retrying.") from None

    def put(self, key, record, sha=None):
        content = base64.b64encode((json.dumps(record, sort_keys=True) + "\n").encode()).decode()
        body = {"message": f"chore: record daily brief delivery {record['date']}", "branch": STATE_BRANCH, "content": content}
        if sha:
            body["sha"] = sha
        _, result = self._api("PUT", f"/contents/deliveries/{key}.json", body)
        try:
            return result["content"]["sha"]
        except (KeyError, TypeError):
            raise NotificationError("Notification ledger write uncertain; no automatic resend.") from None


def deliver(payload, webhook, store, sender=send_wecom):
    return deliver_message(payload["date"], build_message(payload), webhook, store, "wecom-daily", sender)


def deliver_message(report_date, message, webhook, store, namespace, sender=send_wecom):
    """Use independent receipt namespaces for separate daily report products."""
    validate_webhook(webhook)
    if not re.fullmatch(r"[a-z0-9-]+", namespace):
        raise NotificationError("Invalid delivery namespace.")
    date.fromisoformat(report_date)
    target = hashlib.sha256(webhook.encode()).hexdigest()[:24]
    key = f"{namespace}/{target}/{report_date}"
    previous, sha = store.get(key)
    if previous and previous["status"] == "sent":
        return "already_sent"
    if previous and previous["status"] == "sending":
        raise NotificationError("An earlier delivery has no confirmed receipt. Check the group and ledger before retrying.")
    record = {"date": report_date, "status": "sending", "attempted_at": datetime.now(timezone.utc).isoformat(), "content_hash": hashlib.sha256(message.encode()).hexdigest()}
    # Reserve delivery durably before the network request, including on retries.
    sha = store.put(key, record, sha)
    try:
        sender(webhook, message)
    except DeliveryRejected:
        store.put(key, {**record, "status": "rejected"}, sha)
        raise
    store.put(key, {**record, "status": "sent", "sent_at": datetime.now(timezone.utc).isoformat()}, sha)
    return "sent"


def wait_for_publication(payload, get=httpx.get, sleep=time.sleep, attempts=12):
    for attempt in range(attempts):
        try:
            response = get(f"{SITE_URL}/daily/{payload['date']}.json", timeout=10, follow_redirects=False, headers={"Cache-Control": "no-cache"})
            if response.status_code == 200 and response.json() == payload:
                page = get(f"{SITE_URL}/daily/{payload['date']}.html", timeout=10, follow_redirects=False)
                if page.status_code == 200:
                    return
        except (httpx.HTTPError, ValueError):
            pass
        if attempt + 1 < attempts:
            sleep(5)
    raise NotificationError("The matching daily report is not yet publicly available; no message sent.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Preview or send the published BidScout daily report")
    parser.add_argument("--public-dir", type=Path, default=Path("site"))
    parser.add_argument("--date", default=yesterday().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wait-for-publication", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
            raise NotificationError("Report date must use YYYY-MM-DD.")
        payload = json.loads((args.public_dir / "daily" / f"{args.date}.json").read_text(encoding="utf-8"))
        validate_payload(payload, args.date)
        if args.dry_run:
            print(build_message(payload))
            return 0
        if date.fromisoformat(args.date) > yesterday():
            raise NotificationError("Only completed Shanghai calendar days can be delivered.")
        webhook = os.environ.get("WECOM_WEBHOOK_URL", "").strip()
        validate_webhook(webhook)
        if args.wait_for_publication:
            wait_for_publication(payload)
        store = GitHubDeliveryStore(os.environ.get("GITHUB_REPOSITORY", ""), os.environ.get("GITHUB_TOKEN", ""))
        result = deliver(payload, webhook, store)
        print(json.dumps({"date": args.date, "status": result, "notices": payload["total_count"]}, ensure_ascii=False))
        return 0
    except NotificationError as error:
        print(f"Notification error: {error}", file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("Invalid public daily report or notification configuration; no automatic resend.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
