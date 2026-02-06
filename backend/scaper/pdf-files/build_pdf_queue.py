import json
import os 

INPUT_FILE = "data/initiatives_index.json"
OUTPUT_FILE = "data/pdf_queue.json"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    initiatives = json.load(f)["initiatives"]


pdf_queue = []

for item in initiatives:
    for url in item['urls']:
        if url.lower().endswith(".pdf"):
            pdf_queue.append({
                "initiative_id": item["initiative_id"],
                "state": item["state"],
                "title": item["title"],
                "url": url,
                "type": "pdf",
                "status": "pending",
                "processed_pages": 0
            })

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(pdf_queue, f, indent=2, ensure_ascii=False)


print(f"PDF queue created with {len(pdf_queue)} PDFs")