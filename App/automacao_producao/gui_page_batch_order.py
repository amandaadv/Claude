"""Pedido por Lista de REFs page: the client sends a raw list of reference
numbers (any separator -- "/", vírgula, espaço, quebra de linha), e essa
tela acha a figura de cada uma (em qualquer catálogo do computador, ou só
nos catálogos marcados) e manda tudo pra fila de produção de uma vez, um
exemplar de cada REF por padrão.

Separate from "Gerar Pedidos Repetidos" (gui_page_generate_order.py): aquela
tela é pra quando o cliente quer quantidades específicas por REF, digitadas
uma REF por vez. Essa aqui é pra quando o cliente já manda a lista pronta,
e cada número que aparece repetido na lista vira quantidade maior daquela
REF (a mesma REF duas vezes = 2 unidades) -- mesma regra de "junta ao invés
de duplicar" da outra tela, só que decidida automaticamente pela lista
colada em vez de digitada.

Usa a mesma pa.do_generate_combined_order e o mesmo
db.find_approved_arts_by_reference (que já ignora espaço/pontuação/zero à
esquerda) das outras telas -- nada de busca nova aqui, só um jeito mais
rápido de alimentar a REF+quantidade em lote.
"""
import re

import customtkinter as ctk

import db
import gui_theme
import pa

# Medidas disponíveis (espelha regras_medidas.json do servidor)
_MEDIDAS = [
    # Aplique – Termocolante
    {"label": "Aplique TC · 90 mm",               "rule": {"modo": "proporcional", "maior": 90,  "menor": None, "rotulo": "90 mm"}},
    {"label": "Aplique TC · 110 x 100 mm",         "rule": {"modo": "proporcional", "maior": 110, "menor": 100,  "rotulo": "110 x 100 mm"}},
    {"label": "Aplique TC · 140 x 120 mm (fixa)",  "rule": {"modo": "fixa",         "maior": 140, "menor": 120,  "rotulo": "140 x 120 mm (fixa)"}},
    # Aplique – Adesivo UV
    {"label": "Aplique UV · 80 mm",                "rule": {"modo": "proporcional", "maior": 80,  "menor": None, "rotulo": "80 mm"}},
    {"label": "Aplique UV · 90 mm",                "rule": {"modo": "proporcional", "maior": 90,  "menor": None, "rotulo": "90 mm"}},
    {"label": "Aplique UV · 110 x 100 mm",         "rule": {"modo": "proporcional", "maior": 110, "menor": 100,  "rotulo": "110 x 100 mm"}},
    {"label": "Aplique UV · 140 x 120 mm (fixa)",  "rule": {"modo": "fixa",         "maior": 140, "menor": 120,  "rotulo": "140 x 120 mm (fixa)"}},
    # Faixa – Termocolante
    {"label": "Faixa · 488 x 111 mm",             "rule": {"modo": "fixa", "maior": 488, "menor": 111, "rotulo": "488 x 111 mm"}},
    {"label": "Faixa · 400 x 111 mm",             "rule": {"modo": "fixa", "maior": 400, "menor": 111, "rotulo": "400 x 111 mm"}},
    {"label": "Faixa · 350 x 111 mm",             "rule": {"modo": "fixa", "maior": 350, "menor": 111, "rotulo": "350 x 111 mm"}},
    {"label": "Faixa · 290 x 111 mm",             "rule": {"modo": "fixa", "maior": 290, "menor": 111, "rotulo": "290 x 111 mm"}},
    {"label": "Faixa · 290 x 60 mm",              "rule": {"modo": "fixa", "maior": 290, "menor": 60,  "rotulo": "290 x 60 mm"}},
    {"label": "Faixa · 290 x 55 mm",              "rule": {"modo": "fixa", "maior": 290, "menor": 55,  "rotulo": "290 x 55 mm"}},
    {"label": "Faixa · 215 x 50 mm",              "rule": {"modo": "fixa", "maior": 215, "menor": 50,  "rotulo": "215 x 50 mm"}},
    {"label": "Faixa · 215 x 45 mm",              "rule": {"modo": "fixa", "maior": 215, "menor": 45,  "rotulo": "215 x 45 mm"}},
]
_MEDIDA_LABELS = [m["label"] for m in _MEDIDAS]


class BatchOrderPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._catalog_vars = {}  # catalog_id -> BooleanVar

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Pedido por Lista de REFs").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Cola a lista de referências que o cliente mandou (separadas por /, vírgula, espaço "
                 "ou linha -- tanto faz) e clica em Gerar. Acha a figura de cada REF em todos os "
                 "catálogos do computador e manda tudo pra fila de uma vez. REF repetida na lista "
                 "soma quantidade (ex: 045 duas vezes = 2 unidades dela).",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=760, justify="left",
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
        client_row.pack(anchor="w", padx=16, pady=(0, 8))
        self.client_name_entry = ctk.CTkEntry(client_row, width=200, placeholder_text="nome")
        self.client_name_entry.pack(side="left", padx=(0, 8))
        self.client_phone_entry = ctk.CTkEntry(client_row, width=160, placeholder_text="telefone")
        self.client_phone_entry.pack(side="left")
        rep_row = ctk.CTkFrame(client_card, fg_color="transparent")
        rep_row.pack(anchor="w", padx=16, pady=(0, 16))
        ctk.CTkLabel(rep_row, text="Representante:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self.rep_entry = ctk.CTkEntry(rep_row, width=220, placeholder_text="nome do representante (opcional)")
        self.rep_entry.pack(side="left")

        medida_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        medida_card.grid(row=1, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            medida_card, text="Medida e Quantidade",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        medida_row = ctk.CTkFrame(medida_card, fg_color="transparent")
        medida_row.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkLabel(medida_row, text="Medida:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self.medida_var = ctk.StringVar(value=_MEDIDA_LABELS[0])
        self.medida_combo = ctk.CTkComboBox(
            medida_row, values=_MEDIDA_LABELS, variable=self.medida_var, width=300, state="readonly")
        self.medida_combo.pack(side="left")
        qty_row = ctk.CTkFrame(medida_card, fg_color="transparent")
        qty_row.pack(anchor="w", padx=16, pady=(0, 16))
        ctk.CTkLabel(qty_row, text="Quantidade mínima por peça:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))
        self.qty_min_entry = ctk.CTkEntry(qty_row, width=80, placeholder_text="ex: 9")
        self.qty_min_entry.pack(side="left")

        catalog_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        catalog_card.grid(row=2, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            catalog_card, text="Catálogo (opcional -- ajuda a desambiguar REF repetida entre catálogos)",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))
        self.catalogs_frame = ctk.CTkFrame(catalog_card, fg_color="transparent")
        self.catalogs_frame.pack(anchor="w", fill="x", padx=16, pady=(0, 16))

        list_card = ctk.CTkFrame(self.body, corner_radius=10, fg_color=("gray92", "gray17"))
        list_card.grid(row=3, column=0, sticky="ew", pady=(0, 16))
        ctk.CTkLabel(
            list_card, text="Lista de REFs",
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            list_card,
            text="ex: 001/002/012/011/013/030/042/043 -- cola do jeito que o cliente mandou.",
            font=ctk.CTkFont(size=12), text_color="gray50", wraplength=650, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))
        self.refs_textbox = ctk.CTkTextbox(list_card, height=140)
        self.refs_textbox.pack(fill="x", padx=16, pady=(0, 8))

        self._preview_label = ctk.CTkLabel(
            list_card, text="", font=ctk.CTkFont(size=12), text_color="gray50", justify="left", anchor="w")
        self._preview_label.pack(anchor="w", padx=16, pady=(0, 16), fill="x")
        self.refs_textbox.bind("<KeyRelease>", lambda _e: self._update_preview())

        gui_theme.primary_button(
            self.body, text="Gerar Pedido", width=180, height=40, command=self._generate,
        ).grid(row=4, column=0, sticky="w", pady=(0, 8))

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

    def _rep(self):
        return self.rep_entry.get().strip() or None

    def _medida_rule(self):
        label = self.medida_var.get()
        for m in _MEDIDAS:
            if m["label"] == label:
                return m["rule"]  # None = automático
        return None

    def _qty_min(self):
        txt = self.qty_min_entry.get().strip()
        if txt:
            try:
                v = int(txt)
                return v if v > 0 else None
            except ValueError:
                pass
        return None

    # -- parsing da lista colada -------------------------------------------

    def _parse_refs(self) -> list[str]:
        """Any run of digits in the pasted text is one REF -- works no matter
        which separator (/, vírgula, espaço, linha, "REF" na frente etc)."""
        text = self.refs_textbox.get("1.0", "end")
        return re.findall(r"\d+", text)

    def _update_preview(self):
        refs = self._parse_refs()
        if not refs:
            self._preview_label.configure(text="")
            return
        unique_count = len(set(refs))
        total_units = len(refs)
        self._preview_label.configure(
            text=f"{unique_count} REF(s) diferente(s) reconhecida(s), {total_units} unidade(s) no total.")

    def _collect_exact_entries(self):
        refs = self._parse_refs()
        quantities: dict[str, int] = {}
        order: list[str] = []
        for ref in refs:
            if ref not in quantities:
                order.append(ref)
                quantities[ref] = 0
            quantities[ref] += 1
        return [(ref, quantities[ref]) for ref in order]

    # -- gerar ---------------------------------------------------------------

    def _generate(self):
        exact_entries = self._collect_exact_entries()
        if not exact_entries:
            gui_theme.show_message(
                self.app, "Lista vazia", "Cola a lista de REFs antes de gerar.")
            return

        selected_catalog_ids = [cid for cid, var in self._catalog_vars.items() if var.get()]
        client_name, client_phone = self._client()
        try:
            result = pa.do_generate_combined_order(
                selected_catalog_ids, None, exact_entries, client_name, client_phone,
                client_representative=self._rep(),
                medida_rule=self._medida_rule(),
                quantity_min=self._qty_min())
        except ValueError as ex:
            gui_theme.show_message(self.app, "Não deu pra gerar", str(ex))
            return

        if result["exact_queued"] == 0:
            gui_theme.show_message(
                self.app, "Nada gerado",
                "Nenhuma REF da lista foi encontrada (ou tem tamanho definido).")
            return

        self.refs_textbox.delete("1.0", "end")
        self._update_preview()

        if result["skipped_refs"]:
            skipped_txt = "Ficaram de fora: " + "; ".join(result["skipped_refs"]) + "."
            gui_theme.show_message(self.app, "Aviso", skipped_txt)

        # Navega para a fila e dispara a produção com os IDs recém-criados
        queue_ids = result["queue_ids"]
        self.app.show_page("queue")
        self.app.after(150, lambda: self.app._get_page("queue")._generate(queue_ids, client_name))
