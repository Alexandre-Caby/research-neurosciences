"""SQLite control plane: paper lifecycle state shared by every source/worker."""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

DISCOVERED = "discovered"
FETCHED = "fetched"
EXTRACTED = "extracted"
CHUNKED = "chunked"
EMBEDDED = "embedded"
PAYWALLED = "paywalled"
EMPTY = "empty"
DUPLICATE = "duplicate"
FAILED = "failed"

_STATUS_FIELDS = (
    "raw_path", "md_path", "chunks_path", "source_used", "extraction_engine",
    "extraction_quality", "num_chunks", "content_hash", "error",
)


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.create_function("canonical_doi", 1, canonical_doi)
    return conn


def init_db(db_path) -> None:
    conn = connect(db_path)
    try:
        with conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    openalex_id TEXT,
                    doi TEXT,
                    title TEXT,
                    year INTEGER,
                    abstract TEXT,
                    source TEXT,
                    query_block TEXT,
                    landing_url TEXT,
                    status TEXT,
                    raw_path TEXT,
                    md_path TEXT,
                    chunks_path TEXT,
                    source_used TEXT,
                    extraction_engine TEXT,
                    extraction_quality REAL,
                    num_chunks INTEGER,
                    content_hash TEXT,
                    error TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS cursors (
                    source TEXT,
                    block TEXT,
                    state TEXT,
                    PRIMARY KEY (source, block)
                )"""
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_content_hash ON papers(content_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_status ON papers(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title)")
    finally:
        conn.close()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_title(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


_DOI_URL_PREFIXES = ("https://doi.org/", "http://dx.doi.org/")


def canonical_doi(doi) -> str | None:
    if not doi or doi == "N/A":
        return None
    s = str(doi).strip()
    for prefix in _DOI_URL_PREFIXES:
        if s.lower().startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.strip().lower()
    return s or None


def upsert_paper(
    conn, paper_id, *, openalex_id=None, doi=None, title=None, year=None,
    abstract=None, source=None, query_block=None, landing_url=None,
    status=DISCOVERED, content_hash=None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        conn.execute(
            """INSERT INTO papers
            (paper_id, openalex_id, doi, title, year, abstract, source, query_block,
             landing_url, status, content_hash, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET
                openalex_id=excluded.openalex_id,
                doi=excluded.doi,
                title=excluded.title,
                year=excluded.year,
                abstract=excluded.abstract,
                source=excluded.source,
                query_block=excluded.query_block,
                landing_url=excluded.landing_url,
                status=excluded.status,
                content_hash=COALESCE(excluded.content_hash, papers.content_hash),
                updated_at=excluded.updated_at""",
            (paper_id, openalex_id, doi, title, year, abstract, source, query_block,
             landing_url, status, content_hash, now, now),
        )


def update_status(conn, paper_id, status, **fields) -> None:
    now = datetime.now(timezone.utc).isoformat()
    cols = ["status = ?", "updated_at = ?"]
    values = [status, now]
    for key in _STATUS_FIELDS:
        if key in fields:
            cols.append(f"{key} = ?")
            values.append(fields[key])
    values.append(paper_id)
    with conn:
        conn.execute(f"UPDATE papers SET {', '.join(cols)} WHERE paper_id = ?", values)


def get_by_status(conn, status) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM papers WHERE status = ?", (status,)).fetchall()


def hash_seen(conn, content_hash) -> str | None:
    if content_hash is None:
        return None
    row = conn.execute(
        "SELECT paper_id FROM papers WHERE content_hash = ?", (content_hash,)
    ).fetchone()
    return row["paper_id"] if row else None


def doi_seen(conn, doi) -> str | None:
    canon = canonical_doi(doi)
    if not canon:
        return None
    # Canonicalize the stored side too: sources persist DOIs in mixed url/bare form.
    row = conn.execute(
        "SELECT paper_id FROM papers WHERE canonical_doi(doi) = ?", (canon,)
    ).fetchone()
    return row["paper_id"] if row else None


def get_status(conn, paper_id) -> str | None:
    row = conn.execute("SELECT status FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    return row["status"] if row else None


def title_seen(conn, title) -> str | None:
    if not title:
        return None
    target = normalize_title(title)
    for row in conn.execute("SELECT paper_id, title FROM papers WHERE title IS NOT NULL"):
        if normalize_title(row["title"]) == target:
            return row["paper_id"]
    return None


def get_cursor(conn, source, block, default=None) -> dict:
    row = conn.execute(
        "SELECT state FROM cursors WHERE source = ? AND block = ?",
        (source, block),
    ).fetchone()
    if row is None or row["state"] is None:
        return default or {}
    return json.loads(row["state"])


def save_cursor(conn, source, block, state: dict) -> None:
    with conn:
        conn.execute(
            """INSERT INTO cursors (source, block, state)
            VALUES (?, ?, ?)
            ON CONFLICT(source, block) DO UPDATE SET
                state=excluded.state""",
            (source, block, json.dumps(state)),
        )
