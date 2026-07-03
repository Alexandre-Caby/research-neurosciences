import os
import time
import re
import math
import requests
from bs4 import BeautifulSoup
import html2text
import pandas as pd

# API Authorization & Server Path Mapping
API_KEY = "4NtO7zxUXCf2Z0mWwEErr4"
EMAIL_CONTACT = "alexandre.caby@sncf.fr"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "../storage"))

RAW_DIR = os.path.join(STORAGE_DIR, "1_raw_data")
REG_DIR = os.path.join(STORAGE_DIR, "2_register_data")
EXP_DIR = os.path.join(STORAGE_DIR, "3_exploitable_data")

for folder in [RAW_DIR, REG_DIR, EXP_DIR]:
    os.makedirs(folder, exist_ok=True)

REGISTRY_FILE = os.path.join(REG_DIR, "master_registry.csv")
MAX_PAGES_PER_BLOCK = 5

KEYWORDS_BLOCKS = {
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
    )
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'api-key': API_KEY
}

h2t = html2text.HTML2Text()
h2t.ignore_links = False

def clean_filename(title):
    return re.sub(r'[^\w\s-]', '', str(title)).strip().replace(' ', '_')[:60]

def normalize_string(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower()) if s else ""

def try_download_pdf(pdf_url, filename):
    try:
        res = requests.get(pdf_url, headers=HEADERS, timeout=10)
        if res.status_code == 200 and 'pdf' in res.headers.get('Content-Type', '').lower():
            path = os.path.join(RAW_DIR, f"{filename}.pdf")
            with open(path, 'wb') as f:
                f.write(res.content)
            return path
    except Exception:
        pass
    return None

def try_scrape_html_to_markdown(html_url, filename):
    try:
        res = requests.get(html_url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            for el in soup(["script", "style", "nav", "footer", "header"]):
                el.decompose()
            body = soup.find('article') or soup.find('main') or soup.body
            if body:
                markdown_text = h2t.handle(str(body))
                if len(markdown_text.strip()) > 300:
                    path = os.path.join(EXP_DIR, f"{filename}.md")
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(markdown_text)
                    return path
    except Exception:
        pass
    return None

# Cross-script deduplication shield initialization
master_registry = []
processed_ids = set()
known_dois = set()
known_titles = set()

if os.path.exists(REGISTRY_FILE):
    try:
        df_existing = pd.read_csv(REGISTRY_FILE)
        master_registry = df_existing.to_dict('records')
        if 'ID_OpenAlex' in df_existing.columns:
            processed_ids = set(df_existing['ID_OpenAlex'].dropna().astype(str).tolist())
        if 'DOI' in df_existing.columns:
            known_dois = set(df_existing['DOI'].dropna().astype(str).str.lower().tolist())
        if 'Titre' in df_existing.columns:
            known_titles = set(df_existing['Titre'].dropna().apply(normalize_string).tolist())
        print(f"System: Loaded reference registry. Shielding {len(master_registry)} articles from duplication.")
    except Exception as e:
        print(f"Critical: Failed to load registry ({e}). Aborting execution to prevent data corruption.")
        exit()
else:
    print(f"Critical: Base registry file missing at {REGISTRY_FILE}. Run core/ingest.py first.")
    exit()

url = "https://api.openalex.org/works"
items_per_page = 200
global_new_additions = 0

# Multi-Block Processing Cycle
for block_name, query_string in KEYWORDS_BLOCKS.items():
    print(f"\nTargeting Block: {block_name}")
    current_page = 1

    params = {
        'search.title_and_abstract': query_string,
        'sort': 'relevance_score:desc',
        'per_page': items_per_page,
        'page': current_page,
        'mailto': EMAIL_CONTACT,
        'api_key': API_KEY
    }

    try:
        init_res = requests.get(url, params=params, headers=HEADERS, timeout=15).json()
        total_articles = init_res.get('meta', {}).get('count', 0)
        total_pages = min(math.ceil(total_articles / items_per_page), MAX_PAGES_PER_BLOCK)
        print(f" Block Scope: Found {total_articles} items. Parsing set to {total_pages} pages max.")
    except Exception as e:
        print(f" Error connecting to block {block_name}: {e}. Skipping block.")
        continue

    while current_page <= total_pages:
        params['page'] = current_page
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=20).json()
            works = response.get('results', [])
        except Exception as e:
            print(f" Network error on page {current_page}: {e}. Skipping page.")
            current_page += 1
            continue

        if not works:
            break

        block_new_count = 0
        for work in works:
            work_id = str(work.get('id'))
            title = work.get('title') or 'Untitled Work'
            doi = work.get('doi', 'N/A')

            norm_title = normalize_string(title)
            norm_doi = str(doi).lower() if doi != 'N/A' else 'none'

            # Strict cross-script and inter-block deduplication check
            if work_id in processed_ids or (norm_doi in known_dois and norm_doi != 'none') or (norm_title in known_titles):
                continue

            block_new_count += 1
            global_new_additions += 1
            filename = clean_filename(title)
            year = work.get('publication_year', 'N/A')

            abstract_raw = work.get('abstract_inverted_index')
            abstract = "None"
            if abstract_raw:
                abstract = " ".join([word for word, pos in sorted([(w, p) for w, positions in abstract_raw.items() for p in positions], key=lambda x: x[1])])

            best_url = work.get('open_access', {}).get('oa_url')
            landing_page_url = (work.get('primary_location') or {}).get('landing_page_url') or doi or "None"

            # Unified state machine mapping variables
            status_retrieved = "Failure"
            status_processed = "None"
            status_raw = "None"
            raw_path = "None"
            processed_path = "None"

            if best_url:
                if '.pdf' in best_url.lower() or 'pdf' in best_url.lower():
                    pdf_path = try_download_pdf(best_url, filename)
                    if pdf_path:
                        status_retrieved = "Success"
                        status_processed = "Pending"
                        status_raw = "Present"
                        raw_path = pdf_path

                if status_retrieved == "Failure":
                    md_path = try_scrape_html_to_markdown(best_url, filename)
                    if md_path:
                        status_retrieved = "Success"
                        status_processed = "Terminated"
                        status_raw = "None"
                        processed_path = md_path

            print(f"   🆕 [Global #{global_new_additions}] {status_retrieved} | {title[:45]}...")

            master_registry.append({
                "ID_OpenAlex": work_id,
                "Titre": title,
                "Annee": year,
                "DOI": doi,
                "status_retrieved": status_retrieved,
                "status_processed": status_processed,
                "status_raw": status_raw,
                "raw_path": raw_path,
                "processed_path": processed_path,
                "Lien_OpenAccess_Direct": best_url if best_url else "None",
                "Lien_Editeur_Landing": landing_page_url,
                "Resume_Abstract": abstract,
                "Bloc_Origine": block_name
            })

            processed_ids.add(work_id)
            known_dois.add(norm_doi)
            known_titles.add(norm_title)

        if block_new_count > 0:
            pd.DataFrame(master_registry).to_csv(REGISTRY_FILE, index=False, encoding='utf-8')

        current_page += 1
        time.sleep(0.2)

print(f"\nExecution Complete. Multi-block ingestion successful. Total rows: {len(master_registry)}")
