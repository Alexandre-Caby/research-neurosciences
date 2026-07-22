"""Splits extracted markdown into overlapping word-window chunks for embedding."""
import argparse
import json
import os
import re

from core import config
from core import registry as R
from core.log import get_logger

logger = get_logger(__name__)


def parse_front_matter(content):
    match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
    if not match:
        return {}, content

    yaml_block, body = match.groups()
    metadata = {}
    for line in yaml_block.split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip().strip('"')
    return metadata, body


def split_into_sections(body):
    parts = re.split(r'\n##\s+(.+?)\n', body)
    sections = []

    if parts and parts[0].strip():
        sections.append(("Introduction", parts[0].strip()))

    for i in range(1, len(parts), 2):
        heading = parts[i].strip()
        text = parts[i + 1].strip() if i + 1 < len(parts) else ""
        if text:
            sections.append((heading, text))

    if not sections:
        sections = [("Document", body.strip())]

    return sections


def chunk_words(text, size=config.CHUNK_SIZE_WORDS, overlap=config.CHUNK_OVERLAP_WORDS):
    words = text.split()
    if len(words) <= size:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0
    while start < len(words):
        end = start + size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += size - overlap

    if len(chunks) > 1 and len(chunks[-1].split()) < config.MIN_TRAILING_CHUNK_WORDS:
        chunks[-2] = chunks[-2] + " " + chunks[-1]
        chunks.pop()

    return chunks


def build_chunks(body, metadata, doc_stub):
    sections = split_into_sections(body)
    chunks = []

    for sec_idx, (heading, text) in enumerate(sections):
        pieces = chunk_words(text)
        for c_idx, piece in enumerate(pieces):
            chunks.append({
                "chunk_id": f"{doc_stub}__s{sec_idx}_c{c_idx}",
                "paper_id": doc_stub,
                "doi": metadata.get("doi", "N/A"),
                "title": metadata.get("title", "Unknown"),
                "year": metadata.get("year", "N/A"),
                "source_block": metadata.get("source_block", "N/A"),
                "source": metadata.get("source", "N/A"),
                "extraction_quality": metadata.get("extraction_quality", "N/A"),
                "section": heading,
                "section_index": sec_idx,
                "chunk_index": c_idx,
                "word_count": len(piece.split()),
                "text": piece,
            })

    return chunks


def run_chunk(limit=None):
    conn = R.connect(config.DB_PATH)
    papers = R.get_by_status(conn, R.EXTRACTED)
    if limit is not None:
        papers = papers[:limit]

    for row in papers:
        paper_id, md_path = row["paper_id"], row["md_path"]

        if not md_path or not os.path.exists(md_path):
            R.update_status(conn, paper_id, R.EMPTY, error="md_path missing")
            continue

        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()

        metadata, body = parse_front_matter(content)
        if not body.strip():
            R.update_status(conn, paper_id, R.EMPTY, error="empty body")
            continue

        chunks = build_chunks(body, metadata, paper_id)
        if not chunks:
            R.update_status(conn, paper_id, R.EMPTY, error="no chunks produced")
            continue

        chunks_path = os.path.join(config.VECTOR_DIR, f"{paper_id}.json")
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)

        R.update_status(conn, paper_id, R.CHUNKED, chunks_path=chunks_path, num_chunks=len(chunks))
        logger.info("chunked %s (%d chunks)", paper_id, len(chunks))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chunk extracted markdown papers.")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    run_chunk(limit=args.limit)
