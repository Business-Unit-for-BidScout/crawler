import argparse
import json
import os
from pathlib import Path
import yaml
from .crawler import Crawler
from .storage import Storage

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="requirements/knowledge/index/sources.yaml")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--max-sources", type=int, default=int(os.getenv("MAX_SOURCES", "3")))
    parser.add_argument("--max-items", type=int, default=int(os.getenv("MAX_ITEMS_PER_SOURCE", "10")))
    parser.add_argument("--allow-candidates", action="store_true", help="Only for manually dispatched test runs")
    parser.add_argument("--source-id", action="append", default=[])
    args = parser.parse_args()
    with open(args.sources, encoding="utf-8") as f: registry = yaml.safe_load(f)
    selected = []
    for source in registry.get("sources", []):
        eligible = source.get("verification", {}).get("status") == "verified" and source.get("monitoring", {}).get("active") is True
        if args.allow_candidates: eligible = True
        if args.source_id and source.get("id") not in args.source_id: eligible = False
        if eligible and (source.get("access", {}).get("list_urls") or source.get("access", {}).get("homepage_url")): selected.append(source)
    selected = selected[:args.max_sources]
    storage = Storage(args.data_dir)
    crawler = Crawler(storage, os.getenv("CRAWLER_USER_AGENT", "BidScout-Crawler/0.1 (+https://github.com/Business-Unit-for-BidScout/crawler)"), float(os.getenv("CRAWL_DELAY_MIN_SECONDS", "3")), float(os.getenv("CRAWL_DELAY_MAX_SECONDS", "7")))
    results = [crawler.crawl_source(source, args.max_items).__dict__ for source in selected]
    storage.export_jsonl()
    summary = {"eligible_sources": len(selected), "results": results}
    Path(args.data_dir, "last-run.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))

if __name__ == "__main__": main()
