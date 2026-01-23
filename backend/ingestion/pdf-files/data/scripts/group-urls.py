import json
from urllib.parse import urlparse
from collections import defaultdict
import os 

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE= os.path.join(BASE_DIR, "web_queue.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "raw", "grouped_urls.json")

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

groups = defaultdict(list)

for item in data:
    url = item["url"]
    domain = urlparse(url).netloc.replace("www.", "")
    groups[domain].append(item)

grouped = {domain: items for domain, items in groups.items()}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(grouped, f, indent=2, ensure_ascii=False)

print("URLs grouped by domain and saved to grouped_urls.json")
print(len(groups.keys()) )
