import random
from ddgs import DDGS
from playwright.sync_api import sync_playwright

class SearchRunner:
    def __init__(self, country="Global", max_sites=50, avoid_cloudflare=True, custom_dorks=None):
        self.country = country
        self.max_sites = max_sites
        self.avoid_cloudflare = avoid_cloudflare
        self.custom_dorks = custom_dorks or []
        self.proxies = []
        self.current_proxy_index = 0

    def set_proxies(self, proxy_list):
        self.proxies = [p.strip() for p in proxy_list if p.strip() and not p.startswith("#")]

    def get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.current_proxy_index % len(self.proxies)]
        self.current_proxy_index += 1
        return proxy

    def generate_dorks(self, gateways):
        dorks = []
        country = self.country if self.country != "Global" else ""
        for gw in gateways:
            dorks.extend([
                f'{gw} (shop OR store OR tienda) (checkout OR "payment form" OR "add to cart" OR carrito OR "proceed to checkout") {country}',
                f'inurl:(shop|store|tienda|checkout) {gw} {country}',
                f'"{gw}" (checkout OR payment OR "payment form") (shop OR store OR tienda) {country}',
            ])
        # Add custom dorks from user
        dorks.extend(self.custom_dorks)
        return dorks

    def search(self, gateways):
        dorks = self.generate_dorks(gateways)
        results = []
        for dork in dorks:
            if len(results) >= self.max_sites:
                break
            try:
                with DDGS() as ddgs:
                    urls = [r['href'] for r in ddgs.text(dork, max_results=8) if r.get('href')]
                for url in urls:
                    if len(results) >= self.max_sites:
                        break
                    results.append(url)
            except:
                continue
        return results