import httpx
import re
import json
from html import unescape

def search_live_web(query: str, max_results: int = 4) -> str:
    """Robust multi-source live web search with 0 external dependencies (using httpx)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    # 1. Try DuckDuckGo HTML
    try:
        with httpx.Client(timeout=6, follow_redirects=True, headers=headers) as client:
            resp = client.post("https://html.duckduckgo.com/html/", data={"q": query})
            if resp.status_code == 200:
                text = resp.text
                matches = re.findall(r'<a class="result__snippet[^"]*"[^>]*>(.*?)</a>', text, re.DOTALL)
                snippets = []
                for m in matches[:max_results]:
                    clean = re.sub(r"<.*?>", "", m).strip()
                    if clean:
                        snippets.append(unescape(clean))
                if snippets:
                    return "\n\n".join(snippets)
    except Exception:
        pass

    # 2. Try DuckDuckGo Lite
    try:
        with httpx.Client(timeout=6, follow_redirects=True, headers=headers) as client:
            resp = client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
            if resp.status_code == 200:
                text = resp.text
                matches = re.findall(r'<td class="result-snippet">(.*?)</td>', text, re.DOTALL)
                snippets = []
                for m in matches[:max_results]:
                    clean = re.sub(r"<.*?>", "", m).strip()
                    if clean:
                        snippets.append(unescape(clean))
                if snippets:
                    return "\n\n".join(snippets)
    except Exception:
        pass

    # 3. Try duckduckgo_search library if available
    try:
        from duckduckgo_search import DDGS
        results = list(DDGS().text(query, max_results=max_results))
        if results:
            snippets = [f"{r.get('title', '')}: {r.get('body', '')}" for r in results if r.get('body')]
            if snippets:
                return "\n\n".join(snippets)
    except Exception:
        pass

    # 4. Try Wikipedia OpenSearch API
    try:
        wiki_url = f"https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=3&namespace=0&format=json"
        with httpx.Client(timeout=6, headers={"User-Agent": "QuovexTutorBot/1.0"}) as client:
            r = client.get(wiki_url)
            if r.status_code == 200:
                data = r.json()
                titles = data[1] if len(data) > 1 else []
                descriptions = data[2] if len(data) > 2 else []
                snippets = [f"{t}: {d}" for t, d in zip(titles, descriptions) if d]
                if snippets:
                    return "\n\n".join(snippets)
    except Exception:
        pass

    return ""

if __name__ == "__main__":
    for q in [
        "chief minister of tamil nadu 2026",
        "chief minister of bihar 2026",
        "who is the president of the united states 2026",
        "current prime minister of india 2026"
    ]:
        print(f"\n================ QUERY: {q} ================")
        res = search_live_web(q)
        print("RESULT:\n", res[:400] if res else "NO RESULT")
