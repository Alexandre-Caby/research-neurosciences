"""Batch-encodes chunked papers and upserts their chunk vectors into LanceDB."""
import argparse
import json
import os

from core import config
from core import registry as R
from core.store import LanceStore
from core.log import get_logger

logger = get_logger(__name__)


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _row_to_lance(chunk, paper_row):
    return {
        "chunk_id": chunk["chunk_id"],
        "paper_id": chunk["paper_id"],
        "doi": chunk.get("doi") or "",
        "title": chunk.get("title") or "",
        "year": _to_int(chunk.get("year"), 0),
        "source": paper_row["source"] or "",
        "query_block": chunk.get("source_block") or paper_row["query_block"] or "",
        "section": chunk.get("section") or "",
        "section_index": _to_int(chunk.get("section_index"), 0),
        "chunk_index": _to_int(chunk.get("chunk_index"), 0),
        "word_count": _to_int(chunk.get("word_count"), 0),
        "text": chunk["text"],
        "extraction_quality": _to_float(paper_row["extraction_quality"], 0.0),
    }


def run_embed(text_encoder=None, limit=None) -> None:
    if text_encoder is None:
        from core.encoders import TextEncoder
        text_encoder = TextEncoder()

    conn = R.connect(config.DB_PATH)
    papers = R.get_by_status(conn, R.CHUNKED)
    if limit is not None:
        papers = papers[:limit]

    all_chunks = []
    embedded_paper_ids = []
    for row in papers:
        paper_id, chunks_path = row["paper_id"], row["chunks_path"]

        if not chunks_path or not os.path.exists(chunks_path):
            R.update_status(conn, paper_id, R.EMPTY, error="chunks_path missing")
            continue

        with open(chunks_path, "r", encoding="utf-8") as f:
            chunks = json.load(f)

        if not chunks:
            R.update_status(conn, paper_id, R.EMPTY, error="no chunks in file")
            continue

        for chunk in chunks:
            all_chunks.append(_row_to_lance(chunk, row))
        embedded_paper_ids.append(paper_id)

    if not all_chunks:
        return

    vectors = text_encoder.encode([c["text"] for c in all_chunks])
    for chunk_row, vector in zip(all_chunks, vectors):
        chunk_row["vector"] = vector

    LanceStore(lance_dir=config.LANCE_DIR).upsert(all_chunks)

    for paper_id in embedded_paper_ids:
        R.update_status(conn, paper_id, R.EMBEDDED)
        logger.info("embedded %s", paper_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Embed chunked papers into LanceDB.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run_embed(limit=args.limit)
