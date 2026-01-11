import os, json, requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(BASE_DIR, "raw", "webpages")
QUEUE_JSON = os.path.join(BASE_DIR, "web_queue.json")

os.makedirs(WEB_DIR, exist_ok=True)

with open(QUEUE_JSON, "r", encoding="utf-8") as f:
    webpages = json.load(f)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

BATCH = 12
downloaded = 0

for item in webpages:
    if item.get("type") != "web":
        continue
    if item.get("status") == "completed":
        continue

    initiative_id = item["initiative_id"]
    path = os.path.join(WEB_DIR, initiative_id + ".html")

    print("Fetching:", item["url"])

    try:
        r = requests.get(item["url"], headers=HEADERS, timeout=40)
        r.raise_for_status()

        if len(r.text) < 500:
            raise Exception("HTML too small, possible block")

        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)

        item["status"] = "completed"
        downloaded += 1
        print("Saved:", initiative_id)

    except Exception as e:
        item["status"] = "failed"
        print("Failed:", initiative_id, "|", str(e))

    if downloaded >= BATCH:
        break

with open(QUEUE_JSON, "w", encoding="utf-8") as f:
    json.dump(webpages, f, indent=2, ensure_ascii=False)
