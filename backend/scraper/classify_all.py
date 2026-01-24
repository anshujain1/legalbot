import json
import time
from collections import Counter

from classify import classify_url

with open("sources.json") as f:
    sources = json.load(f)

for i, s in enumerate(sources):
    s["type"] = classify_url(s["url"])
    short_url = s["url"][:60]
    print(f'[{i + 1}/{len(sources)}] {s["type"]:20} | {s["state"]:20} | {short_url}')
    time.sleep(0.5)

    if (i + 1) % 20 == 0:
        with open("sources_classified.json", "w") as f:
            json.dump(sources, f, indent=2)

with open("sources_classified.json", "w") as f:
    json.dump(sources, f, indent=2)

print("\nSummary of the classification is as follows:")
print(Counter(s["type"] for s in sources))