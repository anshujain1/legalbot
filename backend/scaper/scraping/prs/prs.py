import requests
from bs4 import BeautifulSoup
import json
import pandas as pd
import time
import random

# --- Base URLs ---
BASE_URL = "https://prsindia.org"
BILLTRACK_URL = f"{BASE_URL}/billtrack"

# --- Keywords for AI relevance ---
AI_KEYWORDS = [
    'artificial intelligence', 'machine learning', 'deep learning',
    'ai', 'neural network', 'robotics', 'autonomous system',
    'computer vision', 'natural language processing', 'chatbot'
]

# --- Headers ---
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
}

# --- Check if text is AI-relevant ---
def is_ai_relevant(text):
    if not text:
        return False
    text = text.lower()
    return any(keyword in text for keyword in AI_KEYWORDS)

# --- Extract details from each bill page ---
def get_bill_details(url):
    try:
        res = requests.get(url, headers=HEADERS)
        soup = BeautifulSoup(res.text, 'lxml')

        def extract(selector):
            tag = soup.select_one(selector)
            return tag.text.strip() if tag else "N/A"

        summary = extract('.field-type-text-with-summary')
        status = extract('.field-name-field-bill-status .field-item')
        ministry = extract('.field-name-field-ministry .field-item')

        pdf_tag = soup.find('a', href=True, text=lambda t: t and 'Download' in t)
        pdf_link = BASE_URL + pdf_tag['href'] if pdf_tag else "N/A"

        return {
            "summary": summary,
            "status": status,
            "ministry": ministry,
            "pdf_link": pdf_link
        }
    except Exception as e:
        print(f"Error getting bill details from {url}: {e}")
        return {"summary":"N/A","status":"N/A","ministry":"N/A","pdf_link":"N/A"}

# --- Main scraper ---
def scrape_ai_bills():
    print("Scraping PRS for AI-related bills...")
    try:
        response = requests.get(BILLTRACK_URL, headers=HEADERS)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error accessing PRSIndia: {e}")
        return

    soup = BeautifulSoup(response.text, 'lxml')
    rows = soup.select(".views-row")
    print(f"Found {len(rows)} bills total")

    ai_bills = []

    for i, row in enumerate(rows, start=1):
        title_tag = row.find("a")
        if not title_tag:
            continue

        title = title_tag.text.strip()
        href = title_tag.get("href")
        url = BASE_URL + href if href else "N/A"

        date_tag = row.select_one('.date-display-single')
        published_on = date_tag.text.strip() if date_tag else "N/A"

        print(f"\n[{i}] Checking: {title}")

        # Get details from bill page
        details = get_bill_details(url)

        # Filter only AI-related
        if is_ai_relevant(title) or is_ai_relevant(details["summary"]):
            print(f"Relevant AI bill found: {title}")
            ai_bills.append({
                "title": title,
                "url": url,
                "published_on": published_on,
                **details
            })
        else:
            print("Not AI-related.")

        time.sleep(random.uniform(0.5, 1.5))

    # Save to JSON & CSV
    with open("prs_ai_bills.json", "w", encoding="utf-8") as f:
        json.dump(ai_bills, f, indent=2, ensure_ascii=False)

    pd.DataFrame(ai_bills).to_csv("prs_ai_bills.csv", index=False)

    print(f"\nDone! {len(ai_bills)} AI-related bills saved as:")
    print(" - prs_ai_bills.json")
    print(" - prs_ai_bills.csv")

if __name__ == "__main__":
    scrape_ai_bills()
