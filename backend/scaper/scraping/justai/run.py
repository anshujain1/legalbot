from ingest import fetch_justai_docs
from storage import save_raw

def main():
    print("Fetching JustAI data...")
    docs = fetch_justai_docs()
    print(f"Found {len(docs)} docs")

    for doc in docs:
        save_raw(doc)

if __name__ == "__main__":
    main()
