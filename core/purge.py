"""Deletes raw PDFs from config.RAW_DIR once their extraction has been validated."""
import argparse
import os

from core import config
from core import registry as R
from core.log import get_logger

logger = get_logger(__name__)

_VALIDATED_STATUSES = (R.EXTRACTED, R.CHUNKED, R.EMBEDDED)


def _candidates(conn, min_quality):
    raw_dir = os.path.abspath(config.RAW_DIR)
    to_purge, kept = [], []
    for status in _VALIDATED_STATUSES:
        for row in R.get_by_status(conn, status):
            raw_path = row["raw_path"]
            if not raw_path or not os.path.exists(raw_path):
                continue
            if os.path.dirname(os.path.abspath(raw_path)) != raw_dir:
                continue
            quality = row["extraction_quality"]
            if min_quality is not None and quality is not None and quality < min_quality:
                kept.append(row)
                continue
            to_purge.append(row)
    return to_purge, kept


def run_purge(dry_run=False, assume_yes=False, min_quality=None):
    conn = R.connect(config.DB_PATH)
    to_purge, kept = _candidates(conn, min_quality)

    for row in kept:
        logger.info("Skip (quality %.2f < %.2f, keep raw for reprocessing): %s",
                    row["extraction_quality"], min_quality, row["raw_path"])

    if not to_purge:
        logger.info("Nothing to purge.")
        return 0

    if dry_run:
        total = sum(os.path.getsize(row["raw_path"]) for row in to_purge)
        for row in to_purge:
            size = os.path.getsize(row["raw_path"])
            logger.info("[DRY RUN] Would purge: %s (%.1f KB)", row["raw_path"], size / 1024)
        logger.info("[DRY RUN] %d files, %.1f MB total.", len(to_purge), total / (1024 * 1024))
        return len(to_purge)

    if not assume_yes:
        confirm = input(
            f"Purge {len(to_purge)} raw PDF(s) from {config.RAW_DIR}? "
            "This cannot be undone. (yes/no): "
        )
        if confirm.strip().lower() != "yes":
            logger.info("Purge cancelled.")
            return 0

    purged, freed = 0, 0
    for row in to_purge:
        raw_path = row["raw_path"]
        try:
            size = os.path.getsize(raw_path)
            os.remove(raw_path)
            purged += 1
            freed += size
            logger.info("Purged: %s", raw_path)
        except OSError as e:
            logger.warning("Failed to purge %s: %s", raw_path, e)

    logger.info("Purge complete: %d files removed, %.1f MB freed.", purged, freed / (1024 * 1024))
    return purged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Purge raw PDFs once their extraction is validated.")
    parser.add_argument("--dry-run", action="store_true", help="Preview deletions without removing any file.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    parser.add_argument("--min-quality", type=float, default=None,
                         help="Keep the raw PDF if extraction_quality is below this threshold.")
    args = parser.parse_args()
    run_purge(dry_run=args.dry_run, assume_yes=args.yes, min_quality=args.min_quality)
