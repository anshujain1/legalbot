import os
import json

# ---------------- CONFIG ----------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHUNK_DIR = os.path.join(BASE_DIR, "processed", "pdf_chunks")
MASTER_JSON = os.path.join(BASE_DIR, "scripts", "pdf_master.json")
DROP_KEYWORDS = [
    'Acknowledgement', 'Table of Contents', 'List of Tables',
    'List of Figures', 'Annexure', 'ISBN', 'Contact:'
]

# Minimum and maximum word counts for RAG-friendly chunks
MIN_WORDS = 300
MAX_WORDS = 600

# ---------------- LOAD MASTER PDF DATA ----------------
with open(MASTER_JSON, "r", encoding="utf-8") as f:
    pdf_master = json.load(f)

# Map initiative_id → URL
id_to_url = {item["initiative_id"]: item.get("url") for item in pdf_master if item["type"] == "pdf"}

def is_junk(text):
    return any(k.lower() in text.lower() for k in DROP_KEYWORDS)

def normalize_chunks(chunks, min_words=MIN_WORDS, max_words=MAX_WORDS):
    normalized = []
    buffer_text = ""
    buffer_pages = []
    buffer_chapter = None
    buffer_section = None

    for c in chunks:
        text = c["text"]
        pages = c.get("pages", [])
        chapter = c.get("chapter")
        section = c.get("section")

        total_words = len((buffer_text + " " + text).split())
        if total_words > max_words:
            if buffer_text.strip():
                normalized.append({
                    "chapter": buffer_chapter,
                    "section": buffer_section,
                    "pages": buffer_pages,
                    "text": buffer_text.strip()
                })
            buffer_text = text
            buffer_pages = pages
            buffer_chapter = chapter
            buffer_section = section
        else:
            buffer_text += " " + text
            buffer_pages += pages
            buffer_chapter = buffer_chapter or chapter
            buffer_section = buffer_section or section

    if buffer_text.strip():
        normalized.append({
            "chapter": buffer_chapter,
            "section": buffer_section,
            "pages": buffer_pages,
            "text": buffer_text.strip()
        })

    return normalized

for file in os.listdir(CHUNK_DIR):
    if not file.endswith(".json"):
        continue

    path = os.path.join(CHUNK_DIR, file)
    initiative_id = file.replace(".json", "")
    url = id_to_url.get(initiative_id)

    with open(path, "r", encoding="utf-8") as f:
        chunks_list = json.load(f)

    if not isinstance(chunks_list, list):
        print(f"Skipping {file}, not a list of chunks")
        continue

    normalized_chunks = normalize_chunks(chunks_list)

    for c in normalized_chunks:
        c["source"] = {
            "type": "pdf",
            "url": url
        }
    normalized_data = {
        "initiative_id": initiative_id,
        "source": {
            "type": "pdf",
            "url": url
        },
        "chunks": normalized_chunks
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized_data, f, indent=2, ensure_ascii=False)

    print(f"Normalized PDF chunks for {initiative_id}, total chunks: {len(normalized_chunks)}")
