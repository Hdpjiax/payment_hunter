"""Abstracción simple de motores de búsqueda.
Mantener ligero (sin deps extras pesadas).
"""
import urllib.parse
import urllib.request
import re
from typing import List

class SearchEngine:
    def search(self, dork: str, max_results: int = 12) -> List[str]:
        raise NotImplementedError

class DDGSEngine(SearchEngine):
    def search(self, dork: str, max_results: int = 12) -> List[str]:
        from ddgs import DDGS
        try:
            with DDGS() as ddgs:
                return [r['href'] for r in ddgs.text(dork, max_results=max_results) if r.get('href')]
        except Exception:
            return []

class BingEngine(SearchEngine):
    """Bing básico usando urllib (sin API key). Crudo pero funcional."""
    def search(self, dork: str, max_results: int = 12) -> List[str]:
        try:
            query = urllib.parse.quote(dork)
            url = f"https://www.bing.com/search?q={query}&count={max_results}"
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as response:
                html = response.read().decode('utf-8', errors='ignore')
            # Extraer links de resultados (regex simple)
            links = re.findall(r'<a href="(https?://[^"]+)"[^>]*>.*?</a>', html)
            clean = []
            for l in links:
                if 'bing.com' not in l and 'microsoft.com' not in l and l not in clean:
                    clean.append(l)
                if len(clean) >= max_results:
                    break
            return clean
        except Exception:
            return []