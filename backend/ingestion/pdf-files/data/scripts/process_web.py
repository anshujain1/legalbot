import os
import json
import hashlib
from bs4 import BeautifulSoup
from filters import is_junk  # your existing junk filter
import re

# -----------------------------
# Config / directories
# -----------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR, "raw", "webpages")
OUT_DIR = os.path.join(BASE_DIR, "processed", "web_chunks")
QUEUE_PATH = os.path.join(BASE_DIR, "web_queue.json")

os.makedirs(OUT_DIR, exist_ok=True)

# -----------------------------
# Chunking parameters
# -----------------------------
SOFT_TOKEN_LIMIT = 500   # ideal chunk size in tokens
HARD_TOKEN_LIMIT = 800   # maximum chunk size in tokens
MIN_TOKENS = 200         # merge tiny chunks
TOKEN_OVERLAP = 50       # optional overlap for RAG

# -----------------------------
# Helpers
# -----------------------------

def tokenize(text):
    """Simple whitespace tokenization"""
    return text.split()

def count_tokens(text):
    return len(tokenize(text))

def deduplicate_blocks(blocks):
    seen = set()
    unique_blocks = []
    for b in blocks:
        h = hashlib.md5(b["text"].encode("utf-8")).hexdigest()
        if h not in seen:
            seen.add(h)
            unique_blocks.append(b)
    return unique_blocks


def clean_text(text):
    """Remove extra spaces, newlines"""
    return re.sub(r"\s+", " ", text.strip())

def is_boilerplate(text):
    """Filter common web boilerplate"""
    patterns = [
        r"register|login|comments|cookie",  # simple regex for common boilerplate
        r"we have migrated to a new commenting platform"
    ]
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in patterns)

# -----------------------------
# Load queue
# -----------------------------
with open(QUEUE_PATH, "r", encoding="utf-8") as f:
    queue = json.load(f)

url_map = {item["initiative_id"]: item.get("url") for item in queue}

# -----------------------------
# Main processing
# -----------------------------
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

    # Remove junk tags
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Extract meaningful blocks
    blocks = []
    for b in soup.find_all(["h1","h2","h3","p","li","div"]):
        text = clean_text(b.get_text(" ", strip=True))
        if not text or is_junk(text) or is_boilerplate(text):
            continue
        tag_name = b.name.lower()
        level = 0
        if tag_name.startswith("h"):
            level = int(tag_name[1])
        blocks.append({
            "text": text,
            "tag": tag_name,
            "level": level
        })

    if not blocks:
        print("No usable blocks:", file)
        continue

    # Deduplicate blocks
    blocks = deduplicate_blocks(blocks)


    # -----------------------------
    # Hybrid chunking
    # -----------------------------
    chunks = []
    current_chunk = ""
    current_section = None
    chunk_counter = 1

    for b in blocks:
        # If heading, start a new chunk
        if b["tag"].startswith("h"):
            if current_chunk:
                # Save previous chunk
                chunks.append({
                    "chunk_id": f"{initiative_id}_web_{chunk_counter:02d}",
                    "section": current_section,
                    "text": current_chunk.strip()
                })
                chunk_counter += 1
                current_chunk = ""
            current_section = b["text"]  # heading becomes section
        else:
            if current_chunk:
                current_chunk += " " + b["text"]
            else:
                current_chunk = b["text"]

            # Check hard token limit
            if count_tokens(current_chunk) > HARD_TOKEN_LIMIT:
                chunks.append({
                    "chunk_id": f"{initiative_id}_web_{chunk_counter:02d}",
                    "section": current_section,
                    "text": current_chunk.strip()
                })
                chunk_counter += 1
                # Optional overlap
                current_chunk = " ".join(tokenize(current_chunk)[-TOKEN_OVERLAP:])

    # Save leftover chunk
    if current_chunk:
        chunks.append({
            "chunk_id": f"{initiative_id}_web_{chunk_counter:02d}",
            "section": current_section,
            "text": current_chunk.strip()
        })

    # Merge tiny chunks
    merged_chunks = []
    for c in chunks:
        if merged_chunks and count_tokens(c["text"]) < MIN_TOKENS:
            merged_chunks[-1]["text"] += " " + c["text"]
        else:
            merged_chunks.append(c)

    # -----------------------------
    # Save JSON
    # -----------------------------
    out_data = {
        "initiative_id": initiative_id,
        "source": {
            "type": "web",
            "url": url_map.get(initiative_id),
            "file": file
        },
        "title": soup.title.string.strip() if soup.title else None,
        "chunks": merged_chunks
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, indent=2, ensure_ascii=False)

    print("Processed WEB:", file)
