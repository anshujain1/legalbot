import json

INPUT_FILE = "data/initiatives_index.json"
OUTPUT_FILE = "data/web_queue.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    initiatives = json.load(f)["initiatives"]

web_queue = []

for item in initiatives:
    for url in item["urls"]:
        if not url.lower().endswith(".pdf"):
            web_queue.append({
                "initiative_id": item["initiative_id"],
                "state": item["state"],
                "title": item["title"],
                "url": url,
                "type": "web",
                "status": "pending"
            })

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(web_queue, f, indent=2, ensure_ascii=False)

print(f"✅ Web queue created with {len(web_queue)} pages")
