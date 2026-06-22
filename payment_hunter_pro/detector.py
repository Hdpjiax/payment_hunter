from playwright.sync_api import sync_playwright
import random

class PaymentDetector:
    def __init__(self, stealth=True, avoid_cloudflare=True):
        self.stealth = stealth
        self.avoid_cloudflare = avoid_cloudflare
        self.USER_AGENTS = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
        ]

    def has_cloudflare(self, html):
        signals = ['cloudflare', 'cf-ray', 'cf-clearance', 'challenge-form']
        return any(s in html.lower() for s in signals)

    def detect(self, url, proxy=None):
        indicators = {
            'ADYEN': ['adyen.com', 'checkoutshopper', 'adyen-dropin'],
            'STRIPE': ['stripe.com', 'js.stripe.com', 'stripe-elements', 'cardnumber'],
            'PAYPAL': ['paypal.com', 'paypalobjects', 'paypal-button'],
            'MERCADOPAGO': ['mercadopago', 'mp.com'],
            'OPENPAY': ['openpay'],
            'AUTHORIZENET': ['authorize.net']
        }

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=random.choice(self.USER_AGENTS),
                    proxy={"server": proxy} if proxy else None
                )
                page = context.new_page()
                if self.stealth:
                    try:
                        from playwright_stealth import stealth_sync
                        stealth_sync(page)
                    except:
                        pass

                page.goto(url, wait_until="networkidle", timeout=25000)
                html = page.content().lower()

                if self.avoid_cloudflare and self.has_cloudflare(html):
                    browser.close()
                    return [], False, "Cloudflare"

                detected = []
                for name, pats in indicators.items():
                    if any(re.search(p, html, re.I) for p in pats):
                        detected.append(name.upper())

                # Real payment form detection
                form_signals = ['card-number', 'cardnumber', 'cvv', 'expiry', 'billing', 'pay-button', 'place-order', 'checkout-form']
                has_real_form = any(k in html for k in form_signals)

                browser.close()
                return detected, has_real_form, None
        except Exception as e:
            return [], False, str(e)[:80]