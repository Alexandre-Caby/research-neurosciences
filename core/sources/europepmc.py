"""Europe PMC discovery source."""
import requests

from core import config
from core.log import get_logger

logger = get_logger(__name__)

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
REQUEST_TIMEOUT = 15


def _record_from_result(r: dict) -> dict:
    doi = r.get("doi")
    pmcid = r.get("pmcid")

    oa_url = None
    if r.get("isOpenAccess") == "Y":
        urls = (r.get("fullTextUrlList") or {}).get("fullTextUrl") or []
        for u in urls:
            if u.get("documentStyle") == "pdf":
                oa_url = u.get("url")
                break

    urls = (r.get("fullTextUrlList") or {}).get("fullTextUrl") or []
    landing_url = urls[0].get("url") if urls else (f"https://doi.org/{doi}" if doi else None)

    year = None
    if r.get("pubYear"):
        year = int(r["pubYear"])

    return {
        "openalex_id": "",
        "doi": doi,
        "title": r.get("title"),
        "year": year,
        "abstract": r.get("abstractText", ""),
        "landing_url": landing_url,
        "ids": {"doi": doi, "pmcid": pmcid, "oa_url": oa_url},
    }


def discover(block, query, cursor, per_page=25):
    params = {
        "query": query,
        "format": "json",
        "resultType": "core",
        "pageSize": per_page,
        "cursorMark": cursor.get("cursor", "*"),
        "mailto": config.EMAIL_CONTACT,
        "email": config.EMAIL_CONTACT,
    }
    try:
        with requests.get(SEARCH_URL, params=params, timeout=REQUEST_TIMEOUT) as res:
            res.raise_for_status()
            data = res.json()
    except requests.RequestException as e:
        logger.error("Europe PMC discover failed for block %s: %s", block, e)
        return [], cursor
    except ValueError as e:
        logger.error("Europe PMC invalid JSON for block %s: %s", block, e)
        return [], cursor

    results = (data.get("resultList") or {}).get("result") or []
    records = [_record_from_result(r) for r in results]
    next_cursor = {
        "cursor": data.get("nextCursorMark", cursor.get("cursor", "*")),
        "next_page": cursor.get("next_page", 1) + 1,
    }
    return records, next_cursor
