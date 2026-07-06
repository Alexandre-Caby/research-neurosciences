import os
import argparse

import pandas as pd

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

REGISTRY_FILE = os.path.join(REG_DIR, f"{TOPIC}_registry.csv")


def execute_purge(registry_csv, dry_run=False, min_quality=None):
    if not os.path.exists(registry_csv):
        print(f"Error: Registry not found at {registry_csv}")
        return

    df = pd.read_csv(registry_csv)

    required_cols = [
        "status_retrieved",
        "status_processed",
        "status_raw",
        "raw_path",
        "processed_path",
    ]
    for col in required_cols:
        if col not in df.columns:
            df[col] = "None"

    mask = (
        (df["status_retrieved"] == "Success")
        & (df["status_processed"] == "Terminated")
        & (df["status_raw"] != "Purged")
        & (df["status_raw"] != "NotApplicable")
    )

    purged_count = 0
    skipped_not_applicable = 0
    total_freed_bytes = 0

    for idx in df[mask].index:
        r_path = str(df.at[idx, "raw_path"])
        p_path = str(df.at[idx, "processed_path"])

        if r_path in ("None", "nan", ""):
            df.at[idx, "status_raw"] = "NotApplicable"
            skipped_not_applicable += 1
            continue

        if not os.path.exists(r_path):
            df.at[idx, "status_raw"] = "Purged"
            continue

        if not os.path.exists(p_path) or os.path.getsize(p_path) <= 200:
            print(f"Skip (missing/suspect markdown, keep raw): {r_path}")
            continue

        if min_quality is not None and "extraction_quality" in df.columns:
            quality = df.at[idx, "extraction_quality"]
            try:
                if pd.notna(quality) and float(quality) < min_quality:
                    print(f"Skip (quality {quality} < {min_quality}, keep raw for reprocessing): {r_path}")
                    continue
            except (TypeError, ValueError):
                pass

        size = os.path.getsize(r_path)

        if dry_run:
            print(f"[DRY RUN] Would purge: {r_path} ({size / 1024:.1f} KB)")
            continue

        try:
            os.remove(r_path)
            df.at[idx, "status_raw"] = "Purged"
            df.at[idx, "raw_path"] = "None"
            total_freed_bytes += size
            purged_count += 1
            print(f"Purged: {r_path}")
        except Exception as e:
            print(f"OS Error on {r_path}: {e}")

    df.to_csv(registry_csv, index=False)

    if not dry_run:
        print(f"\nPurge complete: {purged_count} files removed, {total_freed_bytes / (1024 * 1024):.1f} MB freed.")
        if skipped_not_applicable:
            print(f"{skipped_not_applicable} HTML-sourced records marked as NotApplicable (no raw file expected).")


def parse_args():
    parser = argparse.ArgumentParser(description="Purge raw PDFs once their extraction is validated.")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions without removing any file.")
    parser.add_argument(
        "--min-quality",
        type=float,
        default=None,
        help="Keep the raw PDF if extraction_quality is below this threshold "
             "(requires clean_worker.py's extraction_quality column).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    execute_purge(REGISTRY_FILE, dry_run=args.dry_run, min_quality=args.min_quality)