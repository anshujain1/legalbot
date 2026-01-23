import json
import os
from fetchers.static_fetch import fetch_static
from fetchers.browser_fetch import fetch_browser

with open("raw/grouped_urls.json") as f:
    grouped = json.load(f)

with open("domain_rules.json") as f:
    rules = json.load(f)

OUTPUT_DIR = "clean_text"
os.makedirs(OUTPUT_DIR, exist_ok=True)

for domain, items in grouped.items():
    rule = rules.get(domain)
    if not rule:
        continue  # skip unknown domains for now

    for item in items:
        url = item["url"]

        if rule["fetch"] == "static":
            text = fetch_static(url)
        elif rule["fetch"] == "browser":
            text = fetch_browser(url)

        if not text or len(text) < 800:
            continue  # quality gate

        save_path = os.path.join(OUTPUT_DIR, item["initiative_id"] + ".txt")
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(text)
