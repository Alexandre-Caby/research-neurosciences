#!/usr/bin/env bash
set -euo pipefail

if [ -f "$HOME/.venv/bin/activate" ]; then . "$HOME/.venv/bin/activate"; fi

export HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"

SOURCE=""
LIMIT=""
WORKERS=""
PURGE=false
YES=false

while [[ $# -gt 0 ]]; 
do
    case "$1" in
        --source) SOURCE="$2"; shift 2 ;;
        --limit) LIMIT="$2"; shift 2 ;;
        --workers) WORKERS="$2"; shift 2 ;;
        --purge) PURGE=true; shift ;;
        --yes) YES=true; shift ;;
        *) echo "Unknown flag: $1" >&2; exit 1 ;;
    esac
done

banner() {
    echo "--------------------------------------------------"
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $1"
    echo "--------------------------------------------------"
}

ingest_args=()
[[ -n "$SOURCE" ]] && ingest_args+=(--source "$SOURCE")
[[ -n "$LIMIT" ]] && ingest_args+=(--limit "$LIMIT")

banner "ingest"
python -m core.ingest "${ingest_args[@]}"

limit_args=()
[[ -n "$LIMIT" ]] && limit_args+=(--limit "$LIMIT")

extract_args=("${limit_args[@]}")
[[ -n "$WORKERS" ]] && extract_args+=(--workers "$WORKERS")

banner "extract"
python -m core.extract "${extract_args[@]}"

banner "chunk"
python -m core.chunk "${limit_args[@]}"

banner "embed"
python -m core.embed "${limit_args[@]}"

banner "report"
python -m core.report

if [[ "$PURGE" == true ]]; then
    purge_args=()
    [[ "$YES" == true ]] && purge_args+=(--yes)
    banner "purge"
    python -m core.purge "${purge_args[@]}"
fi

banner "pipeline completed, cleaning up run artifacts"
find . -type d -name "__pycache__" -exec rm -rf {} +

echo "--------------------------------------------------"
echo "Pipeline completed successfully."
echo "Metrics:"
python -c "
from core import config
from core import registry as R
from core.report import run_report
conn = R.connect(config.DB_PATH)
report = run_report(conn)
print(f'- Total papers:   {report[\"total\"]}')
print(f'- By status:      {report[\"by_status\"]}')
print(f'- Chunks total:   {report[\"num_chunks_total\"]}')
"
echo "--------------------------------------------------"