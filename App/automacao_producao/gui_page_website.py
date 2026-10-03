"""Site & Pedidos page: publish approved catalogs to the public website, and
review/validate/delete the orders customers submit there.
"""
import webbrowser

import customtkinter as ctk
from PIL import Image

import db
import gui_theme
import gui_webpedido
import gui_worker
import pa
import website_sync

THUMBNAILS_PER_ROW = 8
SITE_URL = "https://babyluzconfeccao.com.br/"


class WebsitePage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        header.grid_columnconfigure(0, weight=1)
        gui_theme.back_button(header, self.app).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        gui_theme.section_title(header, "Site & Pedidos").grid(row=1, column=0, sticky="w")

        button_row = ctk.CTkFrame(header, fg_color="transparent")
        button_row.grid(row=1, column=1, sticky="e")
        gui_theme.card_button(
            button_row, "🔗", "Ver Site", lambda: webbrowser.open(SITE_URL),
            color=gui_theme.ACCENT_MINT, hover_color=gui_theme.ACCENT_MINT_HOVER, width=110, height=70,
        ).pack(side="left", padx=4)
        gui_theme.card_button(
            button_row, "🔄", "Atualizar", self.refresh,
            color="gray45", hover_color="gray35", width=110, height=70,
        ).pack(side="left", padx=4)

        self.status_label = ctk.CTkLabel(
            self, text="babyluzconfeccao.com.br", font=ctk.CTkFont(size=12), text_color="gray60", anchor="w")
        self.status_label.grid(row=1, column=0, sticky="ew", padx=28)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(8, 8))
        self.list_frame.grid_columnconfigure(0, weight=1)

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=3, column=0, sticky="sew", padx=24, pady=(0, 20))

        self._images = []  # keep CTkImage references alive
        # Data loads on first on_show(), not here -- see gui_page_catalogs.py.
        # This page's refresh() makes a live network call to the site, so
        # this one in particular would have made every app launch wait on a
        # network round-trip before the window even opened.

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._images.clear()

        try:
            pedidos = website_sync.list_pedidos("pendente")
        except Exception as ex:
            ctk.CTkLabel(self.list_frame, text=f"Não consegui falar com o site: {ex}",
                         text_color=gui_theme.DANGER).grid(row=0, column=0, sticky="w")
            return

        if not pedidos:
            ctk.CTkLabel(self.list_frame, text="Nenhum pedido pendente no site.", text_color="gray60").grid(
                row=0, column=0, sticky="w")
            return

        for i, pedido in enumerate(pedidos):
            row = ctk.CTkFrame(
                self.list_frame, corner_radius=10, fg_color=("gray92", "gray17"),
                border_width=2, border_color=gui_theme.ACCENT)
            row.grid(row=i, column=0, sticky="ew", pady=(0 if i == 0 else 14, 0), padx=2)
            row.grid_columnconfigure(0, weight=1)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=0, sticky="w", padx=16, pady=(12, 4))
            titulo = f"{pedido['nome']}  ·  {pedido['telefone']}"
            if pedido.get("representante"):
                titulo += f"  ·  rep: {pedido['representante']}"
            ctk.CTkLabel(info, text=titulo,
                         font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w")
            ctk.CTkLabel(
                info, text=f"pedido_id={pedido['pedido_id']}  ·  {pedido['criado_em']}  ·  "
                           f"{len(pedido['itens'])} item(ns)",
                font=ctk.CTkFont(size=12), text_color="gray50",
            ).pack(anchor="w")

            actions = ctk.CTkFrame(row, fg_color="transparent")
            actions.grid(row=0, column=1, rowspan=2, sticky="ne", padx=16, pady=12)
            gui_theme.primary_button(
                actions, text="Aceitar pedido", width=130, height=30,
                command=lambda p=pedido: self._validate(p),
            ).pack(side="left", padx=4)
            gui_webpedido.make_button(actions, self, pedido["nome"], pedido["telefone"]).pack(side="left", padx=4)
            gui_theme.danger_button(
                actions, text="Cancelar pedido", width=120, height=30,
                command=lambda p=pedido: self._delete(p),
            ).pack(side="left", padx=4)

            items_frame = ctk.CTkFrame(row, fg_color="transparent")
            items_frame.grid(row=1, column=0, sticky="w", padx=12, pady=(0, 12))
            for item_index, item in enumerate(pedido["itens"]):
                self._build_item_thumbnail(items_frame, pedido, item, item_index)

    def _build_item_thumbnail(self, master, pedido, item, item_index):
        reference = item["referencia"]
        card = ctk.CTkFrame(master, fg_color="transparent", width=68)
        card.grid(row=item_index // THUMBNAILS_PER_ROW, column=item_index % THUMBNAILS_PER_ROW, padx=4, pady=4)

        matches = db.find_approved_arts_by_reference(reference)
        preview_path = matches[0][3] if matches else None
        image_holder = ctk.CTkFrame(card, fg_color="transparent", width=60, height=60)
        image_holder.pack()
        image_holder.pack_propagate(False)
        shown = False
        if preview_path:
            try:
                image = Image.open(preview_path)
                image.thumbnail((60, 60))
                ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
                self._images.append(ctk_image)
                ctk.CTkLabel(image_holder, image=ctk_image, text="").pack(expand=True)
                shown = True
            except Exception:
                pass
        if not shown:
            ctk.CTkLabel(image_holder, text="❓", font=ctk.CTkFont(size=26)).pack(expand=True)

        quantity = item.get("quantidade") or 1
        if quantity > 1:
            qty_badge = ctk.CTkLabel(
                image_holder, text=f"x{quantity}", font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=gui_theme.ACCENT_BLUE, text_color="white", corner_radius=6, width=0, height=16)
            qty_badge.place(relx=0.0, rely=1.0, anchor="sw")

        ctk.CTkLabel(card, text=reference, font=ctk.CTkFont(size=10), text_color="gray50",
                     wraplength=64).pack()
        # "texto" = "Termo colante · 110 x 100 mm" (pronto do site); pedidos antigos
        # só têm a medida em texto livre.
        medida = item.get("texto") or item.get("medida")
        if medida:
            ctk.CTkLabel(card, text=medida, font=ctk.CTkFont(size=9, weight="bold"),
                         text_color=gui_theme.ACCENT_BLUE, wraplength=64).pack()

        remove_button = ctk.CTkButton(
            image_holder, text="×", width=18, height=18, corner_radius=9,
            fg_color=gui_theme.DANGER, hover_color=gui_theme.DANGER_HOVER, font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self._remove_item(pedido, item.get("produto_id"), reference, item.get("item_id")),
        )
        remove_button.place(relx=1.0, rely=0.0, anchor="ne")

    def _remove_item(self, pedido, produto_id, reference, item_id=None):
        if produto_id is None:
            return
        if not gui_theme.ask_confirm(
            self.app, "Excluir item",
            f"Tem certeza que quer excluir \"{reference}\" do pedido de \"{pedido['nome']}\"?",
            confirm_text="Excluir", danger=True,
        ):
            return
        website_sync.remover_item_pedido(pedido["pedido_id"], produto_id, item_id)
        self.refresh()
        gui_theme.show_message(self.app, "Excluído", f"\"{reference}\" excluído com sucesso.")

    def _validate(self, pedido):
        # REFs without a locked/override size are skipped (not silently
        # guessed) -- see do_validate_website_order's docstring. Fix a
        # missing size beforehand via Buscar Produto or Ver desenhos; it's
        # a one-time, persistent correction there instead of a popup asked
        # again on every order that happens to include that REF.
        self.log_panel.show(f"Aceitando pedido {pedido['pedido_id']}...\n\n")

        def task():
            pa.do_validate_website_order(pedido["pedido_id"])

        def on_success(_result):
            self.refresh()
            self.log_panel.hide_after()

        gui_worker.run_task(self.app, task, on_log=self.log_panel.append, on_success=on_success)

    def _delete(self, pedido):
        if not gui_theme.ask_confirm(
            self.app, "Cancelar pedido",
            f"Tem certeza que quer cancelar o pedido de \"{pedido['nome']}\" (id={pedido['pedido_id']})?",
            confirm_text="Cancelar pedido", danger=True,
        ):
            return
        website_sync.excluir_pedido(pedido["pedido_id"])
        self.refresh()
        gui_theme.show_message(self.app, "Cancelado", f"Pedido de \"{pedido['nome']}\" cancelado com sucesso.")
