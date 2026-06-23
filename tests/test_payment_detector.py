"""Tests exhaustivos para PaymentDetector usando unittest + mocks async.

No requieren navegador real ni internet.
Actualizados para la API async de Playwright (async_playwright).
"""
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from payment_hunter_pro.detector import PaymentDetector, STEALTH_AVAILABLE
from payment_hunter_pro.models import INDICATORS, FORM_KEYWORDS, GATEWAY_DISPLAY


class TestPaymentDetectorNormalization(unittest.TestCase):
    """Pruebas que cubren la corrección del bug de mayúsculas/minúsculas."""

    def test_normalizes_gateway_names(self):
        detector = PaymentDetector(
            proxies=[],
            use_stealth=False,
            avoid_cloudflare=False,
            active_gateways=["Adyen", "Stripe", "MERCADO PAGO", "  Authorize.net  "],
        )
        self.assertEqual(
            detector.active, {"adyen", "stripe", "mercadopago", "authorizenet"}
        )

    def test_only_detects_active_gateways(self):
        detector = PaymentDetector(
            proxies=[],
            use_stealth=False,
            avoid_cloudflare=False,
            active_gateways=["Stripe"],
        )
        html = "js.stripe.com cardnumber adyen-dropin checkout"
        detected = []
        for name, pats in INDICATORS.items():
            if name in detector.active and any(re.search(p, html, re.I) for p in pats):
                detected.append(GATEWAY_DISPLAY.get(name, name.upper()))
        self.assertEqual(detected, ["Stripe"])


class TestHasCloudflare(unittest.TestCase):
    def test_detects_various_cloudflare_signals(self):
        detector = PaymentDetector([], False, True, [])
        self.assertFalse(detector.has_cloudflare("normal page"))
        self.assertTrue(detector.has_cloudflare("... ray id: 12345 ..."))
        self.assertTrue(detector.has_cloudflare("cf-clearance=xxx"))
        self.assertTrue(detector.has_cloudflare('<title>Just a moment...</title>'))
        self.assertTrue(detector.has_cloudflare("cf-challenge"))


class TestProxyRotation(unittest.TestCase):
    def test_rotates_proxies(self):
        detector = PaymentDetector(
            proxies=["http://p1", "socks5://p2", "http://p3"],
            use_stealth=False,
            avoid_cloudflare=False,
            active_gateways=[],
        )
        self.assertEqual(detector._get_next_proxy(), "http://p1")
        self.assertEqual(detector._get_next_proxy(), "socks5://p2")
        self.assertEqual(detector._get_next_proxy(), "http://p3")
        self.assertEqual(detector._get_next_proxy(), "http://p1")
        self.assertEqual(detector.proxy_index, 4)


