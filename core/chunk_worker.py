import os
import re
import json

import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CHUNK_SIZE_WORDS = 180  
CHUNK_OVERLAP_WORDS = 30
MIN_TRAILING_CHUNK_WORDS = 20  # merge a too-small trailing chunk into the previous one

# Dynamically resolve root project folder name
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_NAME = os.path.basename(ROOT_DIR)
TOPIC = ROOT_NAME.replace("research-", "") if "research-" in ROOT_NAME else ROOT_NAME

STORAGE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../storage"))
REG_DIR = os.path.join(STORAGE_DIR, "2_register_data")
EXP_DIR = os.path.join(STORAGE_DIR, "3_exploitable_data")
VEC_DIR = os.path.join(STORAGE_DIR, "4_vector_data")

for folder in [REG_DIR, EXP_DIR, VEC_DIR]:
    os.makedirs(folder, exist_ok=True)

REGISTRY_PATH = os.path.join(REG_DIR, f"{TOPIC}_registry.csv")


# ---------------------------------------------------------------------------
# Front-matter parsing
# ---------------------------------------------------------------------------
def parse_front_matter(content):
    """Splits the YAML front-matter from the body using a strict anchored
    regex instead of a naive '---' split, which breaks if the body itself
    contains a markdown horizontal rule."""
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


# ---------------------------------------------------------------------------
# Section-aware splitting
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Word-boundary aware sliding window
# ---------------------------------------------------------------------------
def chunk_words(text, chunk_size=CHUNK_SIZE_WORDS, overlap=CHUNK_OVERLAP_WORDS):
    words = text.split()
    if len(words) <= chunk_size:
        return [text.strip()] if text.strip() else []

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start += chunk_size - overlap

    # Avoid a near-empty trailing chunk: merge it into the previous one
    if len(chunks) > 1 and len(chunks[-1].split()) < MIN_TRAILING_CHUNK_WORDS:
        chunks[-2] = chunks[-2] + " " + chunks[-1]
        chunks.pop()

    return chunks


# ---------------------------------------------------------------------------
# Chunk assembly
# ---------------------------------------------------------------------------
def build_chunks_for_document(body, metadata, doc_stub):
    sections = split_into_sections(body)
    chunks = []

    for sec_idx, (heading, text) in enumerate(sections):
        pieces = chunk_words(text)
        total = len(pieces)

        for c_idx, piece in enumerate(pieces):
            chunks.append({
                "chunk_id": f"{doc_stub}__s{sec_idx}_c{c_idx}",
                "doi": metadata.get("doi", "N/A"),
                "title": metadata.get("title", "Unknown"),
                "year": metadata.get("year", "N/A"),
                "source_block": metadata.get("source_block", "N/A"),
                "extraction_engine": metadata.get("extraction_engine", "N/A"),
                "extraction_quality": metadata.get("extraction_quality", "N/A"),
                "section": heading,
                "section_index": sec_idx,
                "chunk_index_in_section": c_idx,
                "total_chunks_in_section": total,
                "word_count": len(piece.split()),
                "text": piece,
            })

    return chunks


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def execute_chunk_worker():
    if not os.path.exists(REGISTRY_PATH):
        print(f"Error: Registry missing at {REGISTRY_PATH}")
        return

    df = pd.read_csv(REGISTRY_PATH)

    if "status_vectorized" not in df.columns:
        df["status_vectorized"] = "None"

    mask = (df["status_processed"] == "Terminated") & (df["status_vectorized"] == "None")
    pending_indices = df[mask].index

    if len(pending_indices) == 0:
        print("System: No new documents to chunk.")
        return

    print(f"System: Chunking {len(pending_indices)} extracted markdown documents...")

    for idx in pending_indices:
        md_path = str(df.at[idx, "processed_path"])

        if not os.path.exists(md_path):
            df.at[idx, "status_vectorized"] = "Failure"
            continue

        try:
            with open(md_path, "r", encoding="utf-8") as f:
                content = f.read()

            metadata, body = parse_front_matter(content)
            if not body.strip():
                df.at[idx, "status_vectorized"] = "Failure"
                continue

            doc_stub = os.path.splitext(os.path.basename(md_path))[0]
            chunks = build_chunks_for_document(body, metadata, doc_stub)

            if not chunks:
                df.at[idx, "status_vectorized"] = "Failure"
                continue

            output_path = os.path.join(VEC_DIR, f"{doc_stub}.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(chunks, f, ensure_ascii=False, indent=2)

            df.at[idx, "status_vectorized"] = "Terminated"
            df.at[idx, "chunked_path"] = output_path
            df.at[idx, "num_chunks"] = len(chunks)

            n_sections = len({c["section"] for c in chunks})
            print(f"Chunked: {doc_stub} ({len(chunks)} chunks across {n_sections} sections)")

        except Exception as e:
            print(f"Chunking error on {md_path}: {e}")
            df.at[idx, "status_vectorized"] = "Failure"

    df.to_csv(REGISTRY_PATH, index=False)


if __name__ == "__main__":
    execute_chunk_worker()