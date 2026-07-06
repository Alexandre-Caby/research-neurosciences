import os
import time
import re
import math
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import html2text
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
EMAIL_CONTACT = ""

CORE_API_KEY = "" #core.ac.uk API key, optional but recommended for higher rate limits

ITEMS_PER_PAGE = 200
MAX_PAGES_PER_RUN = 5
MAX_WORKERS = 8
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
RETRY_BACKOFF = 2
SECONDARY_API_DELAY = 1.0 

# Dynamically resolve root project folder name
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_NAME = os.path.basename(ROOT_DIR)
TOPIC = ROOT_NAME.replace("research-", "") if "research-" in ROOT_NAME else ROOT_NAME

STORAGE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../storage"))
RAW_DIR = os.path.join(STORAGE_DIR, "1_raw_data")
REG_DIR = os.path.join(STORAGE_DIR, "2_register_data")
EXP_DIR = os.path.join(STORAGE_DIR, "3_exploitable_data")

for folder in [RAW_DIR, REG_DIR, EXP_DIR]:
    os.makedirs(folder, exist_ok=True)

REGISTRY_FILE = os.path.join(REG_DIR, f"{TOPIC}_registry.csv")
CURSOR_FILE = os.path.join(REG_DIR, f"{TOPIC}_cursor.json")

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
}

h2t = html2text.HTML2Text()
h2t.ignore_links = False

# ---------------------------------------------------------------------------
# Query blocks
# ---------------------------------------------------------------------------
KEYWORDS_BLOCKS = {
    "0_Base_Query": (
        '("EEG" OR "electroencephalography" OR "brainwaves" OR "brain waves" OR "neural oscillations" OR "cortical potentials") '
        'AND ("ear-EEG" OR "in-ear" OR "around-the-ear" OR "cEEG" OR "mastoid" OR "forehead" OR "sub-hairline" OR "wearable" OR "discreet" OR "non-invasive") '
        'AND ("electrode" OR "sensor" OR "headset" OR "dry-electrode" OR "hardware" OR "device") '
        'AND ("feasibility" OR "signal quality" OR "artifacts" OR "validation" OR "SNR" OR "performance")'
    ),
    "1_AI_Deep_Learning": (
        '("deep learning" OR "convolutional neural network" OR "transformers" OR "machine learning") '
        'AND ("EEG decoding" OR "feature extraction" OR "classification") AND ("neural signals" OR "brainwaves")'
    ),
    "2_Cognitive_States": (
        '("sleep staging" OR "mental workload" OR "cognitive fatigue" OR "emotion recognition" OR "vigilance monitoring") '
        'AND ("wearable" OR "wireless" OR "real-time") AND ("EEG" OR "brainwaves")'
    ),
    "3_BCI_Paradigms": (
        '("BCI" OR "brain-computer interface") AND ("SSVEP" OR "P300" OR "motor imagery" OR "event-related potentials" OR "ERP") '
        'AND ("non-invasive")'
    ),
    "4_Signal_Processing": (
        '("artifact removal" OR "independent component analysis" OR "ICA" OR "wavelet transform" OR "empirical mode decomposition") '
        'AND ("EEG" OR "electroencephalography") AND ("noise reduction" OR "filtering")'
    ),
    "5_NextGen_Hardware": (
        '("dry electrode" OR "textile electrode" OR "graphene sensor" OR "microneedle" OR "conductive polymer") '
        'AND ("EEG" OR "wearable neurotech" OR "biopotential")'
    ),
    "6_Clinical_Biomarkers": (
        '("epilepsy detection" OR "seizure prediction" OR "Alzheimer" OR "Parkinson" OR "ADHD") '
        'AND ("EEG" OR "electroencephalography") AND ("biomarker" OR "diagnostic")'
    ),
    "7_Neurostimulation": (
        '("tDCS" OR "tACS" OR "transcranial magnetic stimulation" OR "TMS" OR "neurostimulation") '
        'AND ("closed-loop" OR "feedback system") AND ("EEG")'
    ),
    "8_Brain_Source_Imaging": (
        '("source localization" OR "inverse problem" OR "brain connectivity" OR "graph theory" OR "functional connectivity") '
        'AND ("EEG" OR "electroencephalography")'
    ),
    "9_Consumer_Neurotech_VR": (
        '("neuromarketing" OR "virtual reality" OR "VR" OR "immersion" OR "gaming") '
        'AND ("EEG" OR "wearable headset" OR "consumer neurotech")'
    ),
    "10_MultiModal_Fusion": (
        '("fNIRS" OR "functional near-infrared spectroscopy" OR "eye tracking" OR "ECG fusion" OR "multimodal") '
        'AND ("EEG" OR "electroencephalography") AND ("wearable" OR "simultaneous")'
    ),
    "11_Ear_Wearable_Extensions": (
        '("mastoid EEG" OR "behind-the-ear" OR "smart eyewear" OR "hearables") '
        'AND ("signal quality" OR "validation" OR "electrode configuration")'
    ),
    "12_Wireless_Power_Efficiency": (
        '("low-power" OR "energy efficient" OR "battery life" OR "wireless power" OR "ultra-low-power ASIC") '
        'AND ("EEG" OR "wearable biosensor" OR "biopotential acquisition")'
    ),
    "13_Data_Privacy_Ethics": (
        '("data privacy" OR "GDPR" OR "informed consent" OR "ethical considerations" OR "cybersecurity") '
        'AND ("EEG" OR "neurotechnology" OR "wearable health device")'
    ),
    "14_Sleep_Consumer_Wearables": (
        '("home sleep monitoring" OR "consumer sleep tracker" OR "insomnia" OR "sleep quality") '
        'AND ("EEG" OR "wearable" OR "ear-worn device")'
    ),
    "15_Driver_Occupational_Fatigue": (
        '("driver drowsiness" OR "fatigue detection" OR "workplace safety" OR "vigilance decrement") '
        'AND ("EEG" OR "wearable monitoring")'
    ),
    "16_Open_Datasets_Benchmarks": (
        '("public EEG dataset" OR "benchmark" OR "open dataset" OR "data standardization" OR "BIDS-EEG") '
        'AND ("EEG" OR "electroencephalography")'
    ),
    "17_Explainable_AI_EEG": (
        '("explainable AI" OR "interpretability" OR "SHAP" OR "attention mechanism" OR "saliency map") '
        'AND ("EEG" OR "deep learning") AND ("classification" OR "decoding")'
    ),
}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def clean_filename(title, work_id):
    base = re.sub(r'[^\w\s-]', '', str(title)).strip().replace(' ', '_')[:60]
    uid = re.sub(r'\W+', '', str(work_id).split('/')[-1])[:12]
    return f"{base}_{uid}" if base else uid


