import json 
from classify import classify_url
from collections import Counter
import time 

with open("sources.json") as f:
    sources = json.load(f)

for i, s in enumerate(sources):
    s["type"] = classify_url(s["url"])
    print(f"[{i+1}/{len(sources)}] {s["type"]:20} | {s["type"]:20} | {s["url"]}[:60]")
    time.sleep(0.5)

    
with open("sources_classified.json") as f:
    json.dump(sources, f , indent=2 )

print("Summary of the classification is as follows")
print(Counter(s[type]) for s in sources)