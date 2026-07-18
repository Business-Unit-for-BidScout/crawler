import json
from pathlib import Path

from bidscout_crawler.report import build_payload, build_site


def sample_data(tmp_path: Path) -> Path:
    data = tmp_path / "input"
    (data / "text").mkdir(parents=True)
    (data / "text" / "one.txt").write_text("医院采购公告正文", encoding="utf-8")
    document = {
        "id": 1,
        "source_id": "hospital",
        "url": "https://example.com/notice/1",
        "final_url": "https://example.com/notice/1",
        "title": "某医院采购公告",
        "published_at": "2026-07-11T00:00:00+00:00",
        "first_seen_at": "2026-07-11T01:00:00+00:00",
        "last_seen_at": "2026-07-11T01:00:00+00:00",
        "text_path": "data/text/one.txt",
        "classification": "procurement_notice",
        "confidence": 0.93,
        "reason": "发现采购公告及响应截止时间",
        "supporting_quotes": ["采购公告"],
        "needs_human_review": 0,
        "classification_method": "ai:test",
    }
    (data / "documents.jsonl").write_text(json.dumps(document, ensure_ascii=False) + "\n", encoding="utf-8")
    (data / "last-run.json").write_text(json.dumps({"eligible_sources": 1, "results": [{"source_id": "hospital", "checked": 1, "saved": 1, "unchanged": 0, "blocked": 0, "failed": 0}]}), encoding="utf-8")
    return data


def test_build_payload_reads_documents_and_text(tmp_path):
    payload = build_payload(sample_data(tmp_path), "123")
    assert payload["meta"]["document_count"] == 1
    assert payload["meta"]["run_id"] == "123"
    assert payload["methods"] == {"AI": 1}
    assert payload["documents"][0]["excerpt"] == "医院采购公告正文"


def test_build_site_writes_static_assets(tmp_path):
    output = tmp_path / "site"
    build_site(sample_data(tmp_path), output, "29156878256")
    assert (output / "index.html").exists()
    assert (output / "assets" / "app.css").exists()
    assert (output / "assets" / "app.js").exists()
    assert (output / ".nojekyll").exists()
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "29156878256" in html
    assert "某医院采购公告" in html