def normalize_string(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower()) if s else ""


def request_with_retry(url, params=None, headers=None, timeout=REQUEST_TIMEOUT):
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
        except requests.RequestException as e:
            last_exc = e
            wait = RETRY_BACKOFF ** attempt
            print(f"   Network retry {attempt}/{MAX_RETRIES} ({e}). Waiting {wait}s...")
            time.sleep(wait)
    print(f"   Critical: all retries exhausted for {url[:70]} ({last_exc})")
    return None


def try_download_pdf(pdf_url, filename):
    res = request_with_retry(pdf_url, timeout=20)
    if res is None or res.status_code != 200:
        return None
    if res.content[:5] == b'%PDF-':
        path = os.path.join(RAW_DIR, f"{filename}.pdf")
        with open(path, 'wb') as f:
            f.write(res.content)
        return path
    return None


def try_scrape_html_to_markdown(html_url, filename):
    res = request_with_retry(html_url)
    if res is None or res.status_code != 200:
        return None
    try:
        soup = BeautifulSoup(res.text, 'html.parser')
    except Exception:
        return None
    for el in soup(["script", "style", "nav", "footer", "header"]):
        el.decompose()
    body = soup.find('article') or soup.find('main') or soup.body
    if not body:
        return None
    markdown_text = h2t.handle(str(body))
    if len(markdown_text.strip()) <= 300:
        return None
    path = os.path.join(EXP_DIR, f"{filename}.md")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(markdown_text)
    return path


def normalize_doi(doi):
    if not doi or doi == 'N/A':
        return None
    return str(doi).replace("https://doi.org/", "").strip()

def try_unpaywall(doi):
    doi_clean = normalize_doi(doi)
    if not doi_clean:
        return None
    res = request_with_retry(
        f"https://api.unpaywall.org/v2/{doi_clean}",
        params={"email": EMAIL_CONTACT},
        timeout=10,
    )
    if res is None or res.status_code != 200:
        return None
    try:
        data = res.json()
        oa_location = data.get("best_oa_location") or {}
        return oa_location.get("url_for_pdf") or oa_location.get("url")
    except Exception:
        return None


