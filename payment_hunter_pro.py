import customtkinter as ctk
from tkinter import scrolledtext, filedialog, messagebox
import threading
import re
import time
import random
import pandas as pd
import webbrowser
from datetime import datetime
from dataclasses import dataclass, asdict
from queue import Queue, Empty
from playwright.sync_api import sync_playwright
from ddgs import DDGS

# Stealth
try:
    from playwright_stealth import stealth_sync
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
]

# Constantes normalizadas (keys internas siempre minúsculas)
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
    """Modelo real para un resultado de búsqueda. Hace el código más claro y testeable."""
    url: str
    gateways: str
    real_form: str
    timestamp: str


class PaymentDetector:
    """Responsable ÚNICO de visitar URLs y detectar formularios de pago reales.
    Completamente aislado de la UI. Fácil de testear y reutilizar.
    """
    def __init__(self, proxies: list[str], use_stealth: bool, avoid_cloudflare: bool, active_gateways: list[str]):
        self.proxies = [p for p in proxies if p] or []
        self.proxy_index = 0
        self.use_stealth = use_stealth
        self.avoid_cloudflare = avoid_cloudflare
        # Normalización defensiva (quita espacios y puntos para que coincida con UI + "Authorize.net")
        self.active = {g.lower().replace(" ", "").replace(".", "") for g in active_gateways}

    def _get_next_proxy(self):
        if not self.proxies:
            return None
        proxy = self.proxies[self.proxy_index % len(self.proxies)]
        self.proxy_index += 1
        return proxy

    def has_cloudflare(self, html: str) -> bool:
        signals = ['cloudflare', 'cf-ray', 'cf-clearance', 'challenge']
        return any(s in html.lower() for s in signals)

    def detect_real_payment_form(self, url: str) -> tuple[list[str], bool]:
        """Devuelve (gateways_detectados, tiene_formulario_real)."""
        try:
            proxy = self._get_next_proxy()
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=random.choice(USER_AGENTS),
                    proxy={"server": proxy} if proxy else None
                )
                page = context.new_page()
                if self.use_stealth and STEALTH_AVAILABLE:
                    stealth_sync(page)

                page.goto(url, wait_until="networkidle", timeout=25000)
                html = page.content().lower()

                if self.avoid_cloudflare and self.has_cloudflare(html):
                    browser.close()
                    return [], False

                detected = []
                for name, pats in INDICATORS.items():
                    if name in self.active and any(re.search(p, html, re.I) for p in pats):
                        detected.append(GATEWAY_DISPLAY.get(name, name.upper()))

                has_real_form = any(k in html for k in FORM_KEYWORDS)

                browser.close()
                return detected, has_real_form
        except Exception:
            # No tragamos silenciosamente en producción real, pero mantenemos compatibilidad
            return [], False


class SearchRunner:
    """Orquesta la búsqueda completa (dorks + detección).
    Maneja hilos, pausa y parada de forma limpia usando Events.
    Comunica TODO vía queue (thread-safe).
    """
    def __init__(self, detector: PaymentDetector, max_sites: int, dorks: list[str], queue: Queue):
        self.detector = detector
        self.max_sites = max_sites
        self.dorks = dorks
        self.queue = queue
        self._running = False
        self._paused = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()

    def start(self):
        self._running = True
        self._stop_event.clear()
        self._pause_event.clear()
        threading.Thread(target=self._run, daemon=True).start()

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

    def is_running(self):
        return self._running

    def is_paused(self):
        return self._paused

    def _send(self, kind: str, payload=None):
        self.queue.put((kind, payload))

    def _run(self):
        found = 0
        self._send("log", "🔥 Iniciando búsqueda con proxies rotativos y dorks avanzados...")

        for dork in self.dorks:
            if not self._running or found >= self.max_sites:
                break
            self._send("log", f"Buscando dork: {dork[:100]}...")

            try:
                with DDGS() as ddgs:
                    urls = [r['href'] for r in ddgs.text(dork, max_results=12) if r.get('href')]
            except Exception:
                continue

            for url in urls:
                if not self._running or found >= self.max_sites:
                    break

                # Pausa cooperativa
                while self._paused and not self._stop_event.is_set():
                    time.sleep(0.5)
                if not self._running:
                    break

                self._send("log", f"Analizando formulario → {url}")
                detected, has_real_form = self.detector.detect_real_payment_form(url)

                if detected and has_real_form:
                    result = SearchResult(
                        url=url,
                        gateways=", ".join(detected),
                        real_form="Sí",
                        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M")
                    )
                    self._send("result", result)
                    self._send("log", f"✅ FORMULARIO DE PAGO REAL ENCONTRADO → {url}")
                    found += 1

                self._send("progress", min(found / self.max_sites, 1.0))
                time.sleep(2.0)

        self._send("log", f"🎉 Búsqueda finalizada. Total encontrados: {found}")
        self._send("done", None)
        self._running = False


