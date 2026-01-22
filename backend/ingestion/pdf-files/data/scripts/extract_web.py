import os
import json
import trafilatura

# -------------------- CONFIG --------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(BASE_DIR,'raw',"raw_webpages")
CHUNK_DIR = os.path.join(BASE_DIR, 'processed',"clean_chunks")
QUEUE_JSON = os.path.join(BASE_DIR, "web_queue.json")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(CHUNK_DIR, exist_ok=True)

# -------------------- FUNCTIONS --------------------

# 1️⃣ Extract article from URL
def extract_article(url):
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return None
    text = trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
        no_fallback=False
    )
    return text

# 2️⃣ Normalize text: remove short/noise lines
def normalize(text):
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if len(line) > 30]  # keep only meaningful lines
    return "\n".join(lines)

# 3️⃣ Chunk text for embeddings/bot
def chunk_text(text, max_words=250):
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i:i + max_words]))
    return chunks

# 4️⃣ Process one URL: download, clean, chunk
def process_url(item):
    url = item["url"]
    initiative_id = item.get("initiative_id", "unknown")

    # Extract article
    text = extract_article(url)
    if not text or len(text) < 500:
        item["status"] = "needs_browser"
        item["chunks"] = []
        return item

    # Normalize and chunk
    clean_text = normalize(text)
    chunks = chunk_text(clean_text)

    # Save raw HTML
    raw_path = os.path.join(RAW_DIR, f"{initiative_id}.html")
    try:
        downloaded_html = trafilatura.fetch_url(url)
        if downloaded_html:
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(downloaded_html)
    except Exception as e:
        print(f"Failed to save raw HTML for {initiative_id}: {e}")

    # Save chunks to text file
    chunk_path = os.path.join(CHUNK_DIR, f"{initiative_id}.txt")
    with open(chunk_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk + "\n\n")

    # Update item status
    item["status"] = "ok"
    item["chunks"] = chunks
    return item

# -------------------- MAIN PIPELINE --------------------
def main():
    # Load queue
    with open(QUEUE_JSON, "r", encoding="utf-8") as f:
        queue = json.load(f)

    # Process each URL
    for item in queue:
        if item.get("status") == "completed":
            continue
        if item.get("type") != "web":
            continue

        print("Processing:", item.get("url"))
        updated_item = process_url(item)
        print("Status:", updated_item["status"], "| Chunks:", len(updated_item.get("chunks", [])))

    # Save updated queue
    with open(QUEUE_JSON, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

# -------------------- RUN --------------------
if __name__ == "__main__":
    main()
