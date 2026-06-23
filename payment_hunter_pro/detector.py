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

# Stealth opcional
try:
    from playwright_stealth import Stealth
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

    def _send_log(self, msg: str):
        logger.info(msg)

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
        # Check for specific Cloudflare interstitial and Turnstile verification/block page indicators.
        # Avoid generic terms like "cloudflare" (found in Shopify serialized renderers) or "challenge" (found in general captcha/checkout modals).
        html_lower = html.lower()
        if '<title>just a moment...</title>' in html_lower or '<title>attention required! | cloudflare</title>' in html_lower:
            return True
            
        specific_signals = [
            'cf-challenge',
            'cf-browser-verification',
            'cf-clearance',
            'cf-turnstile-wrapper',
            'id="cf-challenge-container"',
            'class="cf-browser-verification"',
            '/cdn-cgi/challenge-platform/',
            'challenges.cloudflare.com',
            'cf-ray',
            'ray id:',
        ]
        return any(s in html_lower for s in specific_signals)

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
                await Stealth().apply_stealth_async(page)

            await page.goto(url, wait_until="networkidle", timeout=self.page_timeout)
            html = (await page.content()).lower()

            # Si es la página principal de una tienda, intentamos navegar hasta el checkout
            # (Agregar producto al carrito, ir al carrito e ir al checkout)
            url_lower = url.lower()
            html = (await page.content()).lower()
            
            # 1. Intentar navegar si estamos en la home/catálogo/producto y no en checkout directamente
            if not any(x in url_lower for x in ["checkout", "cart", "pago", "checkout-form"]) and any(x in html for x in ["shop", "store", "product", "tienda", "comprar", "catalog"]):
                self._send_log(f"Iniciando simulacion de compra lenta y segura en: {url}")
                try:
                    # Buscar links de productos
                    product_links = await page.query_selector_all('a[href*="/products/"], a[href*="/product/"], a[href*="/producto/"], a[href*="/shop/product/"]')
                    if not product_links:
                        # Fallback a links que contengan "product" o "shop"
                        product_links = [l for l in await page.query_selector_all('a') if any(w in (await l.get_attribute('href') or '').lower() for w in ['product', 'shop/'])][:5]
                    
                    hrefs = []
                    for l in product_links:
                        href = await l.get_attribute('href')
                        if href:
                            if not href.startswith("http"):
                                from urllib.parse import urljoin
                                href = urljoin(page.url, href)
                            if href not in hrefs:
                                hrefs.append(href)

                    # Si ya estamos en una página de producto, agregamos la URL actual al inicio de la lista
                    if any(x in page.url.lower() for x in ["/products/", "/product/", "/producto/"]):
                        if page.url not in hrefs:
                            hrefs.insert(0, page.url)

                    added_to_cart = False
                    # Intentamos con hasta 5 productos únicos para encontrar uno con stock
                    for prod_url in hrefs[:5]:
                        if page.url != prod_url:
                            self._send_log(f" Navegando a pagina de producto: {prod_url}")
                            try:
                                await page.goto(prod_url, wait_until="networkidle", timeout=self.page_timeout)
                            except Exception as pe:
                                logger.debug(f"Error cargando producto {prod_url}: {pe}")
                                continue

                        # Buscar botones de agregar al carrito con sintaxis de Playwright CSS válida
                        add_cart_buttons = await page.query_selector_all(
                            'button[name="add"], button[id*="add-to-cart"], button[id*="addtocart"], '
                            'input[type="submit"][value*="Cart" i], input[type="submit"][value*="cart" i], '
                            'button:has-text("Add to cart"), button:has-text("Agregar al carrito"), '
                            'a:has-text("Add to cart"), button:has-text("Buy Now"), button:has-text("Comprar")'
                        )
                        
                        active_btn = None
                        for btn in add_cart_buttons:
                            try:
                                # Comprobar si el botón está deshabilitado
                                if await btn.is_disabled():
                                    continue
                                    
                                txt = (await btn.inner_text() or '').lower()
                                val = (await btn.get_attribute("value") or '').lower()
                                
                                sold_out_keywords = ["sold out", "out of stock", "agotado", "no disponible", "sin stock", "out of stock"]
                                if any(k in txt or k in val for k in sold_out_keywords):
                                    continue
                                    
                                active_btn = btn
                                break
                            except Exception:
                                pass

                        if active_btn:
                            self._send_log(f" Click en boton 'Agregar al carrito'.")
                            try:
                                await active_btn.click(timeout=10000)
                                await page.wait_for_timeout(4000) # Esperar animación del carrito
                                added_to_cart = True
                                break
                            except Exception as ce:
                                logger.debug(f"Click en agregar al carrito falló: {ce}")
                        else:
                            logger.debug(f"Producto agotado o sin botón de agregar al carrito: {prod_url}")

                    # 3. Ir al Checkout si pudimos agregar un producto
                    if added_to_cart:
                        self._send_log("Navegando directamente al checkout (/checkout)...")
                        from urllib.parse import urljoin
                        direct_checkout_url = urljoin(page.url, "/checkout")
                        redirect_success = False
                        try:
                            await page.goto(direct_checkout_url, wait_until="networkidle", timeout=self.page_timeout)
                            self._send_log(f"Llegamos con exito al Checkout: {page.url}")
                            redirect_success = True
                        except Exception as ce:
                            logger.debug(f"Direct redirect to /checkout failed: {ce}")
                            self._send_log("Fallo la redireccion directa, intentando buscar botones de checkout...")

                        if not redirect_success:
                            checkout_buttons = await page.query_selector_all(
                                'a[href*="checkout"], button[name="checkout"], button[id*="checkout"], '
                                'a:has-text("Checkout"), button:has-text("Checkout"), '
                                'a:has-text("Proceed to checkout"), button:has-text("Proceed to checkout"), '
                                'a:has-text("Finalizar compra"), button:has-text("Finalizar compra")'
                            )
                            
                            if checkout_buttons:
                                self._send_log(" Click en boton 'Checkout' / 'Finalizar Compra'.")
                                try:
                                    href = await checkout_buttons[0].get_attribute('href')
                                    if href:
                                        if not href.startswith("http"):
                                            href = urljoin(page.url, href)
                                        await page.goto(href, wait_until="networkidle", timeout=self.page_timeout)
                                    else:
                                        await checkout_buttons[0].click(timeout=15000)
                                        await page.wait_for_load_state("networkidle")
                                    self._send_log(f" Llegamos con exito al Checkout via boton: {page.url}")
                                except Exception as che:
                                    logger.debug(f"Error haciendo click en checkout: {che}")
                            else:
                                self._send_log("No se pudo encontrar ningun boton de checkout.")
                    else:
                        self._send_log("No se pudo agregar ningun producto al carrito.")
                    
                    # Esperamos unos segundos para que los campos de pago y pasarelas se carguen asíncronamente
                    self._send_log("Esperando 8 segundos para que carguen las pasarelas y campos de pago...")
                    await page.wait_for_timeout(8000)
                    
                    html = (await page.content()).lower()
                except Exception as ne:
                    logger.debug(f"Navegacion fallida: {ne}")
                    self._send_log(f"Error de navegacion automatica, analizando pagina actual: {page.url}")

            # Recolectamos el contenido HTML del frame principal y de todos los iframes hijos,
            # y también las URLs de todos los frames (útil para detectar pasarelas por dominio de origen del frame)
            all_htmls = [html]
            frame_urls = []
            for frame in page.frames:
                try:
                    if hasattr(frame, 'url') and frame.url:
                        if isinstance(frame.url, str):
                            frame_urls.append(frame.url.lower())
                        else:
                            frame_urls.append(str(frame.url).lower())
                except Exception:
                    pass

                if frame != page.main_frame:
                    try:
                        content = await frame.content()
                        all_htmls.append(content.lower())
                    except Exception:
                        pass
            combined_html = "\n".join(all_htmls)
            combined_urls = "\n".join(frame_urls)

            if self.avoid_cloudflare and self.has_cloudflare(combined_html):
                await context.close()
                return [], False, 0

            detected = []
            for name, pats in INDICATORS.items():
                if name in self.active:
                    matched = False
                    for p in pats:
                        if re.search(p, combined_html, re.I) or re.search(p, combined_urls, re.I):
                            matched = True
                            break
                    if matched:
                        detected.append(GATEWAY_DISPLAY.get(name, name.upper()))

            # === DETECCIÓN AMPLIA: Cualquier formulario de pago o suscripción ===
            has_real_form = False
            score = 0

            string_matches = sum(1 for k in FORM_KEYWORDS if k in combined_html)
            score += min(string_matches * 10, 40)

            try:
                # Buscar campos de pago en todos los frames (incluidos iframes de Stripe/Shopify/etc.)
                all_payment_inputs = []
                input_selectors = [
                    'input[name*="card"]', 'input[id*="card"]', 'input[autocomplete*="cc-"]',
                    'input[name*="cvv"]', 'input[name*="cvc"]', 'input[id*="cvv"]',
                    'input[name*="exp"]', 'input[id*="exp"]',
                    'input[name*="billing"]', 'input[id*="billing"]',
                    'input[type="tel"]', 'input[placeholder*="card" i]', 'input[placeholder*="cvv" i]',
                    'input[name="number"]', 'input[name="expiry"]', 'input[name="verification_value"]',
                    'input[name="name"]'
                ]
                selector_str = ", ".join(input_selectors)

                for frame in page.frames:
                    try:
                        inputs = await frame.query_selector_all(selector_str)
                        all_payment_inputs.extend(inputs)
                    except Exception:
                        pass

                # Buscar botones de acción de pago o suscripción en la página principal
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
                if len(all_payment_inputs) > 0 or has_pay_button:
                    has_real_form = True
                    score += len(all_payment_inputs) * 15
                    if has_pay_button:
                        score += 40

                # También buscar formularios que parezcan de pago/suscripción en todos los frames
                for frame in page.frames:
                    try:
                        forms = await frame.query_selector_all('form')
                        for form in forms:
                            try:
                                form_html = (await form.inner_html() or '').lower()
                                if any(k in form_html for k in ['card', 'cvv', 'expiry', 'billing', 'payment', 'pagar', 'suscrib']):
                                    has_real_form = True
                                    score += 20
                                    break
                            except:
                                pass
                    except Exception:
                        pass

            except Exception as e:
                logger.debug(f"DOM check error: {e}")
                # Fallback muy amplio
                if any(k in combined_html for k in FORM_KEYWORDS) or any(w in combined_html for w in ['pagar', 'pay', 'subscribe', 'suscrib']):
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