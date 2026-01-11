import json, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(BASE_DIR, "processed", "pdf_chunks")

for file in os.listdir(DIR):
    if not file.endswith(".json"):
        continue

    path = os.path.join(DIR, file)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    normalized = []
    for ch in data.get("chunks", []):
        words = ch["text"].split()
        for i in range(0, len(words), 400):
            normalized.append({
                **ch,
                "text": " ".join(words[i:i+400])
            })

    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)

    print("Normalized:", file)
