"""Tests exhaustivos para PaymentDetector usando unittest + mocks.

No requieren navegador real ni internet.
"""
import re
import unittest
from unittest.mock import MagicMock, patch

from payment_hunter_pro import (
    PaymentDetector,
    INDICATORS,
    FORM_KEYWORDS,
    GATEWAY_DISPLAY,
    STEALTH_AVAILABLE,
)


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
        self.assertTrue(detector.has_cloudflare("... CF-RAY: 12345 ..."))
        self.assertTrue(detector.has_cloudflare("cf-clearance=xxx"))
        self.assertTrue(detector.has_cloudflare('<title>Just a moment... | Cloudflare</title>'))
        self.assertTrue(detector.has_cloudflare("CHALLENGE"))


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


class TestDetectRealPaymentForm(unittest.TestCase):
    """Mocks para simular playwright sin lanzar nada real."""

    def _make_successful_mock_context(self, html_content: str):
        """Construye mocks completos de la jerarquía playwright."""
        mock_page = MagicMock()
        mock_page.content.return_value = html_content
        mock_page.goto.return_value = None

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context
        mock_browser.close.return_value = None

        mock_p = MagicMock()
        mock_p.chromium.launch.return_value = mock_browser

        mock_playwright_cm = MagicMock()
        mock_playwright_cm.__enter__.return_value = mock_p
        mock_playwright_cm.__exit__.return_value = False

        return mock_playwright_cm, mock_browser

    @patch("payment_hunter_pro.sync_playwright")
    def test_detects_stripe_and_has_form(self, mock_sync):
        html = """
        <html>
          <script src="https://js.stripe.com/v3/"></script>
          <input id="cardnumber" />
          <input name="cvv" />
          <button>Place Order</button>
        </html>
        """
        mock_playwright, mock_browser = self._make_successful_mock_context(html)
        mock_sync.return_value = mock_playwright

        detector = PaymentDetector(
            proxies=["http://proxy1"],
            use_stealth=False,
            avoid_cloudflare=True,
            active_gateways=["stripe", "adyen"],
        )
        detected, has_form = detector.detect_real_payment_form("https://example-shop.com/checkout")

        self.assertIn("Stripe", detected)
        self.assertTrue(has_form)
        mock_browser.close.assert_called_once()

    @patch("payment_hunter_pro.sync_playwright")
    def test_skips_when_cloudflare_detected_and_avoid_enabled(self, mock_sync):
        html = "cf-ray: abc123 <html>stripe elements</html>"
        mock_playwright, mock_browser = self._make_successful_mock_context(html)
        mock_sync.return_value = mock_playwright

        detector = PaymentDetector(
            proxies=[],
            use_stealth=False,
            avoid_cloudflare=True,
            active_gateways=["stripe"],
        )
        detected, has_form = detector.detect_real_payment_form("https://cloudflare-protected.com")

        self.assertEqual(detected, [])
        self.assertFalse(has_form)
        mock_browser.close.assert_called_once()

    @patch("payment_hunter_pro.sync_playwright")
    def test_detects_multiple_gateways(self, mock_sync):
        html = "paypal.com mercadopago checkout-form card-number"
        mock_playwright, _ = self._make_successful_mock_context(html)
        mock_sync.return_value = mock_playwright

        detector = PaymentDetector([], False, False, ["paypal", "mercadopago", "stripe"])
        detected, has_form = detector.detect_real_payment_form("https://test.com")

        self.assertIn("PayPal", detected)
        self.assertIn("Mercado Pago", detected)
        self.assertTrue(has_form)

    @patch("payment_hunter_pro.sync_playwright")
    def test_returns_empty_on_exception(self, mock_sync):
        mock_sync.side_effect = Exception("Playwright crashed")
        detector = PaymentDetector([], False, False, ["adyen"])
        detected, has_form = detector.detect_real_payment_form("https://bad.com")
        self.assertEqual(detected, [])
        self.assertFalse(has_form)

    @patch("payment_hunter_pro.sync_playwright")
    @patch("payment_hunter_pro.random.choice")
    def test_uses_random_user_agent(self, mock_random, mock_sync):
        mock_random.return_value = "test-ua/1.0"
        html = "<html>adyen</html>"
        mock_playwright, _ = self._make_successful_mock_context(html)
        mock_sync.return_value = mock_playwright

        detector = PaymentDetector([], False, False, ["adyen"])
        detector.detect_real_payment_form("https://x.com")

        call_kwargs = mock_sync.return_value.__enter__.return_value.chromium.launch.return_value.new_context.call_args[1]
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

    @patch("payment_hunter_pro.sync_playwright")
    def test_stealth_applied_when_available_and_enabled(self, mock_sync):
        if not STEALTH_AVAILABLE:
            self.skipTest("playwright-stealth no está disponible")

        html = "<html>openpay</html>"
        mock_playwright, _ = self._make_successful_mock_context(html)
        mock_sync.return_value = mock_playwright

        detector = PaymentDetector([], True, False, ["openpay"])
        with patch("payment_hunter_pro.stealth_sync") as mock_stealth:
            detector.detect_real_payment_form("https://test.com")
            mock_stealth.assert_called_once()


if __name__ == "__main__":
    unittest.main()
