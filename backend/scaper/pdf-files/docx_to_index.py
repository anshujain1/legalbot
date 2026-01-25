import os 
import re
import json 
from docx import Document
from datetime import datetime

STATE_DOCS='State-wise AI initiatives'
OUTPUT_FILE='data/initiatives_index.json'

os.makedirs("data", exist_ok=True)
CANONICAL_STATES = {
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh",
    "Goa", "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand",
    "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
    "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Jammu And Kashmir", "Ladakh", "Delhi",'Puducherry','lakshadweep'
}
VALID_STATES = {s.lower() for s in CANONICAL_STATES}


def infer_state_name(filename):
    name = filename.lower()
    name = name.replace(".docx", "")

    # remove common noise phrases
    name = re.sub(r"ai\s*initiatives?", "", name)
    name = re.sub(r"\bai\b", "", name)
    name = re.sub(r"\bin\b", "", name)

    # normalize separators
    name = name.replace("_", " ").replace("-", " ")

    # clean symbols
    name = name.replace("&", "and")

    # collapse spaces
    name = re.sub(r"\s+", " ", name).strip()
    if name not in VALID_STATES:
        print(f"Unknown state inferred: '{name}' from '{filename}'")

    return name.title()

def normalize_header(text):
    return re.sub(r'\s+', ' ', text.strip().lower())


URL_REGEX = re.compile(
    r'((?:https?://|www\.)[^\s\)\]]+|'
    r'\b[a-zA-Z0-9.-]+\.(?:gov|nic|org|in|com|edu|net)[^\s\)\]]*)',
    re.I
)
def extract_urls(text):
    if not text:
        return []
    text = text.replace("\n", " ")
    urls = URL_REGEX.findall(text)
    clean = []
    for u in urls:
        u=u.strip(").,;\"'")
        if not u.startswith("http"):
            u= "https://" + u
        clean.append(u)

    return list(set(clean))

HEADER_MAP = {
    # TITLE
    "title of initiative": "title",
    "initiative": "title",
    "initiative / framework": "title",
    "initiative (owner)": "title",
    "initiative (owner/agency)": "title",
    "initiative (short name)": "title",
    "title": "title",
    "title (link)": "title",

    # DESCRIPTION
    "what it is (short)": "description",
    "description": "description",
    "brief description": "description",
    "brief description (with link)": "description",
    "brief description (with short link)": "description",
    "brief description (includes source)": "description",
    "brief description (with government / official source)": "description",
    "brief description (with source link)": "description",
    "brief description (with short source)": "description",
    "brief description (with source)": "description",
    "brief description & source": "description",
    "brief description & link": "description",
    "one-liner description": "description",
    "one-line description": "description",
    "status / note & source": "description",
   "brief description with source": "description",

    # YEAR
    "year": "year",
    "launch year": "year",
    "launch/year": "year",
    "year/launch": "year",
    "launch / year": "year",
}



def normalize_row(row):
    clean = {}
    for k, v in row.items():
        header = normalize_header(k)
        key = HEADER_MAP.get(header)
        if key and v and v.strip():
            clean[key] = v.strip()
    return clean


def extract_from_docx(path, state):
    doc=Document(path)
    initiatives = []

    for table in doc.tables:
        headers = [normalize_header(c.text) for c in table.rows[0].cells]

        for idx,row in enumerate(table.rows[1:], start=1):
            values= [c.text.strip() for c in row.cells]
            raw=dict(zip(headers, values))
            clean=normalize_row(raw)

            if not clean:
                continue
            full_text = " ".join(values)
            urls= extract_urls(full_text)

            initiatives.append({
                "initiative_id": f"{state[:2].upper()}_{idx}",
                "state": state,
                "title": clean.get("title"),
                "year": clean.get("year"),
                "description":  clean.get("description"),
                "urls": urls
            })

    return initiatives
    
all_data = []

for file in os.listdir(STATE_DOCS):
    if not file.lower().endswith('.docx') or file.startswith('~$'):
        continue

    state = infer_state_name(file)
    path = os.path.join(STATE_DOCS, file)

    initiatives = extract_from_docx(path, state)
    all_data.extend(initiatives)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump({
        "generated_at": datetime.utcnow().isoformat(),
        "initiatives": all_data
    }, f, indent=2, ensure_ascii=False)

print("DOCX to initiative index created")