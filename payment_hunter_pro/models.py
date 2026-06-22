"""Modelos de datos y constantes compartidas."""
from dataclasses import dataclass
import random

# User agents rotativos
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
]


# Constantes normalizadas (claves internas)
GATEWAY_KEYS = ["adyen", "stripe", "paypal", "mercadopago", "openpay", "authorizenet"]

GATEWAY_DISPLAY = {
    "adyen": "Adyen",
    "stripe": "Stripe",
    "paypal": "PayPal",
    "mercadopago": "Mercado Pago",
    "openpay": "Openpay",
    "authorizenet": "Authorize.net",
}

INDICATORS = {
    'adyen': ['adyen.com', 'checkoutshopper', 'adyen-dropin'],
    'stripe': ['stripe.com', 'js.stripe.com', 'stripe-elements', 'cardnumber'],
    'paypal': ['paypal.com', 'paypalobjects', 'paypal-button'],
    'mercadopago': ['mercadopago', 'mp.com'],
    'openpay': ['openpay'],
    'authorizenet': ['authorize.net'],
}

FORM_KEYWORDS = [
    'card-number', 'cardnumber', 'cvv', 'expiry', 'expiration', 'billing',
    'payment-form', 'pay-button', 'place-order', 'checkout-form'
]


@dataclass
class SearchResult:
    """Modelo real para un resultado de búsqueda. Soporta export rico y scoring."""
    url: str
    gateways: str
    real_form: str
    timestamp: str
    country: str = "Global"
    confidence_score: int = 0
    dork: str = ""


def get_random_user_agent() -> str:
    return random.choice(USER_AGENTS)
