"""SearchRunner - Orquestación ASÍNCRONA con paralelismo.

Usa asyncio + Semaphore para analizar múltiples URLs concurrentemente
mientras mantiene comunicación thread-safe con la UI de Tkinter.
"""
import asyncio
import logging
import threading
from queue import Queue
from typing import Optional

from datetime import datetime

from .search_engines import DDGSEngine, BingEngine, SearchEngine

from .detector import PaymentDetector
from .models import SearchResult

logger = logging.getLogger(__name__)


class SearchRunner:
    """
    Orquesta dorks + detección.

    - Maneja hilos, pausa y parada usando Events.
    - Comunica todo a través de la queue (thread-safe).
    - Gestiona el ciclo de vida del detector (incluyendo cierre de navegador).
    """

    def __init__(
        self,
        detector: PaymentDetector,
        max_sites: int,
        dorks: list[str],
        queue: Queue,
        country: str = "Global",
        max_concurrent: int = 4,
        engine: str = "DuckDuckGo",
    ):
        self.detector = detector
        self.max_sites = max_sites
        self.dorks = dorks
        self.queue = queue
        self._current_country = country
        self.max_concurrent = max(1, min(max_concurrent, 10))
        self.engine_name = engine

        self._running = False
        self._paused = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

    def start(self):
        """Inicia la búsqueda en un hilo separado que ejecuta el loop asyncio."""
        self._running = True
        self._stop_event.clear()
        self._pause_event.clear()
        threading.Thread(target=self._run_in_thread, daemon=True).start()

    def _run_in_thread(self):
        """Ejecuta el runner async dentro de un hilo dedicado (necesario para Tkinter)."""
        asyncio.run(self._async_run())

    def toggle_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._pause_event.set()
        else:
            self._pause_event.clear()

    def stop(self):
        self._running = False
        self._paused = False
        self._stop_event.set()
        self._pause_event.clear()

    def is_running(self) -> bool:
        return self._running

    def is_paused(self) -> bool:
        return self._paused

    def _send(self, kind: str, payload=None):
        self.queue.put((kind, payload))

    async def _async_run(self):
        found = 0
        self._send("log", "🔥 Iniciando búsqueda ASÍNCRONA con paralelismo...")

        try:
            for dork in self.dorks:
                if not self._running or found >= self.max_sites:
                    break

                self._send("log", f"Buscando dork: {dork[:100]}...")

                try:
                    engine: SearchEngine = BingEngine() if self.engine_name.lower() == "bing" else DDGSEngine()
                    urls = engine.search(dork, max_results=12)

                    # Filtro estricto: solo sitios que parezcan de COMPRAS
                    shop_keywords = ["shop", "store", "tienda", "ecommerce", "cart", "checkout", "comprar", "product", "tienda online"]
                    shopping_urls = [u for u in urls if any(k in u.lower() for k in shop_keywords)]
                    if shopping_urls:
                        urls = shopping_urls  # priorizar tiendas reales
                except Exception as exc:
                    logger.warning(f"Error en búsqueda {self.engine_name}: {exc}")
                    continue

                # === PARALELISMO CON SEMÁFORO CONFIGURABLE ===
                semaphore = asyncio.Semaphore(self.max_concurrent)
                tasks = []

                for url in urls:
                    if not self._running or found >= self.max_sites:
                        break

                    # Pausa cooperativa (async)
                    while self._paused and not self._stop_event.is_set():
                        await asyncio.sleep(0.5)
                    if not self._running:
                        break

                    task = asyncio.create_task(
                        self._process_url(url, dork, semaphore)
                    )
                    tasks.append(task)

                if tasks:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for res in results:
                        if isinstance(res, tuple) and res[0]:  # (found_increment, score)
                            found += res[0]

                # Actualizar progreso después del batch
                self._send("progress", min(found / self.max_sites, 1.0))

            self._send("log", f"🎉 Búsqueda asíncrona finalizada. Total encontrados: {found}")

        finally:
            await self.detector.close()
            self._send("done", None)
            self._running = False

    async def _process_url(self, url: str, dork: str, semaphore: asyncio.Semaphore):
        """Procesa una URL con reintentos, pausa y límite de concurrencia."""
        async with semaphore:
            for attempt in range(2):  # 2 reintentos
                if not self._running:
                    return 0, 0

                # Mejor manejo de pausa (chequeo frecuente)
                while self._paused and not self._stop_event.is_set():
                    await asyncio.sleep(0.4)

                if not self._running:
                    return 0, 0

                self._send("log", f"Analizando formulario → {url}" + (f" (retry {attempt})" if attempt > 0 else ""))

                try:
                    detected, has_real_form, score = await self.detector.detect_real_payment_form(url)

                    if detected and has_real_form:
                        result = SearchResult(
                            url=url,
                            gateways=", ".join(detected),
                            real_form="Sí",
                            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M"),
                            country=getattr(self, "_current_country", "Global"),
                            confidence_score=score,
                            dork=dork
                        )
                        self._send("result", result)
                        self._send("log", f"✅ FORMULARIO DE PAGO REAL ENCONTRADO → {url} (score: {score})")
                        return 1, score

                    return 0, 0
                except Exception as e:
                    logger.warning(f"Error en detección {url} (intento {attempt+1}): {e}")
                    if attempt == 1:
                        return 0, 0
                    await asyncio.sleep(1.0)  # backoff corto

            return 0, 0
