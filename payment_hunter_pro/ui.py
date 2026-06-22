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
from .persistence import init_db, save_result, load_all_results, clear_history, is_url_processed, mark_url_processed

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
        self.dorks_generated = []
        self.proxies_data = []
        self.testing_active = False

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

        # View switcher for 3 main sections
        views = ctk.CTkFrame(toolbar, fg_color="transparent")
        views.pack(side="right", padx=20)
        ctk.CTkButton(views, text="1. Resultados", width=100, command=lambda: self.switch_main_view("results")).pack(side="left", padx=2)
        ctk.CTkButton(views, text="2. Generador Dorks", width=120, command=lambda: self.switch_main_view("dorks")).pack(side="left", padx=2)
        ctk.CTkButton(views, text="3. Proxies", width=90, command=lambda: self.switch_main_view("proxies")).pack(side="left", padx=2)

        # === MAIN CONTENT AREA ===
        main_content = ctk.CTkFrame(self, fg_color="#0d0d0d")
        main_content.pack(fill="both", expand=True, padx=12, pady=8)

        # LEFT SIDEBAR - Configuration (professional card style) - SCROLLABLE so you can see the full "GENERADOR DE DORKS AVANZADO" and all options
        sidebar = ctk.CTkScrollableFrame(main_content, fg_color="#161616", width=380, corner_radius=10)
        sidebar.pack(side="left", fill="y", padx=(0, 10), pady=5)

        # Sidebar header
        ctk.CTkLabel(sidebar, text="CONFIGURATION", font=ctk.CTkFont(size=13, weight="bold"), text_color="#888").pack(padx=15, pady=(12, 8), anchor="w")

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
        self.engine_menu = ctk.CTkOptionMenu(row3, values=["Google (Recomendado)", "DuckDuckGo"], width=190, height=26)
        self.engine_menu.pack(side="right")

        self.chk_cloudflare = ctk.CTkCheckBox(filters_card, text="Avoid Cloudflare", onvalue=1, offvalue=0)
        self.chk_cloudflare.select()
        self.chk_cloudflare.pack(anchor="w", padx=12, pady=4)

        self.stealth_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(filters_card, text="Max Stealth Mode", variable=self.stealth_var).pack(anchor="w", padx=12, pady=2)

        # Proxies moved to dedicated view (3. Proxies)

        # Custom Dorks removed from sidebar (now in the dedicated Dorks view)

        # === MAIN VIEW CONTAINER for 3 sections (Resultados / Generador Dorks / Proxies) ===
        self.main_view_container = ctk.CTkFrame(main_content, fg_color="#0d0d0d")
        self.main_view_container.pack(side="left", fill="both", expand=True, pady=5)

        # Pre create 3 frames
        self.results_frame = ctk.CTkFrame(self.main_view_container, fg_color="#161616", corner_radius=10)
        self.dorks_frame = ctk.CTkFrame(self.main_view_container, fg_color="#161616", corner_radius=10)
        self.proxies_frame = ctk.CTkFrame(self.main_view_container, fg_color="#161616", corner_radius=10)

        self.current_view_frame = None
        self.results_tree = None
        self.results_tree_data = {}
        self.dorks_generated = []
        from .persistence import load_all_proxies
        self.proxies_data = load_all_proxies()

        self.build_results_view(self.results_frame)
        self.build_dorks_view(self.dorks_frame)
        self.build_proxies_view(self.proxies_frame)
        self.update_proxies_tree()

        self.switch_main_view("results")

    # Old tab methods removed - new professional single-view UI is in create_ui()

    def switch_main_view(self, view):
        if self.current_view_frame:
            self.current_view_frame.pack_forget()
        if view == "results":
            self.current_view_frame = self.results_frame
        elif view == "dorks":
            self.current_view_frame = self.dorks_frame
        elif view == "proxies":
            self.current_view_frame = self.proxies_frame
        if self.current_view_frame:
            self.current_view_frame.pack(fill="both", expand=True)
        self.current_view = view

    def build_results_view(self, parent):
        # Results header
        results_header = ctk.CTkFrame(parent, fg_color="transparent", height=36)
        results_header.pack(fill="x", padx=12, pady=(8,0))
        ctk.CTkLabel(results_header, text="LIVE RESULTS", font=ctk.CTkFont(size=13, weight="bold"), text_color="#e0e0e0").pack(side="left")
        self.results_count_label = ctk.CTkLabel(results_header, text="0 results", font=ctk.CTkFont(size=11), text_color="#777")
        self.results_count_label.pack(side="right")

        # Professional Treeview
        tree_container = ctk.CTkFrame(parent, fg_color="#121212", corner_radius=6)
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

        style = ttk.Style()
        style.theme_use("default")
        style.configure("Treeview", background="#121212", foreground="#e0e0e0", fieldbackground="#121212", rowheight=26, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#1f1f1f", foreground="#aaa", font=("Segoe UI", 10, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", "#2e4a3e")])

        vsb = ttk.Scrollbar(tree_container, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=vsb.set)
        self.results_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.results_tree.bind("<Double-1>", self._on_tree_double_click)
        self.results_tree_data = {}

        self.progress = ctk.CTkProgressBar(parent, height=6, progress_color="#00c853")
        self.progress.pack(fill="x", padx=12, pady=(0,10))
        self.progress.set(0)

        # Log inside results view
        log_panel = ctk.CTkFrame(parent, fg_color="#161616", height=140, corner_radius=0)
        log_panel.pack(fill="x", padx=12, pady=(0,8))
        log_panel.pack_propagate(False)

        log_header = ctk.CTkFrame(log_panel, fg_color="transparent")
        log_header.pack(fill="x", padx=10, pady=(4,0))
        ctk.CTkLabel(log_header, text="ACTIVITY LOG", font=ctk.CTkFont(size=11, weight="bold"), text_color="#777").pack(side="left")
        ctk.CTkButton(log_header, text="Clear", width=60, height=20, fg_color="#333", command=lambda: self.log_text.delete("1.0", "end")).pack(side="right")

        self.log_text = scrolledtext.ScrolledText(log_panel, height=5, bg="#0f0f0f", fg="#00c853", font=("Consolas", 9), insertbackground="#00c853", relief="flat", borderwidth=0)
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(2,6))

    def build_dorks_view(self, parent):
        """Vista del generador de dorks con categorías y previsualización."""
        parent.grid_columnconfigure(0, weight=2)
        parent.grid_columnconfigure(1, weight=3)
        parent.grid_rowconfigure(0, weight=1)

        # === LEFT: Generator Controls ===
        left = ctk.CTkScrollableFrame(parent, fg_color="#1a1a1a", corner_radius=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=10)

        ctk.CTkLabel(left, text="🎯 GENERADOR DE DORKS",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color="#00c853").pack(anchor="w", padx=15, pady=(15, 4))
        ctk.CTkLabel(left, text="Selecciona categorías para generar dorks\nefectivos para Google",
                     font=ctk.CTkFont(size=13), text_color="#999").pack(anchor="w", padx=15, pady=(0, 15))

        # Category: E-commerce Platforms
        self.cat_platforms = ctk.BooleanVar(value=True)
        cat1 = ctk.CTkFrame(left, fg_color="#222", corner_radius=8)
        cat1.pack(fill="x", padx=12, pady=5)
        ctk.CTkCheckBox(cat1, text="🛒 Plataformas E-commerce",
                        variable=self.cat_platforms,
                        font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(cat1, text="Shopify, WooCommerce, PrestaShop, Magento, OpenCart",
                     font=ctk.CTkFont(size=11), text_color="#777").pack(anchor="w", padx=35, pady=(0, 10))

        # Category: Checkout/Payment Pages
        self.cat_checkout = ctk.BooleanVar(value=True)
        cat2 = ctk.CTkFrame(left, fg_color="#222", corner_radius=8)
        cat2.pack(fill="x", padx=12, pady=5)
        ctk.CTkCheckBox(cat2, text="💳 Páginas de Checkout / Pago",
                        variable=self.cat_checkout,
                        font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(cat2, text="inurl:checkout, inurl:payment, inurl:pago, inurl:cart",
                     font=ctk.CTkFont(size=11), text_color="#777").pack(anchor="w", padx=35, pady=(0, 10))

        # Category: Store URLs
        self.cat_stores = ctk.BooleanVar(value=True)
        cat3 = ctk.CTkFrame(left, fg_color="#222", corner_radius=8)
        cat3.pack(fill="x", padx=12, pady=5)
        ctk.CTkCheckBox(cat3, text="🛍️ Tiendas por URL",
                        variable=self.cat_stores,
                        font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(cat3, text='inurl:shop, inurl:store, inurl:tienda, "add to cart"',
                     font=ctk.CTkFont(size=11), text_color="#777").pack(anchor="w", padx=35, pady=(0, 10))

        # Category: Subscriptions/Memberships
        self.cat_subscriptions = ctk.BooleanVar(value=False)
        cat4 = ctk.CTkFrame(left, fg_color="#222", corner_radius=8)
        cat4.pack(fill="x", padx=12, pady=5)
        ctk.CTkCheckBox(cat4, text="🔄 Suscripciones / Membresías",
                        variable=self.cat_subscriptions,
                        font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(cat4, text='"subscribe" "membership" "plan" "pricing"',
                     font=ctk.CTkFont(size=11), text_color="#777").pack(anchor="w", padx=35, pady=(0, 10))

        # TLD / Country
        tld_frame = ctk.CTkFrame(left, fg_color="#222", corner_radius=8)
        tld_frame.pack(fill="x", padx=12, pady=(15, 5))
        ctk.CTkLabel(tld_frame, text="🌎 País / TLD",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(tld_frame, text="Separa con espacios. Deja vacío para buscar sin filtro de país.",
                     font=ctk.CTkFont(size=10), text_color="#666").pack(anchor="w", padx=12, pady=(0, 2))
        self.dork_tld_entry = ctk.CTkEntry(tld_frame,
                                           placeholder_text=".mx .co .es .com .ar .cl",
                                           font=ctk.CTkFont(size=13), height=36)
        self.dork_tld_entry.pack(fill="x", padx=12, pady=(0, 10))
        self.dork_tld_entry.insert(0, ".mx .co .com")

        # Custom dorks
        custom_frame = ctk.CTkFrame(left, fg_color="#222", corner_radius=8)
        custom_frame.pack(fill="x", padx=12, pady=5)
        ctk.CTkLabel(custom_frame, text="🔧 Dorks Personalizados (uno por línea)",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.custom_dorks_text = ctk.CTkTextbox(custom_frame, height=80,
                                                font=ctk.CTkFont(family="Consolas", size=12))
        self.custom_dorks_text.pack(fill="x", padx=12, pady=(0, 10))
        self.custom_dorks_text.insert("1.0", '# Un dork por línea\ninurl:"shop centri"\n"powered by shopify" site:.mx')

        # Buttons
        btn_frame = ctk.CTkFrame(left, fg_color="transparent")
        btn_frame.pack(fill="x", padx=12, pady=(15, 10))
        ctk.CTkButton(btn_frame, text="⚡ GENERAR DORKS",
                      fg_color="#00c853", text_color="#111",
                      height=44, font=ctk.CTkFont(size=15, weight="bold"),
                      command=self.generate_dorks).pack(fill="x", pady=3)
        ctk.CTkButton(btn_frame, text="🚀 GENERAR Y BUSCAR",
                      fg_color="#2196f3", text_color="#fff",
                      height=44, font=ctk.CTkFont(size=15, weight="bold"),
                      command=self.generate_and_search).pack(fill="x", pady=3)

        # === RIGHT: Generated Dorks Preview ===
        right = ctk.CTkFrame(parent, fg_color="#1a1a1a", corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=10)

        header = ctk.CTkFrame(right, fg_color="transparent")
        header.pack(fill="x", padx=15, pady=(12, 0))
        ctk.CTkLabel(header, text="📋 DORKS GENERADOS",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color="#e0e0e0").pack(side="left")
        self.dorks_count_label = ctk.CTkLabel(header, text="0 dorks",
                                              font=ctk.CTkFont(size=13), text_color="#777")
        self.dorks_count_label.pack(side="right")

        self.dorks_listbox = ctk.CTkTextbox(right,
                                            font=ctk.CTkFont(family="Consolas", size=13))
        self.dorks_listbox.pack(fill="both", expand=True, padx=12, pady=8)

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.pack(fill="x", padx=12, pady=(0, 10))
        ctk.CTkButton(btns, text="Copiar a búsqueda activa", width=180,
                      command=self.copy_dorks_to_search).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Limpiar duplicados", width=140,
                      fg_color="#555", command=self.clean_dups_dorks).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Limpiar todo", width=100,
                      fg_color="#aa3333",
                      command=lambda: (self.dorks_generated.clear(), self.update_dorks_list())).pack(side="left", padx=4)

    def build_proxies_view(self, parent):
        ctk.CTkLabel(parent, text="PROXIES - Gestión Avanzada (test real con timing)", font=ctk.CTkFont(size=14, weight="bold"), text_color="#00c853").pack(anchor="w", padx=10, pady=8)

        # Manual add + import row
        add_frame = ctk.CTkFrame(parent, fg_color="transparent")
        add_frame.pack(fill="x", padx=10, pady=4)
        self.manual_proxy_entry = ctk.CTkEntry(add_frame, placeholder_text="Add proxy: 1.2.3.4:80 or http://user:pass@ip:port")
        self.manual_proxy_entry.pack(side="left", fill="x", expand=True, padx=(0,5))
        ctk.CTkButton(add_frame, text="Add Manual", width=100, command=self.add_manual_proxy).pack(side="left")

        # Import and control buttons
        import_frame = ctk.CTkFrame(parent, fg_color="transparent")
        import_frame.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(import_frame, text="Import TXT", command=lambda: self.import_proxies_file("txt")).pack(side="left", padx=4)
        ctk.CTkButton(import_frame, text="Import JSON", command=lambda: self.import_proxies_file("json")).pack(side="left", padx=4)
        ctk.CTkButton(import_frame, text="Import CSV", command=lambda: self.import_proxies_file("csv")).pack(side="left", padx=4)
        self.test_btn = ctk.CTkButton(import_frame, text="Test All (Real)", fg_color="#00c853", text_color="#111", command=self.test_all_proxies)
        self.test_btn.pack(side="left", padx=10)
        self.pause_test_btn = ctk.CTkButton(import_frame, text="Pause Test", fg_color="#ff9800", command=self.pause_proxy_test)
        self.pause_test_btn.pack(side="left", padx=4)
        ctk.CTkButton(import_frame, text="Delete Dead", fg_color="#aa3333", command=self.delete_dead_proxies).pack(side="left", padx=4)
        ctk.CTkButton(import_frame, text="Delete Selected", command=self.delete_selected_proxy).pack(side="left", padx=4)

        # Proxies tree
        columns = ("proxy", "type", "status", "time_ms")
        self.proxies_tree = ttk.Treeview(parent, columns=columns, show="headings", height=15)
        for col, txt in [("proxy", "Proxy"), ("type", "Tipo"), ("status", "Estado"), ("time_ms", "Tiempo (ms)")]:
            self.proxies_tree.heading(col, text=txt)
        self.proxies_tree.column("proxy", width=320)
        self.proxies_tree.column("type", width=70)
        self.proxies_tree.column("status", width=140)
        self.proxies_tree.column("time_ms", width=90)
        self.proxies_tree.pack(fill="both", expand=True, padx=10, pady=8)

        self.proxies_tree_data = {}  # index mapping

        # Double click to delete individual
        self.proxies_tree.bind("<Double-1>", self._on_proxy_double_click_delete)

    def generate_dorks(self):
        """Genera dorks efectivos basados en las categorías seleccionadas y TLDs."""
        tld_raw = self.dork_tld_entry.get().strip()

        # Parse TLDs
        tlds = []
        for t in tld_raw.split():
            t = t.strip()
            if not t:
                continue
            if not t.startswith("site:"):
                if t.startswith("."):
                    t = f"site:{t}"
                else:
                    t = f"site:.{t}"
            tlds.append(t)

        base_patterns = []

        if self.cat_platforms.get():
            base_patterns.extend([
                '"powered by shopify"',
                '"woocommerce" shop',
                '"prestashop"',
                '"magento" store',
                '"opencart"'
            ])

        if self.cat_checkout.get():
            base_patterns.extend([
                'inurl:checkout "credit card"',
                'inurl:payment "card number"',
                'inurl:pago "tarjeta"',
                'inurl:checkout "stripe"'
            ])

        if self.cat_stores.get():
            base_patterns.extend([
                'inurl:shop "add to cart"',
                'inurl:store "buy now"',
                'inurl:tienda "comprar"'
            ])

        if self.cat_subscriptions.get():
            base_patterns.extend([
                'inurl:subscribe "membership"',
                'inurl:subscribe "plan"',
                'inurl:subscribe "pricing"'
            ])

        # Combinar base_patterns con TLDs
        generated = []
        if tlds:
            for pat in base_patterns:
                for tld in tlds:
                    generated.append(f"{pat} {tld}")
        else:
            generated = base_patterns[:]

        # Dorks personalizados
        custom_raw = self.custom_dorks_text.get("1.0", "end").strip()
        custom_lines = []
        for line in custom_raw.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                custom_lines.append(line)

        # Combinar y quitar duplicados
        all_dorks = generated + custom_lines
        unique = []
        seen = set()
        for d in all_dorks:
            if d not in seen:
                seen.add(d)
                unique.append(d)

        self.dorks_generated = unique
        self.update_dorks_list()
        self._do_log(f"Generados {len(self.dorks_generated)} dorks efectivos para Google.")

    def generate_and_search(self):
        """Genera los dorks, los copia para la búsqueda y arranca el escaneo."""
        self.generate_dorks()
        if not self.dorks_generated:
            self._do_log("⚠️ No se generaron dorks. Selecciona alguna categoría o añade dorks personalizados.")
            return
        self.copy_dorks_to_search()
        self.switch_main_view("results")
        if not self.runner or not self.runner.is_running():
            self.toggle_search()

    def update_dorks_list(self):
        self.dorks_listbox.delete("1.0", "end")
        self.dorks_listbox.insert("1.0", "\n".join(self.dorks_generated))

    def clean_dups_dorks(self):
        before = len(self.dorks_generated)
        self.dorks_generated = list(dict.fromkeys(self.dorks_generated))  # preserve order, remove dups
        self.update_dorks_list()
        self._do_log(f"Limpiados {before - len(self.dorks_generated)} duplicados.")

    def copy_dorks_to_search(self):
        # For search, we can set the custom or a active list
        if not self.dorks_generated:
            return
        # For simplicity, append to a search dorks
        if not hasattr(self, 'search_dorks'):
            self.search_dorks = []
        self.search_dorks.extend(self.dorks_generated)
        self.search_dorks = list(dict.fromkeys(self.search_dorks))
        self._do_log("Dorks copiados para la búsqueda.")

    def import_proxies_file(self, ftype):
        import json, csv
        path = filedialog.askopenfilename(filetypes=[(f"{ftype.upper()} files", f"*.{ftype}")])
        if not path:
            return
        added = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                if ftype == "txt":
                    for line in f:
                        p = line.strip()
                        if p and p not in [x['raw'] for x in self.proxies_data]:
                            self.proxies_data.append({"raw": p, "type": "unknown", "status": "not tested", "time_ms": None})
                            added += 1
                elif ftype == "json":
                    data = json.load(f)
                    for item in data if isinstance(data, list) else []:
                        p = item if isinstance(item, str) else item.get("proxy", "")
                        if p and p not in [x['raw'] for x in self.proxies_data]:
                            self.proxies_data.append({"raw": p, "type": "unknown", "status": "not tested", "time_ms": None})
                            added += 1
                elif ftype == "csv":
                    reader = csv.reader(f)
                    for row in reader:
                        if row and row[0].strip():
                            p = row[0].strip()
                            if p not in [x['raw'] for x in self.proxies_data]:
                                self.proxies_data.append({"raw": p, "type": "unknown", "status": "not tested", "time_ms": None})
                                added += 1
            self.update_proxies_tree()
            self.save_all_proxies_to_db()
            self._do_log(f"Importados {added} proxies desde {path}")
        except Exception as e:
            self._do_log(f"Error importando: {e}")


    def test_all_proxies(self):
        import time
        from playwright.sync_api import sync_playwright

        if not self.proxies_data:
            self._do_log("No proxies to test.")
            return

        self.testing_active = True

        def test_thread():
            self.after(0, lambda: self.test_btn.configure(text="Testing... (use Pause)"))
            self.after(0, lambda: self.pause_test_btn.configure(text="Pause", fg_color="#ff9800"))
            self._do_log("🔄 Starting proxy test (real connection, reusing browser)...")

            pw = None
            browser = None
            try:
                pw = sync_playwright().start()
                browser = pw.chromium.launch(headless=True, timeout=15000)

                # Obtener timeout configurable del usuario
                try:
                    timeout_sec = int(self.page_timeout_entry.get() or 45)
                except Exception:
                    timeout_sec = 45
                timeout_ms = timeout_sec * 1000

                for idx, p in enumerate(self.proxies_data):
                    if not getattr(self, 'testing_active', True):
                        self._do_log("⏹️ Proxy test paused/stopped.")
                        break

                    raw = p['raw'].strip()
                    if not raw:
                        continue

                    # Auto add scheme if missing
                    if '://' not in raw:
                        candidates = [f"http://{raw}", f"https://{raw}", f"socks5://{raw}", f"socks4://{raw}"]
                    else:
                        candidates = [raw]

                    best_time = None
                    best_type = "unknown"
                    status = "dead"

                    for cand in candidates:
                        # Si es http o https, usar urllib (muy rápido)
                        if cand.startswith("http://") or cand.startswith("https://"):
                            import urllib.request
                            import urllib.error

                            proxy_handler = urllib.request.ProxyHandler({
                                'http': cand,
                                'https': cand
                            })
                            opener = urllib.request.build_opener(proxy_handler)

                            # Intentar con HTTP y HTTPS generate_204
                            for test_url in ["http://google.com/generate_204", "https://google.com/generate_204"]:
                                try:
                                    start = time.time()
                                    req = urllib.request.Request(test_url, headers={'User-Agent': 'Mozilla/5.0'})
                                    with opener.open(req, timeout=timeout_sec) as resp:
                                        resp.read()
                                    elapsed = int((time.time() - start) * 1000)
                                    if best_time is None or elapsed < best_time:
                                        best_time = elapsed
                                        best_type = cand.split("://")[0]
                                    status = "alive"
                                    break
                                except urllib.error.HTTPError as he:
                                    elapsed = int((time.time() - start) * 1000)
                                    # 407, 403, 502, etc. de un proxy indica que está activo
                                    if he.code in (407, 403, 502, 503, 504, 204):
                                        if best_time is None or elapsed < best_time:
                                            best_time = elapsed
                                            best_type = cand.split("://")[0]
                                        status = "alive"
                                        break
                                except Exception as e:
                                    elapsed = int((time.time() - start) * 1000)
                                    err_str = str(e).lower()
                                    if "connection refused" in err_str or "connection failed" in err_str:
                                        if status != "alive" and status != "timeout":
                                            status = "dead"
                                    else:
                                        if status != "alive":
                                            status = "timeout"
                                        if best_time is None or elapsed < best_time:
                                            best_time = elapsed
                                            best_type = cand.split("://")[0]

                            if status == "alive":
                                break
                        else:
                            # SOCKS u otro tipo de proxy -> Usar Playwright
                            ctx = None
                            try:
                                start = time.time()
                                ctx = browser.new_context(
                                    proxy={"server": cand},
                                    ignore_https_errors=True,
                                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                                )
                                pg = ctx.new_page()
                                pg.goto("https://google.com/generate_204", timeout=timeout_ms, wait_until="domcontentloaded")
                                elapsed = int((time.time() - start) * 1000)
                                if best_time is None or elapsed < best_time:
                                    best_time = elapsed
                                    best_type = cand.split("://")[0]
                                status = "alive"
                                break
                            except Exception as e:
                                elapsed = int((time.time() - start) * 1000)
                                err_str = str(e)
                                if "ERR_PROXY_CONNECTION_FAILED" in err_str or "net::ERR" in err_str or "Connection refused" in err_str:
                                    if status != "alive" and status != "timeout":
                                        status = "dead"
                                else:
                                    if status != "alive":
                                        status = "timeout"
                                    if best_time is None or elapsed < best_time:
                                        best_time = elapsed
                                        best_type = cand.split("://")[0]
                                continue
                            finally:
                                if ctx:
                                    try:
                                        ctx.close()
                                    except Exception:
                                        pass

                    p['type'] = best_type
                    p['status'] = status
                    p['time_ms'] = best_time if best_time else None

                    # Persist single proxy test result
                    from .persistence import save_single_proxy
                    save_single_proxy(p)

                    # Thread-safe update
                    self.after(0, lambda p=p: self._update_single_proxy_in_tree(p))

                    msg = f"Test {raw} : {status}"
                    if best_time:
                        msg += f" ({best_time}ms)"
                    self.after(0, lambda m=msg: self._do_log(m))

            except Exception as e:
                self.after(0, lambda e=e: self._do_log(f"❌ Error launching browser: {e}"))
            finally:
                if browser:
                    try:
                        browser.close()
                    except Exception:
                        pass
                if pw:
                    try:
                        pw.stop()
                    except Exception:
                        pass

            self.testing_active = False
            self.after(0, lambda: self.test_btn.configure(text="Test All (Real)"))
            self.after(0, lambda: self.pause_test_btn.configure(text="Pause Test", fg_color="#ff9800"))
            self.after(0, lambda: self._do_log("✅ Proxy test finished."))

        threading.Thread(target=test_thread, daemon=True).start()

    def _update_single_proxy_in_tree(self, p):
        # Update the tree for this proxy
        self.update_proxies_tree()  # simple way, or optimize later

    def pause_proxy_test(self):
        self.testing_active = False
        self._do_log("Pause requested for proxy test.")

    def delete_dead_proxies(self):
        before = len(self.proxies_data)
        self.proxies_data = [p for p in self.proxies_data if p.get('status') != 'dead']
        self.update_proxies_tree()
        self.save_all_proxies_to_db()
        self._do_log(f"Borrados {before - len(self.proxies_data)} proxies caídos.")


    def add_manual_proxy(self):
        text = self.manual_proxy_entry.get().strip()
        if not text:
            return
        added = 0
        for line in text.splitlines():
            p = line.strip()
            if p and p not in [x['raw'] for x in self.proxies_data]:
                self.proxies_data.append({"raw": p, "type": "unknown", "status": "not tested", "time_ms": None})
                added += 1
        self.manual_proxy_entry.delete(0, "end")
        self.update_proxies_tree()
        self.save_all_proxies_to_db()
        self._do_log(f"Added {added} manual proxy(es).")

    def delete_selected_proxy(self):
        selected = self.proxies_tree.selection()
        if not selected:
            return
        indices = sorted([self.proxies_tree_data[item] for item in selected if item in self.proxies_tree_data], reverse=True)
        for idx in indices:
            if 0 <= idx < len(self.proxies_data):
                del self.proxies_data[idx]
        self.update_proxies_tree()
        self.save_all_proxies_to_db()
        self._do_log("Deleted selected proxy(ies).")

    def _on_proxy_double_click_delete(self, event):
        item = self.proxies_tree.identify_row(event.y)
        if item and item in self.proxies_tree_data:
            idx = self.proxies_tree_data[item]
            if 0 <= idx < len(self.proxies_data):
                del self.proxies_data[idx]
            self.update_proxies_tree()
            self.save_all_proxies_to_db()
            self._do_log("Deleted proxy.")

    def update_proxies_tree(self):
        for item in self.proxies_tree.get_children():
            self.proxies_tree.delete(item)
        self.proxies_tree_data.clear()
        for i, p in enumerate(self.proxies_data):
            vals = (p.get('raw', ''), p.get('type', '?'), p.get('status', 'not tested'), str(p.get('time_ms')) if p.get('time_ms') is not None else '-')
            item_id = self.proxies_tree.insert("", "end", values=vals)
            self.proxies_tree_data[item_id] = i

    def save_all_proxies_to_db(self):
        from .persistence import save_proxies
        save_proxies(self.proxies_data)

    # ============== MÉTODOS DE UTILIDAD ==============

    def _do_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.update_idletasks()

    def get_active_gateways(self):
        # Always detect all gateways (no selection needed - we identify after visiting)
        return ["adyen", "stripe", "paypal", "mercadopago", "openpay", "authorizenet"]


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
                    # Usar la función centralizada
                    if not is_url_processed(payload.url):
                        self.results.append(payload)
                        mark_url_processed(
                            payload.url,
                            had_payment=True,
                            gateways=payload.gateways,
                            score=payload.confidence_score,
                            dork=payload.dork,
                            country=payload.country
                        )
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
            if hasattr(self, 'proxies_data') and self.proxies_data:
                # Auto use only live proxies if tested
                live_proxies = [p['raw'] for p in self.proxies_data if p.get('status') in ('alive', 'timeout')]
                if live_proxies:
                    proxies = live_proxies
                    self._do_log(f"Using {len(live_proxies)} live/timeout proxies automatically.")
                else:
                    proxies = [p['raw'] for p in self.proxies_data]
                    self._do_log("No live proxies marked, using all.")
            else:
                proxies = []
            max_sites = int(self.max_entry.get() or "50")
            max_concurrent = int(getattr(self, 'concurrent_entry', None).get() if hasattr(self, 'concurrent_entry') else 4) or 4
            country = self.country_menu.get() if hasattr(self, 'country_menu') else "Global"

            # Dorks: usar los generados, o crear dorks básicos de fallback
            if hasattr(self, 'dorks_generated') and self.dorks_generated:
                custom = self.dorks_generated[:]
            elif hasattr(self, 'search_dorks') and self.search_dorks:
                custom = self.search_dorks[:]
            else:
                custom = []

            # Si no hay dorks, generar unos básicos efectivos
            if not custom:
                tld = country if country != "Global" else "site:.com"
                base_dorks = [
                    f'"powered by shopify" {tld}',
                    f'inurl:checkout "payment" {tld}',
                    f'inurl:shop "add to cart" {tld}',
                    f'inurl:store "buy now" {tld}',
                    f'"woocommerce" "add to cart" {tld}',
                    f'inurl:tienda "comprar" {tld}',
                    f'inurl:checkout "credit card" {tld}',
                    f'"prestashop" tienda {tld}',
                ]
            else:
                base_dorks = []

            all_dorks = base_dorks + custom

            use_stealth = self.stealth_var.get() and STEALTH_AVAILABLE
            avoid_cf = bool(self.chk_cloudflare.get())
            page_timeout = int(self.page_timeout_entry.get() or 45) * 1000

            detector = PaymentDetector(
                proxies=proxies,
                use_stealth=use_stealth,
                avoid_cloudflare=avoid_cf,
                active_gateways=["adyen", "stripe", "paypal", "mercadopago", "openpay", "authorizenet"],
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