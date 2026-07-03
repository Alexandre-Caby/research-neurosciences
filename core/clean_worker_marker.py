import os
import pandas as pd
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from marker.output import text_from_rendered

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

def execute_marker_worker():
    if not os.path.exists(REGISTRY_FILE):
        print(f"Error: Registry missing at {REGISTRY_FILE}")
        return

    df = pd.read_csv(REGISTRY_FILE)
    mask = (df["status_retrieved"] == "Success") & (df["status_processed"] == "None")
    pending_indices = df[mask].index

    if len(pending_indices) == 0:
        print("System: No pending records found for processing.")
        return

    print("System: Instantiating Marker PDF layout models...")
    # Loading up-to-date neural engine architectures
    converter = PdfConverter(artifact_dict=create_model_dict())

    for idx in pending_indices:
        raw_pdf_path = str(df.at[idx, "raw_path"])

        if not os.path.exists(raw_pdf_path):
            df.at[idx, "status_processed"] = "Failure"
            continue

        try:
            # Modern execution pattern: Converter object call returns RenderedDocument
            rendered_doc = converter(raw_pdf_path)
            md_content, _, _ = text_from_rendered(rendered_doc)

            if len(md_content.strip()) > 300:
                filename = os.path.basename(raw_pdf_path).replace(".pdf", ".md")
                output_md_path = os.path.join(EXP_DIR, filename)

                with open(output_md_path, "w", encoding="utf-8") as f:
                    f.write(md_content)

                df.at[idx, "status_processed"] = "Terminated"
                df.at[idx, "processed_path"] = output_md_path
                print(f"Processed (Marker AI): {filename}")
            else:
                df.at[idx, "status_processed"] = "Failure"

        except Exception as e:
            print(f"Marker pipeline crash on {raw_pdf_path}: {e}")
            df.at[idx, "status_processed"] = "Failure"

    df.to_csv(REGISTRY_FILE, index=False)

if __name__ == "__main__":
    execute_marker_worker()
