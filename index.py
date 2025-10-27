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
    "User-Agent": "CountryOutlineBot/1.0 (+https://example.com; contact: you@example.com)"
}

def get_canonical_wiki_page(country: str):
    """
    Use MediaWiki API to resolve the canonical Wikipedia URL & normalized title.
    """
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
    """
    Parse HTML and extract headings H1..H6 (in order). Skip the first H1
    because we'll render '# <page_title>' ourselves. Build Markdown outline.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Collect headings in document order
    tags = ["h1", "h2", "h3", "h4", "h5", "h6"]
    headings = []
    for tag in soup.find_all(tags):
        # Prefer the visible headline text (mw-headline), fallback to the tag text
        text_el = tag.find(class_="mw-headline")
        text = (text_el.get_text(strip=True) if text_el else tag.get_text(strip=True)) or ""
        if not text:
            continue
        level = int(tag.name[1])
        headings.append((level, text))

    # If the document H1 equals the page title, drop it; we'll add our own '# Title'
    if headings and headings[0][0] == 1 and headings[0][1].lower() == (page_title or "").lower():
        headings = headings[1:]

    # Build Markdown
    lines = []
    lines.append("## Contents")
    lines.append("")  # spacer
    lines.append(f"# {page_title}")
    lines.append("")
    for level, text in headings:
        # Headings should begin with # in Markdown; cap at reasonable levels
        level = max(1, min(6, level))
        lines.append(f"{'#' * level} {text}")

    return "\n".join(lines)

@app.get("/api/outline", response_class=PlainTextResponse)
def outline(country: str = Query(..., description="Country name (e.g., Vanuatu)")):
    url, title = get_canonical_wiki_page(country)
    if not url or not title:
        raise HTTPException(status_code=404, detail="Country page not found on Wikipedia.")

    # Fetch canonical page HTML
    resp = requests.get(url, headers=HEADERS, timeout=20)
    if not resp.ok:
        raise HTTPException(status_code=502, detail="Failed to fetch Wikipedia page.")

    markdown = extract_headings_markdown(resp.text, title)
    return PlainTextResponse(content=markdown, media_type="text/markdown")
