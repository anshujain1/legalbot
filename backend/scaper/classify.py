import requests 
from bs4 import BeautifulSoup
def classify_url(url: str) -> str:

    if url.lower().endswith(".pdf"):
        return 'pdf'
    
    try:
        r= requests.get(url, timeout= 10 , headers={ 'User-agent' : 'Mozilla/5.0'})
        soup = BeautifulSoup(r.text, "html.parser")

        for tags in soup(["script", "style"]):
            tags.decompose()

        text = soup.get_text(strip = True)

        if len(text) < 500:
            return 'js_rendered'
        
        return 'static_html'
    
    except Exception as e:
        return f'error: {str(e)[:50]}'
