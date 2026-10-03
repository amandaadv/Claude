"""Tabela de Preços page: cadastra o preço de cada tipo de produto por
medida (ex: "Aplique Baby" 9x8,5cm Têxtil = R$2,47) -- é aí que
pa.do_generate_budget busca o valor unitário de cada REF na hora de montar
um orçamento (ver gui_page_queue.py, botão "Gerar Orçamento"). Cadastro
100% local (nada disso vai pro site) -- só precisa bater com o "tipo" e
"material" marcados em cada catálogo (ver gui_page_catalogs.py, botão
"Definir tipo").
"""
import customtkinter as ctk

import db
import gui_theme

# Rótulo mostrado no dropdown -> valor gravado no banco (mesmo valor cru que
# gui_page_catalogs.py usa -- as duas telas têm que bater exatamente pra
# do_generate_budget achar o preço).
MATERIAIS_SITE = {"Têxtil - Termocolante": "Textil", "Adesivo - UV": "UV"}


class PriceDialog(ctk.CTkToplevel):
    def __init__(self, master, title, price=None):
        super().__init__(master)
        self.title(title)
        gui_theme.center_over_master(self, master, 360, 420)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.result = None

        tipos_existentes = db.list_distinct_price_types()

        ctk.CTkLabel(self, text="Tipo (ex: Aplique Baby, Faixa Digital)",
                     font=ctk.CTkFont(size=12), text_color="gray50").pack(padx=24, pady=(20, 0), anchor="w")
        self.tipo_combo = ctk.CTkComboBox(self, values=tipos_existentes, state="normal")
        self.tipo_combo.pack(padx=24, pady=(2, 10), fill="x")

        ctk.CTkLabel(self, text="Material", font=ctk.CTkFont(size=12), text_color="gray50").pack(
            padx=24, pady=(0, 0), anchor="w")
        self.material_combo = ctk.CTkComboBox(self, values=list(MATERIAIS_SITE), state="readonly")
        self.material_combo.pack(padx=24, pady=(2, 10), fill="x")

        medidas_row = ctk.CTkFrame(self, fg_color="transparent")
        medidas_row.pack(padx=24, pady=(0, 10), fill="x")
        medidas_row.grid_columnconfigure((0, 1), weight=1)
        largura_col = ctk.CTkFrame(medidas_row, fg_color="transparent")
        largura_col.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(largura_col, text="Largura (cm)", font=ctk.CTkFont(size=12), text_color="gray50").pack(
            anchor="w")
        self.largura_entry = ctk.CTkEntry(largura_col, placeholder_text="ex: 9")
        self.largura_entry.pack(fill="x", pady=(2, 0))
        altura_col = ctk.CTkFrame(medidas_row, fg_color="transparent")
        altura_col.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkLabel(altura_col, text="Altura (cm)", font=ctk.CTkFont(size=12), text_color="gray50").pack(
            anchor="w")
        self.altura_entry = ctk.CTkEntry(altura_col, placeholder_text="ex: 8,5")
        self.altura_entry.pack(fill="x", pady=(2, 0))

        ctk.CTkLabel(self, text="Valor (R$)", font=ctk.CTkFont(size=12), text_color="gray50").pack(
            padx=24, pady=(0, 0), anchor="w")
        self.valor_entry = ctk.CTkEntry(self, placeholder_text="ex: 2,47")
        self.valor_entry.pack(padx=24, pady=(2, 10), fill="x")

        if price is not None:
            _id, tipo, material, largura_cm, altura_cm, valor = price
            self.tipo_combo.set(tipo)
            self.material_combo.set(next(
                (label for label, value in MATERIAIS_SITE.items() if value == material),
                next(iter(MATERIAIS_SITE))))
            self.largura_entry.insert(0, _fmt(largura_cm))
            self.altura_entry.insert(0, _fmt(altura_cm))
            self.valor_entry.insert(0, _fmt(valor))
        else:
            self.material_combo.set(next(iter(MATERIAIS_SITE)))

        self.erro_label = ctk.CTkLabel(self, text="", text_color="#c0392b", font=ctk.CTkFont(size=12))
        self.erro_label.pack(padx=24, anchor="w")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(6, 20))
        ctk.CTkButton(button_row, text="Cancelar", fg_color="gray40", hover_color="gray30",
                      width=110, command=self._cancel).pack(side="left", padx=8)
        gui_theme.primary_button(button_row, text="Salvar", width=110, command=self._confirm).pack(
            side="left", padx=8)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())
        self.tipo_combo.focus()

    def _confirm(self):
        tipo = self.tipo_combo.get().strip()
        material_label = self.material_combo.get().strip()
        material = MATERIAIS_SITE.get(material_label, material_label)
        if not tipo or not material:
            self.erro_label.configure(text="Tipo e material são obrigatórios.")
            return
        try:
            largura_cm = _parse_number(self.largura_entry.get())
            altura_cm = _parse_number(self.altura_entry.get())
            valor = _parse_number(self.valor_entry.get())
        except ValueError:
            self.erro_label.configure(text="Largura, altura e valor precisam ser números (ex: 8,5).")
            return
        if largura_cm <= 0 or altura_cm <= 0 or valor < 0:
            self.erro_label.configure(text="Largura e altura precisam ser maiores que zero.")
            return
        self.result = {"tipo": tipo, "material": material, "largura_cm": largura_cm,
                        "altura_cm": altura_cm, "valor": valor}
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def _parse_number(text: str) -> float:
    return float(text.strip().replace(",", "."))