def try_semantic_scholar(doi):
    doi_clean = normalize_doi(doi)
    if not doi_clean:
        return None
    res = request_with_retry(
        f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi_clean}",
        params={"fields": "openAccessPdf"},
        timeout=10,
    )
    time.sleep(SECONDARY_API_DELAY)
    if res is None or res.status_code != 200:
        return None
    try:
        data = res.json()
        oa = data.get("openAccessPdf") or {}
        return oa.get("url")
    except Exception:
        return None


def try_core(doi):
    if not CORE_API_KEY:
        return None
    doi_clean = normalize_doi(doi)
    if not doi_clean:
        return None
    res = request_with_retry(
        "https://api.core.ac.uk/v3/search/works",
        params={"q": f'doi:"{doi_clean}"'},
        headers={"Authorization": f"Bearer {CORE_API_KEY}"},
        timeout=15,
    )
    time.sleep(SECONDARY_API_DELAY)
    if res is None or res.status_code != 200:
        return None
    try:
        data = res.json()
        results = data.get("results", [])
        if not results:
            return None
        top = results[0]
        return top.get("downloadUrl") or (top.get("sourceFulltextUrls") or [None])[0]
    except Exception:
        return None


def get_direct_candidates(work):
    """Cheap, no-extra-API-call candidates derivable straight from the
    OpenAlex work object: its own best_url, plus arXiv/PMC direct links
    reconstructed from identifiers OpenAlex already provides."""
    ids = work.get('ids', {}) or {}
    doi = work.get('doi') or ids.get('doi')
    pmcid = ids.get('pmcid')
    best_url = (work.get('open_access', {}) or {}).get('oa_url')

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

    return candidates, doi


# ---------------------------------------------------------------------------
# Core per-work processing
# ---------------------------------------------------------------------------
def process_work(work, block_name):
    work_id = str(work.get('id'))
    title = work.get('title') or 'Untitled Work'
    year = work.get('publication_year', 'N/A')
    doi_raw = work.get('doi', 'N/A')
    filename = clean_filename(title, work_id)

    abstract_raw = work.get('abstract_inverted_index')
    abstract = "None"
    if abstract_raw:
        pairs = [(w, p) for w, positions in abstract_raw.items() for p in positions]
        abstract = " ".join(w for w, _ in sorted(pairs, key=lambda x: x[1]))

    landing_page_url = (work.get('primary_location') or {}).get('landing_page_url') or doi_raw or "None"

    status_retrieved = "Failure"
    status_processed = "None"
    status_raw = "None"
    raw_path = "None"
    processed_path = "None"
    source_used = "None"

    def attempt(source_name, url):
        nonlocal status_retrieved, status_processed, status_raw, raw_path, processed_path, source_used
        pdf_path = try_download_pdf(url, filename)
        if pdf_path:
            status_retrieved, status_processed, status_raw = "Success", "Pending", "Present"
            raw_path, source_used = pdf_path, f"{source_name}_PDF"
            return True
        md_path = try_scrape_html_to_markdown(url, filename)
        if md_path:
            status_retrieved, status_processed = "Success", "Terminated"
            processed_path, source_used = md_path, f"{source_name}_HTML"
            return True
        return False

    direct_candidates, doi = get_direct_candidates(work)
    for source_name, url in direct_candidates:
        if attempt(source_name, url):
            break

    if status_retrieved == "Failure":
        for source_name, resolver in (
            ("Unpaywall", try_unpaywall),
            ("SemanticScholar", try_semantic_scholar),
            ("CORE", try_core),
        ):
            url = resolver(doi)
            if url and attempt(source_name, url):
                break

    return {
        "ID_OpenAlex": work_id,
        "Titre": title,
        "Annee": year,
        "DOI": doi_raw,
        "status_retrieved": status_retrieved,
        "status_processed": status_processed,
        "status_raw": status_raw,
        "raw_path": raw_path,
        "processed_path": processed_path,
        "Source_Utilisee": source_used,
        "Lien_Editeur_Landing": landing_page_url,
        "Resume_Abstract": abstract,
        "Bloc_Origine": block_name,
    }


