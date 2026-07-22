"""QC stats over the registry: paper counts by status/source/query_block/engine."""

from core import config
from core import registry as R
from core.log import get_logger

logger = get_logger(__name__)


def _counts(conn, column) -> dict:
    rows = conn.execute(f"SELECT {column}, COUNT(*) AS n FROM papers GROUP BY {column}").fetchall()
    return {row[column]: row["n"] for row in rows}


def run_report(conn=None) -> dict:
    if conn is None:
        conn = R.connect(config.DB_PATH)

    total = conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"]
    by_status = _counts(conn, "status")
    by_source = _counts(conn, "source")
    by_query_block = _counts(conn, "query_block")
    by_engine = _counts(conn, "extraction_engine")
    num_chunks_total = conn.execute(
        "SELECT COALESCE(SUM(num_chunks), 0) AS n FROM papers"
    ).fetchone()["n"]

    out = {
        "total": total,
        "by_status": by_status,
        "by_source": by_source,
        "by_query_block": by_query_block,
        "by_engine": by_engine,
        "num_chunks_total": num_chunks_total,
    }
    logger.info(
        "QC report: total=%d by_status=%s by_source=%s by_query_block=%s by_engine=%s num_chunks_total=%d",
        total, by_status, by_source, by_query_block, by_engine, num_chunks_total,
    )
    return out


if __name__ == "__main__":
    conn = R.connect(config.DB_PATH)
    report = run_report(conn)
    for key, value in report.items():
        if isinstance(value, dict):
            print(key)
            for sub_key, count in value.items():
                print(f"  {sub_key:<20} {count}")
        else:
            print(f"{key:<20} {value}")
