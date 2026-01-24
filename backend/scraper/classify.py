import requests
from bs4 import BeautifulSoup

def classify_url(url: str) -> str:

    if url.lower().endswith(".pdf"):
        return "pdf"

    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})

        if r.status_code >= 400:
            return f"error: HTTP {r.status_code}"
        
        content_type = r.headers.get("Content-Type", "").lower()
        if "application/pdf" in content_type:
            return "pdf"

        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()

        text = soup.get_text(strip=True)

        if len(text) < 500:
            return "js_rendered"

        return "static_html"

    except Exception as e:
        return f"error: {str(e)[:50]}"