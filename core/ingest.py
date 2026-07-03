import os
import time
import re
import math
import requests
from bs4 import BeautifulSoup
import html2text
import pandas as pd

# API Authorization & Deployment Paths
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

MASTER_QUERY = (
    '("EEG" OR "electroencephalography" OR "brainwaves" OR "brain waves" OR "neural oscillations" OR "cortical potentials") '
    'AND ("ear-EEG" OR "in-ear" OR "around-the-ear" OR "cEEG" OR "mastoid" OR "forehead" OR "sub-hairline" OR "wearable" OR "discreet" OR "non-invasive") '
    'AND ("electrode" OR "sensor" OR "headset" OR "dry-electrode" OR "hardware" OR "device") '
    'AND ("feasibility" OR "signal quality" OR "artifacts" OR "validation" OR "SNR" OR "performance")'
)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'api-key': API_KEY
}

h2t = html2text.HTML2Text()
h2t.ignore_links = False

def clean_filename(title):
    return re.sub(r'[^\w\s-]', '', str(title)).strip().replace(' ', '_')[:60]

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

# Resume engine initialization
master_registry = []
processed_ids = set()

if os.path.exists(REGISTRY_FILE):
    try:
        df_existing = pd.read_csv(REGISTRY_FILE)
        if 'ID_OpenAlex' in df_existing.columns:
            processed_ids = set(df_existing['ID_OpenAlex'].dropna().astype(str).tolist())
            master_registry = df_existing.to_dict('records')
            print(f"System: Found registry. Skipping {len(processed_ids)} known items.")
    except Exception as e:
        print(f"Warning: Failed to parse registry ({e}). Starting fresh.")

url = "https://api.openalex.org/works"
current_page = 1
items_per_page = 200

params = {
    'search.title_and_abstract': MASTER_QUERY,
    'sort': 'relevance_score:desc',
    'per_page': items_per_page,
    'page': current_page,
    'mailto': EMAIL_CONTACT,
    'api_key': API_KEY
}

try:
    init_res = requests.get(url, params=params, headers=HEADERS, timeout=15).json()
    total_articles = init_res.get('meta', {}).get('count', 0)
    total_pages = math.ceil(total_articles / items_per_page)
    print(f"Metadata: Found {total_articles} target works across {total_pages} pages.")
except Exception as e:
    print(f"Critical: API Handshake failed: {e}")
    exit()

# Operational Engine Loop
while current_page <= total_pages:
    if (current_page * items_per_page) <= len(processed_ids):
        current_page += 1
        continue

    print(f"Processing Page {current_page}/{total_pages}...")
    params['page'] = current_page

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=20).json()
        works = response.get('results', [])
    except Exception as e:
        print(f"Network error page {current_page}: {e}. Skipping page.")
        current_page += 1
        continue

    if not works:
        break

    for idx, work in enumerate(works, 1):
        work_id = str(work.get('id'))
        if work_id in processed_ids:
            continue

        title = work.get('title') or 'Untitled Work'
        filename = clean_filename(title)
        year = work.get('publication_year', 'N/A')
        doi = work.get('doi', 'N/A')

        abstract_raw = work.get('abstract_inverted_index')
        abstract = "None"
        if abstract_raw:
            abstract = " ".join([word for word, pos in sorted([(w, p) for w, positions in abstract_raw.items() for p in positions], key=lambda x: x[1])])

        best_url = work.get('open_access', {}).get('oa_url')
        landing_page_url = (work.get('primary_location') or {}).get('landing_page_url') or doi or "None"

        # Unified state machine variables (State Matrix mapping)
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

        global_idx = ((current_page - 1) * items_per_page) + idx
        print(f" [{global_idx}/{total_articles}] {status_retrieved} | {title[:50]}...")

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
            "Resume_Abstract": abstract
        })
        processed_ids.add(work_id)

    if master_registry:
        pd.DataFrame(master_registry).to_csv(REGISTRY_FILE, index=False, encoding='utf-8')

    current_page += 1
    time.sleep(0.2)

print("Execution complete. Base Registry Synchronized.")
