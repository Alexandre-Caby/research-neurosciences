import gc
import os
import argparse
from statistics import median
from concurrent.futures import ProcessPoolExecutor, as_completed

import fitz  # PyMuPDF

from core import config
from core import registry as R
from core.log import get_logger

logger = get_logger(__name__)

BOILERPLATE_MIN_PAGES = 4

_marker_state = {"converter": None, "text_from_rendered": None, "available": True}


def get_marker():
    if not _marker_state["available"]:
        return None, None
    if _marker_state["converter"] is None:
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict
            from marker.output import text_from_rendered
        except ImportError:
            logger.warning("marker-pdf not installed; Marker fallback disabled.")
            _marker_state["available"] = False
            return None, None
        logger.info("Loading Marker vision models (first use only)...")
        _marker_state["converter"] = PdfConverter(artifact_dict=create_model_dict())
        _marker_state["text_from_rendered"] = text_from_rendered
    return _marker_state["converter"], _marker_state["text_from_rendered"]


def extract_with_fitz(pdf_path):
    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    pages_blocks = []
    text_counts = {}

    for page in doc:
        page_dict = page.get_text("dict")
        blocks_out = []

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            lines = block.get("lines", [])
            if not lines:
                continue

            line_texts = []
            max_size = 0.0
            for line in lines:
                spans = line.get("spans", [])
                line_text = "".join(s.get("text", "") for s in spans).strip()
                if not line_text:
                    continue
                line_texts.append(line_text)
                sizes = [s.get("size", 0) for s in spans]
                if sizes:
                    max_size = max(max_size, max(sizes))

            if not line_texts:
                continue

            paragraph = line_texts[0]
            for lt in line_texts[1:]:
                if paragraph.endswith('-') and lt[:1].islower():
                    paragraph = paragraph[:-1] + lt
                else:
                    paragraph += " " + lt

            bbox = block["bbox"]
            blocks_out.append({"text": paragraph, "size": max_size, "y": bbox[1], "x": bbox[0]})
            text_counts[paragraph.lower().strip()] = text_counts.get(paragraph.lower().strip(), 0) + 1

        pages_blocks.append(blocks_out)

    doc.close()

    boilerplate = set()
    if total_pages >= BOILERPLATE_MIN_PAGES:
        threshold = max(2, int(total_pages * 0.4))
        boilerplate = {t for t, c in text_counts.items() if c >= threshold}

    all_sizes = [b["size"] for page in pages_blocks for b in page if b["size"] > 0]
    body_size = median(all_sizes) if all_sizes else 10.0

    markdown_lines = []
    bibliography_reached = False

    for page_blocks in pages_blocks:
        if bibliography_reached:
            break
        page_blocks.sort(key=lambda b: (round(b["y"]), b["x"]))

        for b in page_blocks:
            text = b["text"]
            norm = text.lower().strip()

            if norm in boilerplate:
                continue

            if any(text.startswith(x) for x in ["References", "REFERENCES", "Bibliography", "BIBLIOGRAPHY"]):
                bibliography_reached = True
                break

            if b["size"] >= body_size * 1.15 and len(text) < 120:
                markdown_lines.append(f"\n## {text}\n")
            else:
                markdown_lines.append(text)

    return "\n\n".join(markdown_lines)


def assess_quality(text):
    if not text or len(text.strip()) < 300:
        return 0.0, "too_short"

    length = len(text)
    alnum_ratio = sum(c.isalnum() or c.isspace() for c in text) / length
    lines = [l for l in text.split("\n") if l.strip()]
    avg_line_len = sum(len(l) for l in lines) / max(len(lines), 1)
    short_line_ratio = sum(1 for l in lines if len(l) < 15) / max(len(lines), 1)

    score = 1.0
    reasons = []
    if alnum_ratio < 0.85:
        score -= 0.4
        reasons.append("low_alnum_ratio")
    if avg_line_len < 25:
        score -= 0.3
        reasons.append("short_avg_line")
    if short_line_ratio > 0.4:
        score -= 0.3
        reasons.append("fragmented_lines")

    return max(score, 0.0), (",".join(reasons) if reasons else "ok")


