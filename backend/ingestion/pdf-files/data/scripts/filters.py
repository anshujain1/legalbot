DROP_KEYWORDS = [
    "acknowledgement",
    "special acknowledgement",
    "list of",
    "former",
    "advisor",
    "officer",
    "team members",
    "personnel",
    "isbn",
    "copyright",
    "all rights reserved"
]

def is_junk(text: str) -> bool:
    text_l = text.lower()
    hits = sum(1 for k in DROP_KEYWORDS if k in text_l)
    return hits >= 2 or len(text.split()) < 40
