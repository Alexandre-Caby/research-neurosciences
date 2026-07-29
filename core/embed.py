"""Batch-encodes chunked papers into LanceDB with streaming checkpoints and inode cleanup."""

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


MAX_CHUNKS_PER_BATCH = int(os.environ.get("EMBED_MAX_CHUNKS_PER_BATCH", "1500"))


def run_embed(text_encoder=None, limit=None, batch_size=32, purge_chunks_json=True,
              max_chunks_per_batch=MAX_CHUNKS_PER_BATCH) -> None:
    if text_encoder is None:
        from core.encoders import TextEncoder
        text_encoder = TextEncoder()

    conn = R.connect(config.DB_PATH)
    papers = R.get_by_status(conn, R.CHUNKED)

    if limit is not None:
        papers = papers[:limit]
    if not papers:
        logger.info("No chunked papers to embed.")
        return

    store = LanceStore(lance_dir=config.LANCE_DIR)
    logger.info(
        "Embedding %d papers, capped at %d chunks/batch (encoder internal batch_size=%d)...",
        len(papers), max_chunks_per_batch, batch_size,
    )

    batch_chunks: list[dict] = []
    embedded_paper_ids: list[str] = []
    json_paths_to_purge: list[str] = []

    def flush():
        nonlocal batch_chunks, embedded_paper_ids, json_paths_to_purge
        if not batch_chunks:
            return
        vectors = text_encoder.encode([c["text"] for c in batch_chunks], batch_size=batch_size)
        for chunk_row, vector in zip(batch_chunks, vectors):
            chunk_row["vector"] = vector

        store.upsert(batch_chunks)

        for paper_id in embedded_paper_ids:
            R.update_status(conn, paper_id, R.EMBEDDED)
            logger.info("Embedded: %s", paper_id)

        if purge_chunks_json:
            for json_p in json_paths_to_purge:
                try:
                    if os.path.exists(json_p):
                        os.remove(json_p)
                except OSError as e:
                    logger.warning("Failed to purge chunk json %s: %s", json_p, e)

        batch_chunks, embedded_paper_ids, json_paths_to_purge = [], [], []

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

        if batch_chunks and len(batch_chunks) + len(chunks) > max_chunks_per_batch:
            flush()

        for chunk in chunks:
            batch_chunks.append(_row_to_lance(chunk, row))

        embedded_paper_ids.append(paper_id)
        json_paths_to_purge.append(chunks_path)

        if len(batch_chunks) >= max_chunks_per_batch:
            flush()

    flush()  # final partial batch


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Embed chunked papers into LanceDB.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    run_embed(limit=args.limit, batch_size=args.batch_size)