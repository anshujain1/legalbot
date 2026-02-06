import requests
from bs4 import BeautifulSoup
from datetime import datetime
from utils import clean_text

BASE_URL = "https://justai.in"
POSTS_API = f"{BASE_URL}/wp-json/wp/v2/posts"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return clean_text(soup.get_text(" "))

def infer_page_type(url: str) -> str:
    if "/blog/" in url:
        return "blog"
    if "/news/" in url:
        return "newsletter"
    return "article"

def wp_post_to_doc(post: dict) -> dict:
    title = BeautifulSoup(
        post["title"]["rendered"], "html.parser"
    ).get_text(strip=True)

    raw_text = html_to_text(post["content"]["rendered"])
    summary = html_to_text(post["excerpt"]["rendered"]) if post.get("excerpt") else None
    url = post["link"]

    doc = {
        "source": "JustAI",
        "source_type": "wp_rest_api",
        "page_type": infer_page_type(url),
        "title": title,
        "url": url,
        "raw_text": raw_text,
        "summary": summary,
        "published_date": post.get("date"),
        "author": post.get("author"),
        "scraped_at": datetime.utcnow().isoformat(),
        "tags": post.get("tags", []),
        "language": "en",
        "reference": {
            "label": f"{title} – JustAI",
            "domain": "justai.in",
            "url": url
        }
    }
    return doc

def fetch_justai_docs(per_page=100, max_pages=10):
    docs = []
    page = 1

    while page <= max_pages:
        params = {"per_page": per_page, "page": page}
        r = requests.get(POSTS_API, headers=HEADERS, params=params)

        if r.status_code != 200:
            break

        posts = r.json()
        if not posts:
            break

        for post in posts:
            docs.append(wp_post_to_doc(post))

        page += 1

    return docs
