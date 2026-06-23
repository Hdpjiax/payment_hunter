"""Motores de búsqueda para Google Dorking.

GoogleEngine (default): Usa googlesearch-python — soporta TODOS los operadores
de Google (inurl:, site:, intitle:, filetype:, "exact match", etc.)

DDGSEngine (fallback): DuckDuckGo Search.
"""
import logging
from typing import List, Optional

from .models import get_random_user_agent

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

    Incluye soporte para rotación de proxies y delay entre queries.
    """

    def __init__(self, sleep_interval: float = 3.0, proxies: List[str] = None):
        self.sleep_interval = sleep_interval
        self.proxies = proxies or []
        self._proxy_index = 0

    def _get_next_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None
        p = self.proxies[self._proxy_index % len(self.proxies)]
        self._proxy_index += 1
        
        # googlesearch-python espera el formato http://... o https://...
        if '://' not in p:
            p = f"http://{p}"
        return p

    def search(self, dork: str, max_results: int = 10) -> List[str]:
        # Si hay proxies configurados, intentar rotar por cada uno de ellos en caso de error/bloqueo
        max_attempts = max(1, len(self.proxies))
        
        for attempt in range(max_attempts):
            proxy = self._get_next_proxy()
            try:
                from googlesearch import search
                p_log = f" (via proxy {proxy})" if proxy else ""
                logger.info(f"Google: buscando '{dork[:50]}'{p_log}...")
                
                results = list(search(
                    dork,
                    num_results=max_results,
                    sleep_interval=self.sleep_interval,
                    proxy=proxy,
                    user_agent=get_random_user_agent()
                ))
                logger.info(f"Google: {len(results)} resultados para '{dork[:80]}'")
                return results
            except Exception as e:
                logger.warning(f"Google error ({type(e).__name__}) con proxy {proxy}: {e}")
                # Si no hay más proxies en la lista, rompemos para hacer fallback directo
                if not proxy:
                    break

        logger.info("Google bloqueado o fallido. Intentando fallback a DuckDuckGo...")
        try:
            return DDGSEngine().search(dork, max_results)
        except Exception:
            return []


class DDGSEngine(SearchEngine):
    """DuckDuckGo Search.

    Soporta la gran mayoría de operadores avanzados de Google Dorks (inurl:, site:, quotes).
    No suele bloquearse con captchas y es gratuito.
    Soporta rotación de proxies.
    """

    def __init__(self, proxies: List[str] = None):
        self.proxies = proxies or []
        self._proxy_index = 0

    def _get_next_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None
        p = self.proxies[self._proxy_index % len(self.proxies)]
        self._proxy_index += 1
        if '://' not in p:
            p = f"http://{p}"
        return p

    def search(self, dork: str, max_results: int = 10) -> List[str]:
        # Si hay proxies configurados, rotar e intentar con ellos en caso de error
        max_attempts = max(1, len(self.proxies))
        
        for attempt in range(max_attempts):
            proxy = self._get_next_proxy()
            try:
                from ddgs import DDGS
                p_log = f" (via proxy {proxy})" if proxy else ""
                logger.info(f"DuckDuckGo: buscando '{dork[:50]}'{p_log}...")
                
                with DDGS(proxy=proxy) as ddgs:
                    results = [r['href'] for r in ddgs.text(dork, max_results=max_results) if r.get('href')]
                    logger.info(f"DuckDuckGo: {len(results)} resultados")
                    return results
            except Exception as e:
                logger.warning(f"DuckDuckGo error ({type(e).__name__}) con proxy {proxy}: {e}")
                if not proxy:
                    break
        return []