"""Public daily reports, grouped by first discovery in Asia/Shanghai."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .notify import CLASS_LABELS, SHANGHAI, parse_timestamp

PROCUREMENT_CLASSES = set(CLASS_LABELS) - {"not_procurement", "uncertain"}


def yesterday() -> date:
    return datetime.now(SHANGHAI).date() - timedelta(days=1)


def safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme in {"https", "http"} and parts.hostname and not parts.username and not parts.password:
            return value
    except ValueError:
        pass
    return ""


def clean(value, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_daily_payload(documents: list[dict], report_date: date, *, snapshot_updated_at: str = "", eligible_sources: int | None = None, collection_incomplete: bool = False) -> dict:
    start = datetime.combine(report_date, time.min, SHANGHAI)
    end = start + timedelta(days=1)
    notices = []
    seen = set()
    for document in documents:
        discovered = parse_timestamp(document["first_seen_at"])
        if not start <= discovered < end:
            continue
        url = safe_url(document.get("final_url") or document.get("url") or "")
        identity = url or document.get("url") or str(document.get("id"))
        if identity in seen:
            continue
        seen.add(identity)
        classification = document.get("classification") or "uncertain"
        if classification not in CLASS_LABELS:
            classification = "uncertain"
        notices.append({
            "title": clean(document.get("title") or "未命名公告"),
            "source_id": clean(document.get("source_id") or "未知来源", 100),
            "url": url,
            "first_seen_at": discovered.isoformat(),
            "published_at": clean(document.get("published_at"), 50),
            "classification": classification,
            "class_label": CLASS_LABELS[classification],
            "needs_human_review": bool(document.get("needs_human_review")),
            "excerpt": clean(document.get("excerpt")),
        })
    notices.sort(key=lambda item: item["first_seen_at"], reverse=True)
    classes = Counter(item["classification"] for item in notices)
    sources = Counter(item["source_id"] for item in notices)
    if not snapshot_updated_at:
        coverage = {"status": "unknown", "message": "数据快照更新时间未知，无法确认报告日的采集覆盖情况。"}
    elif parse_timestamp(snapshot_updated_at) < end:
        coverage = {"status": "stale", "message": "数据快照尚未更新至报告日结束，采集覆盖不足；零新增不代表当天没有招采公告。"}
    elif eligible_sources == 0:
        coverage = {"status": "no_sources", "message": "最近一次采集没有参与的来源，无法据此判断报告日是否存在新增公告。"}
    elif collection_incomplete:
        coverage = {"status": "partial", "message": "最近一次采集有来源未完成，以下仅汇总已入库信息；零新增不代表当天没有招采公告。"}
    else:
        coverage = {"status": "snapshot_available", "message": "按当前归档统计，结果仅覆盖实际采集来源，不代表所有网站或公告。"}
    return {
        "schema_version": 1,
        "date": report_date.isoformat(),
        "timezone": "Asia/Shanghai",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "count_basis": "first_seen_at",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "snapshot_updated_at": snapshot_updated_at,
        "coverage": coverage,
        "total_count": len(notices),
        "procurement_count": sum(classes[key] for key in PROCUREMENT_CLASSES),
        "uncertain_count": classes["uncertain"],
        "non_procurement_count": classes["not_procurement"],
        "review_count": sum(item["needs_human_review"] for item in notices),
        "source_count": len(sources),
        "classes": [{"key": key, "label": label, "count": classes[key]} for key, label in CLASS_LABELS.items()],
        "sources": [{"source_id": key, "count": count} for key, count in sources.most_common()],
        "notices": notices,
    }


def _page(title: str, body: str) -> str:
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · BidScout</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6fb;color:#17243b;font:16px/1.7 system-ui,sans-serif}}
main{{max-width:1000px;margin:auto;padding:32px 20px 60px}}a{{color:#1559b7;overflow-wrap:anywhere}}
nav{{display:flex;gap:22px;margin-bottom:28px}}h1{{font-size:34px;line-height:1.3;margin-bottom:12px}}h2{{font-size:23px}}
.muted{{color:#56657a}}.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:26px 0}}
.stat,article,.panel{{background:white;border:1px solid #dce3ef;border-radius:12px;padding:20px}}
.stat strong{{display:block;font-size:30px;color:#1559b7}}.notice{{background:#fff5df;border-left:4px solid #b87410;padding:16px 20px;border-radius:6px}}
.coverage{{background:#eaf1fd;border-left:4px solid #1559b7;padding:16px 20px;border-radius:6px}}
article{{margin:14px 0;overflow-wrap:anywhere}}article h3{{margin:8px 0;font-size:20px}}.tag{{font-size:13px;color:#1559b7}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:10px 8px;text-align:left;border-bottom:1px solid #e5eaf3}}
footer{{margin-top:32px;font-size:14px;color:#56657a}}@media(max-width:600px){{h1{{font-size:27px}}main{{padding:20px 14px}}}}
</style></head><body><main><nav><a href="../index.html">全部招采信息</a><a href="index.html">日报归档</a></nav>{body}
<footer>按首次采集时间统计，非公告发布日期；分类与摘录供线索发现，请以原始公告为准。</footer></main></body></html>'''


def render_daily_html(payload: dict) -> str:
    esc = html.escape
    cards = "".join(f'<div class="stat">{label}<strong>{payload[key]}</strong></div>' for label, key in (
        ("新增信息", "total_count"), ("招采相关", "procurement_count"), ("待分类确认", "uncertain_count"),
        ("非招采信息", "non_procurement_count"), ("信息来源", "source_count"),
    ))
    rows = "".join(f'<tr><td>{esc(item["label"])}</td><td>{item["count"]}</td></tr>' for item in payload["classes"])
    notices = []
    for item in payload["notices"]:
        link = f'<a href="{esc(item["url"], quote=True)}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a>' if item["url"] else "原文链接待核验"
        review = " · 需要人工复核" if item["needs_human_review"] else ""
        notices.append(f'''<article><span class="tag">{esc(item['class_label'])}{review}</span>
<h3>{esc(item['title'])}</h3><p class="muted">来源：{esc(item['source_id'])} · 首次采集：{esc(item['first_seen_at'])}</p>
<p>{esc(item['excerpt'])}</p>{link}</article>''')
    if not notices:
        notices.append('<div class="panel">归档中没有该日首次采集的信息。请结合上方数据覆盖说明判断。</div>')
    status_class = "coverage" if payload["coverage"]["status"] == "snapshot_available" else "notice"
    snapshot = esc(payload["snapshot_updated_at"] or "未知")
    body = f'''<p class="tag">BIDSCOUT DAILY REPORT</p><h1>{payload['date']} 招采日报</h1>
<p class="muted">统计范围：{payload['date']} 00:00 至次日 00:00（北京时间）</p>
<div class="{status_class}">{esc(payload['coverage']['message'])}<br>数据快照更新：{snapshot}</div>
<div class="stats">{cards}</div><section class="panel"><h2>公告分类</h2><table><thead><tr><th>分类</th><th>条数</th></tr></thead><tbody>{rows}</tbody></table>
<p class="muted">其中 {payload['review_count']} 条需要人工复核；此数量可能与上方分类重叠。</p></section>
<h2>当日新增信息</h2>{''.join(notices)}'''
    return _page(f"{payload['date']} 招采日报", body)


def write_daily_reports(documents: list[dict], output_dir: Path, *, report_date: date | None = None, snapshot_updated_at: str = "", eligible_sources: int | None = None, collection_incomplete: bool = False) -> dict:
    report_date = report_date or yesterday()
    if report_date > yesterday():
        raise ValueError("Daily reports require a completed Shanghai calendar day")
    first_day = min((parse_timestamp(item["first_seen_at"]).date() for item in documents), default=report_date)
    first_day = min(first_day, report_date)
    # One page per calendar day preserves zero-count days without another data store.
    grouped: dict[date, list[dict]] = {}
    for document in documents:
        grouped.setdefault(parse_timestamp(document["first_seen_at"]).date(), []).append(document)
    destination = output_dir / "daily"
    destination.mkdir(parents=True, exist_ok=True)
    entries = []
    current = first_day
    while current <= report_date:
        payload = build_daily_payload(grouped.get(current, []), current, snapshot_updated_at=snapshot_updated_at, eligible_sources=eligible_sources, collection_incomplete=collection_incomplete)
        (destination / f"{current}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (destination / f"{current}.html").write_text(render_daily_html(payload), encoding="utf-8")
        entries.append({"date": str(current), "total_count": payload["total_count"], "procurement_count": payload["procurement_count"]})
        current += timedelta(days=1)
    rows = "".join(f'<tr><td><a href="{item["date"]}.html">{item["date"]}</a></td><td>{item["total_count"]}</td><td>{item["procurement_count"]}</td></tr>' for item in reversed(entries))
    (destination / "index.html").write_text(_page("招采日报归档", f'<h1>招采日报归档</h1><p class="muted">按北京时间自然日汇总首次采集信息，每天 09:00 更新前一日报告。历史日期根据当前归档回溯。</p><div class="panel"><table><thead><tr><th>日期</th><th>新增信息</th><th>招采相关</th></tr></thead><tbody>{rows}</tbody></table></div>'), encoding="utf-8")
    return payload
