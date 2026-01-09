import os
import json
import fitz
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(BASE_DIR, "raw", "pdfs")
OUT_DIR = os.path.join(BASE_DIR, "processed", "pdf_chunks")
MASTER_JSON = os.path.join(BASE_DIR, "pdf_queue.json")

os.makedirs(OUT_DIR, exist_ok=True)

CHAPTER_RE = re.compile(r"(Chapter\s+[IVX]+)", re.IGNORECASE)
SECTION_RE = re.compile(r"(\d+\.\d+(\.\d+)*)")
DROP_KEYWORDS = [
    'Acknowledgement',
    'Table of Contents',
    'List of Tables',
    'List of Figures',
    'Annexure',
    'ISBN',
    'Contact:'
]

def clean(text):
    return " ".join(text.replace("\n", " ").split())

def is_junk_page(text):
    hits = sum(1 for k in DROP_KEYWORDS if k.lower() in text.lower())
    return hits >= 2

def group_by_structure(pages):
    groups = []
    current = {"chapter": None, "section": None, "pages": [], "text": ""}
    
    for p in pages:
        text = p['text']
        chapter_match = CHAPTER_RE.search(text)
        if chapter_match:
            if current["text"]:
                groups.append(current)
            current = {"chapter": chapter_match.group(1), "section": None, "pages": [], "text": ""}
        
        section_match = SECTION_RE.search(text)
        if section_match:
            current["section"] = section_match.group(1)
        
        current["pages"].append(p["page"])
        current["text"] += " " + text
    
    if current["text"]:
        groups.append(current)
    return groups

def chunk_by_tokens(text, max_words=1200):
    words = text.split()
    chunks = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i:i+max_words]))
    return chunks

with open(MASTER_JSON, "r", encoding="utf-8") as f:
    pdfs = json.load(f)


for item in pdfs:
    if item["type"] != "pdf" or item["status"] == "completed":
        continue

    pdf_path = os.path.join(PDF_DIR, item["initiative_id"] + ".pdf")
    if not os.path.exists(pdf_path):
        print("PDF not found:", pdf_path)
        continue

    doc = fitz.open(pdf_path)
    pages = []

   
    for i, page in enumerate(doc):
        text = clean(page.get_text())
        if len(text) > 150 and not is_junk_page(text):
            pages.append({"page": i+1, "text": text})

    if not pages:
        print("No usable text found for", item["initiative_id"])
        continue

    groups = group_by_structure(pages)

    final_chunks = []
    for g in groups:
        text_chunks = chunk_by_tokens(g["text"])
        for t in text_chunks:
            final_chunks.append({
                "chapter": g["chapter"],
                "section": g["section"],
                "pages": g["pages"],
                "text": t
            })

    out_path = os.path.join(OUT_DIR, item["initiative_id"] + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "initiative_id": item["initiative_id"],
            "state": item["state"],
            "title": item["title"],
            "chunks": final_chunks
        }, f, indent=2, ensure_ascii=False)

    item["status"] = "completed"
    with open("pdf_master.json", "w", encoding="utf-8") as f:
        json.dump(pdfs, f, indent=2, ensure_ascii=False)

    print("Processed:", item["initiative_id"])