class PaymentHunter(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🔥 PAYMENT HUNTER PRO v4.3 🔥")
        self.geometry("1550x1050")
        self.configure(fg_color="#0a0a0a")

        # Estado de resultados (usando modelo real)
        self.results: list[SearchResult] = []
        self.result_widgets = []

        # Comunicación thread-safe
        self.update_queue: Queue = Queue()
        self.runner: SearchRunner | None = None

        self.create_ui()
        # Iniciar el procesador de actualizaciones UI (seguro para hilos)
        self.after(100, self._process_updates)

    def create_ui(self):
        ctk.CTkLabel(self, text="PAYMENT HUNTER PRO v4.3", 
                    font=ctk.CTkFont(family="Consolas", size=52, weight="bold"), 
                    text_color="#00ff41").pack(pady=15)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=25, pady=10)

        self.tabview.add("🔍 Búsqueda")
        self.tabview.add("📋 Resultados")
        self.tabview.add("📜 Historial")
        self.tabview.add("⚙️ Configuración")

        self.build_search_tab()
        self.build_results_tab()
        self.build_history_tab()
        self.build_config_tab()

    def build_search_tab(self):
        tab = self.tabview.tab("🔍 Búsqueda")
        
        # Pasarelas
        ctk.CTkLabel(tab, text="Pasarelas:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=25, pady=(15,5))
        self.gateway_vars = {}
        gws = ["Adyen", "Stripe", "PayPal", "Mercado Pago", "Openpay", "Authorize.net"]
        frame = ctk.CTkFrame(tab)
        frame.pack(fill="x", padx=25, pady=5)
        for i, gw in enumerate(gws):
            var = ctk.BooleanVar(value=True)
            cb = ctk.CTkCheckBox(frame, text=gw, variable=var)
            cb.grid(row=i//3, column=i%3, padx=25, pady=8, sticky="w")
            self.gateway_vars[gw.lower().replace(" ", "")] = var

        # Filtros
        fframe = ctk.CTkFrame(tab)
        fframe.pack(fill="x", padx=25, pady=12)
        
        ctk.CTkLabel(fframe, text="País:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.country_menu = ctk.CTkOptionMenu(fframe, values=["Global", "site:.com", "site:.us", "site:.co", "site:.mx", "site:.es", "site:.br"], width=170)
        self.country_menu.grid(row=0, column=1, padx=10, pady=5)

        ctk.CTkLabel(fframe, text="Máx. sitios:").grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.max_entry = ctk.CTkEntry(fframe, width=90)
        self.max_entry.insert(0, "50")
        self.max_entry.grid(row=0, column=3, padx=10, pady=5)

        self.chk_commercial = ctk.CTkCheckBox(fframe, text="Solo Tiendas", onvalue=1, offvalue=0)
        self.chk_commercial.select()
        self.chk_commercial.grid(row=1, column=0, pady=8, padx=10, sticky="w")

        self.chk_cloudflare = ctk.CTkCheckBox(fframe, text="Evitar Cloudflare", onvalue=1, offvalue=0)
        self.chk_cloudflare.select()
        self.chk_cloudflare.grid(row=1, column=1, pady=8, padx=10, sticky="w")

        # Proxies + Rotación
        pframe = ctk.CTkFrame(tab)
        pframe.pack(fill="x", padx=25, pady=10)
        ctk.CTkLabel(pframe, text="Proxies (uno por línea):").pack(anchor="w", padx=10)
        self.proxy_text = ctk.CTkTextbox(pframe, height=110)
        self.proxy_text.pack(fill="x", padx=10, pady=5)
        self.proxy_text.insert("1.0", "# Ejemplos residenciales:\nhttp://user:pass@ip:port\nsocks5://user:pass@ip:port")

        # Dorks personalizados
        dframe = ctk.CTkFrame(tab)
        dframe.pack(fill="x", padx=25, pady=10)
        ctk.CTkLabel(dframe, text="Dorks personalizados (uno por línea):").pack(anchor="w", padx=10)
        self.custom_dorks = ctk.CTkTextbox(dframe, height=100)
        self.custom_dorks.pack(fill="x", padx=10, pady=5)
        self.custom_dorks.insert("1.0", "# Ejemplo:\nadyen checkout payment site:.com\nstripe \"payment form\" shop")

        # Botones
        btnf = ctk.CTkFrame(tab)
        btnf.pack(pady=15)
        self.start_btn = ctk.CTkButton(btnf, text="🚀 INICIAR BÚSQUEDA", fg_color="#00ff41", text_color="black",
                                      height=65, width=340, font=ctk.CTkFont(size=18, weight="bold"),
                                      command=self.toggle_search)
        self.start_btn.pack(side="left", padx=10)

        self.pause_btn = ctk.CTkButton(btnf, text="⏸️ PAUSAR", fg_color="#ffaa00", height=65, width=180,
                                      command=self.toggle_pause, state="disabled")
        self.pause_btn.pack(side="left", padx=10)

        ctk.CTkButton(btnf, text="🛑 DETENER", fg_color="#ff3333", height=65, width=180,
                     command=self.stop_search).pack(side="left", padx=10)

        ctk.CTkButton(btnf, text="💾 Exportar CSV", fg_color="#0088ff", height=65, width=200,
                     command=self.export).pack(side="left", padx=10)

        self.progress = ctk.CTkProgressBar(tab, width=1250, height=24)
        self.progress.pack(pady=15)
        self.progress.set(0)

        self.log_text = scrolledtext.ScrolledText(tab, height=16, bg="#000000", fg="#00ff41", font=("Consolas", 12))
        self.log_text.pack(fill="both", expand=True, padx=25, pady=10)

    def build_results_tab(self):
        tab = self.tabview.tab("📋 Resultados")
        self.results_frame = ctk.CTkScrollableFrame(tab)
        self.results_frame.pack(fill="both", expand=True, padx=25, pady=10)

    def build_history_tab(self):
        tab = self.tabview.tab("📜 Historial")
        self.history_text = scrolledtext.ScrolledText(tab, bg="#000000", fg="#00ccff", font=("Consolas", 11))
        self.history_text.pack(fill="both", expand=True, padx=25, pady=10)

    def build_config_tab(self):
        tab = self.tabview.tab("⚙️ Configuración")
        ctk.CTkLabel(tab, text="Anti-Detección", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=30, pady=10)
        self.stealth_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(tab, text="🛡️ Modo Stealth Máximo", variable=self.stealth_var).pack(anchor="w", padx=30)

    # ============== MÉTODOS DE UI (se mantienen) ==============

    def _do_log(self, msg: str):
        """Actualización directa de log (solo llamar desde hilo principal)."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.update_idletasks()

    def get_active_gateways(self):
        return [name for name, var in self.gateway_vars.items() if var.get()]

    def update_results_ui(self):
        for w in self.result_widgets:
            w.destroy()
        self.result_widgets.clear()

        for row in self.results[-25:]:
            frame = ctk.CTkFrame(self.results_frame)
            frame.pack(fill="x", padx=10, pady=5)

            ctk.CTkLabel(frame, text=row.url[:90] + "...", anchor="w").pack(side="left", fill="x", expand=True, padx=10)
            ctk.CTkLabel(frame, text=row.gateways, text_color="#00ff41").pack(side="left", padx=10)

            ctk.CTkButton(frame, text="🌐 Abrir", width=90, height=30,
                         command=lambda u=row.url: webbrowser.open(u)).pack(side="right", padx=8)
            self.result_widgets.append(frame)

    # ============== CAMINO SEGURO DE ACTUALIZACIONES DESDE HILOS ==============

    def _process_updates(self):
        """Procesa la cola de mensajes desde el worker thread. Llamado periódicamente con after()."""
        try:
            while True:
                kind, payload = self.update_queue.get_nowait()

                if kind == "log":
                    self._do_log(payload)
                elif kind == "result":
                    self.results.append(payload)
                    self.update_results_ui()
                elif kind == "progress":
                    self.progress.set(payload)
                elif kind == "done":
                    self.stop_search()
        except Empty:
            pass

        # Reprogramar
        if self.winfo_exists():
            self.after(100, self._process_updates)

    # ============== CONTROL DE BÚSQUEDA (ahora delega en runner) ==============

    def toggle_search(self):
        if not self.runner or not self.runner.is_running():
            # Preparar configuración
            proxies = [
                line.strip() for line in self.proxy_text.get("1.0", "end").splitlines()
                if line.strip() and not line.startswith("#")
            ]
            max_sites = int(self.max_entry.get() or "50")
            active_gws = self.get_active_gateways()

            base_dorks = [
                f'{gw} ("checkout" OR "payment form" OR "proceed to payment" OR "finalizar compra") (shop OR store OR tienda OR cart) {self.country_menu.get()}'
                for gw in active_gws
            ]
            custom = [
                d.strip() for d in self.custom_dorks.get("1.0", "end").splitlines()
                if d.strip() and not d.startswith("#")
            ]
            all_dorks = base_dorks + custom

            # Crear detector y runner (lógica separada)
            use_stealth = self.stealth_var.get() and STEALTH_AVAILABLE
            avoid_cf = bool(self.chk_cloudflare.get())

            detector = PaymentDetector(
                proxies=proxies,
                use_stealth=use_stealth,
                avoid_cloudflare=avoid_cf,
                active_gateways=active_gws
            )

            self.results.clear()
            self.update_results_ui()

            self.runner = SearchRunner(
                detector=detector,
                max_sites=max_sites,
                dorks=all_dorks,
                queue=self.update_queue
            )

            self.start_btn.configure(state="disabled", text="⏹️ CORRIENDO...")
            self.pause_btn.configure(state="normal", text="⏸️ PAUSAR")
            self.runner.start()
        else:
            self.stop_search()

    def toggle_pause(self):
        if self.runner:
            self.runner.toggle_pause()
            paused = self.runner.is_paused()
            self.pause_btn.configure(text="▶️ REANUDAR" if paused else "⏸️ PAUSAR")

    def stop_search(self):
        if self.runner:
            self.runner.stop()
        self.runner = None
        self.start_btn.configure(state="normal", text="🚀 INICIAR BÚSQUEDA")
        self.pause_btn.configure(state="disabled", text="⏸️ PAUSAR")

    def export(self):
        if not self.results:
            messagebox.showwarning("Sin datos", "No hay resultados para exportar")
            return
        # Usar modelo real → DataFrame
        df = pd.DataFrame([asdict(r) for r in self.results])
        file = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Excel", "*.xlsx")]
        )
        if file:
            if file.endswith('.xlsx'):
                df.to_excel(file, index=False)
            else:
                df.to_csv(file, index=False, encoding='utf-8')
            self._do_log(f"💾 Exportado correctamente: {file}")

if __name__ == "__main__":
    app = PaymentHunter()
    app.mainloop()