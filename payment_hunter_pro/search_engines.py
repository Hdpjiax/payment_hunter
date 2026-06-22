"""Motores de búsqueda para Google Dorking.

GoogleEngine (default): Usa googlesearch-python — soporta TODOS los operadores
de Google (inurl:, site:, intitle:, filetype:, "exact match", etc.)

DDGSEngine (fallback): DuckDuckGo Search.
"""
import logging
from typing import List

logger = logging.getLogger(__name__)


class SearchEngine:
    """Interfaz base para motores de búsqueda."""
    def search(self, dork: str, max_results: int = 10) -> List[str]:
        raise NotImplementedError


class GoogleEngine(SearchEngine):
    """Google Search via googlesearch-python.

    Soporta todos los operadores de Google Dorks:
    - inurl: / intext: / intitle: / filetype:
    - site:.mx / site:.com
    - "exact match"
    - OR / AND / -exclude

    Incluye delay entre queries para evitar bloqueos.
    """

    def __init__(self, sleep_interval: float = 3.0):
        self.sleep_interval = sleep_interval

    def search(self, dork: str, max_results: int = 10) -> List[str]:
        try:
            from googlesearch import search
            results = list(search(
                dork,
                num_results=max_results,
                sleep_interval=self.sleep_interval,
            ))
            logger.info(f"Google: {len(results)} resultados para '{dork[:80]}'")
            return results
        except Exception as e:
            logger.warning(f"Google error ({type(e).__name__}): {e}")
            logger.info("Intentando fallback a DuckDuckGo...")
            try:
                return DDGSEngine().search(dork, max_results)
            except Exception:
                return []


class DDGSEngine(SearchEngine):
    """DuckDuckGo Search (fallback).

    NOTA: No soporta operadores avanzados como inurl: o site:.
    Útil como fallback cuando Google bloquea.
    """

    def search(self, dork: str, max_results: int = 10) -> List[str]:
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = [r['href'] for r in ddgs.text(dork, max_results=max_results) if r.get('href')]
                logger.info(f"DuckDuckGo: {len(results)} resultados")
                return results
        except Exception as e:
            logger.warning(f"DuckDuckGo error: {e}")
            return []