def process_pdf(pdf_path):
    """Try fitz first (cheap, CPU-friendly). Escalate to Marker only if
    quality is insufficient. Returns (markdown_text, engine_used, quality_score)."""
    try:
        fitz_text = extract_with_fitz(pdf_path)
    except Exception as e:
        logger.warning("Fitz extraction crashed on %s: %s", pdf_path, e)
        fitz_text = ""

    fitz_score, reason = assess_quality(fitz_text)

    if fitz_score >= config.QUALITY_THRESHOLD:
        return fitz_text, "fitz", fitz_score

    logger.info("Fitz quality insufficient (%s, score=%.2f). Escalating to Marker...", reason, fitz_score)
    converter, text_from_rendered = get_marker()
    if converter is None:
        return fitz_text, "fitz", fitz_score

    try:
        rendered = converter(pdf_path)
        marker_text, _, _ = text_from_rendered(rendered)
    except Exception as e:
        logger.warning("Marker crashed on %s: %s", pdf_path, e)
        return fitz_text, "fitz", fitz_score

    marker_score, _ = assess_quality(marker_text)
    if marker_score > fitz_score:
        return marker_text, "marker", marker_score
    return fitz_text, "fitz", fitz_score


def build_front_matter(meta, engine, quality):
    title = str(meta.get("title") or "Unknown").replace('"', "'")
    doi = meta.get("doi") or "N/A"
    year = meta.get("year") if meta.get("year") is not None else "N/A"
    block = meta.get("query_block") or "N/A"

    return (
        "---\n"
        f'title: "{title}"\n'
        f'doi: "{doi}"\n'
        f"year: {year}\n"
        f'source_block: "{block}"\n'
        f'extraction_engine: "{engine}"\n'
        f"extraction_quality: {round(quality, 2)}\n"
        "---\n\n"
    )


def _fitz_only(pdf_path):
    """Worker process isolation."""
    try:
        text = extract_with_fitz(pdf_path)
    except Exception as e:
        return "", 0.0, f"fitz_error:{e}"
    score, reason = assess_quality(text)
    return text, score, reason


def run_extract(limit=None, workers=None):
    conn = R.connect(config.DB_PATH)
    papers = [p for p in R.get_by_status(conn, R.FETCHED) if p["raw_path"] and os.path.exists(p["raw_path"])]
    
    if limit:
        papers = papers[:limit]
    if not papers:
        logger.info("No fetched PDFs to extract.")
        return

    logger.info("CAD/Doc Extractor: Extracting %d paper(s)...", len(papers))

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fitz_only, p["raw_path"]): p for p in papers}

        for future in as_completed(futures):
            paper = futures[future]
            paper_id = paper["paper_id"]

            try:
                fitz_text, fitz_score, reason = future.result()
            except Exception as e:
                fitz_text, fitz_score, reason = "", 0.0, f"worker_error:{e}"

            markdown, engine, quality = fitz_text, "fitz", fitz_score

            if fitz_score < config.QUALITY_THRESHOLD:
                logger.info("Fitz quality insufficient for %s (%s, score=%.2f). Escalating to Marker...", paper_id, reason, fitz_score)
                converter, text_from_rendered = get_marker()
                if converter is not None:
                    try:
                        rendered = converter(paper["raw_path"])
                        marker_text, _, _ = text_from_rendered(rendered)
                        marker_score, _ = assess_quality(marker_text)
                        if marker_score > fitz_score:
                            markdown, engine, quality = marker_text, "marker", marker_score
                    except Exception as e:
                        logger.warning("Marker crashed on %s: %s", paper_id, e)
                    finally:
                        gc.collect()
                        if has_torch and torch.cuda.is_available():
                            torch.cuda.empty_cache()

            if len(markdown.strip()) > 300:
                content_hash = R.content_hash(markdown)
                dup_id = R.hash_seen(conn, content_hash)
                
                if dup_id and dup_id != paper_id:
                    R.update_status(conn, paper_id, R.DUPLICATE, content_hash=content_hash)
                    logger.info("Duplicate content (matches %s): %s", dup_id, paper_id)
                else:
                    md_path = os.path.join(config.EXP_DIR, f"{paper_id}.md")
                    front_matter = build_front_matter(dict(paper), engine, quality)
                    
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(front_matter + markdown)
                        
                    R.update_status(
                        conn, paper_id, R.EXTRACTED,
                        md_path=md_path, extraction_engine=engine,
                        extraction_quality=round(quality, 2), content_hash=content_hash
                    )
                    logger.info("Extracted (%s, q=%.2f): %s", engine, quality, paper_id)
            else:
                R.update_status(conn, paper_id, R.FAILED, extraction_engine=engine, extraction_quality=round(quality, 2))
                logger.info("Extraction failed: %s", paper_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    run_extract(limit=args.limit, workers=args.workers)