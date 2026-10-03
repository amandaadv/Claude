"""Gerar Aleatório page: sorteia N desenhos DIFERENTES de um ou mais
catálogos pra um cliente -- cada um repete numa linha até encher a
folha (a área útil, com a tolerância de 5mm), e o próximo desenho
sorteado começa na linha de baixo. NÃO é uma contagem de peças físicas
-- é quantos desenhos distintos entram no sorteio.

Simple by design: nome, telefone, catálogo(s), quantidade, gerar. The
exact-quantity counterpart ("Gerar Pedidos Repetidos") lives on its own
page/dashboard card (gui_page_generate_order.py) -- these used to be
two cards on the same page, but that read as one confusing combined
form; splitting them into separate pages made each one's purpose
obvious at a glance.
"""
import customtkinter as ctk

import db
import gui_theme
import pa


class GenerateRandomPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._catalog_vars = {}  # catalog_id -> BooleanVar

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Gerar Aleatório").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Sorteia desenhos diferentes de um ou mais catálogos pra um cliente -- cada um repete "
                 "numa linha até encher a folha, e o próximo desenho começa na linha de baixo.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=700, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(8, 20))
        self.body.grid_columnconfigure(0, weight=1)

        client_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        client_card.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            client_card, text="Cliente (opcional)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        client_row = ctk.CTkFrame(client_card, fg_color="transparent")
        client_row.pack(anchor="w", padx=16, pady=(0, 16))
        self.client_name_entry = ctk.CTkEntry(client_row, width=200, placeholder_text="nome")
        self.client_name_entry.pack(side="left", padx=(0, 8))
        self.client_phone_entry = ctk.CTkEntry(client_row, width=160, placeholder_text="telefone")
        self.client_phone_entry.pack(side="left")

        random_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        random_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            random_card, text="Catálogo e quantidade",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))

        self.catalogs_frame = ctk.CTkFrame(random_card, fg_color="transparent")
        self.catalogs_frame.pack(anchor="w", fill="x", padx=16, pady=(0, 8))

        qty_row = ctk.CTkFrame(random_card, fg_color="transparent")
        qty_row.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkLabel(
            qty_row, text="Quantidade de desenhos diferentes:", font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=(0, 8))
        self.quantity_entry = ctk.CTkEntry(qty_row, width=100, placeholder_text="ex: 16")
        self.quantity_entry.pack(side="left")

        gui_theme.primary_button(
            random_card, text="Gerar Aleatório", width=220, height=36, command=self._generate,
        ).pack(anchor="w", padx=16, pady=(8, 16))

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.catalogs_frame.winfo_children():
            child.destroy()
        self._catalog_vars.clear()

        catalogs = db.get_all_catalogs()
        if not catalogs:
            ctk.CTkLabel(self.catalogs_frame, text="Nenhum catálogo importado ainda.", text_color="gray60").pack(
                anchor="w")
            return

        for catalog_id, name, status, created_at, total_arts, approved_arts, \
                arts_with_reference, published_at in catalogs:
            var = ctk.BooleanVar(value=False)
            self._catalog_vars[catalog_id] = var
            ctk.CTkCheckBox(
                self.catalogs_frame, variable=var,
                text=f"{name}  ·  {approved_arts or 0} aprovada(s)",
            ).pack(anchor="w", pady=2)

    def _client(self):
        return self.client_name_entry.get().strip() or None, self.client_phone_entry.get().strip() or None

    def _generate(self):
        selected_catalog_ids = [cid for cid, var in self._catalog_vars.items() if var.get()]
        if not selected_catalog_ids:
            gui_theme.show_message(self.app, "Escolha um catálogo", "Marca pelo menos um catálogo antes de gerar.")
            return

        try:
            design_count = int(self.quantity_entry.get().strip())
            if design_count <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self.app, "Quantidade inválida",
                "Informe quantos desenhos diferentes sortear (um número inteiro maior que zero).")
            return

        client_name, client_phone = self._client()
        try:
            result = pa.do_generate_combined_order(
                selected_catalog_ids, design_count, [], client_name, client_phone)
        except ValueError as ex:
            gui_theme.show_message(self.app, "Não deu pra gerar", str(ex))
            return

        self.quantity_entry.delete(0, "end")
        gui_theme.show_message(
            self.app, "Pedido gerado",
            f"{result['random_queued']} desenho(s) sorteado(s), cada um enchendo sua linha, "
            f"adicionado(s) à fila de produção. Vá em \"Gerar Produção\" pra continuar.")
