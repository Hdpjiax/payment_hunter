"""UI principal usando CustomTkinter.

PaymentHunter es ahora un shell delgado que solo construye la interfaz
y coordina con SearchRunner y PaymentDetector.
"""
import logging
import threading
from datetime import datetime
from queue import Queue, Empty
from tkinter import scrolledtext, filedialog, messagebox, ttk
import webbrowser

import customtkinter as ctk
import pandas as pd

from .models import SearchResult
from .detector import PaymentDetector, STEALTH_AVAILABLE
from .runner import SearchRunner
from .persistence import init_db, save_result, load_all_results, clear_history

init_db()

# Configuración de logging
logger = logging.getLogger(__name__)


class QueueLogHandler(logging.Handler):
    """Handler que envía logs a la cola de la UI."""
    def __init__(self, queue: Queue):
        super().__init__()
        self.queue = queue
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record):
        try:
            msg = self.format(record)
            self.queue.put(("log", msg))
        except Exception:
            pass


class PaymentHunter(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🔥 PAYMENT HUNTER PRO v4.3 🔥")
        self.geometry("1580x1020")
        self.configure(fg_color="#0f0f0f")  # fondo más oscuro y limpio

        # Estado
        self.results: list[SearchResult] = []
        self.update_queue: Queue = Queue()
        self.runner: SearchRunner | None = None
        self.results_tree_data = {}

        # Logging → queue
        self._setup_logging()

        self.create_ui()
        self.after(80, self._process_updates)
        self._update_status("Listo")

    def _setup_logging(self):
        """Configura logging para que también vaya a la UI."""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Handler para la UI
        ui_handler = QueueLogHandler(self.update_queue)
        root_logger.addHandler(ui_handler)

        # Opcional: también a consola
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        root_logger.addHandler(console)

    def create_ui(self):
        """Nueva interfaz completamente profesional y limpia."""
        self.configure(fg_color="#0d0d0d")

        # === TOP TOOLBAR ===
        toolbar = ctk.CTkFrame(self, fg_color="#161616", height=68, corner_radius=0)
        toolbar.pack(fill="x", padx=0, pady=0)
        toolbar.pack_propagate(False)

        # Left title
        title_frame = ctk.CTkFrame(toolbar, fg_color="transparent")
        title_frame.pack(side="left", padx=20)
        ctk.CTkLabel(
            title_frame,
            text="PAYMENT HUNTER PRO",
            font=ctk.CTkFont(family="Segoe UI", size=20, weight="bold"),
            text_color="#e0e0e0"
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_frame,
            text="Professional Payment Gateway Scanner",
            font=ctk.CTkFont(size=11),
            text_color="#666666"
        ).pack(anchor="w")

        # Status
        self.status_label = ctk.CTkLabel(
            toolbar,
            text="● READY",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#00c853"
        )
        self.status_label.pack(side="left", padx=30)

        # Right actions
        actions = ctk.CTkFrame(toolbar, fg_color="transparent")
        actions.pack(side="right", padx=15)

        self.start_btn = ctk.CTkButton(
            actions, text="START SCAN", fg_color="#00c853", text_color="#111",
            width=140, height=38, font=ctk.CTkFont(size=13, weight="bold"),
            command=self.toggle_search
        )
        self.start_btn.pack(side="left", padx=5)

        self.pause_btn = ctk.CTkButton(
            actions, text="PAUSE", fg_color="#ff9800", text_color="#111",
            width=90, height=38, font=ctk.CTkFont(size=12, weight="bold"),
            command=self.toggle_pause, state="disabled"
        )
        self.pause_btn.pack(side="left", padx=5)

        ctk.CTkButton(
            actions, text="STOP", fg_color="#e53935", text_color="#fff",
            width=80, height=38, font=ctk.CTkFont(size=12, weight="bold"),
            command=self.stop_search
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            actions, text="EXPORT", fg_color="#2196f3", text_color="#fff",
            width=95, height=38, font=ctk.CTkFont(size=12, weight="bold"),
            command=self.export
        ).pack(side="left", padx=5)

        # === MAIN CONTENT AREA ===
        main_content = ctk.CTkFrame(self, fg_color="#0d0d0d")
        main_content.pack(fill="both", expand=True, padx=12, pady=8)

        # LEFT SIDEBAR - Configuration (professional card style)
        sidebar = ctk.CTkFrame(main_content, fg_color="#161616", width=360, corner_radius=10)
        sidebar.pack(side="left", fill="y", padx=(0, 10), pady=5)
        sidebar.pack_propagate(False)

        # Sidebar header
        ctk.CTkLabel(sidebar, text="CONFIGURATION", font=ctk.CTkFont(size=13, weight="bold"), text_color="#888").pack(padx=15, pady=(12, 8), anchor="w")

        # Gateways section
        gw_card = ctk.CTkFrame(sidebar, fg_color="#1f1f1f", corner_radius=8)
        gw_card.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(gw_card, text="Payment Gateways", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(8,4))

        self.gateway_vars = {}
        gws = ["Adyen", "Stripe", "PayPal", "Mercado Pago", "Openpay", "Authorize.net"]
        for gw in gws:
            var = ctk.BooleanVar(value=True)
            cb = ctk.CTkCheckBox(gw_card, text=gw, variable=var, font=ctk.CTkFont(size=12))
            cb.pack(anchor="w", padx=14, pady=2)
            key = gw.lower().replace(" ", "").replace(".", "")
            self.gateway_vars[key] = var

        # Filters card
        filters_card = ctk.CTkFrame(sidebar, fg_color="#1f1f1f", corner_radius=8)
        filters_card.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(filters_card, text="Search Filters", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(8,4))

        ctk.CTkLabel(filters_card, text="Country / TLD", font=ctk.CTkFont(size=11), text_color="#aaa").pack(anchor="w", padx=12)
        self.country_menu = ctk.CTkOptionMenu(filters_card, values=["Global", "site:.com", "site:.us", "site:.co", "site:.mx", "site:.es", "site:.br"], width=200, height=28)
        self.country_menu.pack(anchor="w", padx=12, pady=(0,6))

        row = ctk.CTkFrame(filters_card, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row, text="Max Sites", font=ctk.CTkFont(size=11), text_color="#aaa").pack(side="left")
        self.max_entry = ctk.CTkEntry(row, width=70, height=26)
        self.max_entry.insert(0, "60")
        self.max_entry.pack(side="right")

        row2 = ctk.CTkFrame(filters_card, fg_color="transparent")
        row2.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row2, text="Concurrency", font=ctk.CTkFont(size=11), text_color="#aaa").pack(side="left")
        self.concurrent_entry = ctk.CTkEntry(row2, width=70, height=26)
        self.concurrent_entry.insert(0, "4")
        self.concurrent_entry.pack(side="right")

        row3 = ctk.CTkFrame(filters_card, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=2)
        ctk.CTkLabel(row3, text="Page Timeout (s)", font=ctk.CTkFont(size=11), text_color="#aaa").pack(side="left")
        self.page_timeout_entry = ctk.CTkEntry(row3, width=70, height=26)
        self.page_timeout_entry.insert(0, "45")
        self.page_timeout_entry.pack(side="right")

        row3 = ctk.CTkFrame(filters_card, fg_color="transparent")
        row3.pack(fill="x", padx=12, pady=(2,6))
        ctk.CTkLabel(row3, text="Search Engine", font=ctk.CTkFont(size=11), text_color="#aaa").pack(side="left")
        self.engine_menu = ctk.CTkOptionMenu(row3, values=["DuckDuckGo", "Bing"], width=120, height=26)
        self.engine_menu.pack(side="right")

        self.chk_cloudflare = ctk.CTkCheckBox(filters_card, text="Avoid Cloudflare", onvalue=1, offvalue=0)
        self.chk_cloudflare.select()
        self.chk_cloudflare.pack(anchor="w", padx=12, pady=4)

        self.stealth_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(filters_card, text="Max Stealth Mode", variable=self.stealth_var).pack(anchor="w", padx=12, pady=2)

        # Proxies card
        proxies_card = ctk.CTkFrame(sidebar, fg_color="#1f1f1f", corner_radius=8)
        proxies_card.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(proxies_card, text="Proxies (one per line)", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(8,2))
        self.proxy_text = ctk.CTkTextbox(proxies_card, height=85, font=ctk.CTkFont(size=11))
        self.proxy_text.pack(fill="x", padx=12, pady=4)
        self.proxy_text.insert("1.0", "# http://user:pass@ip:port")
        ctk.CTkButton(proxies_card, text="Test Proxies", width=140, height=26, fg_color="#333", command=self.test_proxies).pack(anchor="e", padx=12, pady=(0,8))

        # Dorks card
        dorks_card = ctk.CTkFrame(sidebar, fg_color="#1f1f1f", corner_radius=8)
        dorks_card.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(dorks_card, text="Custom Dorks", font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=12, pady=(8,2))
        self.custom_dorks = ctk.CTkTextbox(dorks_card, height=70, font=ctk.CTkFont(size=11))
        self.custom_dorks.pack(fill="x", padx=12, pady=4)
        self.custom_dorks.insert("1.0", "# Dorks personalizados (se recomienda usar el Generador Avanzado)")

        # === ADVANCED DORK GENERATOR (New Professional Section) ===
        dork_gen_card = ctk.CTkFrame(sidebar, fg_color="#1f1f1f", corner_radius=8)
        dork_gen_card.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(dork_gen_card, text="GENERADOR DE DORKS AVANZADO", font=ctk.CTkFont(size=12, weight="bold"), text_color="#00c853").pack(anchor="w", padx=12, pady=(8,4))

        ctk.CTkLabel(dork_gen_card, text="Términos de Formulario de Pago", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=12)
        self.payment_terms = ctk.CTkEntry(dork_gen_card, placeholder_text="payment form,checkout form,card details,formulario de pago")
        self.payment_terms.pack(fill="x", padx=12, pady=2)
        self.payment_terms.insert(0, "payment form,checkout form,card details,formulario de pago,pagar,place order")

        ctk.CTkLabel(dork_gen_card, text="Términos de Sitios de Compras", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=12)
        self.shop_terms = ctk.CTkEntry(dork_gen_card, placeholder_text="shop,store,tienda,ecommerce,cart,checkout")
        self.shop_terms.pack(fill="x", padx=12, pady=2)
        self.shop_terms.insert(0, "shop,store,tienda,ecommerce,cart,checkout,comprar,tienda online")

        ctk.CTkButton(
            dork_gen_card, 
            text="⚡ Generar Dorks Avanzados", 
            fg_color="#00c853", 
            text_color="#111",
            command=self.generate_advanced_dorks
        ).pack(fill="x", padx=12, pady=(8, 8))

        # === RIGHT MAIN AREA (Results) ===
        results_area = ctk.CTkFrame(main_content, fg_color="#161616", corner_radius=10)
        results_area.pack(side="left", fill="both", expand=True, pady=5)

        # Results header
        results_header = ctk.CTkFrame(results_area, fg_color="transparent", height=36)
        results_header.pack(fill="x", padx=12, pady=(8,0))
        ctk.CTkLabel(results_header, text="LIVE RESULTS", font=ctk.CTkFont(size=13, weight="bold"), text_color="#e0e0e0").pack(side="left")
        self.results_count_label = ctk.CTkLabel(results_header, text="0 results", font=ctk.CTkFont(size=11), text_color="#777")
        self.results_count_label.pack(side="right")

        # Professional Treeview
        tree_container = ctk.CTkFrame(results_area, fg_color="#121212", corner_radius=6)
        tree_container.pack(fill="both", expand=True, padx=12, pady=8)

        columns = ("url", "gateways", "score", "timestamp", "dork")
        self.results_tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=18)

        self.results_tree.heading("url", text="URL")
        self.results_tree.heading("gateways", text="Gateways")
        self.results_tree.heading("score", text="Score")
        self.results_tree.heading("timestamp", text="Time")
        self.results_tree.heading("dork", text="Dork")

        self.results_tree.column("url", width=420)
        self.results_tree.column("gateways", width=140)
        self.results_tree.column("score", width=70, anchor="center")
        self.results_tree.column("timestamp", width=110)
        self.results_tree.column("dork", width=160)

        # Style the treeview for dark professional look
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", 
                        background="#121212", 
                        foreground="#e0e0e0", 
                        fieldbackground="#121212",
                        rowheight=26,
                        font=("Segoe UI", 10))
        style.configure("Treeview.Heading", 
                        background="#1f1f1f", 
                        foreground="#aaa", 
                        font=("Segoe UI", 10, "bold"),
                        relief="flat")
        style.map("Treeview", background=[("selected", "#2e4a3e")])

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=vsb.set)
        self.results_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.results_tree.bind("<Double-1>", self._on_tree_double_click)
        self.results_tree_data = {}

        # Progress bar under results
        self.progress = ctk.CTkProgressBar(results_area, height=6, progress_color="#00c853")
        self.progress.pack(fill="x", padx=12, pady=(0,10))
        self.progress.set(0)

        # === BOTTOM LOG PANEL ===
        log_panel = ctk.CTkFrame(self, fg_color="#161616", height=160, corner_radius=0)
        log_panel.pack(fill="x", padx=12, pady=(0,12))
        log_panel.pack_propagate(False)

        log_header = ctk.CTkFrame(log_panel, fg_color="transparent")
        log_header.pack(fill="x", padx=10, pady=(6,0))
        ctk.CTkLabel(log_header, text="ACTIVITY LOG", font=ctk.CTkFont(size=11, weight="bold"), text_color="#777").pack(side="left")
        ctk.CTkButton(log_header, text="Clear", width=60, height=22, fg_color="#333", command=lambda: self.log_text.delete("1.0", "end")).pack(side="right")

        self.log_text = scrolledtext.ScrolledText(
            log_panel, height=7, bg="#0f0f0f", fg="#00c853", 
            font=("Consolas", 9), insertbackground="#00c853", relief="flat", borderwidth=0
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(2,8))

    # Old tab methods removed - new professional single-view UI is in create_ui()

    # ============== MÉTODOS DE UTILIDAD ==============

    def _do_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.update_idletasks()

    def get_active_gateways(self):
        return [name for name, var in self.gateway_vars.items() if var.get()]

    def test_proxies(self):
        """Testea los proxies de forma robusta. Soporta proxies lentos."""
        raw_proxies = [
            line.strip() for line in self.proxy_text.get("1.0", "end").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        if not raw_proxies:
            messagebox.showinfo("Proxies", "No hay proxies para probar.")
            return

        # Usar el timeout configurado por el usuario (más alto para proxies lentos)
        timeout_sec = int(self.page_timeout_entry.get() or 45)
        timeout_ms = timeout_sec * 1000

        self._do_log(f"🔍 Iniciando test de proxies (timeout: {timeout_sec}s)...")

        def _test():
            from playwright.sync_api import sync_playwright
            for proxy in raw_proxies:
                # Mostrar versión segura del proxy
                safe_proxy = proxy
                if "@" in proxy:
                    parts = proxy.split("@")
                    safe_proxy = parts[0].split(":")[0] + ":****@" + parts[1] if ":" in parts[0] else proxy

                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(
                            headless=True,
                            args=["--disable-blink-features=AutomationControlled"]
                        )
                        context = browser.new_context(
                            proxy={"server": proxy},
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                            ignore_https_errors=True,
                        )
                        page = context.new_page()

                        response = page.goto(
                            "https://httpbin.org/ip",
                            timeout=timeout_ms,
                            wait_until="domcontentloaded"
                        )
                        browser.close()

                        if response and response.ok:
                            self.update_queue.put(("log", f"✅ Proxy OK: {safe_proxy}"))
                        else:
                            self.update_queue.put(("log", f"⚠️ Proxy respondió pero status raro: {safe_proxy}"))
                except Exception as e:
                    err = str(e)
                    if "ERR_PROXY_CONNECTION_FAILED" in err or "net::ERR" in err:
                        msg = "ERR_PROXY_CONNECTION_FAILED (no se pudo conectar al proxy)"
                    elif "Timeout" in err or "timeout" in err:
                        msg = f"Timeout ({timeout_sec}s) - proxy lento. Se usará en la búsqueda principal."
                    else:
                        msg = err[:150]
                    self.update_queue.put(("log", f"⚠️ Proxy LENTO/INCIERTO: {safe_proxy} → {msg}"))

        threading.Thread(target=_test, daemon=True).start()

    def update_results_ui(self):
        # Clear tree
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        self.results_tree_data.clear()

        for row in self.results:
            item_id = self.results_tree.insert(
                "",
                "end",
                values=(
                    row.url[:85] + ("..." if len(row.url) > 85 else ""),
                    row.gateways,
                    str(row.confidence_score),
                    row.timestamp,
                    row.dork[:45] + ("..." if len(row.dork) > 45 else ""),
                ),
            )
            self.results_tree_data[item_id] = row.url

        # Update count
        if hasattr(self, "results_count_label"):
            self.results_count_label.configure(text=f"{len(self.results)} results")

    def _on_tree_double_click(self, event):
        """Abrir URL al hacer doble click en la fila."""
        item = self.results_tree.identify_row(event.y)
        if item and item in self.results_tree_data:
            url = self.results_tree_data[item]
            webbrowser.open(url)

    def _animate_button(self, button, temp_color="#00aa33", duration=180):
        """Pequeña animación de clic en botones."""
        try:
            orig = button.cget("fg_color")
            button.configure(fg_color=temp_color)
            self.after(duration, lambda: button.configure(fg_color=orig))
        except Exception:
            pass

    def _animate_stop(self):
        """Animación al detener."""
        if hasattr(self, "start_btn"):
            self._animate_button(self.start_btn, "#ff4444", 120)

    def generate_advanced_dorks(self):
        """Genera dorks avanzados ultra-específicos para FORMULARIOS DE PAGO en sitios de COMPRAS solamente."""
        active_gws = self.get_active_gateways()
        country = self.country_menu.get()

        if not active_gws:
            messagebox.showwarning("Dorks", "Selecciona al menos una pasarela.")
            return

        generated = []

        # Términos de alta precisión para formularios de pago reales
        payment_signals = [
            '"payment form"', '"checkout form"', '"card details"', '"formulario de pago"',
            '"datos de la tarjeta"', '"pagar ahora"', '"place order"', '"finalizar compra"',
            'inurl:checkout "card"', 'inurl:payment "cvv"'
        ]

        # Términos que garantizan que sea una tienda/comercio
        shop_signals = [
            "shop", "store", "tienda", "ecommerce", "cart", "checkout", "comprar",
            '"tienda online"', '"online shop"', '"add to cart"', "product"
        ]

        for gw in active_gws:
            for ps in payment_signals:
                for ss in shop_signals[:6]:
                    d = f'{gw} {ps} {ss} {country}'
                    generated.append(d)

            # Variaciones con operadores avanzados (muy efectivas para tiendas)
            generated.append(f'{gw} (inurl:checkout OR inurl:payment OR inurl:cart OR inurl:form) ("pagar" OR "pay" OR "place order") {shop_signals[0]} {country}')
            generated.append(f'{gw} ("formulario de pago" OR "payment form") ("tienda" OR shop OR store) ("pagar" OR checkout) {country}')

        # Limpiar duplicados
        seen = set()
        unique = [d for d in generated if not (d in seen or seen.add(d))]

        # Añadir al campo de dorks personalizados
        current = self.custom_dorks.get("1.0", "end").strip()
        new_block = "\n".join(unique[:30])

        if current and not current.startswith("#"):
            self.custom_dorks.delete("1.0", "end")
            self.custom_dorks.insert("1.0", current + "\n" + new_block)
        else:
            self.custom_dorks.delete("1.0", "end")
            self.custom_dorks.insert("1.0", new_block)

        self._do_log(f"⚡ Generados {len(unique[:30])} dorks AVANZADOS enfocados 100% en tiendas + formularios de pago.")
        messagebox.showinfo("Generador Avanzado", f"Se crearon {len(unique[:30])} dorks de alta precisión.\nSolo sitios de compras con formularios de pago.")

    def load_history(self):
        if not hasattr(self, 'history_tree'):
            return
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        try:
            results = load_all_results()
            for r in results:
                self.history_tree.insert("", "end", values=(r.url[:70], r.gateways, r.confidence_score, r.timestamp))
        except Exception as e:
            self._do_log(f"Error cargando historial: {e}")

    def clear_history(self):
        try:
            clear_history()
            self.load_history()
            self._do_log("Historial limpiado.")
        except Exception as e:
            self._do_log(f"Error limpiando historial: {e}")

    # ============== PROCESAMIENTO SEGURO DESDE HILOS ==============

    def _process_updates(self):
        try:
            while True:
                kind, payload = self.update_queue.get_nowait()

                if kind == "log":
                    self._do_log(payload)
                elif kind == "result":
                    self.results.append(payload)
                    save_result(payload)
                    self.update_results_ui()
                    self._flash_new_result()  # animación
                elif kind == "progress":
                    self._smooth_progress(payload)
                elif kind == "done":
                    self.stop_search()
                    self.progress.stop()
                    self.progress.configure(mode="determinate")
                    self._update_status("Búsqueda finalizada")
        except Empty:
            pass

        if self.winfo_exists():
            self.after(80, self._process_updates)

    def _update_status(self, text: str):
        if hasattr(self, "status_text"):
            self.status_text.configure(text=text)
        if hasattr(self, "status_label"):
            self.status_label.configure(text=text)

    def _smooth_progress(self, target: float):
        """Animación suave de la barra de progreso."""
        current = self.progress.get()
        step = (target - current) / 8
        for i in range(8):
            val = current + step * (i + 1)
            self.after(i * 25, lambda v=val: self.progress.set(v))

    def _flash_new_result(self):
        """Animación visual cuando llega un nuevo resultado."""
        if not self.results_tree.get_children():
            return
        last_item = self.results_tree.get_children()[-1]
        self.results_tree.tag_configure("flash", background="#003311")
        self.results_tree.item(last_item, tags=("flash",))
        self.after(650, lambda: self.results_tree.item(last_item, tags=()))

    # ============== CONTROL DE BÚSQUEDA ==============

    def toggle_search(self):
        if not self.runner or not self.runner.is_running():
            proxies = [
                line.strip() for line in self.proxy_text.get("1.0", "end").splitlines()
                if line.strip() and not line.startswith("#")
            ]
            max_sites = int(self.max_entry.get() or "50")
            max_concurrent = int(getattr(self, 'concurrent_entry', None).get() if hasattr(self, 'concurrent_entry') else 4) or 4
            active_gws = self.get_active_gateways()

            # Dorks 100% enfocados en sitios de COMPRAS + formularios de pago reales
            base_dorks = []
            country = self.country_menu.get()
            shop_context = '(shop OR store OR tienda OR ecommerce OR "tienda online" OR cart OR checkout OR "comprar" OR "add to cart")'

            for gw in active_gws:
                base_dorks.extend([
                    # Ultra específicos para formulario de pago + botón pagar
                    f'{gw} ("payment form" OR "checkout form" OR "formulario de pago" OR "card details" OR "datos de tarjeta") '
                    f'("pagar" OR "pay now" OR "place order" OR "botón de pago" OR "finalizar compra") '
                    f'{shop_context} {country}',

                    f'{gw} (inurl:checkout OR inurl:payment OR inurl:cart) '
                    f'("pagar" OR "pay" OR "place order" OR checkout) '
                    f'{shop_context} {country}',

                    f'{gw} (cvv OR "card number" OR expiry) '
                    f'("pagar" OR "pay" OR "place order") '
                    f'{shop_context} {country}',
                ])
            custom = [
                d.strip() for d in self.custom_dorks.get("1.0", "end").splitlines()
                if d.strip() and not d.startswith("#")
            ]
            all_dorks = base_dorks + custom

            use_stealth = self.stealth_var.get() and STEALTH_AVAILABLE
            avoid_cf = bool(self.chk_cloudflare.get())
            page_timeout = int(self.page_timeout_entry.get() or 45) * 1000

            detector = PaymentDetector(
                proxies=proxies,
                use_stealth=use_stealth,
                avoid_cloudflare=avoid_cf,
                active_gateways=active_gws,
                page_timeout=page_timeout,
            )

            self.results.clear()
            self.update_results_ui()

            self.runner = SearchRunner(
                detector=detector,
                max_sites=max_sites,
                dorks=all_dorks,
                queue=self.update_queue,
                country=self.country_menu.get(),
                max_concurrent=max_concurrent,
                engine=self.engine_menu.get(),
            )

            self._animate_button(self.start_btn, "#00aa33")
            self.start_btn.configure(state="disabled", text="⏹️ CORRIENDO...")
            self.pause_btn.configure(state="normal", text="⏸️ PAUSAR")
            self._update_status("Buscando...")
            self.progress.configure(mode="indeterminate")
            self.progress.start()
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
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self._update_status("Detenido")
        self._animate_stop()

    def export(self):
        if not self.results:
            messagebox.showwarning("Sin datos", "No hay resultados para exportar")
            return

        from dataclasses import asdict
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


def main():
    """Punto de entrada principal de la aplicación."""
    app = PaymentHunter()
    app.mainloop()


if __name__ == "__main__":
    main()
