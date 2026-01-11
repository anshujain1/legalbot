import os, json, requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PDF_DIR = os.path.join(BASE_DIR, "raw", "pdfs")
MASTER_JSON = os.path.join(BASE_DIR, "pdf_queue.json")

os.makedirs(PDF_DIR, exist_ok=True)

with open(MASTER_JSON, "r", encoding="utf-8") as f:
    pdfs = json.load(f)

BATCH = 5
count = 0

for item in pdfs:
    if item["type"] != "pdf":
        continue

    filename = item["initiative_id"] + ".pdf"
    path = os.path.join(PDF_DIR, filename)

    if os.path.exists(path):
        continue

    print("Downloading:", filename)
    try:
        r = requests.get(item["url"], timeout=40)
        r.raise_for_status()
        with open(path, "wb") as f:
            f.write(r.content)
        item["downloaded"] = True
        count += 1
    except Exception as e:
        print("Failed:", item["initiative_id"], e)

    if count >= BATCH:
        break

    with open(MASTER_JSON, "w", encoding="utf-8") as f:
        json.dump(pdfs, f, indent=2, ensure_ascii=False)
