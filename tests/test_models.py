"""Tests para el modelo de datos SearchResult (compatible con unittest)."""
import unittest
from dataclasses import asdict

from payment_hunter_pro import SearchResult


class TestSearchResult(unittest.TestCase):
    def test_search_result_creation(self):
        result = SearchResult(
            url="https://example.com/checkout",
            gateways="Stripe, PayPal",
            real_form="Sí",
            timestamp="2026-06-22 10:30"
        )
        self.assertEqual(result.url, "https://example.com/checkout")
        self.assertEqual(result.gateways, "Stripe, PayPal")
        self.assertEqual(result.real_form, "Sí")

    def test_search_result_asdict_for_dataframe(self):
        """Útil porque export usa asdict para pandas."""
        result = SearchResult(
            url="https://tienda.com/pago",
            gateways="Adyen",
            real_form="Sí",
            timestamp="2026-06-22 11:00"
        )
        d = asdict(result)
        self.assertEqual(d, {
            "url": "https://tienda.com/pago",
            "gateways": "Adyen",
            "real_form": "Sí",
            "timestamp": "2026-06-22 11:00"
        })

    def test_search_result_equality(self):
        r1 = SearchResult("https://a.com", "Stripe", "Sí", "2026-01-01 00:00")
        r2 = SearchResult("https://a.com", "Stripe", "Sí", "2026-01-01 00:00")
        self.assertEqual(r1, r2)
        self.assertNotEqual(r1, SearchResult("https://b.com", "Stripe", "Sí", "2026-01-01 00:00"))


if __name__ == "__main__":
    unittest.main()
