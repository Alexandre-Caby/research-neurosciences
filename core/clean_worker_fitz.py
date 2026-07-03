import os
import pandas as pd
import fitz  # PyMuPDF

# Dynamically resolve root project folder name
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_NAME = os.path.basename(ROOT_DIR)
# Extract suffix (e.g., 'research-neurosciences' -> 'neurosciences')
TOPIC = ROOT_NAME.replace("research-", "") if "research-" in ROOT_NAME else ROOT_NAME

# Standard Server Storage Path Mapping
STORAGE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../storage"))
RAW_DIR = os.path.join(STORAGE_DIR, "1_raw_data")
REG_DIR = os.path.join(STORAGE_DIR, "2_register_data")
EXP_DIR = os.path.join(STORAGE_DIR, "3_exploitable_data")

for folder in [RAW_DIR, REG_DIR, EXP_DIR]:
    os.makedirs(folder, exist_ok=True)

# Automated Dynamic Naming Execution
REGISTRY_FILE = os.path.join(REG_DIR, f"{TOPIC}_registry.csv")

def extract_structural_markdown(pdf_path):
    doc = fitz.open(pdf_path)
    markdown_lines = []
    bibliography_reached = False

    for page in doc:
        if bibliography_reached:
            break

        # "blocks" automatically resolves 2-column reading order via C-libraries
        # Returns: (x0, y0, x1, y1, "text", block_no, block_type)
        blocks = page.get_text("blocks")

        # Sort blocks primarily by vertical position (Y) to maintain reading flow
        blocks.sort(key=lambda b: (b[1], b[0]))

        for block in blocks:
            # block[6] == 0 means it's a text block (1 would be an image)
            if block[6] != 0:
                continue

            text_content = block[4].strip()

            # Global generic bibliography detection trigger
            if any(
                text_content.startswith(x)
                for x in [
                    "References",
                    "REFERENCES",
                    "Bibliography",
                    "BIBLIOGRAPHY",
                ]
            ):
                bibliography_reached = True
                break

            # Basic structural heuristic mapping based on line properties
            if len(text_content) < 100 and text_content.isupper():
                # Treat short uppercase lines as section headers
                markdown_lines.append(f"\n## {text_content}\n")
            else:
                # Standard paragraph line merge
                clean_text = text_content.replace("\n", " ")
                markdown_lines.append(clean_text)

    doc.close()
    return "\n\n".join(markdown_lines)


def execute_clean_worker():
    if not os.path.exists(REGISTRY_FILE):
        print("Error: Registry missing.")
        return

    df = pd.read_csv(REGISTRY_FILE)
    mask = (df["status_retrieved"] == "Success") & (
        df["status_processed"] == "None"
    )
    pending_indices = df[mask].index

    if len(pending_indices) == 0:
        return

    for idx in pending_indices:
        raw_pdf_path = str(df.at[idx, "raw_path"])

        if not os.path.exists(raw_pdf_path):
            df.at[idx, "status_processed"] = "Failure"
            continue

        try:
            # Process via geometric layout extraction
            md_content = extract_structural_markdown(raw_pdf_path)

            if len(md_content.strip()) > 300:
                filename = os.path.basename(raw_pdf_path).replace(
                    ".pdf", ".md"
                )
                output_md_path = os.path.join(EXP_DIR, filename)

                with open(output_md_path, "w", encoding="utf-8") as f:
                    f.write(md_content)

                df.at[idx, "status_processed"] = "Terminated"
                df.at[idx, "processed_path"] = output_md_path
                print(f"Processed: {filename}")
            else:
                df.at[idx, "status_processed"] = "Failure"

        except Exception as e:
            print(f"Extraction error on {raw_pdf_path}: {e}")
            df.at[idx, "status_processed"] = "Failure"

    df.to_csv(REGISTRY_FILE, index=False)


if __name__ == "__main__":
    execute_clean_worker()
