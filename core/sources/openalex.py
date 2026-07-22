"""OpenAlex discovery source, ported from v1 core/ingest.py."""
import math

import requests

from core import config
from core.log import get_logger

logger = get_logger(__name__)

API_URL = "https://api.openalex.org/works"
REQUEST_TIMEOUT = 20


def _decode_abstract(inverted_index):
    if not inverted_index:
        return ""
    pairs = [(w, p) for w, positions in inverted_index.items() for p in positions]
    return " ".join(w for w, _ in sorted(pairs, key=lambda x: x[1]))


def _record_from_work(work: dict) -> dict:
    ids = dict(work.get("ids") or {})
    ids["doi"] = work.get("doi") or ids.get("doi")
    ids["oa_url"] = (work.get("open_access") or {}).get("oa_url")

    return {
        "openalex_id": str(work["id"]),
        "doi": work.get("doi"),
        "title": work.get("title") or "Untitled Work",
        "year": work.get("publication_year"),
        "abstract": _decode_abstract(work.get("abstract_inverted_index")),
        "landing_url": (work.get("primary_location") or {}).get("landing_page_url"),
        "ids": ids,
    }


def discover(block, query, cursor, per_page=25):
    page = cursor.get("next_page", 1)
    params = {
        "search.title_and_abstract": query,
        "sort": "relevance_score:desc",
        "per_page": per_page,
        "page": page,
        "mailto": config.EMAIL_CONTACT,
    }

    try:
        with requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT) as res:
            res.raise_for_status()
            payload = res.json()
    except Exception as e:
        logger.error("OpenAlex discover failed for block %s: %s", block, e)
        return [], cursor

    records = [_record_from_work(w) for w in payload.get("results", [])]
    count = payload.get("meta", {}).get("count", 0)
    total_pages = math.ceil(count / per_page) if count else 0
    next_page = page + 1 if page < total_pages else 1
    next_cursor = {"next_page": next_page, "total_pages": total_pages}

    return records, next_cursor
