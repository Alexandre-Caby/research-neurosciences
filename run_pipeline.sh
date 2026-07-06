#!/bin/bash

# Stop execution immediately if any command exits with a non-zero status
set -e

echo "--------------------------------------------------"
echo "🚀 STARTING NEUROSCIENCE RESEARCH DATA PIPELINE"
echo "--------------------------------------------------"

# Step 1: Base Ingestion Engine (Phase 1)
echo "LOG: Executing Base Ingestion..."
python3 core/ingest.py

# Step 2: Heuristic PDF Text Extraction (Phase 2)
echo "LOG: Running Dynamic Cleaner..."
python3 core/clean_worker.py

# Step 3: Chunking and Vectorization (Phase 3)
echo "LOG: Running Chunk Worker..."
python3 core/chunk_worker.py

# Step 4: Purging (Phase 4)
echo "LOG: Running Purge Worker..."
read -p "Are you sure you want to purge the data? This action cannot be undone. (yes/no): " confirm
if [[ "$confirm" == "yes" ]]; then
    python3 core/purge_worker.py
fi

echo "--------------------------------------------------"
echo "🏁 PIPELINE EXECUTION COMPLETED SUCCESSFULLY"
echo "--------------------------------------------------"