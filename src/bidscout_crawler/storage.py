import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(
 id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, url TEXT NOT NULL UNIQUE, final_url TEXT,
 title TEXT, published_at TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 content_hash TEXT NOT NULL, raw_path TEXT, text_path TEXT, http_status INTEGER, content_type TEXT,
 classification TEXT, confidence REAL, reason TEXT, supporting_quotes TEXT, needs_human_review INTEGER,
 classification_method TEXT, classifier_version TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_class ON documents(classification);
CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id);
"""

def now(): return datetime.now(timezone.utc).isoformat()
def sha256(data): return hashlib.sha256(data).hexdigest()

class Storage:
    def __init__(self, root="data"):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "raw").mkdir(exist_ok=True); (self.root / "text").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "bidscout.sqlite3")
        self.db.executescript(SCHEMA)
    def seen_hash(self, url):
        row = self.db.execute("SELECT content_hash FROM documents WHERE url=?", (url,)).fetchone()
        return row[0] if row else None
    def save(self, source_id, url, final_url, title, published_at, raw, text, status, content_type, classification, version="0.1.0"):
        digest = sha256(raw); timestamp = now(); key = hashlib.sha256(url.encode()).hexdigest()
        raw_path = self.root / "raw" / f"{key}.bin"; text_path = self.root / "text" / f"{key}.txt"
        raw_path.write_bytes(raw); text_path.write_text(text, encoding="utf-8")
        c = classification.to_dict()
        self.db.execute("""INSERT INTO documents(source_id,url,final_url,title,published_at,first_seen_at,last_seen_at,content_hash,raw_path,text_path,http_status,content_type,classification,confidence,reason,supporting_quotes,needs_human_review,classification_method,classifier_version)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET final_url=excluded.final_url,title=excluded.title,published_at=excluded.published_at,last_seen_at=excluded.last_seen_at,content_hash=excluded.content_hash,raw_path=excluded.raw_path,text_path=excluded.text_path,http_status=excluded.http_status,content_type=excluded.content_type,classification=excluded.classification,confidence=excluded.confidence,reason=excluded.reason,supporting_quotes=excluded.supporting_quotes,needs_human_review=excluded.needs_human_review,classification_method=excluded.classification_method,classifier_version=excluded.classifier_version""",
        (source_id, url, final_url, title, published_at, timestamp, timestamp, digest, str(raw_path), str(text_path), status, content_type, c["primary_class"], c["confidence"], c["reason"], json.dumps(c["supporting_quotes"], ensure_ascii=False), int(c["needs_human_review"]), c["method"], version))
        self.db.commit(); return digest
    def export_jsonl(self):
        columns = [x[1] for x in self.db.execute("PRAGMA table_info(documents)")]
        with (self.root / "documents.jsonl").open("w", encoding="utf-8") as f:
            for row in self.db.execute("SELECT * FROM documents ORDER BY first_seen_at"):
                d = dict(zip(columns, row)); d["supporting_quotes"] = json.loads(d["supporting_quotes"] or "[]")
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
