"""Shared PDF/HTML candidate cascade, ported from core/ingest.py."""
import re
import time

import requests

from core import config
from core.log import get_logger

logger = get_logger(__name__)

REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF = 2
SECONDARY_API_DELAY = 1.0

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
}


def normalize_doi(doi):
    if not doi or doi == 'N/A':
        return None
    return str(doi).replace("https://doi.org/", "").strip()


def request_with_retry(url, params=None, headers=None, timeout=REQUEST_TIMEOUT):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
        except requests.exceptions.ProxyError as e:
            logger.warning("Proxy error on %s (%s). Skipping retries.", url[:70], e)
            return None
        except requests.RequestException as e:
            last_exc = e
            wait = RETRY_BACKOFF ** attempt
            logger.warning("Network retry %d/%d (%s). Waiting %ds...", attempt, MAX_RETRIES, e, wait)
            time.sleep(wait)
    logger.error("Critical: all retries exhausted for %s (%s)", url[:70], last_exc)
    return None


def direct_candidates(record):
    ids = record.get("ids", {}) or {}
    doi = record.get("doi") or ids.get("doi")
    pmcid = ids.get("pmcid")
    best_url = ids.get("oa_url")

    candidates = []
    if best_url:
        candidates.append(("OpenAlex", best_url))

    doi_clean = normalize_doi(doi)
    if doi_clean:
        m = re.search(r'10\.48550/arxiv\.(.+)', doi_clean, re.IGNORECASE)
        if m:
            candidates.append(("arXiv", f"https://arxiv.org/pdf/{m.group(1)}.pdf"))

    if pmcid:
        candidates.append(("PMC", f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"))
        candidates.append(("PMC_HTML", f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"))

    return candidates


def unpaywall(doi):
    doi_clean = normalize_doi(doi)
    if not doi_clean:
        return None
    res = request_with_retry(
        f"https://api.unpaywall.org/v2/{doi_clean}",
        params={"email": config.EMAIL_CONTACT},
        timeout=10,
    )
    if res is None:
        return None
    with res:
        if res.status_code != 200:
            return None
        try:
            data = res.json()
        except Exception:
            return None
    oa_location = data.get("best_oa_location") or {}
    return oa_location.get("url_for_pdf") or oa_location.get("url")


def semantic_scholar(doi):
    doi_clean = normalize_doi(doi)
    if not doi_clean:
        return None
    res = request_with_retry(
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi_clean}",
        params={"fields": "openAccessPdf"},
        timeout=10,
    )
    time.sleep(SECONDARY_API_DELAY)
    if res is None:
        return None
    with res:
        if res.status_code != 200:
            return None
        try:
            data = res.json()
        except Exception:
            return None
    oa = data.get("openAccessPdf") or {}
    return oa.get("url")


def core(doi):
    if not config.CORE_API_KEY:
        return None
    doi_clean = normalize_doi(doi)
    if not doi_clean:
        return None
    res = request_with_retry(
        "https://api.core.ac.uk/v3/search/works",
        params={"q": f'doi:"{doi_clean}"'},
        headers={"Authorization": f"Bearer {config.CORE_API_KEY}"},
        timeout=15,
    )
    time.sleep(SECONDARY_API_DELAY)
    if res is None:
        return None
    with res:
        if res.status_code != 200:
            return None
        try:
            data = res.json()
        except Exception:
            return None
    results = data.get("results", [])
    if not results:
        return None
    top = results[0]
    return top.get("downloadUrl") or (top.get("sourceFulltextUrls") or [None])[0]


def resolve(record):
    candidates = direct_candidates(record)
    doi = record.get("doi") or (record.get("ids", {}) or {}).get("doi")
    for name, resolver in (
        ("Unpaywall", unpaywall),
        ("SemanticScholar", semantic_scholar),
        ("CORE", core),
    ):
        url = resolver(doi)
        if url:
            candidates.append((name, url))
    return candidates