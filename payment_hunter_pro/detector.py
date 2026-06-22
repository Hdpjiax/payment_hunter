"""PaymentDetector - Lógica de detección de formularios de pago (ahora ASÍNCRONA).

Soporta Playwright Async API + paralelismo controlado desde el runner.
"""
import re
import logging
from typing import Optional

from playwright.async_api import async_playwright, Browser, Playwright

from .models import (
    INDICATORS, FORM_KEYWORDS, GATEWAY_DISPLAY,
    get_random_user_agent
)

# Stealth opcional (stealth_sync funciona en páginas async para inyección JS)
try:
    from playwright_stealth import stealth_sync
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

logger = logging.getLogger(__name__)


class PaymentDetector:
    """
    Responsable ASÍNCRONO de visitar URLs y detectar formularios de pago reales.

    - Usa Playwright Async API
    - Reutiliza el navegador (lanzado una vez)
    - Soporta concurrencia controlada desde el runner (semáforo)
    """

    def __init__(
        self,
        proxies: list[str],
        use_stealth: bool,
        avoid_cloudflare: bool,
        active_gateways: list[str],
        page_timeout: int = 45000,
    ):
        self.proxies = [p for p in proxies if p] or []
        self.proxy_index = 0
        self.use_stealth = use_stealth
        self.avoid_cloudflare = avoid_cloudflare
        self.active = {
            g.lower().replace(" ", "").replace(".", "") for g in active_gateways
        }
        self.page_timeout = page_timeout  # allow slow proxies

        # Async browser reuse
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None

    def _get_next_proxy(self) -> Optional[str]:
        if not self.proxies:
            return None
        proxy = self.proxies[self.proxy_index % len(self.proxies)]
        self.proxy_index += 1
        return proxy

    def has_cloudflare(self, html: str) -> bool:
        signals = ['cloudflare', 'cf-ray', 'cf-clearance', 'challenge']
        return any(s in html.lower() for s in signals)

    async def _ensure_browser(self):
        """Lanza el navegador (async) solo la primera vez."""
        if self._browser is not None:
            return

        logger.info("Lanzando navegador Chromium ASÍNCRONO (una sola vez)...")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def detect_real_payment_form(self, url: str) -> tuple[list[str], bool, int]:
        """
        Versión ASÍNCRONA.
        Devuelve (gateways, has_real_form, confidence_score).
        """
        try:
            await self._ensure_browser()
            proxy = self._get_next_proxy()

            context = await self._browser.new_context(
                user_agent=get_random_user_agent(),
                proxy={"server": proxy} if proxy else None,
            )
            page = await context.new_page()

            if self.use_stealth and STEALTH_AVAILABLE:
                stealth_sync(page)  # inyección JS funciona en async page

            await page.goto(url, wait_until="networkidle", timeout=self.page_timeout)
            html = (await page.content()).lower()

            if self.avoid_cloudflare and self.has_cloudflare(html):
                await context.close()
                return [], False, 0

            detected = []
            for name, pats in INDICATORS.items():
                if name in self.active and any(re.search(p, html, re.I) for p in pats):
                    detected.append(GATEWAY_DISPLAY.get(name, name.upper()))

            # === DETECCIÓN AMPLIA: Cualquier formulario de pago o suscripción ===
            # El objetivo es encontrar TODO lo que tenga un formulario de pago (incluyendo suscripciones, membresías, etc.)
            has_real_form = False
            score = 0

            string_matches = sum(1 for k in FORM_KEYWORDS if k in html)
            score += min(string_matches * 10, 40)

            try:
                # Buscar campos de pago (tarjeta, cvv, expiry, billing, etc.)
                payment_inputs = await page.query_selector_all(
                    'input[name*="card"], input[id*="card"], input[autocomplete*="cc-"], '
                    'input[name*="cvv"], input[name*="cvc"], input[id*="cvv"], '
                    'input[name*="exp"], input[id*="exp"], '
                    'input[name*="billing"], input[id*="billing"], '
                    'input[type="tel"], input[placeholder*="card" i], input[placeholder*="cvv" i]'
                )

                # Buscar botones de acción de pago o suscripción
                action_buttons = await page.query_selector_all(
                    'button, input[type="submit"], a[role="button"]'
                )

                pay_or_subscribe_words = [
                    'pagar', 'pay', 'place order', 'comprar', 'checkout', 'finalizar', 
                    'subscribe', 'suscribir', 'suscribirse', 'membership', 'plan', 
                    'buy now', 'get started', 'join now', 'payment', 'billing'
                ]

                has_pay_button = False
                for btn in action_buttons:
                    try:
                        text = (await btn.inner_text() or '').lower()
                        if any(word in text for word in pay_or_subscribe_words):
                            has_pay_button = True
                            break
                    except:
                        pass

                # Si hay inputs de pago O botón de pago/suscripción → es resultado
                if len(payment_inputs) > 0 or has_pay_button:
                    has_real_form = True
                    score += len(payment_inputs) * 15
                    if has_pay_button:
                        score += 40

                # También buscar formularios que parezcan de pago/suscripción
                forms = await page.query_selector_all('form')
                for form in forms:
                    try:
                        form_html = (await form.inner_html() or '').lower()
                        if any(k in form_html for k in ['card', 'cvv', 'expiry', 'billing', 'payment', 'pagar', 'suscrib']):
                            has_real_form = True
                            score += 20
                            break
                    except:
                        pass

            except Exception as e:
                logger.debug(f"DOM check error: {e}")
                # Fallback muy amplio
                if any(k in html for k in FORM_KEYWORDS) or any(w in html for w in ['pagar', 'pay', 'subscribe', 'suscrib']):
                    has_real_form = True
                    score += 30

            # Asegurar que si hay indicios claros, lo marquemos como resultado
            if has_real_form:
                score = max(score, 50)

            score = min(max(score, 0), 100)

            await context.close()
            return detected, has_real_form, score

        except Exception as exc:
            logger.warning(f"Error detectando {url}: {exc}")
            return [], False, 0

    async def close(self):
        """Cierra recursos de forma asíncrona."""
        try:
            if self._browser:
                await self._browser.close()
                logger.info("Navegador async cerrado.")
            if self._playwright:
                await self._playwright.stop()
        except Exception as exc:
            logger.warning(f"Error cerrando navegador async: {exc}")
        finally:
            self._browser = None
            self._playwright = None
