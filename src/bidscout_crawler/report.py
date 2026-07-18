from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

CLASS_LABELS = {
    "procurement_notice": "采购公告",
    "award_or_result_notice": "中标/结果",
    "procurement_change_notice": "采购变更",
    "contract_notice": "合同公告",
    "other_procurement_related": "其他招采相关",
    "not_procurement": "非招采信息",
    "uncertain": "待确认",
}


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _find_data_root(root: Path) -> Path:
    if (root / "documents.jsonl").exists():
        return root
    if (root / "data" / "documents.jsonl").exists():
        return root / "data"
    raise FileNotFoundError(f"documents.jsonl not found under {root}")


def _safe_text_path(data_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if candidate.is_absolute():
        return None
    parts = list(candidate.parts)
    if parts and parts[0] == "data":
        parts = parts[1:]
    resolved = (data_root / Path(*parts)).resolve()
    try:
        resolved.relative_to(data_root.resolve())
    except ValueError:
        return None
    return resolved


def _clean_text(value: str, limit: int = 6000) -> str:
    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def load_documents(data_root: Path) -> list[dict]:
    documents = []
    with (data_root / "documents.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            document = json.loads(line)
            text_path = _safe_text_path(data_root, document.get("text_path"))
            excerpt = ""
            if text_path and text_path.exists():
                excerpt = _clean_text(text_path.read_text(encoding="utf-8", errors="replace"))
            document["excerpt"] = excerpt
            document["class_label"] = CLASS_LABELS.get(document.get("classification"), document.get("classification") or "未分类")
            document["host"] = urlparse(document.get("final_url") or document.get("url") or "").netloc
            documents.append(document)
    documents.sort(key=lambda item: item.get("published_at") or item.get("first_seen_at") or "", reverse=True)
    return documents


def build_payload(data_root: Path, run_id: str = "") -> dict:
    documents = load_documents(data_root)
    last_run = _read_json(data_root / "last-run.json", {"eligible_sources": 0, "results": []})
    results = last_run.get("results") or []
    totals = {key: sum(int(row.get(key, 0) or 0) for row in results) for key in ("checked", "saved", "unchanged", "blocked", "failed")}
    classes = Counter(document.get("classification") or "uncertain" for document in documents)
    methods = Counter("AI" if str(document.get("classification_method", "")).startswith("ai:") else "规则" for document in documents)
    sources = Counter(document.get("source_id") or "unknown" for document in documents)
    review_count = sum(bool(document.get("needs_human_review")) for document in documents)
    generated_at = datetime.now(timezone.utc).isoformat()
    return {
        "meta": {
            "title": "BidScout 招采情报",
            "run_id": str(run_id),
            "generated_at": generated_at,
            "document_count": len(documents),
            "source_count": len(sources),
            "eligible_sources": int(last_run.get("eligible_sources", 0) or 0),
            "review_count": review_count,
        },
        "totals": totals,
        "classes": [{"key": key, "label": CLASS_LABELS.get(key, key), "count": classes.get(key, 0)} for key in CLASS_LABELS],
        "methods": dict(methods),
        "sources": [{"source_id": key, "count": count} for key, count in sources.most_common()],
        "source_results": results,
        "documents": documents,
    }


def render_html(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    run_id = html.escape(payload["meta"].get("run_id") or "最新")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="description" content="BidScout 公开招采信息采集与 AI 分类结果">
  <title>BidScout 招采情报</title>
  <link rel="stylesheet" href="assets/app.css">
</head>
<body>
  <header class="masthead">
    <div class="brand"><span class="brand-mark">B</span><div><strong>BidScout</strong><small>公开招采情报</small></div></div>
    <div class="run-pill">RUN {run_id}</div>
  </header>
  <main>
    <section class="hero">
      <div><p class="eyebrow">PROCUREMENT INTELLIGENCE</p><h1>从公开来源中，<br><span>更早发现招采信号。</span></h1><p class="hero-copy">采集公开页面，保存原始证据，并通过 AI 区分采购公告、中标结果、变更与其他信息。</p></div>
      <div class="hero-stat"><span id="heroCount">0</span><small>累计收录文档</small></div>
    </section>
    <section id="summary" class="summary-grid" aria-label="运行摘要"></section>
    <section class="workspace">
      <aside>
        <div class="panel"><h2>分类</h2><div id="classFilters"></div></div>
        <div class="panel"><h2>采集方式</h2><div id="methodStats"></div></div>
        <div class="panel"><h2>来源运行状态</h2><div id="runStats"></div></div>
      </aside>
      <div class="content">
        <div class="toolbar">
          <label class="search"><span>⌕</span><input id="search" type="search" placeholder="搜索标题、来源、正文或 AI 理由"></label>
          <select id="sourceFilter" aria-label="筛选来源"><option value="">全部来源</option></select>
          <select id="reviewFilter" aria-label="筛选复核状态"><option value="">全部状态</option><option value="review">需要复核</option><option value="ai">AI 分类</option><option value="rules">规则分类</option></select>
        </div>
        <div class="result-head"><div><strong id="resultCount">0</strong> 条结果</div><div id="generatedAt"></div></div>
        <div id="documentList" class="document-list"></div>
        <button id="loadMore" class="load-more" type="button">加载更多</button>
      </div>
    </section>
  </main>
  <footer><span>BidScout · 公开信息聚合</span><span>分类仅供线索发现，请以原始公告为准</span></footer>
  <dialog id="detailDialog"><button class="dialog-close" aria-label="关闭">×</button><div id="dialogContent"></div></dialog>
  <script id="bidscout-data" type="application/json">{data}</script>
  <script src="assets/app.js"></script>
</body>
</html>"""


def build_site(input_dir: Path, output_dir: Path, run_id: str = "") -> dict:
    data_root = _find_data_root(input_dir)
    payload = build_payload(data_root, run_id)
    assets = output_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (output_dir / ".nojekyll").write_text("", encoding="utf-8")
    (output_dir / "index.html").write_text(render_html(payload), encoding="utf-8")
    (output_dir / "data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    template_root = Path(__file__).resolve().parent / "report_assets"
    for name in ("app.css", "app.js"):
        (assets / name).write_text((template_root / name).read_text(encoding="utf-8"), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a static BidScout report")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-id", default="")
    args = parser.parse_args()
    payload = build_site(args.input, args.output, args.run_id)
    print(json.dumps({"documents": payload["meta"]["document_count"], "output": str(args.output), "run_id": args.run_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
