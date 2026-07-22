"""Crossref discovery source. No full text; feeds the resolver cascade."""
import re

import requests

from core import config
from core.log import get_logger

logger = get_logger(__name__)

API_URL = "https://api.crossref.org/works"
REQUEST_TIMEOUT = 20


def _record_from_item(item: dict) -> dict:
    doi = item.get("DOI")
    date_parts = (item.get("published") or {}).get("date-parts") or [[]]
    year = date_parts[0][0] if date_parts and date_parts[0] else None

    abstract = re.sub(r"<[^>]+>", " ", item.get("abstract") or "").strip()

    return {
        "openalex_id": "",
        "doi": doi,
        "title": (item.get("title") or [""])[0],
        "year": year,
        "abstract": abstract,
        "landing_url": item.get("URL"),
        "ids": {"doi": doi},
    }


def discover(block, query, cursor, per_page=25):
    page = cursor.get("next_page", 1)
    params = {
        "query": query,
        "rows": per_page,
        "offset": (page - 1) * per_page,
        "mailto": config.EMAIL_CONTACT,
    }

    try:
        with requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT) as res:
            res.raise_for_status()
            payload = res.json()
    except Exception as e:
        logger.error("Crossref discover failed for block %s: %s", block, e)
        return [], {"next_page": page + 1, "exhausted": True}

    items = (payload.get("message") or {}).get("items", [])
    records = [_record_from_item(i) for i in items]
    next_cursor = {"next_page": page + 1}

    return records, next_cursor
