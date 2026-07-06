import os
import re
from statistics import median

import pandas as pd
import fitz  # PyMuPDF

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
QUALITY_THRESHOLD = 0.6   # below this score, escalate from fitz to Marker
BOILERPLATE_MIN_PAGES = 4  # only run header/footer dedup on documents with enough pages

# Dynamically resolve root project folder name
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_NAME = os.path.basename(ROOT_DIR)
TOPIC = ROOT_NAME.replace("research-", "") if "research-" in ROOT_NAME else ROOT_NAME

STORAGE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../storage"))
RAW_DIR = os.path.join(STORAGE_DIR, "1_raw_data")
REG_DIR = os.path.join(STORAGE_DIR, "2_register_data")
EXP_DIR = os.path.join(STORAGE_DIR, "3_exploitable_data")

for folder in [RAW_DIR, REG_DIR, EXP_DIR]:
    os.makedirs(folder, exist_ok=True)

REGISTRY_FILE = os.path.join(REG_DIR, f"{TOPIC}_registry.csv")


# ---------------------------------------------------------------------------
# Marker: lazy-loaded, optional
# ---------------------------------------------------------------------------
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
            print("   Warning: marker-pdf not installed. Fallback disabled, keeping fitz output as-is.")
            _marker_state["available"] = False
            return None, None
        print("System: Loading Marker vision models (first use only -- can be slow on CPU)...")
        _marker_state["converter"] = PdfConverter(artifact_dict=create_model_dict())
        _marker_state["text_from_rendered"] = text_from_rendered
    return _marker_state["converter"], _marker_state["text_from_rendered"]


# ---------------------------------------------------------------------------
# Fitz extraction
# ---------------------------------------------------------------------------
def extract_with_fitz(pdf_path):
    doc = fitz.open(pdf_path)
    total_pages = doc.page_count
    pages_blocks = []
    text_counts = {}

    for page in doc:
        page_dict = page.get_text("dict")
        blocks_out = []

        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:  # 0 = text block, 1 = image
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

    # Body font size = median block size across the whole document.
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


# ---------------------------------------------------------------------------
# Quality control
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Adaptive engine selection
# ---------------------------------------------------------------------------
def process_pdf(pdf_path):
    """Try fitz first (cheap, CPU-friendly). Escalate to Marker only if
    quality is insufficient. Returns (markdown_text, engine_used, quality_score)."""
    try:
        fitz_text = extract_with_fitz(pdf_path)
    except Exception as e:
        print(f"   Fitz extraction crashed: {e}")
        fitz_text = ""

    fitz_score, reason = assess_quality(fitz_text)

    if fitz_score >= QUALITY_THRESHOLD:
        return fitz_text, "fitz", fitz_score

    print(f"   Fitz quality insufficient ({reason}, score={fitz_score:.2f}). Escalating to Marker...")
    converter, text_from_rendered = get_marker()
    if converter is None:
        return fitz_text, "fitz", fitz_score

    try:
        rendered = converter(pdf_path)
        marker_text, _, _ = text_from_rendered(rendered)
    except Exception as e:
        print(f"   Marker crashed: {e}")
        return fitz_text, "fitz", fitz_score

    marker_score, _ = assess_quality(marker_text)
    if marker_score > fitz_score:
        return marker_text, "marker", marker_score
    return fitz_text, "fitz", fitz_score


# ---------------------------------------------------------------------------
# Knowledge-base friendly output
# ---------------------------------------------------------------------------
def build_front_matter(df, idx, engine, quality):
    def _get(col, default="N/A"):
        return df.at[idx, col] if col in df.columns else default

    title = str(_get("Titre", "Unknown")).replace('"', "'")
    doi = _get("DOI", "N/A")
    year = _get("Annee", "N/A")
    block = _get("Bloc_Origine", "N/A")

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def execute_clean_worker():
    if not os.path.exists(REGISTRY_FILE):
        print("Error: Registry missing.")
        return

    df = pd.read_csv(REGISTRY_FILE)
    mask = (df["status_retrieved"] == "Success") & (df["status_processed"] == "Pending")
    pending_indices = df[mask].index

    if len(pending_indices) == 0:
        print("System: No pending PDFs to process.")
        return

    print(f"System: {len(pending_indices)} PDFs pending. Adaptive engine ready (fitz first, Marker fallback).")

    for idx in pending_indices:
        raw_pdf_path = str(df.at[idx, "raw_path"])

        if not os.path.exists(raw_pdf_path):
            df.at[idx, "status_processed"] = "Failure"
            continue

        print(f"System: Open and testing layout for -> {os.path.basename(raw_pdf_path)}")
        
        try:
            md_content, engine_used, quality_score = process_pdf(raw_pdf_path)
        except Exception as e:
            print(f"Extraction error on {raw_pdf_path}: {e}")
            df.at[idx, "status_processed"] = "Failure"
            continue

        if len(md_content.strip()) > 300:
            filename = os.path.basename(raw_pdf_path).replace(".pdf", ".md")
            output_md_path = os.path.join(EXP_DIR, filename)
            front_matter = build_front_matter(df, idx, engine_used, quality_score)

            with open(output_md_path, "w", encoding="utf-8") as f:
                f.write(front_matter + md_content)

            df.at[idx, "status_processed"] = "Terminated"
            df.at[idx, "processed_path"] = output_md_path
            df.at[idx, "extraction_engine"] = engine_used
            df.at[idx, "extraction_quality"] = round(quality_score, 2)
            print(f"Processed ({engine_used}, q={quality_score:.2f}): {filename}")
        else:
            df.at[idx, "status_processed"] = "Failure"
            df.at[idx, "extraction_engine"] = engine_used
            df.at[idx, "extraction_quality"] = round(quality_score, 2)

    df.to_csv(REGISTRY_FILE, index=False)


if __name__ == "__main__":
    import faulthandler
    faulthandler.enable()
    execute_clean_worker()