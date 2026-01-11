import os
import json
import fitz
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(BASE_DIR, "raw", "pdfs")
OUT_DIR = os.path.join(BASE_DIR, "processed", "pdf_chunks")
MASTER_JSON = os.path.join(BASE_DIR, "scripts", "pdf_master.json")

import os, json, re, fitz

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PDF_DIR = os.path.join(BASE_DIR, "raw", "pdfs")
OUT_DIR = os.path.join(BASE_DIR, "processed", "pdf_chunks")
MASTER_JSON = os.path.join(BASE_DIR, "scripts", "pdf_master.json")

os.makedirs(OUT_DIR, exist_ok=True)


CHUNK_SIZE = 400          
OVERLAP = 70              
MIN_CHUNK = 150           

CHAPTER_RE = re.compile(r"(Chapter\s+[IVX]+)", re.IGNORECASE)
SECTION_RE = re.compile(r"(\d+(\.\d+)+)")
DROP_KEYWORDS = [
    "table of contents", "acknowledgement", "isbn",
    "list of figures", "list of tables", "annexure"
]

def clean(text):
    return " ".join(text.replace("\n", " ").split())

def is_junk(text):
    return sum(1 for k in DROP_KEYWORDS if k in text.lower()) >= 2

def chunk_text(words):
    chunks = []
    i = 0
    while i < len(words):
        chunk = words[i:i + CHUNK_SIZE]
        chunks.append(" ".join(chunk))
        i += CHUNK_SIZE - OVERLAP
    return chunks

with open(MASTER_JSON, "r", encoding="utf-8") as f:
    pdfs = json.load(f)

for item in pdfs:
    if item["type"] != "pdf" or item["status"] == "completed":
        continue

    pdf_path = os.path.join(PDF_DIR, item["initiative_id"] + ".pdf")
    if not os.path.exists(pdf_path):
        print("Missing PDF:", pdf_path)
        continue

    doc = fitz.open(pdf_path)
    last_chapter, last_section = None, None
    final_chunks = []

    for page_no, page in enumerate(doc, start=1):
        text = clean(page.get_text())
        if len(text) < 150 or is_junk(text):
            continue

        chap = CHAPTER_RE.search(text)
        sec = SECTION_RE.search(text)

        if chap:
            last_chapter = chap.group(1)
        if sec:
            last_section = sec.group(1)

        words = text.split()
        page_chunks = chunk_text(words)

        for ch in page_chunks:
            if len(ch.split()) < MIN_CHUNK:
                continue

            final_chunks.append({
                "initiative_id": item["initiative_id"],
                "source_type": "pdf",
                "url": item.get("url"),
                "state": item["state"],
                "title": item["title"],
                "chapter": last_chapter,
                "section": last_section,
                "pages": [page_no],
                "text": ch
            })

    if not final_chunks:
        print("No usable content:", item["initiative_id"])
        continue

    out_path = os.path.join(OUT_DIR, item["initiative_id"] + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(final_chunks, f, indent=2, ensure_ascii=False)

    item["status"] = "completed"
    print("Processed PDF:", item["initiative_id"])

with open(MASTER_JSON, "w", encoding="utf-8") as f:
    json.dump(pdfs, f, indent=2, ensure_ascii=False)
