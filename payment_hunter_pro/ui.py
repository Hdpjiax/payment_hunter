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
        self.engine_menu = ctk.CTkOptionMenu(row3, values=["DuckDuckGo", "Bing"], width=120, height=26)
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
        self.proxies_data = []  # list of dicts {'raw': str, 'type': str, 'status': str, 'time_ms': int or None}

        self.build_results_view(self.results_frame)
        self.build_dorks_view(self.dorks_frame)
        self.build_proxies_view(self.proxies_frame)

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
        # Two columns: Generator controls | Generated Dorks
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        # Left column: Controls to generate specific inurl dorks
        left = ctk.CTkFrame(parent, fg_color="#1f1f1f", corner_radius=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(10,5), pady=10)

        ctk.CTkLabel(left, text="GENERADOR DE DORKS ESPECÍFICOS", font=ctk.CTkFont(size=14, weight="bold"), text_color="#00c853").pack(anchor="w", padx=10, pady=8)

        ctk.CTkLabel(left, text="Estilo: inurl:orderstatus=, inurl:payment=, shop/orders?, etc.", font=ctk.CTkFont(size=10), text_color="#888").pack(anchor="w", padx=10)

        self.dgen_categories = ctk.CTkTextbox(left, height=8, font=ctk.CTkFont(size=10))
        self.dgen_categories.pack(fill="x", padx=10, pady=4)
        self.dgen_categories.insert("1.0", "# Categorías (una por línea)\norderstatus\norderhistory\ninvoice\nbill\npayment\nreceipt\ncheckoutid\ntransactionid\npaymethod\nconfirmorder\ncancelorder\nrefund\npaymentstatus\norderconfirmation\npaymentdetails\npaymentgateway\nshippingstatus\npaymentamount\nordertracking\npaymentreceipt\nordercancelled\nshop/products\nshop/orders\nshop/checkout\nshop/cart\nshop/payment\nshop/invoice")

        ctk.CTkLabel(left, text="Dominios / TLD (ej: site:.com site:.co)", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=10)
        self.dgen_tld = ctk.CTkEntry(left)
        self.dgen_tld.pack(fill="x", padx=10, pady=2)
        self.dgen_tld.insert(0, "site:.com site:.co site:.mx site:.es site:.ar site:.cl")

        ctk.CTkLabel(left, text="Cantidad por categoría", font=ctk.CTkFont(size=10)).pack(anchor="w", padx=10)
        self.dgen_count = ctk.CTkEntry(left, width=80)
        self.dgen_count.pack(anchor="w", padx=10, pady=2)
        self.dgen_count.insert(0, "3")

        ctk.CTkButton(left, text="GENERAR DORKS (estilo que pegaste)", fg_color="#00c853", text_color="#111", height=36,
                      command=self.generate_specific_dorks).pack(fill="x", padx=10, pady=10)

        ctk.CTkButton(left, text="Limpiar duplicados", fg_color="#555", command=self.clean_dups_dorks).pack(fill="x", padx=10, pady=4)

        # Right column: Generated list
        right = ctk.CTkFrame(parent, fg_color="#1f1f1f", corner_radius=8)
        right.grid(row=0, column=1, sticky="nsew", padx=(5,10), pady=10)

        ctk.CTkLabel(right, text="DORKS GENERADOS", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=10, pady=8)

        self.dorks_listbox = ctk.CTkTextbox(right, height=22, font=ctk.CTkFont(family="Consolas", size=10))
        self.dorks_listbox.pack(fill="both", expand=True, padx=10, pady=4)

        btns = ctk.CTkFrame(right, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=4)
        ctk.CTkButton(btns, text="Copiar a Dorks Activos", command=self.copy_dorks_to_search).pack(side="left", padx=4)
        ctk.CTkButton(btns, text="Limpiar lista", fg_color="#aa3333", command=lambda: self.dorks_listbox.delete("1.0", "end")).pack(side="left", padx=4)

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

    def generate_specific_dorks(self):
        """Genera dorks en el estilo EXACTO que pegaste (inurl:orderstatus=, inurl:payment=, shop/orders?, etc).
        Sin pasarelas (se detectan después).
        Usa las categorías del campo (prellenado).
        Cada clic añade más nuevos.
        """
        categories_raw = self.dgen_categories.get("1.0", "end").strip()
        tld_raw = self.dgen_tld.get().strip()
        try:
            count = int(self.dgen_count.get() or "4")
        except:
            count = 4

        categories = [c.strip() for c in categories_raw.splitlines() if c.strip() and not c.startswith("#")]
        if not categories:
            categories = [
                "orderstatus", "orderhistory", "invoice", "bill", "payment", "receipt",
                "checkoutid", "transactionid", "paymethod", "confirmorder", "cancelorder",
                "refund", "refundstatus", "paymentstatus", "orderconfirmation", "ordercomplete",
                "orderedit", "paymentdetails", "paymentgateway", "shippingstatus", "shippingdetails",
                "shippingmethod", "paymentamount", "invoiceid", "transactionstatus", "ordertracking",
                "paymentreceipt", "paymentinvoice", "ordercancelled", "orderrefund", "orderupdate",
                "orderreview", "ordereditform", "paymentform", "ordertrackingid", "deliverystatus",
                "deliverydetails", "shiptracking", "shippingform", "orderid", "orderupdateform",
                "transactstatus", "paymentauth",
                "shop/products", "shop/categories", "shop/orders", "shop/customers", "shop/invoice",
                "shop/payment", "shop/trackorder", "shop/viewcart", "shop/wishlist", "shop/checkout",
                "shop/promotions", "shop/discounts", "shop/coupons", "shop/deals", "shop/bestsellers",
                "shop/newarrivals", "shop/trending", "shop/sale", "shop/featured", "shop/productdetails",
                "shop/reviews", "shop/rating", "shop/compare", "shop/refund", "shop/returnpolicy",
                "shop/shippinginfo", "shop/deliveryoptions", "shop/orderhistory", "shop/orderstatus",
                "shop/paymentoptions", "shop/addressbook", "shop/personalization", "shop/giftcards",
                "shop/storelocator", "shop/subscriptions", "shop/loyaltypoints", "shop/saveditems",
                "shop/relatedproducts"
            ]

        tlds = [t.strip() for t in tld_raw.split() if t.strip()] or ["site:.com", "site:.co", "site:.mx", "site:.es"]

        new_dorks = []
        for cat in categories:
            for _ in range(count):
                for tld in tlds:
                    new_dorks.append(f"{tld} inurl:{cat}=")
                    new_dorks.append(f"{tld} inurl:{cat}?")
                    if "/" in cat or cat.startswith("shop"):
                        new_dorks.append(f"{tld} inurl:{cat}")

        # Quitar duplicados de esta tanda
        seen = set()
        unique = [d for d in new_dorks if not (d in seen or seen.add(d))]

        # Añadir solo los que no estaban antes
        current = set(self.dorks_generated)
        added = 0
        for d in unique:
            if d not in current:
                self.dorks_generated.append(d)
                current.add(d)
                added += 1

        self.update_dorks_list()
        self._do_log(f"Generados {added} nuevos dorks estilo inurl (exacto al que pegaste). Total: {len(self.dorks_generated)}")

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
        from tkinter import filedialog
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
            self._do_log(f"Importados {added} proxies desde {path}")
        except Exception as e:
            self._do_log(f"Error importando: {e}")

    def update_proxies_tree(self):
        for item in self.proxies_tree.get_children():
            self.proxies_tree.delete(item)
        for i, p in enumerate(self.proxies_data):
            item = self.proxies_tree.insert("", "end", values=(p['raw'], p.get('type','?'), p.get('status','?'), p.get('time_ms') or '-'))
            self.proxies_tree_data[item] = i

    def test_all_proxies(self):
        import time
        from playwright.sync_api import sync_playwright

        if not self.proxies_data:
            self._do_log("No proxies to test.")
            return

        self.testing_active = True
        test_btn = None  # we'll find or use a ref, for now use log

        def test_thread():
            self.after(0, lambda: self.test_btn.configure(text="Testing... (use Pause)"))
            self.after(0, lambda: self.pause_test_btn.configure(text="Pause", fg_color="#ff9800"))
            self._do_log("🔄 Starting proxy test (real connection, auto scheme detect)...")
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
                    try:
                        start = time.time()
                        with sync_playwright() as pl:
                            b = pl.chromium.launch(headless=True, timeout=10000)
                            ctx = b.new_context(
                                proxy={"server": cand},
                                ignore_https_errors=True,
                                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                            )
                            pg = ctx.new_page()
                            # Use fast reliable target
                            pg.goto("https://1.1.1.1", timeout=15000, wait_until="domcontentloaded")
                            b.close()
                        elapsed = int((time.time() - start) * 1000)
                        if best_time is None or elapsed < best_time:
                            best_time = elapsed
                            best_type = cand.split("://")[0]
                        status = "alive"
                        break
                    except Exception as e:
                        err_str = str(e)
                        if "ERR_PROXY_CONNECTION_FAILED" in err_str or "net::ERR" in err_str or "Connection refused" in err_str:
                            status = "dead"
                        else:
                            status = "timeout"
                        continue

                p['type'] = best_type
                p['status'] = status
                p['time_ms'] = best_time if best_time else None

                # Thread-safe update
                self.after(0, lambda p=p: self._update_single_proxy_in_tree(p))

                msg = f"Test {raw} : {status}"
                if best_time:
                    msg += f" ({best_time}ms)"
                self.after(0, lambda m=msg: self._do_log(m))

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
        self._do_log(f"Borrados {before - len(self.proxies_data)} proxies caídos.")

    def _on_tree_double_click(self, event):
        item = self.results_tree.identify_row(event.y)
        if item and item in self.results_tree_data:
            webbrowser.open(self.results_tree_data[item])

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
        self._do_log("Deleted selected proxy(ies).")

    def _on_proxy_double_click_delete(self, event):
        item = self.proxies_tree.identify_row(event.y)
        if item and item in self.proxies_tree_data:
            idx = self.proxies_tree_data[item]
            if 0 <= idx < len(self.proxies_data):
                del self.proxies_data[idx]
            self.update_proxies_tree()
            self._do_log("Deleted proxy.")

    def update_proxies_tree(self):
        for item in self.proxies_tree.get_children():
            self.proxies_tree.delete(item)
        self.proxies_tree_data.clear()
        for i, p in enumerate(self.proxies_data):
            vals = (p.get('raw', ''), p.get('type', '?'), p.get('status', 'not tested'), str(p.get('time_ms')) if p.get('time_ms') is not None else '-')
            item_id = self.proxies_tree.insert("", "end", values=vals)
            self.proxies_tree_data[item_id] = i

    # ============== MÉTODOS DE UTILIDAD ==============

    def _do_log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{ts}] {msg}\n")
        self.log_text.see("end")
        self.update_idletasks()

    def get_active_gateways(self):
        # Always detect all gateways (no selection needed - we identify after visiting)
        return ["adyen", "stripe", "paypal", "mercadopago", "openpay", "authorizenet"]

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

    def _generate_dorks_in_results(self):
        """Genera muchos dorks desde el panel principal de resultados y los añade."""
        payment = [t.strip() for t in self.main_payment_terms.get().split(",") if t.strip()]
        shop = [t.strip() for t in self.main_shop_terms.get().split(",") if t.strip()]
        active = self.get_active_gateways()
        country = self.country_menu.get() if hasattr(self, 'country_menu') else "Global"

        if not active:
            messagebox.showwarning("Dorks", "Selecciona pasarelas primero.")
            return

        generated = []
        for gw in active:
            for p in payment[:5]:
                for s in shop[:5]:
                    generated.append(f'{gw} "{p}" {s} {country}')
            generated.append(f'{gw} (inurl:checkout OR inurl:payment OR inurl:subscribe) (pagar OR pay OR suscrib) {country}')

        seen = set()
        unique = []
        for d in generated:
            if d not in seen:
                seen.add(d)
                unique.append(d)

        current = self.custom_dorks.get("1.0", "end").strip()
        new_text = "\n".join(unique[:35])

        if current and not current.startswith("#"):
            self.custom_dorks.delete("1.0", "end")
            self.custom_dorks.insert("1.0", current + "\n" + new_text)
        else:
            self.custom_dorks.delete("1.0", "end")
            self.custom_dorks.insert("1.0", new_text)

        self._do_log(f"Generados {len(unique[:35])} dorks desde el panel de resultados.")

    # generate_advanced_dorks removido del sidebar (queda la versión integrada en resultados)

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
                live_proxies = [p['raw'] for p in self.proxies_data if p.get('status') == 'alive']
                if live_proxies:
                    proxies = live_proxies
                    self._do_log(f"Using {len(live_proxies)} live proxies automatically.")
                else:
                    proxies = [p['raw'] for p in self.proxies_data]
                    self._do_log("No live proxies marked, using all.")
            else:
                proxies = [
                    line.strip() for line in (self.proxy_text.get("1.0", "end") if hasattr(self, 'proxy_text') else '').splitlines()
                    if line.strip() and not line.startswith("#")
                ]
            max_sites = int(self.max_entry.get() or "50")
            max_concurrent = int(getattr(self, 'concurrent_entry', None).get() if hasattr(self, 'concurrent_entry') else 4) or 4

            # Dorks generales (sin nombres de pasarela).
            # La pasarela se detecta al visitar la página.
            base_dorks = []
            country = self.country_menu.get()

            shop_context = '(shop OR store OR tienda OR ecommerce OR "tienda online" OR cart OR checkout OR "comprar")'

            base_dorks.extend([
                f'("checkout" OR "payment form" OR "proceed to checkout" OR "place order" OR "finalizar compra") '
                f'("form" OR "card" OR "cvv" OR "billing" OR "pagar" OR "pay") '
                f'{shop_context} {country}',

                f'inurl:(checkout OR payment OR cart OR billing) '
                f'("form" OR "card" OR "pagar") '
                f'{shop_context} {country}',

                f'("add to cart" OR "buy now" OR "suscribirse") '
                f'("payment" OR "checkout" OR "pagar") '
                f'{shop_context} {country}',
            ])

            # Para que coincida con tu estilo, si usas dorks del generador (inurl:orderstatus= etc), se priorizarán
            # las que también tengan palabras de tienda.
            if hasattr(self, 'dorks_generated') and self.dorks_generated:
                custom = self.dorks_generated[:]
            else:
                custom = [
                    d.strip() for d in (self.custom_dorks.get("1.0", "end") if hasattr(self, 'custom_dorks') else "").splitlines()
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
