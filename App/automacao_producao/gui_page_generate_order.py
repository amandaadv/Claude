"""Gerar Pedidos Repetidos page: reserve specific quantities for specific
REFs (e.g. 4 of REF 5) for one client, added one at a time via "Adicionar
figura repetida" -- a small form (REF + quantidade + Salvar) appears,
and saving adds it to a plain list with its own remove button. Adding
the same REF twice MERGES into one combined quantity rather than
creating two separate queue entries -- keeps that REF's copies
contiguous on the production sheet (all of it placed before moving to
the next REF) instead of splitting across two disjoint blocks.

Catalog selection scopes the REF lookup -- useful when the same REF
number exists in more than one catalog and would otherwise be
ambiguous. Leaving every catalog unchecked searches all of them, same
as before catalog selection existed here.

The random-sampling counterpart ("Gerar Aleatório") lives on its own
page/dashboard card (gui_page_generate_random.py) -- these used to be
two cards on this same page, but that read as one confusing combined
form; splitting them into separate pages made each one's purpose
obvious at a glance.
"""
import customtkinter as ctk

import db
import gui_theme
import pa


class GenerateOrderPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._catalog_vars = {}  # catalog_id -> BooleanVar

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Gerar Pedidos Repetidos").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Reserva quantidades exatas de REFs específicas pra um cliente -- ex: 10 de REF 5, "
                 "5 de REF 12.",
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

        catalog_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        catalog_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            catalog_card, text="Catálogo (opcional -- ajuda a desambiguar REF repetida entre catálogos)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        self.catalogs_frame = ctk.CTkFrame(catalog_card, fg_color="transparent")
        self.catalogs_frame.pack(anchor="w", fill="x", padx=16, pady=(0, 16))

        # -- Lista exata -------------------------------------------------------
        list_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        list_card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            list_card, text="REF + quantidade",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            list_card,
            text="Clica em \"Adicionar figura repetida\", preenche a REF e a quantidade, e clica em Salvar. "
                 "Cada REF sai inteira, na sequência, antes de passar pra próxima.",
            font=ctk.CTkFont(size=12), text_color="gray50", wraplength=650, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        self.exact_list_frame = ctk.CTkFrame(list_card, fg_color="transparent")
        self.exact_list_frame.pack(anchor="w", fill="x", padx=16, pady=(0, 4))
        self._exact_entries = []  # each: {"reference": str, "quantity": int}
        self._refresh_exact_list()

        self._add_form_frame = None
        self._add_form_container = ctk.CTkFrame(list_card, fg_color="transparent")
        self._add_form_container.pack(anchor="w", fill="x", padx=16, pady=(0, 4))

        gui_theme.secondary_button(
            list_card, text="+ Adicionar figura repetida", width=220, height=32, command=self._open_add_form,
        ).pack(anchor="w", padx=16, pady=(4, 16))

        gui_theme.primary_button(
            self.body, text="Gerar Pedido Repetido", width=220, height=40, command=self._generate,
        ).grid(row=3, column=0, sticky="w", pady=(0, 8))

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

    # -- lista exata: adicionar/salvar/remover -------------------------------

    def _refresh_exact_list(self):
        for child in self.exact_list_frame.winfo_children():
            child.destroy()

        if not self._exact_entries:
            ctk.CTkLabel(
                self.exact_list_frame, text="Nenhuma figura repetida adicionada ainda.",
                text_color="gray60", font=ctk.CTkFont(size=12),
            ).pack(anchor="w")
            return

        for index, entry in enumerate(self._exact_entries):
            row = ctk.CTkFrame(self.exact_list_frame, fg_color="transparent")
            row.pack(anchor="w", pady=2, fill="x")
            ctk.CTkLabel(
                row, text=f"{entry['reference']} — {entry['quantity']} unidade(s)",
                font=ctk.CTkFont(size=13),
            ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                row, text="×", width=24, height=24, corner_radius=12,
                fg_color=gui_theme.DANGER, hover_color=gui_theme.DANGER_HOVER,
                font=ctk.CTkFont(size=12, weight="bold"),
                command=lambda i=index: self._remove_exact_entry(i),
            ).pack(side="left")

    def _remove_exact_entry(self, index):
        del self._exact_entries[index]
        self._refresh_exact_list()

    def _open_add_form(self):
        if self._add_form_frame is not None:
            return  # form already open

        self._add_form_frame = ctk.CTkFrame(
            self._add_form_container, corner_radius=8, fg_color=("gray85", "gray22"))
        self._add_form_frame.pack(anchor="w", fill="x")

        row = ctk.CTkFrame(self._add_form_frame, fg_color="transparent")
        row.pack(anchor="w", padx=10, pady=10)
        self._add_ref_entry = ctk.CTkEntry(row, width=140, placeholder_text="REF (ex: REF 5)")
        self._add_ref_entry.pack(side="left", padx=(0, 8))
        self._add_qty_entry = ctk.CTkEntry(row, width=90, placeholder_text="quantidade")
        self._add_qty_entry.pack(side="left", padx=(0, 8))
        gui_theme.primary_button(
            row, text="Salvar", width=80, height=28, command=self._save_add_form,
        ).pack(side="left", padx=(0, 4))
        gui_theme.secondary_button(
            row, text="Cancelar", width=80, height=28, command=self._close_add_form,
        ).pack(side="left")

        self._add_ref_entry.focus_set()

    def _close_add_form(self):
        if self._add_form_frame is not None:
            self._add_form_frame.destroy()
            self._add_form_frame = None

    def _save_add_form(self):
        reference = self._add_ref_entry.get().strip()
        if not reference:
            gui_theme.show_message(self.app, "REF vazia", "Digita o número da REF antes de salvar.")
            return
        try:
            quantity = int(self._add_qty_entry.get().strip())
            if quantity <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self.app, "Quantidade inválida", "A quantidade precisa ser um número inteiro maior que zero.")
            return

        # Adding the same REF again merges into its existing quantity
        # instead of creating a second entry -- keeps that REF's copies
        # together as one block on the production sheet, not split into
        # two separate groups with something else queued in between.
        for entry in self._exact_entries:
            if entry["reference"] == reference:
                entry["quantity"] += quantity
                break
        else:
            self._exact_entries.append({"reference": reference, "quantity": quantity})

        self._refresh_exact_list()
        self._close_add_form()

    def _reset_exact_list(self):
        self._close_add_form()
        self._exact_entries = []
        self._refresh_exact_list()

    def _collect_exact_entries(self):
        return [(entry["reference"], entry["quantity"]) for entry in self._exact_entries]

    # -- gerar pedido repetido -------------------------------------------------

    def _generate(self):
        exact_entries = self._collect_exact_entries()
        if not exact_entries:
            gui_theme.show_message(
                self.app, "Lista vazia",
                "Adiciona pelo menos uma figura repetida (REF + quantidade) antes de gerar.")
            return

        selected_catalog_ids = [cid for cid, var in self._catalog_vars.items() if var.get()]
        client_name, client_phone = self._client()
        try:
            result = pa.do_generate_combined_order(
                selected_catalog_ids, None, exact_entries, client_name, client_phone)
        except ValueError as ex:
            gui_theme.show_message(self.app, "Não deu pra gerar", str(ex))
            return

        if result["exact_queued"] == 0:
            gui_theme.show_message(
                self.app, "Nada gerado",
                "Nenhuma REF da lista foi encontrada (ou tem tamanho definido).")
            return

        self._reset_exact_list()
        message = (
            f"{result['exact_queued']} REF(s) adicionada(s) à fila de produção, cada uma na quantidade "
            f"exata pedida. Vá em \"Gerar Produção\" pra continuar.")
        if result["skipped_refs"]:
            message += "\n\nAviso -- ficaram de fora: " + "; ".join(result["skipped_refs"]) + "."
        gui_theme.show_message(self.app, "Pedido gerado", message)
