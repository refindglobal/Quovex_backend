import httpx
import re
import json
from html import unescape

def search_ddg_api(query: str) -> str:
    """Method 1: DuckDuckGo instant answer / search API"""
    try:
        url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1&skip_disambig=1"
        with httpx.Client(timeout=8, headers={"User-Agent": "Mozilla/5.0"}) as client:
            r = client.get(url)
            if r.status_code == 200:
                data = r.json()
                abstract = data.get("AbstractText", "")
                heading = data.get("Heading", "")
                related = data.get("RelatedTopics", [])
                snippets = []
                if abstract:
                    snippets.append(f"{heading}: {abstract}")
                for item in related[:3]:
                    if isinstance(item, dict) and item.get("Text"):
                        snippets.append(item.get("Text"))
                if snippets:
                    return "\n\n".join(snippets)
    except Exception as e:
        print("API error:", e)
    return ""

def search_ddg_html(query: str) -> str:
    """Method 2: DuckDuckGo HTML endpoint with standard httpx"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        with httpx.Client(timeout=8, follow_redirects=True, headers=headers) as client:
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": query})
            if resp.status_code == 200:
                text = resp.text
                matches = re.findall(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', text, re.DOTALL)
                snippets = []
                for m in matches[:4]:
                    clean = re.sub(r"<.*?>", "", m).strip()
                    if clean:
                        snippets.append(unescape(clean))
                if snippets:
                    return "\n\n".join(snippets)
    except Exception as e:
        print("HTML error:", e)
    return ""

def search_wikipedia_api(query: str) -> str:
    """Method 3: Wikipedia API for entity lookups"""
    try:
        headers = {"User-Agent": "QuovexTutorBot/1.0 (study@quovex.online)"}
        url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=3&namespace=0&format=json"
        with httpx.Client(timeout=8, headers=headers) as client:
            r = client.get(url)
            if r.status_code == 200:
                data = r.json()
                titles = data[1] if len(data) > 1 else []
                descriptions = data[2] if len(data) > 2 else []
                snippets = []
                for t, d in zip(titles, descriptions):
                    if d:
                        snippets.append(f"{t}: {d}")
                if snippets:
                    return "\n\n".join(snippets)
    except Exception as e:
        print("Wiki error:", e)
    return ""

def multi_search(query: str) -> str:
    # 1. Try DuckDuckGo HTML
    s = search_ddg_html(query)
    if s:
        return s
    # 2. Try DuckDuckGo API
    s = search_ddg_api(query)
    if s:
        return s
    # 3. Try Wikipedia
    s = search_wikipedia_api(query)
    if s:
        return s
    return ""

if __name__ == "__main__":
    queries = [
        "chief minister of tamil nadu 2026",
        "chief minister of bihar 2026",
        "current president of usa 2026"
    ]
    for q in queries:
        print(f"\n================ QUERY: {q} ================")
        res = multi_search(q)
        print("RESULT:\n", res[:400] if res else "NO RESULT")