class TestDetectRealPaymentForm(unittest.IsolatedAsyncioTestCase):
    """Mocks async para simular Playwright sin lanzar nada real."""

    def _make_mock_page(self, html_content, payment_inputs=None, action_buttons=None, forms=None):
        """Construye un mock de página async con query_selector_all diferenciado."""
        mock_page = AsyncMock()
        mock_page.content.return_value = html_content
        mock_page.goto.return_value = None
        mock_page.main_frame = mock_page

        _payment_inputs = payment_inputs or []
        _action_buttons = action_buttons or []
        _forms = forms or []

        async def _query_selector_all(selector):
            if any(s in selector for s in ['input[name*="card"]', 'input[id*="card"]', 'input[name="number"]', 'input[name="expiry"]']):
                return _payment_inputs
            elif 'button' in selector:
                return _action_buttons
            elif selector == 'form':
                return _forms
            return []

        mock_page.query_selector_all = AsyncMock(side_effect=_query_selector_all)
        mock_page.frames = [mock_page]
        return mock_page

    def _make_mock_context(self, mock_page):
        mock_context = AsyncMock()
        mock_context.new_page.return_value = mock_page
        return mock_context

    def _make_mock_browser(self, mock_context):
        mock_browser = AsyncMock()
        mock_browser.new_context.return_value = mock_context
        return mock_browser

    def _setup_detector(self, detector, mock_browser):
        """Pre-set browser para que _ensure_browser() sea no-op."""
        detector._browser = mock_browser
        detector._playwright = AsyncMock()

    async def test_detects_stripe_and_has_form(self):
        html = """
        <html>
          <script src="https://js.stripe.com/v3/"></script>
          <input id="cardnumber" />
          <input name="cvv" />
          <button>Place Order</button>
        </html>
        """
        mock_btn = AsyncMock()
        mock_btn.inner_text.return_value = "Place Order"

        mock_input = AsyncMock()
        mock_page = self._make_mock_page(
            html, payment_inputs=[mock_input], action_buttons=[mock_btn]
        )
        mock_context = self._make_mock_context(mock_page)
        mock_browser = self._make_mock_browser(mock_context)

        detector = PaymentDetector(
            proxies=["http://proxy1"],
            use_stealth=False,
            avoid_cloudflare=True,
            active_gateways=["stripe", "adyen"],
        )
        self._setup_detector(detector, mock_browser)

        detected, has_form, score = await detector.detect_real_payment_form(
            "https://example-shop.com/checkout"
        )

        self.assertIn("Stripe", detected)
        self.assertTrue(has_form)
        self.assertGreaterEqual(score, 50)
        mock_context.close.assert_called_once()

    async def test_skips_when_cloudflare_detected_and_avoid_enabled(self):
        html = "cf-ray: abc123 <html>stripe elements</html>"
        mock_page = self._make_mock_page(html)
        mock_context = self._make_mock_context(mock_page)
        mock_browser = self._make_mock_browser(mock_context)

        detector = PaymentDetector(
            proxies=[],
            use_stealth=False,
            avoid_cloudflare=True,
            active_gateways=["stripe"],
        )
        self._setup_detector(detector, mock_browser)

        detected, has_form, score = await detector.detect_real_payment_form(
            "https://cloudflare-protected.com"
        )

        self.assertEqual(detected, [])
        self.assertFalse(has_form)
        self.assertEqual(score, 0)
        mock_context.close.assert_called_once()

    async def test_detects_multiple_gateways(self):
        html = "paypal.com mercadopago checkout-form card-number"
        mock_page = self._make_mock_page(html)
        mock_context = self._make_mock_context(mock_page)
        mock_browser = self._make_mock_browser(mock_context)

        detector = PaymentDetector([], False, False, ["paypal", "mercadopago", "stripe"])
        self._setup_detector(detector, mock_browser)

        detected, has_form, score = await detector.detect_real_payment_form("https://test.com")

        self.assertIn("PayPal", detected)
        self.assertIn("Mercado Pago", detected)

    async def test_returns_empty_on_exception(self):
        detector = PaymentDetector([], False, False, ["adyen"])
        # _ensure_browser lanza excepción → detect atrapa y devuelve vacío
        detector._ensure_browser = AsyncMock(side_effect=Exception("Playwright crashed"))

        detected, has_form, score = await detector.detect_real_payment_form("https://bad.com")

        self.assertEqual(detected, [])
        self.assertFalse(has_form)
        self.assertEqual(score, 0)

    async def test_uses_random_user_agent(self):
        html = "<html>adyen</html>"
        mock_page = self._make_mock_page(html)
        mock_context = self._make_mock_context(mock_page)
        mock_browser = self._make_mock_browser(mock_context)

        detector = PaymentDetector([], False, False, ["adyen"])
        self._setup_detector(detector, mock_browser)

        with patch("payment_hunter_pro.models.random.choice", return_value="test-ua/1.0"):
            await detector.detect_real_payment_form("https://x.com")

        call_kwargs = mock_browser.new_context.call_args[1]
        self.assertIn("user_agent", call_kwargs)
        self.assertEqual(call_kwargs["user_agent"], "test-ua/1.0")

    def test_no_detection_when_gateway_not_active(self):
        """Lógica pura sin mocks de browser."""
        detector = PaymentDetector([], False, False, ["paypal"])
        html = "js.stripe.com cardnumber"
        detected = []
        for name, pats in INDICATORS.items():
            if name in detector.active and any(re.search(p, html, re.I) for p in pats):
                detected.append(GATEWAY_DISPLAY.get(name, name.upper()))
        self.assertEqual(detected, [])

    async def test_stealth_applied_when_available_and_enabled(self):
        if not STEALTH_AVAILABLE:
            self.skipTest("playwright-stealth no está disponible")

        html = "<html>openpay</html>"
        mock_page = self._make_mock_page(html)
        mock_context = self._make_mock_context(mock_page)
        mock_browser = self._make_mock_browser(mock_context)

        detector = PaymentDetector([], True, False, ["openpay"])
        self._setup_detector(detector, mock_browser)

        with patch("payment_hunter_pro.detector.Stealth.apply_stealth_async", new_callable=AsyncMock) as mock_stealth:
            await detector.detect_real_payment_form("https://test.com")
            mock_stealth.assert_called_once()

    async def test_form_analysis_detects_payment_form(self):
        """Verifica que el análisis de <form> con keywords de pago funciona."""
        html = "<html><body>some content</body></html>"

        mock_form = AsyncMock()
        mock_form.inner_html.return_value = '<input name="card" /><input name="cvv" /><button>Pagar</button>'

        mock_page = self._make_mock_page(html, forms=[mock_form])
        mock_context = self._make_mock_context(mock_page)
        mock_browser = self._make_mock_browser(mock_context)

        detector = PaymentDetector([], False, False, ["stripe"])
        self._setup_detector(detector, mock_browser)

        detected, has_form, score = await detector.detect_real_payment_form("https://tienda.com/pago")

        self.assertTrue(has_form)
        self.assertGreaterEqual(score, 50)

    async def test_checkout_navigation_skips_sold_out(self):
        """Verifica que la simulación de compra salta productos agotados y llega a checkout."""
        mock_page = AsyncMock()
        mock_page.url = "https://tienda.com"
        mock_page.content.return_value = "<html><body>shop store product catalog</body></html>"
        mock_page.main_frame = mock_page
        mock_page.frames = [mock_page]
        
        mock_link1 = AsyncMock()
        mock_link1.get_attribute.return_value = "/products/out-of-stock"
        mock_link2 = AsyncMock()
        mock_link2.get_attribute.return_value = "/products/in-stock"
        
        mock_btn_sold_out = AsyncMock()
        mock_btn_sold_out.is_disabled.return_value = True
        mock_btn_sold_out.inner_text.return_value = "Sold out"
        mock_btn_sold_out.get_attribute.return_value = None
        
        mock_btn_active = AsyncMock()
        mock_btn_active.is_disabled.return_value = False
        mock_btn_active.inner_text.return_value = "Add to cart"
        mock_btn_active.get_attribute.return_value = None
        mock_btn_active.click.return_value = None
        
        mock_checkout_btn = AsyncMock()
        mock_checkout_btn.get_attribute.return_value = "/checkout"
        
        async def _query_selector_all_side_effect(selector):
            if 'a[href*="/products/"]' in selector:
                return [mock_link1, mock_link2]
            elif 'button[name="add"]' in selector:
                if "out-of-stock" in mock_page.url:
                    return [mock_btn_sold_out]
                else:
                    return [mock_btn_active]
            elif 'a[href*="checkout"]' in selector:
                return [mock_checkout_btn]
            elif any(s in selector for s in ['input[name*="card"]', 'input[id*="card"]', 'input[name="number"]', 'input[name="expiry"]']):
                return [AsyncMock()]
            return []
            
        mock_page.query_selector_all.side_effect = _query_selector_all_side_effect
        
        async def _goto_side_effect(url, **kwargs):
            mock_page.url = url
            if "checkout" in url:
                mock_page.content.return_value = "<html>stripe.com billing checkout-form</html>"
            return None
        mock_page.goto.side_effect = _goto_side_effect
        
        mock_context = self._make_mock_context(mock_page)
        mock_browser = self._make_mock_browser(mock_context)
        
        detector = PaymentDetector([], False, False, ["stripe"])
        self._setup_detector(detector, mock_browser)
        
        detected, has_form, score = await detector.detect_real_payment_form("https://tienda.com")
        
        self.assertTrue(has_form)
        self.assertIn("Stripe", detected)
        self.assertEqual(mock_page.url, "https://tienda.com/checkout")

    async def test_close_cleans_up_resources(self):
        """Verifica que close() cierra browser y playwright correctamente."""
        mock_browser = AsyncMock()
        mock_pw = AsyncMock()

        detector = PaymentDetector([], False, False, [])
        detector._browser = mock_browser
        detector._playwright = mock_pw

        await detector.close()

        mock_browser.close.assert_called_once()
        mock_pw.stop.assert_called_once()
        self.assertIsNone(detector._browser)
        self.assertIsNone(detector._playwright)


if __name__ == "__main__":
    unittest.main()
