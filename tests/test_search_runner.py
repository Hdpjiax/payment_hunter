"""Tests para SearchRunner usando unittest.

Cubrimos estados, pausa, stop y comunicación por queue con detector mock.
"""
import unittest
from queue import Queue
from unittest.mock import MagicMock

from payment_hunter_pro.runner import SearchRunner
from payment_hunter_pro.models import SearchResult
from payment_hunter_pro.detector import PaymentDetector


class TestSearchRunnerStates(unittest.TestCase):
    def test_initial_state(self):
        detector = MagicMock(spec=PaymentDetector)
        q = Queue()
        runner = SearchRunner(detector, max_sites=10, dorks=[], queue=q)
        self.assertFalse(runner.is_running())
        self.assertFalse(runner.is_paused())

    def test_toggle_pause_and_is_paused(self):
        detector = MagicMock()
        q = Queue()
        runner = SearchRunner(detector, 10, [], q, max_concurrent=3)

        self.assertFalse(runner.is_paused())
        runner.toggle_pause()
        self.assertTrue(runner.is_paused())
        runner.toggle_pause()
        self.assertFalse(runner.is_paused())

    def test_stop_resets_flags(self):
        detector = MagicMock()
        q = Queue()
        runner = SearchRunner(detector, 10, [], q, max_concurrent=3)
        runner._running = True
        runner._paused = True
        runner.stop()
        self.assertFalse(runner.is_running())
        self.assertFalse(runner.is_paused())


class TestSearchRunnerQueueMessages(unittest.TestCase):
    def test_sends_log_and_result_messages(self):
        mock_detector = MagicMock()
        mock_detector.detect_real_payment_form.return_value = (["Stripe"], True, 75)

        q = Queue()
        dorks = ["stripe checkout site:.com"]
        runner = SearchRunner(mock_detector, max_sites=3, dorks=dorks, queue=q, max_concurrent=3)

        # Ejecutamos versión controlada del loop (sin thread ni DDGS real)
        runner._running = True
        runner._paused = False

        def fake_run():
            runner._send("log", "Iniciando búsqueda fake...")
            detected, has_form, score = runner.detector.detect_real_payment_form("https://fake.com")
            if detected and has_form:
                res = SearchResult(
                    url="https://fake.com",
                    gateways=", ".join(detected),
                    real_form="Sí",
                    timestamp="2026-06-22 12:00"
                )
                runner._send("result", res)
                runner._send("log", "✅ FORMULARIO DETECTADO")
            runner._send("progress", 1.0)
            runner._send("done", None)
            runner._running = False

        runner._run = fake_run
        runner._run()

        messages = []
        while not q.empty():
            messages.append(q.get_nowait())

        kinds = [m[0] for m in messages]
        self.assertIn("log", kinds)
        self.assertIn("result", kinds)
        self.assertIn("progress", kinds)
        self.assertIn("done", kinds)

        result_msgs = [m[1] for m in messages if m[0] == "result"]
        self.assertEqual(len(result_msgs), 1)
        self.assertIsInstance(result_msgs[0], SearchResult)
        self.assertEqual(result_msgs[0].gateways, "Stripe")

    def test_pause_does_not_block_stop(self):
        detector = MagicMock()
        q = Queue()
        runner = SearchRunner(detector, 10, [], q, max_concurrent=3)
        runner.toggle_pause()
        self.assertTrue(runner.is_paused())
        runner.stop()
        self.assertFalse(runner.is_paused())
        self.assertFalse(runner.is_running())


if __name__ == "__main__":
    unittest.main()
