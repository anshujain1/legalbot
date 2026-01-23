import os
import json
import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_FILE = os.path.join(BASE_DIR, "raw", "grouped_urls.json")
RAW_DIR = os.path.join(BASE_DIR, "raw", "gov_html")

os.makedirs(RAW_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DataCollector/1.0)"
}

with open(QUEUE_FILE, "r", encoding="utf-8") as f:
    queue = json.load(f)

for item in queue:
    if item.get("status") == "downloaded":
        continue

    url = item["url"]
    initiative_id = item["initiative_id"]
    out_path = os.path.join(RAW_DIR, f"{initiative_id}.html")

    print(f"Downloading: {initiative_id}")

    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        response.raise_for_status()

        if len(response.text) < 1000:
            raise Exception("HTML too small")

        with open(out_path, "w", encoding="utf-8") as f:
            f.write(response.text)

        item["status"] = "downloaded"

    except Exception as e:
        item["status"] = "failed"
        item["error"] = str(e)

with open(QUEUE_FILE, "w", encoding="utf-8") as f:
    json.dump(queue, f, indent=2, ensure_ascii=False)

print("Download phase complete")
