import os
import json
import re

# ---------------- CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNK_DIR = os.path.join(BASE_DIR, "processed", "pdf_chunks")
MASTER_JSON = os.path.join(BASE_DIR, "scripts", "pdf_master.json")

MIN_WORDS = 300
MAX_WORDS = 600
MIN_RAW_WORDS = 80

DROP_KEYWORDS = [
    "table of contents", "acknowledgement", "annexure",
    "appendix", "references", "bibliography",
    "isbn", "contact", "list of figures", "list of tables"
]

NUMBER_HEAVY_RATIO = 0.35

# ---------------- LOAD MASTER PDF DATA ----------------
with open(MASTER_JSON, "r", encoding="utf-8") as f:
    pdf_master = json.load(f)

id_to_meta = {
    item["initiative_id"]: {
        "url": item.get("url"),
        "title": item.get("title")
    }
    for item in pdf_master
    if item.get("type") == "pdf"
}

# ---------------- FILTERS ----------------
def is_english(text):
    return not bool(re.search(r"[^\x00-\x7F]", text))

def is_junk(text):
    lower = text.lower()
    return any(k in lower for k in DROP_KEYWORDS)

def is_table_like(text):
    tokens = text.split()
    if not tokens:
        return True
    numeric = sum(1 for t in tokens if any(c.isdigit() for c in t))
    return (numeric / len(tokens)) > NUMBER_HEAVY_RATIO

def is_heading_like(text):
    return text.isupper() or len(text.split()) < 10

def clean_meta(v):
    if not v:
        return None
    if isinstance(v, str) and re.fullmatch(r"[\d.\-]+", v.strip()):
        return None
    return v

# ---------------- NORMALIZATION ----------------
def normalize_chunks(chunks):
    cleaned = []

    # STEP 1: FILTER
    for c in chunks:
        text = c.get("text", "").strip()
        if len(text.split()) < MIN_RAW_WORDS:
            continue
        if not is_english(text):
            continue
        if is_junk(text):
            continue
        if is_table_like(text):
            continue
        if is_heading_like(text):
            continue

        cleaned.append({
            "text": text,
            "pages": c.get("pages", []),
            "chapter": clean_meta(c.get("chapter")),
            "section": clean_meta(c.get("section"))
        })

    # STEP 2: MERGE
    final = []
    buf_text = ""
    buf_pages = []
    buf_ch = None
    buf_sec = None

    for c in cleaned:
        words = (buf_text + " " + c["text"]).split()
        if len(words) > MAX_WORDS:
            if len(buf_text.split()) >= MIN_WORDS:
                final.append({
                    "chapter": buf_ch,
                    "section": buf_sec,
                    "pages": sorted(set(buf_pages)),
                    "text": buf_text.strip()
                })
            buf_text = c["text"]
            buf_pages = c["pages"]
            buf_ch = c["chapter"]
            buf_sec = c["section"]
        else:
            buf_text += " " + c["text"]
            buf_pages += c["pages"]
            buf_ch = buf_ch or c["chapter"]
            buf_sec = buf_sec or c["section"]

    if len(buf_text.split()) >= MIN_WORDS:
        final.append({
            "chapter": buf_ch,
            "section": buf_sec,
            "pages": sorted(set(buf_pages)),
            "text": buf_text.strip()
        })

    return final

# ---------------- MAIN ----------------
for file in os.listdir(CHUNK_DIR):
    if not file.endswith(".json"):
        continue

    path = os.path.join(CHUNK_DIR, file)
    initiative_id = file.replace(".json", "")
    meta = id_to_meta.get(initiative_id, {})

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ✅ SUPPORT BOTH FORMATS
    if isinstance(data, dict) and "chunks" in data:
        raw_chunks = data["chunks"]
        title = data.get("title")
    elif isinstance(data, list):
        raw_chunks = data
        title = None
    else:
        print(f"Skipping {file}: unknown format")
        continue

    normalized = normalize_chunks(raw_chunks)

    final_data = {
        "initiative_id": initiative_id,
        "source": {
            "type": "pdf",
            "url": meta.get("url")
        },
        "title": title or meta.get("title"),
        "chunks": normalized
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print(f"Normalized {initiative_id}: {len(normalized)} chunks")