def _fmt(value: float) -> str:
    return f"{value:g}".replace(".", ",")


class PricesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(28, 8))
        header.grid_columnconfigure(0, weight=1)
        gui_theme.back_button(header, self.app).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        gui_theme.section_title(header, "Tabela de Preços").grid(row=1, column=0, sticky="w")
        gui_theme.card_button(
            header, "+", "Novo preço", self._create,
            color=gui_theme.ACCENT, hover_color=gui_theme.ACCENT_HOVER, width=100, height=70,
        ).grid(row=1, column=1, sticky="e")

        self.status_label = ctk.CTkLabel(
            self, text="Usado pra montar o orçamento -- o \"tipo\" precisa bater com o que está "
                       "marcado em cada catálogo (aba Catálogos, botão \"Definir tipo\").",
            font=ctk.CTkFont(size=12), text_color="gray60", anchor="w", wraplength=900, justify="left")
        self.status_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=28)

        self.list_frame = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.list_frame.grid(row=2, column=0, sticky="nsew", padx=24, pady=(8, 20))
        self.list_frame.grid_columnconfigure(0, weight=1)

    def on_show(self):
        self.refresh()

    def refresh(self):
        for child in self.list_frame.winfo_children():
            child.destroy()

        prices = db.list_product_prices()
        if not prices:
            ctk.CTkLabel(
                self.list_frame, text="Nenhum preço cadastrado ainda.", text_color="gray60",
            ).grid(row=0, column=0, sticky="w")
            return

        for i, price in enumerate(prices):
            price_id, tipo, material, largura_cm, altura_cm, valor = price
            material_label = next(
                (label for label, value in MATERIAIS_SITE.items() if value == material), material)
            row = ctk.CTkFrame(
                self.list_frame, corner_radius=10, fg_color=("gray92", "gray17"))
            row.grid(row=i, column=0, sticky="ew", pady=(0 if i == 0 else 8, 0), padx=2)
            row.grid_columnconfigure(0, weight=1)

            info = ctk.CTkFrame(row, fg_color="transparent")
            info.grid(row=0, column=0, sticky="w", padx=16, pady=10)
            ctk.CTkLabel(
                info, text=f"{tipo}  ·  {material_label}  ·  {_fmt(largura_cm)}x{_fmt(altura_cm)}cm",
                font=ctk.CTkFont(size=14, weight="bold"),
            ).pack(anchor="w")
            ctk.CTkLabel(
                info, text=f"R$ {valor:.2f}".replace(".", ","),
                font=ctk.CTkFont(size=12), text_color="gray50",
            ).pack(anchor="w")

            actions = ctk.CTkFrame(row, fg_color="transparent")
            actions.grid(row=0, column=1, sticky="e", padx=16, pady=10)
            gui_theme.secondary_button(
                actions, text="Editar", width=90, height=30,
                command=lambda p=price: self._edit(p),
            ).pack(side="left", padx=4)
            gui_theme.danger_button(
                actions, text="Excluir", width=90, height=30,
                command=lambda p=price: self._delete(p),
            ).pack(side="left", padx=4)

    def _create(self):
        dialog = PriceDialog(self.app, "Novo preço")
        self.app.wait_window(dialog)
        if not dialog.result:
            return
        data = dialog.result
        try:
            db.add_product_price(data["tipo"], data["material"], data["largura_cm"],
                                  data["altura_cm"], data["valor"])
        except Exception as ex:
            gui_theme.show_message(
                self.app, "Erro ao cadastrar",
                f"{ex}\n\nJá deve existir um preço pra esse tipo+material+medida.")
            return
        self.refresh()

    def _edit(self, price):
        dialog = PriceDialog(self.app, "Editar preço", price=price)
        self.app.wait_window(dialog)
        if not dialog.result:
            return
        data = dialog.result
        try:
            db.update_product_price(
                price[0], data["tipo"], data["material"], data["largura_cm"], data["altura_cm"], data["valor"])
        except Exception as ex:
            gui_theme.show_message(
                self.app, "Erro ao salvar",
                f"{ex}\n\nJá deve existir outro preço pra esse tipo+material+medida.")
            return
        self.refresh()

    def _delete(self, price):
        price_id, tipo, material, largura_cm, altura_cm, _valor = price
        if not gui_theme.ask_confirm(
            self.app, "Excluir preço",
            f'Tem certeza que quer excluir o preço de "{tipo}  ·  {material}  ·  '
            f'{_fmt(largura_cm)}x{_fmt(altura_cm)}cm"?',
            confirm_text="Excluir", danger=True,
        ):
            return
        db.delete_product_price(price_id)
        self.refresh()
