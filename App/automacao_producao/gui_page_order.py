"""Montar Pedido -- três modos de entrada que alimentam a mesma fila de
produção, agora numa página com abas em vez de três cards separados na
dashboard:

  🎲 Aleatório:       sorteia N designs diferentes de catálogos selecionados.
  📋 Lista de REFs:   cola a lista bruta do cliente; REF repetida = +1 unidade.
  🔁 REFs específicas: adiciona REF+quantidade manualmente, uma por vez.

Antes eram gui_page_generate_random, gui_page_batch_order e
gui_page_generate_order -- seções de cliente/catálogo idênticas em cada uma,
e as três chamando o mesmo pa.do_generate_combined_order no final.
"""
import re

import customtkinter as ctk

import db
import gui_theme
import pa


class OrderPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._catalog_vars: dict[int, ctk.BooleanVar] = {}
        self._exact_entries: list[dict] = []
        self._add_form_frame = None

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Montar Pedido").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Três formas de montar um pedido — todas caem na mesma fila de produção. "
                 "Escolha a aba que combina com o pedido que chegou.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=760, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.body.grid(row=1, column=0, sticky="nsew", padx=24, pady=(8, 20))
        self.body.grid_columnconfigure(0, weight=1)

        # ── Seção compartilhada: cliente ──────────────────────────────────
        client_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        client_card.grid(row=0, column=0, sticky="ew", pady=(0, 12))
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

        # ── Seção compartilhada: catálogos ────────────────────────────────
        catalog_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        catalog_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        ctk.CTkLabel(
            catalog_card,
            text="Catálogo  ·  \"Aleatório\" exige pelo menos um marcado; as outras abas buscam em "
                 "todos os catálogos se nenhum for marcado.",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        self.catalogs_frame = ctk.CTkFrame(catalog_card, fg_color="transparent")
        self.catalogs_frame.pack(anchor="w", fill="x", padx=16, pady=(0, 8))

        # Recorta a margem invisível (transparente ou branca) só das REFs
        # que realmente vão entrar nesse pedido -- gera e já resolve, sem
        # precisar de uma passada separada em "Recortar Bordas
        # Transparentes" antes (ver pa.do_generate_combined_order).
        self.trim_borders_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            catalog_card, variable=self.trim_borders_var,
            text="Recortar bordas transparentes das REFs desse pedido antes de gerar",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=16, pady=(0, 16))

        # ── Abas ──────────────────────────────────────────────────────────
        self.tabview = ctk.CTkTabview(self.body)
        self.tabview.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.tabview.grid_columnconfigure(0, weight=1)

        for tab_name in ("🎲 Aleatório", "📋 Lista de REFs", "🔁 REFs específicas"):
            self.tabview.add(tab_name)
            self.tabview.tab(tab_name).grid_columnconfigure(0, weight=1)

        self._build_tab_random()
        self._build_tab_list()
        self._build_tab_exact()

    # ── helpers compartilhados ────────────────────────────────────────────

    def _client(self):
        return (self.client_name_entry.get().strip() or None,
                self.client_phone_entry.get().strip() or None)

    def _selected_catalog_ids(self) -> list[int]:
        return [cid for cid, var in self._catalog_vars.items() if var.get()]

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.catalogs_frame.winfo_children():
            child.destroy()
        self._catalog_vars.clear()

        catalogs = db.get_all_catalogs()
        if not catalogs:
            ctk.CTkLabel(
                self.catalogs_frame, text="Nenhum catálogo importado ainda.",
                text_color="gray60",
            ).pack(anchor="w")
            return

        for catalog_id, name, _status, _created_at, _total, approved_arts, _refs, _pub in catalogs:
            # Marcado por padrão -- antes vinha tudo desmarcado e era preciso
            # clicar catálogo por catálogo toda vez antes de gerar qualquer
            # pedido, mesmo quando a intenção quase sempre é buscar em tudo.
            # Desmarcar manualmente pra restringir a um catálogo específico
            # continua funcionando igual.
            var = ctk.BooleanVar(value=True)
            self._catalog_vars[catalog_id] = var
            ctk.CTkCheckBox(
                self.catalogs_frame, variable=var,
                text=f"{name}  ·  {approved_arts or 0} aprovada(s)",
            ).pack(anchor="w", pady=2)

    # ── Aba: Aleatório ────────────────────────────────────────────────────

    def _build_tab_random(self):
        tab = self.tabview.tab("🎲 Aleatório")
        ctk.CTkLabel(
            tab,
            text="Sorteia N desenhos DIFERENTES dos catálogos marcados acima — cada um repete "
                 "numa linha até encher a folha, e o próximo começa na linha de baixo.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=700, justify="left",
        ).pack(anchor="w", padx=12, pady=(10, 8))

        qty_row = ctk.CTkFrame(tab, fg_color="transparent")
        qty_row.pack(anchor="w", padx=12, pady=(0, 10))
        ctk.CTkLabel(
            qty_row, text="Quantidade de desenhos diferentes:", font=ctk.CTkFont(size=13),
        ).pack(side="left", padx=(0, 8))
        self.random_qty_entry = ctk.CTkEntry(qty_row, width=100, placeholder_text="ex: 16")
        self.random_qty_entry.pack(side="left")

        gui_theme.primary_button(
            tab, text="Gerar Aleatório", width=200, height=36, command=self._generate_random,
        ).pack(anchor="w", padx=12, pady=(4, 16))

    def _generate_random(self):
        selected_catalog_ids = self._selected_catalog_ids()
        if not selected_catalog_ids:
            gui_theme.show_message(
                self.app, "Escolha um catálogo",
                "Marca pelo menos um catálogo antes de gerar aleatório.")
            return
        try:
            design_count = int(self.random_qty_entry.get().strip())
            if design_count <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self.app, "Quantidade inválida",
                "Informe quantos desenhos diferentes sortear (número inteiro maior que zero).")
            return
        client_name, client_phone = self._client()
        try:
            result = pa.do_generate_combined_order(
                selected_catalog_ids, design_count, [], client_name, client_phone,
                trim_borders=self.trim_borders_var.get())
        except ValueError as ex:
            gui_theme.show_message(self.app, "Não deu pra gerar", str(ex))
            return
        self.random_qty_entry.delete(0, "end")
        trim_note = f" ({result['trimmed_count']} recortada(s))" if result.get("trimmed_count") else ""
        gui_theme.show_message(
            self.app, "Pedido gerado",
            f"{result['random_queued']} desenho(s) sorteado(s) adicionado(s) à fila de produção{trim_note}. "
            f"Vá em \"Gerar Produção\" pra continuar.")

    # ── Aba: Lista de REFs ────────────────────────────────────────────────

    def _build_tab_list(self):
        tab = self.tabview.tab("📋 Lista de REFs")
        ctk.CTkLabel(
            tab,
            text="Cola a lista que o cliente mandou (/, vírgula, espaço, linha — tanto faz). "
                 "REF repetida na lista soma quantidade: 045 duas vezes = 2 unidades.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=700, justify="left",
        ).pack(anchor="w", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            tab, text="ex: 001/002/012/011/013/030",
            font=ctk.CTkFont(size=11), text_color="gray50",
        ).pack(anchor="w", padx=12, pady=(0, 4))

        self.refs_textbox = ctk.CTkTextbox(tab, height=100)
        self.refs_textbox.pack(fill="x", padx=12, pady=(0, 4))

        self._list_preview_label = ctk.CTkLabel(
            tab, text="", font=ctk.CTkFont(size=12), text_color="gray50",
            justify="left", anchor="w")
        self._list_preview_label.pack(anchor="w", padx=12, pady=(0, 8), fill="x")
        self.refs_textbox.bind("<KeyRelease>", lambda _e: self._update_list_preview())

        gui_theme.primary_button(
            tab, text="Gerar Pedido", width=180, height=36, command=self._generate_list,
        ).pack(anchor="w", padx=12, pady=(0, 16))

    def _parse_refs(self) -> list[str]:
        # "/" doubles as BOTH the item separator ("001/002/003" -- a
        # customer pasting several different REFs) AND, since a catalog can
        # offer the same base design in more than one size, part of a
        # single REF's own identity ("2217/1" vs "2217/2" -- see
        # master_artwork.REF_CAPTION_PATTERN). Plain "\d+" used to shred
        # "2217/1" into two meaningless separate REFs ("2217" and "1"),
        # so pasting the exact reference the site shows the customer could
        # never be found. The "(?!\d)" after the optional "/\d" makes sure
        # a genuine two-REF paste like "2217/2219" isn't misread as
        # "2217/2" + "19" -- a real variant suffix here is always a single
        # digit, so a second digit right after it means it was never a
        # variant to begin with, just the next REF in the list.
        return re.findall(r"\d+(?:/\d)?(?!\d)", self.refs_textbox.get("1.0", "end"))

    def _update_list_preview(self):
        refs = self._parse_refs()
        if not refs:
            self._list_preview_label.configure(text="")
            return
        self._list_preview_label.configure(
            text=f"{len(set(refs))} REF(s) diferente(s), {len(refs)} unidade(s) no total.")

    def _collect_list_entries(self):
        refs = self._parse_refs()
        quantities: dict[str, int] = {}
        order: list[str] = []
        for ref in refs:
            if ref not in quantities:
                order.append(ref)
                quantities[ref] = 0
            quantities[ref] += 1
        return [(ref, quantities[ref]) for ref in order]

    def _generate_list(self):
        exact_entries = self._collect_list_entries()
        if not exact_entries:
            gui_theme.show_message(self.app, "Lista vazia", "Cola a lista de REFs antes de gerar.")
            return
        client_name, client_phone = self._client()
        try:
            result = pa.do_generate_combined_order(
                self._selected_catalog_ids(), None, exact_entries, client_name, client_phone,
                trim_borders=self.trim_borders_var.get())
        except ValueError as ex:
            gui_theme.show_message(self.app, "Não deu pra gerar", str(ex))
            return
        if result["exact_queued"] == 0:
            gui_theme.show_message(
                self.app, "Nada gerado",
                "Nenhuma REF da lista foi encontrada (ou tem tamanho definido).")
            return
        self.refs_textbox.delete("1.0", "end")
        self._update_list_preview()
        self._show_result_report(result)

    # ── Aba: REFs específicas ─────────────────────────────────────────────

    def _build_tab_exact(self):
        tab = self.tabview.tab("🔁 REFs específicas")
        ctk.CTkLabel(
            tab,
            text="Reserva quantidades exatas de REFs específicas — ex: 10 de REF 5, 5 de REF 12. "
                 "A mesma REF adicionada duas vezes soma a quantidade em vez de criar linha dupla.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=700, justify="left",
        ).pack(anchor="w", padx=12, pady=(10, 8))

        self.exact_list_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.exact_list_frame.pack(anchor="w", fill="x", padx=12, pady=(0, 4))
        self._refresh_exact_list()

        self._add_form_container = ctk.CTkFrame(tab, fg_color="transparent")
        self._add_form_container.pack(anchor="w", fill="x", padx=12, pady=(0, 4))

        btn_row = ctk.CTkFrame(tab, fg_color="transparent")
        btn_row.pack(anchor="w", padx=12, pady=(4, 16))
        gui_theme.secondary_button(
            btn_row, text="+ Adicionar figura repetida", width=220, height=32,
            command=self._open_add_form,
        ).pack(side="left", padx=(0, 10))
        gui_theme.primary_button(
            btn_row, text="Gerar Pedido Repetido", width=200, height=32,
            command=self._generate_exact,
        ).pack(side="left")

    def _refresh_exact_list(self):
        for child in self.exact_list_frame.winfo_children():
            child.destroy()
        if not self._exact_entries:
            ctk.CTkLabel(
                self.exact_list_frame, text="Nenhuma figura adicionada ainda.",
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
            return
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
                self.app, "Quantidade inválida",
                "A quantidade precisa ser um número inteiro maior que zero.")
            return
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

    def _generate_exact(self):
        exact_entries = [(e["reference"], e["quantity"]) for e in self._exact_entries]
        if not exact_entries:
            gui_theme.show_message(
                self.app, "Lista vazia",
                "Adiciona pelo menos uma figura repetida (REF + quantidade) antes de gerar.")
            return
        client_name, client_phone = self._client()
        try:
            result = pa.do_generate_combined_order(
                self._selected_catalog_ids(), None, exact_entries, client_name, client_phone,
                trim_borders=self.trim_borders_var.get())
        except ValueError as ex:
            gui_theme.show_message(self.app, "Não deu pra gerar", str(ex))
            return
        if result["exact_queued"] == 0:
            gui_theme.show_message(
                self.app, "Nada gerado",
                "Nenhuma REF da lista foi encontrada (ou tem tamanho definido).")
            return
        self._reset_exact_list()
        self._show_result_report(result)

    def _show_result_report(self, result):
        # Substitui o popup de texto corrido (MessageDialog é uma caixa fixa
        # de 380x170, sem scroll -- uma lista de REFs longa simplesmente
        # cortava/transbordava) por um relatório rolável separando claramente
        # o que entrou na fila do que ficou de fora e por quê.
        trim_note = f" ({result['trimmed_count']} tiveram a borda recortada)" if result.get("trimmed_count") else ""
        summary = (f"{result['exact_queued']} REF(s) adicionada(s) à fila de produção{trim_note}. "
                   f"Vá em \"Gerar Produção\" pra continuar.")
        gui_theme.show_ref_report(
            self.app, "Pedido gerado", summary,
            "Adicionadas à fila", result.get("queued_refs", []),
            "Ficaram de fora", result["skipped_refs"])