# ---------------------------------------------------------------------------
# Cursor persistence
# ---------------------------------------------------------------------------
def load_cursor():
    if os.path.exists(CURSOR_FILE):
        try:
            with open(CURSOR_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cursor(cursor):
    with open(CURSOR_FILE, 'w') as f:
        json.dump(cursor, f, indent=2)


# ---------------------------------------------------------------------------
# Main ingestion loop
# ---------------------------------------------------------------------------
def run_ingestion():
    master_registry = []
    processed_ids, known_dois, known_titles = set(), set(), set()

    if os.path.exists(REGISTRY_FILE):
        try:
            df_existing = pd.read_csv(REGISTRY_FILE)
            master_registry = df_existing.to_dict('records')
            processed_ids = set(df_existing['ID_OpenAlex'].dropna().astype(str))
            known_dois = set(df_existing['DOI'].dropna().astype(str).str.lower())
            known_titles = set(df_existing['Titre'].dropna().apply(normalize_string))
            print(f"System: Loaded registry. Shielding {len(master_registry)} known articles.")
        except Exception as e:
            print(f"Warning: Failed to parse registry ({e}). Starting fresh.")
    else:
        print("System: No existing registry found. Starting fresh.")

    cursor = load_cursor()
    api_url = "https://api.openalex.org/works"
    global_new = 0

    for block_name, query_string in KEYWORDS_BLOCKS.items():
        print(f"\nTargeting Block: {block_name}")
        block_state = cursor.get(block_name, {"next_page": 1})
        start_page = block_state.get("next_page", 1)

        params = {
            'search.title_and_abstract': query_string,
            'sort': 'relevance_score:desc',
            'per_page': ITEMS_PER_PAGE,
            'page': start_page,
            'mailto': EMAIL_CONTACT,
        }

        init_res = request_with_retry(api_url, params=params, timeout=20)
        if init_res is None:
            print(f" Skipping block {block_name}: API unreachable.")
            continue

        try:
            payload = init_res.json()
            total_articles = payload.get('meta', {}).get('count', 0)
            total_pages_available = math.ceil(total_articles / ITEMS_PER_PAGE) if total_articles else 0
        except Exception as e:
            print(f" Error parsing metadata for {block_name}: {e}")
            continue

        if total_pages_available == 0:
            print(" Block scope: 0 items found.")
            cursor[block_name] = {"next_page": 1, "total_pages": 0}
            save_cursor(cursor)
            continue

        end_page = min(start_page + MAX_PAGES_PER_RUN - 1, total_pages_available)
        print(f" Block scope: {total_articles} items total. Fetching pages {start_page}-{end_page}/{total_pages_available}.")

        current_page = start_page
        block_new_count = 0

        while current_page <= end_page:
            params['page'] = current_page
            response = request_with_retry(api_url, params=params, timeout=20)
            if response is None:
                current_page += 1
                continue

            try:
                works = response.json().get('results', [])
            except Exception as e:
                print(f" Error parsing page {current_page}: {e}")
                current_page += 1
                continue

            if not works:
                break

            fresh_works = []
            for work in works:
                work_id = str(work.get('id'))
                title = work.get('title') or 'Untitled Work'
                doi = work.get('doi', 'N/A')
                norm_title = normalize_string(title)
                norm_doi = str(doi).lower() if doi != 'N/A' else 'none'

                if work_id in processed_ids:
                    continue
                if norm_doi != 'none' and norm_doi in known_dois:
                    continue
                if norm_title in known_titles:
                    continue

                fresh_works.append(work)
                processed_ids.add(work_id)
                known_dois.add(norm_doi)
                known_titles.add(norm_title)

            if fresh_works:
                with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    futures = {executor.submit(process_work, w, block_name): w for w in fresh_works}
                    for future in as_completed(futures):
                        try:
                            record = future.result()
                        except Exception as e:
                            print(f"   Worker error: {e}")
                            continue
                        block_new_count += 1
                        global_new += 1
                        print(
                            f"   [Global #{global_new}] {record['status_retrieved']} "
                            f"({record['Source_Utilisee']}) | {record['Titre'][:45]}..."
                        )
                        master_registry.append(record)

                pd.DataFrame(master_registry).to_csv(REGISTRY_FILE, index=False, encoding='utf-8')

            current_page += 1
            time.sleep(0.2)

        next_page = current_page if current_page <= total_pages_available else 1
        cursor[block_name] = {"next_page": next_page, "total_pages": total_pages_available}
        save_cursor(cursor)

        print(f" Block {block_name}: {block_new_count} new articles added.")

    print(f"\nExecution complete. Total rows in registry: {len(master_registry)}. New this run: {global_new}.")


if __name__ == "__main__":
    run_ingestion()