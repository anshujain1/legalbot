import os
import json
import hashlib
from bs4 import BeautifulSoup
from filters import is_junk  # your existing junk filter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "raw", "webpages")
OUT_DIR = os.path.join(BASE_DIR, "processed", "web_chunks")
QUEUE_PATH = os.path.join(BASE_DIR, "web_queue.json")

os.makedirs(OUT_DIR, exist_ok=True)

# --- Configurable chunk size ---
WEB_CHUNK_SIZE = 200  # words per chunk for web content

# --- Helper: split text into chunks ---
def chunk_text(text, chunk_size=WEB_CHUNK_SIZE):
    words = text.split()
    for i in range(0, len(words), chunk_size):
        yield " ".join(words[i:i + chunk_size])

# --- Helper: deduplicate text in-page ---
def deduplicate_texts(texts):
    seen_hashes = set()
    unique_texts = []
    for t in texts:
        h = hashlib.md5(t.encode("utf-8")).hexdigest()
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique_texts.append(t)
    return unique_texts

# --- Load queue to map initiative_id → source URL ---
with open(QUEUE_PATH, "r", encoding="utf-8") as f:
    queue = json.load(f)
url_map = {item["initiative_id"]: item.get("url") for item in queue}

# --- Main processing ---
for file in os.listdir(RAW_DIR):
    if not file.endswith(".html"):
        continue

    initiative_id = file.replace(".html", "")
    in_path = os.path.join(RAW_DIR, file)
    out_path = os.path.join(OUT_DIR, initiative_id + ".json")

    if os.path.exists(out_path):
        print("Skipped (already processed):", file)
        continue

    with open(in_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    # --- Remove junk tags ---
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # --- Extract title ---
    title = soup.title.string.strip() if soup.title else None
    source_url = url_map.get(initiative_id)

    # --- Extract paragraphs and list items ---
    raw_texts = []
    for block in soup.find_all(["p", "li", "h2", "h3"]):
        text = block.get_text(" ", strip=True)
        if not text or is_junk(text):
            continue
        raw_texts.append(text)

    if not raw_texts:
        print("No usable content:", file)
        continue

    # --- Deduplicate within page ---
    raw_texts = deduplicate_texts(raw_texts)

    # --- Chunking ---
    chunks = []
    for t in raw_texts:
        for c in chunk_text(t, WEB_CHUNK_SIZE):
            chunks.append({
                "section": None,  # optionally, could infer from <h2>/<h3>
                "text": c
            })

    if not chunks:
        print("No usable chunks after processing:", file)
        continue

    # --- Save JSON ---
    out_data = {
        "initiative_id": initiative_id,
        "source": {
            "type": "web",
            "url": source_url,
            "file": file
        },
        "title": title,
        "chunks": chunks
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False)

    print("Processed WEB:", file)
