import os
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

# Automated Dynamic Naming Execution
REGISTRY_FILE = os.path.join(REG_DIR, f"{TOPIC}_registry.csv")

def execute_purge(registry_csv):
    if not os.path.exists(registry_csv):
        print(f"Error: Registry not found at {registry_csv}")
        return

    df = pd.read_csv(registry_csv)

    # Initialize required tracking columns if missing
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

    # Strict binary filtering mask
    mask = (
        (df["status_retrieved"] == "Success")
        & (df["status_processed"] == "Terminated")
        & (df["status_raw"] != "Purged")
    )

    # Core execution loop
    for idx in df[mask].index:
        r_path = str(df.at[idx, "raw_path"])
        p_path = str(df.at[idx, "processed_path"])

        # Compressed physical validation (File integrity check)
        if (
            os.path.exists(r_path)
            and os.path.exists(p_path)
            and os.path.getsize(p_path) > 200
        ):
            try:
                os.remove(r_path)
                df.at[idx, "status_raw"] = "Purged"
                df.at[idx, "raw_path"] = "None"
                print(f"Purged: {r_path}")
            except Exception as e:
                print(f"OS Error on {r_path}: {e}")

    df.to_csv(registry_csv, index=False)


if __name__ == "__main__":
    execute_purge(REGISTRY_FILE)
