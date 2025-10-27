from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
import requests
from bs4 import BeautifulSoup

app = FastAPI(title="Country Wikipedia Outline API")

# CORS: allow any origin for GET
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

WIKI_API = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "CountryOutlineAPI/1.0 (+https://github.com/your/repo; contact: you@example.com)"
}

def get_canonical_wiki_page(country: str):
    params = {
        "action": "query",
        "format": "json",
        "prop": "info",
        "inprop": "url",
        "redirects": 1,
        "titles": country.strip(),
    }
    r = requests.get(WIKI_API, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    pages = data.get("query", {}).get("pages", {})
    if not pages or list(pages.keys())[0] == "-1":
        return None, None
    page = next(iter(pages.values()))
    return page.get("canonicalurl"), page.get("title")

def extract_headings_markdown(html: str, page_title: str):
    soup = BeautifulSoup(html, "html.parser")
    headings = []
    for tag in soup.find_all(["h1","h2","h3","h4","h5","h6"]):
        text_el = tag.find(class_="mw-headline")
        text = (text_el.get_text(strip=True) if text_el else tag.get_text(strip=True)) or ""
        if not text:
            continue
        level = int(tag.name[1])
        headings.append((level, text))

    # If first H1 equals title, skip it; we'll add our own "# <title>"
    if headings and headings[0][0] == 1 and page_title and headings[0][1].strip().lower() == page_title.strip().lower():
        headings = headings[1:]

    lines = ["## Contents", "", f"# {page_title}", ""]
    for level, text in headings:
        lines.append(f"{'#' * max(1, min(6, level))} {text}")

    return "\n".join(lines)

# IMPORTANT: route is "/" so final URL is /api/outline?country=...
@app.get("/", response_class=PlainTextResponse)
def outline(country: str = Query(..., description="Country name (e.g., Vanuatu)")):
    url, title = get_canonical_wiki_page(country)
    if not url or not title:
        raise HTTPException(status_code=404, detail="Country page not found on Wikipedia.")
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if not resp.ok:
        raise HTTPException(status_code=502, detail="Failed to fetch Wikipedia page.")
    markdown = extract_headings_markdown(resp.text, title)
    return PlainTextResponse(content=markdown, media_type="text/markdown")

@app.get("/health")
def health():
    return {"ok": True}
