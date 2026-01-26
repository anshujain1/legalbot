import requests, os, json, hashlib, time, traceback
from bs4 import BeautifulSoup
from datetime import datetime

with open("sources_classified.json", "r", encoding="utf-8") as f:
    sources_classified = json.load(f)
    SOURCES = [s for s in sources_classified if s["type"] == "static_html"]

def scrape_static(url: str) -> str:
    r = requests.get(url, timeout=15, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    r.encoding = 'utf-8'
    soup = BeautifulSoup(r.text, 'lxml')

    for tag in soup(['nav', 'footer', 'script', 'style',
                     'header', 'aside', 'iframe', 'noscript']):
        tag.decompose()

    JUNK_WORDS = ['related', 'sidebar', 'ads', 'social', 'share',
                  'comment', 'newsletter', 'recommended', 'trending',
                  'taboola', 'sponsored', 'tags', 'author']

    for tag in soup.find_all(True):
        if not hasattr(tag, 'attrs') or tag.attrs is None:
            continue
        label = ' '.join(tag.attrs.get('class', [])) + ' ' + str(tag.attrs.get('id', ''))
        if any(j in label.lower() for j in JUNK_WORDS):
            tag.decompose()

    main = (soup.find('article') or soup.find('main') or
            soup.find('div', {'class': lambda c: c and 'article' in ' '.join(c).lower()}) or
            soup)
   
    raw_lines = main.get_text(separator='\n', strip=True).split('\n')
    clean_lines = []

    for line in raw_lines:
        line = line.strip()
        if len(line) < 40:
            continue

        line_lower = line.lower()

        HARD_STOP = [
            'murder case', 'iran war', 'israel war', 'viral video',
            'taboola', 'sponsored links', 'download app',
            '(this story has not been edited',
            'auto-generated from pti',
            'पत्रकारिता में', 'फ्रीलांसिंग', 'डिजिटल मीडिया में कार्यरत',
            'वायरल खबरें', 'विज्ञापन'
        ]
        if any(signal in line_lower for signal in HARD_STOP):
            break

        SOFT_JUNK = [
            'read more', 'tags:', 'author:', 'share this',
            'जरूर पढ़ें', 'यह भी पढ़ें', 'ये भी पढ़ें'
        ]
        if any(signal in line_lower for signal in SOFT_JUNK):
            continue

        clean_lines.append(line)

    return '\n'.join(clean_lines)

results = []

for i, source in enumerate(SOURCES):
    url   = source["url"]
    state = source["state"]
    print(f"[{i+1:3}/{len(SOURCES)}] {state:25} | {url[:50]}")

    record = {
        "url": url, "state": state,
        "status": None, "chars": 0,
        "file": None, "error": None,
        "scraped_at": datetime.utcnow().isoformat()
    }

    try:
        text = scrape_static(url)

        if len(text) < 100:
            record["status"] = "empty"
            record["chars"]  = len(text)
            print(f"  SKIP — only {len(text)} chars")

        else:
            folder = f"../../data/raw/{state.lower().replace(' ','_').replace('&','and')}"
            os.makedirs(folder, exist_ok=True)
            fname = hashlib.md5(url.encode()).hexdigest()[:12] + ".json"
            fpath = f"{folder}/{fname}"

            # Skip if already scraped
            if os.path.exists(fpath):
                print(f"  SKIP — already exists")
                record["status"] = "exists"
                record["file"]   = fpath
            else:
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump({
                        "url": url, "state": state,
                        "text": text,
                        "scraped_at": datetime.utcnow().isoformat(),
                        "hash": hashlib.md5(text.encode()).hexdigest()
                    }, f, ensure_ascii=False, indent=2)

                record["status"] = "success"
                record["chars"]  = len(text)
                record["file"]   = fpath
                print(f"  OK — {len(text)} chars → {fpath}")

    except Exception as e:
        record["status"] = "failed"
        record["error"]  = str(e)[:120]
        print(f"  FAIL — {str(e)[:70]}")

    results.append(record)
    time.sleep(0.5)

os.makedirs("../../data/logs", exist_ok=True)
log = {
    "run_at":  datetime.utcnow().isoformat(),
    "total":   len(results),
    "success": len([r for r in results if r["status"] == "success"]),
    "exists":  len([r for r in results if r["status"] == "exists"]),
    "empty":   len([r for r in results if r["status"] == "empty"]),
    "failed":  len([r for r in results if r["status"] == "failed"]),
    "results": results
}
with open("../../data/logs/scrape_summary.json", "w") as f:
    json.dump(log, f, indent=2)


print(f"\n{'='*55}")
print(f"  success: {log['success']}  |  exists: {log['exists']}  |  empty: {log['empty']}  |  failed: {log['failed']}")
print(f"  log → data/logs/scrape_summary.json")

if log["failed"] > 0:
    print(f"\n  Failed URLs:")
    for r in [r for r in results if r["status"] == "failed"]:
        print(f"    [{r['state']:20}] {r['url'][:55]}")
        print(f"      {r['error']}")