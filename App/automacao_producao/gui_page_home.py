"""Início page: the single hub every other screen is reached from and comes
back to -- one dashboard of cards instead of a sidebar full of nav buttons,
so there's only one place to go looking for "where's X".
"""
import customtkinter as ctk

import db
import gui_theme
import gui_worker
import website_sync


class HomePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=32, pady=(36, 24))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="O que você precisa fazer?", font=ctk.CTkFont(size=24, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            header, text="🔄 Atualizar", width=110, height=32, fg_color="gray45", hover_color="gray35",
            command=lambda: self.on_show(),
        ).grid(row=0, column=1, sticky="e")

        # Scrollable: 14 cards no longer fit a single fixed-height screen the way the original 9 did.
        # The scrollbar track itself is hidden (mouse-wheel scrolling still works -- customtkinter
        # binds that independently of the scrollbar widget's visibility).
        self.cards_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.cards_frame.grid(row=1, column=0, sticky="nsew", padx=16)
        self.cards_frame._scrollbar.grid_remove()
        for col in range(4):
            self.cards_frame.grid_columnconfigure(col, weight=1)

        # ── Produção ──────────────────────────────────────────────────────
        self._build_section_header(row=0, text="Produção")
        self.orders_card = self._build_card(
            row=1, column=0, emoji="🌐", title="Pedidos do site",
            subtitle="Ver o que os clientes escolheram, validar e mandar pra produção.",
            color=gui_theme.ACCENT, hover=gui_theme.ACCENT_HOVER,
            command=lambda: app.show_page("website"),
        )
        self.queue_card = self._build_card(
            row=1, column=1, emoji="🧵", title="Gerar Produção",
            subtitle="Ver a fila e gerar a folha de produção no CorelDRAW.",
            color=gui_theme.ACCENT_BLUE, hover=gui_theme.ACCENT_BLUE_HOVER,
            command=lambda: app.show_page("queue"),
        )
        self._build_card(
            row=1, column=2, emoji="📦", title="Montar Pedido",
            subtitle="Aleatório, lista de REFs ou quantidades específicas — tudo cai na mesma fila.",
            color=gui_theme.ACCENT_PURPLE, hover=gui_theme.ACCENT_PURPLE_HOVER,
            command=lambda: app.show_page("order"),
        )
        self._build_card(
            row=1, column=3, emoji="🔍", title="Buscar Produto",
            subtitle="Achar um produto pelo REF ou por foto do cliente.",
            color=gui_theme.ACCENT_MINT, hover=gui_theme.ACCENT_MINT_HOVER,
            command=lambda: app.show_page("search"),
        )

        # ── Catálogos ─────────────────────────────────────────────────────
        self._build_section_header(row=2, text="Catálogos")
        self._build_card(
            row=3, column=0, emoji="📁", title="Catálogos",
            subtitle="Importar, publicar ou excluir catálogos.",
            color=gui_theme.ACCENT_MINT, hover=gui_theme.ACCENT_MINT_HOVER,
            command=lambda: app.show_page("catalogs"),
        )
        self._build_card(
            row=3, column=1, emoji="🖨️", title="Gerador de Catálogos",
            subtitle="Abre um catálogo master e gera uma versão nova em outro tamanho.",
            color=gui_theme.ACCENT_BLUE, hover=gui_theme.ACCENT_BLUE_HOVER,
            command=lambda: app.show_page("catalog_generator"),
        )
        self._build_card(
            row=3, column=2, emoji="📐", title="Catálogo Multi-Tamanho",
            subtitle="Separa as figuras em até 3 tamanhos fixos; REFs preenchidas automaticamente.",
            color=gui_theme.ACCENT_PURPLE, hover=gui_theme.ACCENT_PURPLE_HOVER,
            command=lambda: app.show_page("catalog_3_sizes"),
        )
        self._build_card(
            row=3, column=3, emoji="🆕", title="Criar Catálogo do Zero",
            subtitle="Monta um catálogo novo a partir de figuras soltas (REF e tamanho automáticos).",
            color=gui_theme.ACCENT, hover=gui_theme.ACCENT_HOVER,
            command=lambda: app.show_page("scratch_catalog"),
        )
        self._build_card(
            row=4, column=0, emoji="📥", title="Importar .cdr em Lote",
            subtitle="Escolhe vários arquivos .cdr do computador e importa tudo num catálogo só.",
            color=gui_theme.ACCENT_SLATE, hover=gui_theme.ACCENT_SLATE_HOVER,
            command=lambda: app.show_page("merge_catalogs"),
        )
        self._build_card(
            row=4, column=1, emoji="🔗", title="Catálogo Personalizado",
            subtitle="Gera um link só com um catálogo escolhido, com o nome do cliente, pra mandar no WhatsApp.",
            color=gui_theme.ACCENT_MINT, hover=gui_theme.ACCENT_MINT_HOVER,
            command=lambda: app.show_page("personalized_catalog"),
        )
        self._build_card(
            row=4, column=2, emoji="👤", title="Representantes",
            subtitle="Cadastra quem aparece no seletor do pedido e tem painel próprio de pedidos no site.",
            color=gui_theme.ACCENT_PURPLE, hover=gui_theme.ACCENT_PURPLE_HOVER,
            command=lambda: app.show_page("representantes"),
        )
        self._build_card(
            row=4, column=3, emoji="🏷️", title="Tabela de Preços",
            subtitle="Preço por tipo de produto e medida -- usado pra gerar o orçamento de um pedido.",
            color=gui_theme.ACCENT_SLATE, hover=gui_theme.ACCENT_SLATE_HOVER,
            command=lambda: app.show_page("prices"),
        )
        # ── Preparar Arquivos ─────────────────────────────────────────────
        self._build_section_header(row=5, text="Preparar Arquivos")
        self._build_card(
            row=6, column=0, emoji="✂️", title="Separador de Figuras (IA)",
            subtitle="Separa uma folha com várias figuras em PNGs individuais.",
            color=gui_theme.ACCENT_BLUE, hover=gui_theme.ACCENT_BLUE_HOVER,
            command=lambda: app.show_page("figure_splitter"),
        )
        self._build_card(
            row=6, column=1, emoji="📏", title="Redimensionador em Lote",
            subtitle="Redimensiona várias figuras já cortadas pra dois ou mais tamanhos de uma vez.",
            color=gui_theme.ACCENT, hover=gui_theme.ACCENT_HOVER,
            command=lambda: app.show_page("batch_resize"),
        )
        self._build_card(
            row=6, column=2, emoji="🪄", title="Melhorador de Imagens (IA)",
            subtitle="Melhora a nitidez e remove o fundo das figuras de um catálogo, em lote.",
            color=gui_theme.ACCENT_MINT, hover=gui_theme.ACCENT_MINT_HOVER,
            command=lambda: app.show_page("image_enhancer"),
        )
        self._build_card(
            row=6, column=3, emoji="✨", title="Criar Figura (IA)",
            subtitle="Descreve em português e a IA desenha uma figura nova (experimental).",
            color=gui_theme.ACCENT_PURPLE, hover=gui_theme.ACCENT_PURPLE_HOVER,
            command=lambda: app.show_page("ai_figure_creator"),
        )

        # ── CorelDRAW ─────────────────────────────────────────────────────
        self._build_section_header(row=7, text="CorelDRAW")
        self._build_card(
            row=8, column=0, emoji="🧩", title="Montador de Folha",
            subtitle="Tila figuras direto numa folha do CorelDRAW, sem passar pela fila.",
            color=gui_theme.ACCENT_PURPLE, hover=gui_theme.ACCENT_PURPLE_HOVER,
            command=lambda: app.show_page("sheet_assembler"),
        )
        self._build_card(
            row=8, column=1, emoji="🏭", title="Produção do Catálogo Inteiro",
            subtitle="Acha as REFs de uma medida atual e gera a produção delas numa medida nova.",
            color=gui_theme.ACCENT_MINT, hover=gui_theme.ACCENT_MINT_HOVER,
            command=lambda: app.show_page("catalog_production"),
        )
        self._build_card(
            row=8, column=2, emoji="📄", title="Ajuntador de Páginas",
            subtitle="Junta todas as páginas do documento aberto no CorelDRAW numa página só.",
            color=gui_theme.ACCENT_SLATE, hover=gui_theme.ACCENT_SLATE_HOVER,
            command=lambda: app.show_page("join_pages"),
        )
        self._build_card(
            row=8, column=3, emoji="🔃", title="Conversor de Versão",
            subtitle="Abre um .cdr, mostra a versão e salva convertido pra outra.",
            color=gui_theme.ACCENT_BLUE, hover=gui_theme.ACCENT_BLUE_HOVER,
            command=lambda: app.show_page("version_converter"),
        )
        self._build_card(
            row=9, column=0, emoji="📏", title="Corrigir Tamanho",
            subtitle="Acha peças na medida errada no documento aberto no CorelDRAW e ajusta pro tamanho certo.",
            color=gui_theme.ACCENT_PURPLE, hover=gui_theme.ACCENT_PURPLE_HOVER,
            command=lambda: app.show_page("fix_shape_sizes"),
        )

        # ── Mais Ferramentas ──────────────────────────────────────────────
        self._build_section_header(row=10, text="Mais Ferramentas")
        self._build_card(
            row=11, column=0, emoji="🏷️", title="Gerador de Etiquetas",
            subtitle="Gera referência + código de barras (EAN-13) em PDF pra imprimir.",
            color=gui_theme.ACCENT_SLATE, hover=gui_theme.ACCENT_SLATE_HOVER,
            command=lambda: app.show_page("label_generator"),
        )
        self._build_card(
            row=11, column=1, emoji="📐", title="Perfis de Produção",
            subtitle="Tamanho da área, margens e espaçamento entre peças.",
            color=gui_theme.ACCENT_BLUE, hover=gui_theme.ACCENT_BLUE_HOVER,
            command=lambda: app.show_page("profiles"),
        )
        self._build_card(
            row=11, column=2, emoji="⚙️", title="Configurações",
            subtitle="Versão do CorelDRAW de destino e outras opções do sistema.",
            color=gui_theme.ACCENT_SLATE, hover=gui_theme.ACCENT_SLATE_HOVER,
            command=lambda: app.show_page("settings"),
        )
        self._build_card(
            row=11, column=3, emoji="🖼️", title="Recortar Bordas Transparentes",
            subtitle="Corta a margem invisível ao redor da figura -- cabe mais por linha e imprime no tamanho certo.",
            color=gui_theme.ACCENT_MINT, hover=gui_theme.ACCENT_MINT_HOVER,
            command=lambda: app.show_page("trim_borders"),
        )

        self.on_show()

    def _build_section_header(self, row: int, text: str):
        frame = ctk.CTkFrame(self.cards_frame, fg_color="transparent")
        frame.grid(row=row, column=0, columnspan=4, sticky="ew", padx=12, pady=(22, 4))
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            frame, text=text.upper(),
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("gray45", "gray60"),
        ).grid(row=0, column=0, sticky="w", padx=(2, 10))
        ctk.CTkFrame(frame, height=1, fg_color=("gray75", "gray35")).grid(
            row=0, column=1, sticky="ew")

    def _build_card(self, row, column, emoji, title, subtitle, color, hover, command):
        # A plain frame, not a CTkButton -- a CTkButton with a frame of
        # widgets placed on top of it (needed for the emoji/title/subtitle
        # layout) shows an ugly mismatched-background flash on click/hover,
        # since the overlay frame's "transparent" doesn't resolve to the
        # button's own color. Bindings on every child do the clicking/hover
        # instead, and the color change is explicit, not a widget quirk.
        # Fixed width/height (not grid-stretched): CTkFrame's rounded-corner
        # canvas is drawn for its declared size, and stretching it afterwards
        # via sticky="nsew" leaves an unrounded rectangular flap in one corner.
        card = ctk.CTkFrame(self.cards_frame, fg_color=color, corner_radius=14, width=228, height=148)
        card.grid(row=row, column=column, padx=8, pady=6)
        card.grid_propagate(False)

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(content, text=emoji, font=ctk.CTkFont(size=26), text_color="white").pack()
        ctk.CTkLabel(
            content, text=title,
            font=ctk.CTkFont(size=14, weight="bold"), text_color="white",
            wraplength=200, justify="center",
        ).pack(pady=(4, 3))
        ctk.CTkLabel(
            content, text=subtitle,
            font=ctk.CTkFont(size=11), text_color=("white", "gray90"),
            wraplength=200, justify="center",
        ).pack()
        badge = ctk.CTkLabel(
            content, text="", font=ctk.CTkFont(size=10, weight="bold"), text_color="white",
            fg_color=("gray25", "gray20"), corner_radius=8, width=100, height=18)
        card.badge = badge

        def on_enter(_event=None):
            card.configure(fg_color=hover)

        def on_leave(_event=None):
            card.configure(fg_color=color)

        clickable_widgets = [card, content] + content.winfo_children()
        for widget in clickable_widgets:
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", lambda _e: command())
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        return card

    def on_show(self):
        # Queue count is a local SQLite read -- cheap, shows immediately.
        queue_count = len(db.get_pending_queue_items())
        self.queue_card.badge.configure(text=f"{queue_count} item(ns) na fila")
        self.queue_card.badge.pack(pady=(4, 0))

        # Pending-orders count needs a network call to the site -- this used
        # to run synchronously right here, which on the very first call (at
        # app startup, before the window has even painted once) meant the
        # whole app sat there waiting on a network round-trip before
        # anything appeared at all. Runs in the background instead; the
        # badge just shows "..." until it resolves.
        self.orders_card.badge.configure(text="...")
        self.orders_card.badge.pack(pady=(4, 0))

        def fetch_pending_count():
            return len(website_sync.list_pedidos("pendente"))

        def on_success(pending):
            self.orders_card.badge.configure(text=f"{pending} pendente(s)")

        def on_error(_ex):
            self.orders_card.badge.configure(text="site indisponível")

        gui_worker.run_task(self.app, fetch_pending_count, on_success=on_success, on_error=on_error)
