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

            # === DETECCIÓN ESTRICTA: SOLO formularios de pago REALES con botón de pagar ===
            has_real_form = False
            score = 0
            visible_pay = False

            string_matches = sum(1 for k in FORM_KEYWORDS if k in html)
            score += min(string_matches * 8, 30)

            try:
                # Campos de pago obligatorios (DOM estricto)
                card_fields = await page.query_selector_all(
                    'input[name*="card"], input[id*="card"], input[autocomplete*="cc-number"], '
                    'input[data-braintree-name="number"], input[placeholder*="card" i]'
                )
                cvv_fields = await page.query_selector_all(
                    'input[name*="cvv"], input[name*="cvc"], input[id*="cvv"], input[autocomplete*="cc-csc"]'
                )
                expiry_fields = await page.query_selector_all(
                    'input[name*="exp"], input[id*="exp"], select[name*="exp"], input[autocomplete*="cc-exp"]'
                )

                payment_fields_count = len(card_fields) + len(cvv_fields) + len(expiry_fields)
                score += payment_fields_count * 12

                # Botón de PAGAR visible y con texto claro (lo más importante)
                pay_button_selectors = [
                    'button:has-text("pagar")', 'button:has-text("pay")', 'button:has-text("place order")',
                    'button:has-text("comprar")', 'button:has-text("checkout")', 'button:has-text("finalizar")',
                    'input[type="submit"][value*="pagar" i]', 'input[type="submit"][value*="pay" i]',
                    '[data-testid*="pay"]', '[class*="pay-button"]'
                ]
                pay_buttons = []
                for sel in pay_button_selectors:
                    try:
                        els = await page.query_selector_all(sel)
                        pay_buttons.extend(els)
                    except:
                        pass

                # Verificar si el botón es visible
                for btn in pay_buttons:
                    try:
                        is_visible = await btn.is_visible()
                        if is_visible:
                            visible_pay = True
                            break
                    except:
                        pass

                if visible_pay:
                    score += 35
                    has_real_form = True

                # Regla estricta: solo verdadero si hay campos de pago Y botón pagar visible
                if payment_fields_count >= 2 and visible_pay:
                    has_real_form = True
                    score += 20
                elif payment_fields_count >= 1 and visible_pay:
                    has_real_form = True
                    score += 10

            except Exception as e:
                logger.debug(f"DOM check fallback: {e}")
                # Fallback muy conservador
                if any(k in html for k in ['card-number', 'cvv', 'pagar', 'place-order']):
                    has_real_form = True
                    score += 15

            # Solo si tiene botón de pagar + campos, subimos el score alto
            if has_real_form and visible_pay:
                score = max(score, 70)

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
