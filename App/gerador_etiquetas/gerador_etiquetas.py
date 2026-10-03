"""Gerador de Etiquetas: a standalone tool, separate from the main
production app and from Gerador de Catálogos, that turns figures already
imported into the database into printable barcode labels. Doesn't read or
write CorelDRAW at all -- everything it needs (catalogs, figures, sizes) is
already in the same database automacao_producao/db.py uses (see
db_etiquetas.py), and its output is a PDF sheet of labels, not a .cdr.

Each figure gets a new sequential reference + EAN-13 barcode the first time
it's generated (see ean13.py, db_etiquetas.get_or_create_reference) --
generating it again for the same figure (and, in modo "por tamanho", the
same size) always returns that same code instead of minting a new one.

Two modes, chosen per batch (some clients want one barcode per drawing,
others want one per drawing+tamanho -- both happen in practice):
  - por_desenho: one label per figure, regardless of size.
  - por_tamanho: one label per figure+medida -- a figure sold in more than
    one size needs a size row added per size it actually comes in.

Run with:
    python gerador_etiquetas.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

import customtkinter as ctk

import db_etiquetas
import file_picker
import gui_theme
import gui_worker
import labels_pdf

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class LabelGeneratorPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._catalogs: list[tuple[int, str, int]] = []
        self._catalog_id: int | None = None
        self._rows: list[dict] = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Gerador de Etiquetas").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Escolhe um catálogo já importado, marca quais figuras entram, e gera uma "
                 "referência + código de barras (EAN-13) pra cada uma -- em PDF, pronto pra imprimir.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=820, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        pick_row = ctk.CTkFrame(self, fg_color="transparent")
        pick_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(pick_row, text="Catálogo:", font=ctk.CTkFont(size=13)).pack(side="left")
        self.catalog_var = ctk.StringVar(value="")
        self.catalog_combo = ctk.CTkComboBox(
            pick_row, values=[], variable=self.catalog_var, width=360,
            command=self._on_catalog_selected, state="readonly")
        self.catalog_combo.pack(side="left", padx=(8, 0))

        mode_row = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        mode_row.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(
            mode_row, text="Modo de geração", font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 4))
        self.mode_var = ctk.StringVar(value=db_etiquetas.MODE_POR_DESENHO)
        radios = ctk.CTkFrame(mode_row, fg_color="transparent")
        radios.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkRadioButton(
            radios, text="Por desenho (um código por figura)", variable=self.mode_var,
            value=db_etiquetas.MODE_POR_DESENHO, command=self._build_rows_ui,
        ).pack(side="left", padx=(0, 24))
        ctk.CTkRadioButton(
            radios, text="Por tamanho (um código por figura + medida)", variable=self.mode_var,
            value=db_etiquetas.MODE_POR_TAMANHO, command=self._build_rows_ui,
        ).pack(side="left")

        client_row = ctk.CTkFrame(mode_row, fg_color="transparent")
        client_row.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkLabel(client_row, text="Cliente (opcional):", font=ctk.CTkFont(size=12)).pack(side="left")
        self.client_entry = ctk.CTkEntry(client_row, width=260, placeholder_text="ex: Loja da Ana")
        self.client_entry.pack(side="left", padx=(8, 0))

        label_text_row = ctk.CTkFrame(mode_row, fg_color="transparent")
        label_text_row.pack(anchor="w", padx=16, pady=(0, 14))
        ctk.CTkLabel(label_text_row, text="Tipo de produto (opcional):", font=ctk.CTkFont(size=12)).pack(side="left")
        self.product_type_entry = ctk.CTkEntry(
            label_text_row, width=260, placeholder_text="ex: FAIXA TERMOCOLANTE DIGITAL")
        self.product_type_entry.pack(side="left", padx=(8, 16))
        ctk.CTkLabel(label_text_row, text="Composição (opcional):", font=ctk.CTkFont(size=12)).pack(side="left")
        self.composition_entry = ctk.CTkEntry(
            label_text_row, width=200, placeholder_text="ex: 100% POLIAMIDA")
        self.composition_entry.pack(side="left", padx=(8, 0))

        self.table_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.table_frame.grid(row=3, column=0, sticky="nsew", padx=28, pady=(0, 8))
        self.table_frame.grid_columnconfigure(0, weight=1)
        self._empty_label = ctk.CTkLabel(
            self.table_frame, text="Escolha um catálogo acima pra ver as figuras dele.",
            font=ctk.CTkFont(size=12), text_color="gray60")
        self._empty_label.pack(anchor="w", pady=20)

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            footer, text="Gerar etiquetas (PDF)", width=220, height=36, command=self._generate,
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(footer, text="", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(side="left", padx=(16, 0))

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=5, column=0, sticky="sew", padx=28, pady=(0, 20))

        db_etiquetas.ensure_schema()
        self._load_catalogs()

    def on_show(self):
        self._load_catalogs()

    # -- catálogo ------------------------------------------------------

    def _load_catalogs(self):
        self._catalogs = db_etiquetas.get_catalogs_with_approved_arts()
        values = [f"{name}  ({approved_count} aprovada(s))" for _id, name, approved_count in self._catalogs]
        self.catalog_combo.configure(values=values)
        if values:
            self.catalog_var.set(values[0])
            self._on_catalog_selected(values[0])
        else:
            self.catalog_var.set("")
            self.status_label.configure(text="Nenhum catálogo com figuras aprovadas encontrado.")

    def _on_catalog_selected(self, _choice):
        index = self.catalog_combo.cget("values").index(self.catalog_var.get())
        catalog_id, _name, _count = self._catalogs[index]
        self._catalog_id = catalog_id

        arts = db_etiquetas.get_arts_for_catalog(catalog_id)
        self._rows = [
            {
                "catalog_art_id": art_id,
                "reference": reference or f"#{art_id}",
                "default_width_mm": width_mm,
                "default_height_mm": height_mm,
                "include_var": ctk.BooleanVar(value=True),
                "size_rows": [],
            }
            for art_id, reference, _preview_path, width_mm, height_mm in arts
        ]
        self._build_rows_ui()

    # -- tabela de figuras -----------------------------------------------

    def _build_rows_ui(self):
        for child in self.table_frame.winfo_children():
            child.destroy()

        if not self._rows:
            ctk.CTkLabel(
                self.table_frame, text="Esse catálogo não tem figuras aprovadas.",
                font=ctk.CTkFont(size=12), text_color="gray60").pack(anchor="w", pady=20)
            return

        por_tamanho = self.mode_var.get() == db_etiquetas.MODE_POR_TAMANHO
        for row in self._rows:
            row["size_rows"] = []
            card = ctk.CTkFrame(self.table_frame, fg_color=("gray95", "gray14"), corner_radius=8)
            card.pack(fill="x", pady=4)

            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 4 if por_tamanho else 10))
            ctk.CTkCheckBox(top, variable=row["include_var"], text=row["reference"],
                             font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
            if row["default_width_mm"] and row["default_height_mm"]:
                ctk.CTkLabel(
                    top, text=f"medida atual: {row['default_width_mm']:.0f}x{row['default_height_mm']:.0f}mm",
                    font=ctk.CTkFont(size=11), text_color="gray60",
                ).pack(side="left", padx=(12, 0))

            if por_tamanho:
                sizes_frame = ctk.CTkFrame(card, fg_color="transparent")
                sizes_frame.pack(fill="x", padx=12, pady=(0, 10))
                row["sizes_frame"] = sizes_frame
                initial = (row["default_width_mm"], row["default_height_mm"]) \
                    if row["default_width_mm"] and row["default_height_mm"] else None
                self._add_size_row(row, initial)
                gui_theme.secondary_button(
                    card, text="+ tamanho", width=110, height=26,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    command=lambda row=row: self._add_size_row(row),
                ).pack(anchor="w", padx=12, pady=(0, 10))

    def _add_size_row(self, row, initial: tuple[float, float] | None = None):
        size_row_frame = ctk.CTkFrame(row["sizes_frame"], fg_color="transparent")
        size_row_frame.pack(fill="x", pady=2)

        ctk.CTkLabel(size_row_frame, text="Largura (mm):", font=ctk.CTkFont(size=11)).pack(side="left")
        width_entry = ctk.CTkEntry(size_row_frame, width=70)
        width_entry.pack(side="left", padx=(4, 12))
        ctk.CTkLabel(size_row_frame, text="Altura (mm):", font=ctk.CTkFont(size=11)).pack(side="left")
        height_entry = ctk.CTkEntry(size_row_frame, width=70)
        height_entry.pack(side="left", padx=(4, 12))
        if initial:
            width_entry.insert(0, f"{initial[0]:.0f}")
            height_entry.insert(0, f"{initial[1]:.0f}")

        size_row = {"frame": size_row_frame, "width_entry": width_entry, "height_entry": height_entry}

        def remove():
            if len(row["size_rows"]) <= 1:
                return
            row["size_rows"].remove(size_row)
            size_row_frame.destroy()

        ctk.CTkButton(
            size_row_frame, text="x", width=26, height=26, fg_color="gray40", hover_color="gray30",
            command=remove,
        ).pack(side="left")

        row["size_rows"].append(size_row)

    # -- gerar -------------------------------------------------------------

    def _collect_specs(self):
        """Returns (specs, error_message). specs: list of
        (catalog_art_id, reference_text, width_mm | None, height_mm | None)."""
        mode = self.mode_var.get()
        specs = []
        for row in self._rows:
            if not row["include_var"].get():
                continue
            if mode == db_etiquetas.MODE_POR_DESENHO:
                specs.append((row["catalog_art_id"], row["reference"], None, None))
                continue

            for size_row in row["size_rows"]:
                width_text = size_row["width_entry"].get().strip().replace(",", ".")
                height_text = size_row["height_entry"].get().strip().replace(",", ".")
                try:
                    width_mm = float(width_text)
                    height_mm = float(height_text)
                    if width_mm <= 0 or height_mm <= 0:
                        raise ValueError
                except ValueError:
                    return None, f"Tamanho inválido em \"{row['reference']}\": informe largura e altura em mm."
                specs.append((row["catalog_art_id"], row["reference"], width_mm, height_mm))

        if not specs:
            return None, "Marque pelo menos uma figura pra gerar etiqueta."
        return specs, None

    def _generate(self):
        specs, error = self._collect_specs()
        if error:
            gui_theme.show_message(self, "Não deu pra gerar", error)
            return

        default_name = "etiquetas.pdf"
        save_path = file_picker.pick_save_path_pdf(default_name)
        if not save_path:
            return

        mode = self.mode_var.get()
        client_name = self.client_entry.get().strip()
        product_type = self.product_type_entry.get().strip()
        composition = self.composition_entry.get().strip()
        catalog_id = self._catalog_id

        self.status_label.configure(text="Gerando...")
        self.log_panel.show(f"Gerando {len(specs)} etiqueta(s)...\n\n")

        def task():
            items = []
            reference_ids = []
            for catalog_art_id, reference_text, width_mm, height_mm in specs:
                ref_id, _sequence, ean13_code = db_etiquetas.get_or_create_reference(
                    catalog_art_id, mode, width_mm, height_mm)
                reference_ids.append(ref_id)
                items.append(labels_pdf.LabelItem(
                    reference_text=reference_text, ean13_code=ean13_code,
                    width_mm=width_mm, height_mm=height_mm))
                print(f"  {reference_text} -> {ean13_code}")

            labels_pdf.generate_label_sheet(
                items, save_path, product_type=product_type, composition=composition)
            db_etiquetas.create_batch(catalog_id, mode, client_name, reference_ids)
            print(f"\nPronto: {save_path}")
            return save_path

        def on_success(result_path):
            self.status_label.configure(text=f"Gerado: {os.path.basename(result_path)}")
            self.log_panel.hide_after()

        def on_error(ex):
            self.status_label.configure(text="Falhou.")
            gui_theme.show_message(self, "Erro ao gerar etiquetas", str(ex))

        gui_worker.run_task(
            self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)


if __name__ == "__main__":
    root = ctk.CTk()
    root.title("Baby Luz — Gerador de Etiquetas")
    root.geometry("900x760")
    root.minsize(760, 600)

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    LabelGeneratorPage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
