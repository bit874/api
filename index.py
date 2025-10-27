# main.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

app = FastAPI(title="Country Outline API", version="1.0.0")

# Enable permissive CORS (GET from any origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

HEADERS = {
    "User-Agent": "CountryOutlineBot/1.0 (+https://example.com; contact=dev@example.com)"
}

def build_wikipedia_url(country: str, lang: str = "en") -> str:
    # Wikipedia uses underscores in path; also percent-encode safely
    slug = quote(country.replace(" ", "_"))
    return f"https://{lang}.wikipedia.org/wiki/{slug}"

def extract_headings_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    # Page title (Wikipedia H1)
    title_el = soup.select_one("#firstHeading")
    title = title_el.get_text(strip=True) if title_el else None

    # Wikipedia article content wrapper
    content = soup.select_one("#mw-content-text .mw-parser-output") or soup

    # Collect headings in order (H2–H6 appear inside content; H1 is the page title above)
    headings = []
    if title:
        headings.append(("#", title))  # H1 as Markdown

    for el in content.find_all(["h2", "h3", "h4", "h5", "h6"]):
        # Remove 'edit' buttons/spans etc. while keeping the visible headline text
        # (get_text(strip=True) handles nested spans)
        text = el.get_text(separator=" ", strip=True)
        # Skip empty or boilerplate headings often present
        if not text:
            continue
        # Wikipedia sometimes appends “[edit]”; strip common bracketed suffix
        if text.endswith("[edit]"):
            text = text[:-6].rstrip()
        level = int(el.name[1])  # 'h2' -> 2
        markdown_prefix = "#" * level
        headings.append((markdown_prefix, text))

    # Assemble Markdown outline (with the "Contents" line as requested)
    lines = ["## Contents", ""]
    for prefix, text in headings:
        lines.append(f"{prefix} {text}")
        lines.append("")  # blank line for readability
    return "\n".join(lines).rstrip() + "\n"

@app.get("/api/outline", response_class=PlainTextResponse)
def outline(
    country: str = Query(..., description="Country name, e.g. 'Vanuatu'"),
    lang: str = Query("en", description="Wikipedia language code, e.g. 'en', 'fr' (optional)"),
):
    """
    Fetches the Wikipedia page for the given country, extracts H1–H6 headings in order,
    and returns a Markdown outline. Response Content-Type: text/markdown.
    """
    wiki_url = build_wikipedia_url(country, lang)

    try:
        resp = requests.get(wiki_url, headers=HEADERS, timeout=15, allow_redirects=True)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Error fetching Wikipedia: {e}")

    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail=f"Wikipedia page not found: {wiki_url}")
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"Wikipedia returned {resp.status_code}")

    md = extract_headings_markdown(resp.text)

    if not md.strip():
        raise HTTPException(status_code=500, detail="Failed to build outline from page HTML.")

    # Serve as Markdown (clients can render or save as .md)
    return PlainTextResponse(content=md, media_type="text/markdown")
