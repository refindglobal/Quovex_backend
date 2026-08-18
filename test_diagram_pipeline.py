"""
FINAL TEST: Full pipeline for actual student questions
- Human brain diagram (Wikipedia image expected)
- Trigonometry explanation diagram (SVG expected)
"""
import sys, os, re, time
import httpx
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))
from app.config import settings

CEREBRAS_KEY = (settings.CEREBRAS_API_KEYS or settings.CEREBRAS_API_KEY or "").split(",")[0].strip()


def fetch_wiki_image(query: str):
    """Wikipedia REST API with Action API fallback."""
    slug = query.replace(" ", "_")
    try:
        with httpx.Client(timeout=8, follow_redirects=True, headers={
            "User-Agent": "QuovexAI/1.0 (educational; https://quovex.app)",
            "Accept": "application/json",
        }) as client:
            # Try REST first
            r = client.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}")
            if r.status_code == 200:
                d = r.json()
                img = d.get("thumbnail", {}).get("source", "")
                title = d.get("title", query)
                extract = d.get("extract", "")[:300]
                if img and "svg" not in img.lower():
                    return img, title, extract

            # Action API fallback
            sr = client.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search",
                "srsearch": query, "srlimit": 1, "format": "json"
            })
            if sr.status_code == 200:
                hits = sr.json().get("query", {}).get("search", [])
                if hits:
                    title = hits[0]["title"]
                    pr = client.get("https://en.wikipedia.org/w/api.php", params={
                        "action": "query", "titles": title,
                        "prop": "pageimages|extracts",
                        "pithumbsize": 600, "pilicense": "any",
                        "exintro": True, "exsentences": 2, "explaintext": True,
                        "redirects": 1, "format": "json"
                    })
                    if pr.status_code == 200:
                        for page in pr.json().get("query", {}).get("pages", {}).values():
                            img = page.get("thumbnail", {}).get("source", "")
                            if img and "svg" not in img.lower():
                                return img, title, page.get("extract", "")[:300]
    except Exception as e:
        print(f"   Wiki error: {e}")
    return None


def cerebras_text_verify(page_title: str, page_extract: str, question: str) -> bool:
    """Text-based Cerebras verification: does the Wikipedia article match the question?"""
    prompt = (
        f"Student question: '{question}'\n"
        f"Wikipedia article title: '{page_title}'\n"
        f"Article preview: {page_extract}\n\n"
        f"Does this Wikipedia article DIRECTLY illustrate or answer the student's question?\n"
        f"Answer ONLY: YES or NO"
    )
    try:
        with httpx.Client(timeout=12) as client:
            r = client.post("https://api.cerebras.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {CEREBRAS_KEY}", "Content-Type": "application/json"},
                json={"model": settings.CEREBRAS_MODEL,
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.0, "max_tokens": 5})
            if r.status_code == 200:
                ans = r.json()["choices"][0]["message"]["content"].strip().upper()
                return "YES" in ans
    except Exception as e:
        print(f"   Verify error: {e}")
    return True  # trust on error


def cerebras_generate_svg(question: str, retries=3) -> str:
    svg_prompt = (
        f"Draw a clean, labeled educational SVG diagram for: '{question}'\n"
        "Output ONLY raw <svg>...</svg>, no markdown, no explanation outside SVG.\n"
        "Dark theme: background #1E1E2A, text #E8E8F0, accent #6C63FF.\n"
        "width=400 height=300 viewBox='0 0 400 300'. Label each part clearly."
    )
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=25) as client:
                r = client.post("https://api.cerebras.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {CEREBRAS_KEY}", "Content-Type": "application/json"},
                    json={"model": settings.CEREBRAS_MODEL,
                          "messages": [{"role": "user", "content": svg_prompt}],
                          "temperature": 0.3, "max_tokens": 2000})
                if r.status_code == 200:
                    return r.json()["choices"][0]["message"]["content"].strip()
                if r.status_code == 429:
                    print(f"   Rate limited, waiting 8s (attempt {attempt+1})...")
                    time.sleep(8)
        except Exception as e:
            print(f"   SVG error: {e}")
    return ""


def solve_diagram(question: str, subject_hint: str = ""):
    """Full pipeline: try Wikipedia image → verify → show. Else SVG."""
    print(f"\n{'='*55}")
    print(f"QUESTION: {question!r}")
    print(f"{'='*55}")

    # 1. Build search query
    query = re.sub(r"\b(draw|diagram|of the|of a|a|an|the|please|show me|explain)\b", "", question.lower()).strip()
    if not query:
        query = question
    print(f"Search query: {query!r}")

    # 2. Try Wikipedia
    wiki = fetch_wiki_image(query)
    if wiki:
        img_url, title, extract = wiki
        print(f"Wikipedia image: {title} -> {img_url[:70]}...")

        # 3. Text-verify with Cerebras
        verified = cerebras_text_verify(title, extract, question)
        print(f"Cerebras text verify: {verified}")

        if verified:
            html = (
                '<!DOCTYPE html><html><head>'
                '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
                '<style>body{margin:0;padding:12px;background:#1E1E2A;font-family:sans-serif;}'
                'img{width:100%;border-radius:12px;display:block;max-height:280px;object-fit:contain;}'
                '.caption{color:#9898B0;font-size:11px;text-align:center;padding:6px 0 2px;}'
                '.source{color:#6C63FF;font-size:10px;text-align:center;}'
                '</style></head><body>'
                f'<img src="{img_url}" alt="{title}" />'
                f'<p class="caption">{title}</p>'
                '<p class="source">Source: Wikipedia</p>'
                '</body></html>'
            )
            print(f"RESULT: REAL IMAGE (Wikipedia)")
            print(f"HTML length: {len(html)} chars")
            print(f"Image URL: {img_url}")
            return "image", html
        else:
            print("Cerebras rejected the image - falling back to SVG")

    # 4. SVG Fallback
    print("Generating SVG via Cerebras...")
    svg = cerebras_generate_svg(question)
    svg = re.sub(r"```[a-zA-Z]*\n?", "", svg).replace("```", "").strip()

    if "<svg" in svg.lower():
        html = (
            '<!DOCTYPE html><html><head>'
            '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
            '<style>body{margin:0;padding:12px;background:#1E1E2A;}'
            'svg{width:100%;height:auto;display:block;}'
            '</style></head><body>'
            f'{svg}'
            '</body></html>'
        )
        print(f"RESULT: SVG FALLBACK, {len(svg)} chars")
        print(f"SVG preview:\n{svg[:300]}")
        return "svg", html
    else:
        print(f"FAIL: Neither image nor SVG worked")
        return "none", ""


# ─────────────────────────────────────────────────────────────
print("FINAL PIPELINE TEST")

q1_type, q1_html = solve_diagram("draw a diagram of human brain")
q2_type, q2_html = solve_diagram("trigonometry explanation diagram", subject_hint="Mathematics")

print("\n" + "="*55)
print("FINAL RESULTS")
print("="*55)
print(f"Human brain:    {q1_type.upper()} ({'OK' if q1_html else 'FAIL'})")
print(f"Trigonometry:   {q2_type.upper()} ({'OK' if q2_html else 'FAIL'})")
