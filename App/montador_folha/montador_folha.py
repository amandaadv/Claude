"""Montador de Folha: imports a sequence of figures and lays them out
directly inside a CorelDRAW document, each figure tiled across a row (as
many copies as fit) repeated 3 rows deep before moving to the next figure,
automatically starting a new PAGE whenever the current one runs out of
room -- see montador_folha_ia.py for exactly how.

Run with:
    python montador_folha.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "automacao_producao"))

import customtkinter as ctk
from PIL import Image

import db
import file_picker
import gui_theme
import gui_worker
import montador_folha_ia


def _normalize_ref(text: str) -> str:
    """Digits only, leading zeros stripped -- "001" and "1" both match the
    same REF, same convention db.py uses for reference lookups elsewhere."""
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.lstrip("0") or ("0" if digits else "")

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

THUMB_SIZE = 70


class SheetAssemblerPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.image_paths: list[str] = []
        self.image_labels: list[str] = []  # what shows under each thumbnail -- REF when known, else filename

        gui_theme.back_button(self, self.app).pack(anchor="w", padx=20, pady=(16, 0))

        # Everything below is inside a scrollable frame -- on a small laptop
        # screen (short vertical resolution), the form + "Gerar no CorelDRAW"
        # button used to overflow the window with no way to reach them at
        # all, since the page itself didn't scroll.
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        scroll.pack(fill="both", expand=True, padx=0, pady=0)

        top_bar = ctk.CTkFrame(scroll, fg_color="transparent")
        top_bar.pack(fill="x", padx=20, pady=16)
        ctk.CTkLabel(
            top_bar, text="Montador de Folha", font=ctk.CTkFont(size=20, weight="bold"),
        ).pack(side="left")
        gui_theme.secondary_button(
            top_bar, text="📂 Importar Figuras (arquivos)", width=210, command=self.import_images,
        ).pack(side="right")

        catalog_section = ctk.CTkFrame(scroll, fg_color=("gray95", "gray14"), corner_radius=12)
        catalog_section.pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(
            catalog_section, text="Importar REFs de um catálogo", font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 6))

        ctk.CTkLabel(
            catalog_section, text="Catálogos (marque um ou mais -- a busca de REF procura em todos):",
            font=ctk.CTkFont(size=12),
        ).pack(anchor="w", padx=16)
        catalogs_list_frame = ctk.CTkScrollableFrame(
            catalog_section, fg_color=("gray90", "gray17"), corner_radius=8, height=90,
            **gui_theme.SCROLLBAR_KWARGS)
        catalogs_list_frame.pack(fill="x", padx=16, pady=(4, 8))
        self._catalogs_list_frame = catalogs_list_frame
        # catalog_id -> BooleanVar, kept across _load_catalogs() calls so
        # on_show() (every time this page is opened) doesn't reset what the
        # operator already had marked.
        self._catalog_check_vars: dict[int, ctk.BooleanVar] = {}

        refs_row = ctk.CTkFrame(catalog_section, fg_color="transparent")
        refs_row.pack(fill="x", padx=16, pady=(0, 14))
        ctk.CTkLabel(refs_row, text="REFs (separadas por \"/\"):", font=ctk.CTkFont(size=12)).pack(side="left")
        self.refs_entry = ctk.CTkEntry(refs_row, width=260, placeholder_text="ex: 001/1393/2458")
        self.refs_entry.pack(side="left", padx=(8, 12))
        gui_theme.primary_button(
            refs_row, text="Importar do catálogo", width=170, height=32, command=self.import_from_catalog,
        ).pack(side="left")

        self._catalogs: list[tuple] = []
        self._load_catalogs()

        self.count_label = ctk.CTkLabel(
            scroll, text="Nenhuma figura importada ainda.", font=ctk.CTkFont(size=13), text_color="gray60")
        self.count_label.pack(anchor="w", padx=24)

        self.thumbs_frame = ctk.CTkScrollableFrame(
            scroll, fg_color=("gray95", "gray14"), corner_radius=10, height=110,
            orientation="horizontal", **gui_theme.SCROLLBAR_KWARGS)
        self.thumbs_frame.pack(fill="x", padx=20, pady=(8, 20))

        form = ctk.CTkFrame(scroll, fg_color=("gray95", "gray14"), corner_radius=12)
        form.pack(fill="x", padx=20)
        form.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkLabel(form, text="Tamanho da folha", font=ctk.CTkFont(size=14, weight="bold")).grid(
            row=0, column=0, columnspan=2, padx=20, pady=(16, 8), sticky="w")

        ctk.CTkLabel(form, text="Largura da folha (mm):").grid(row=1, column=0, padx=(20, 8), sticky="w")
        self.sheet_width_entry = ctk.CTkEntry(form, placeholder_text="ex: 400")
        self.sheet_width_entry.grid(row=2, column=0, padx=(20, 8), pady=(2, 14), sticky="ew")

        ctk.CTkLabel(form, text="Comprimento da folha (mm):").grid(row=1, column=1, padx=(8, 20), sticky="w")
        self.sheet_length_entry = ctk.CTkEntry(form, placeholder_text="ex: 2000")
        self.sheet_length_entry.grid(row=2, column=1, padx=(8, 20), pady=(2, 14), sticky="ew")

        ctk.CTkLabel(form, text="Tamanho do lado maior de cada figura (mm):").grid(
            row=3, column=0, padx=(20, 8), sticky="w")
        self.figure_size_entry = ctk.CTkEntry(form, placeholder_text="ex: 90")
        self.figure_size_entry.grid(row=4, column=0, padx=(20, 8), pady=(2, 14), sticky="ew")

        ctk.CTkLabel(form, text="Espaçamento entre figuras (mm):").grid(
            row=3, column=1, padx=(8, 20), sticky="w")
        self.gap_entry = ctk.CTkEntry(form, placeholder_text="ex: 2")
        self.gap_entry.grid(row=4, column=1, padx=(8, 20), pady=(2, 14), sticky="ew")

        ctk.CTkLabel(form, text="Quantidade de cada figura:").grid(
            row=5, column=0, padx=(20, 8), sticky="w")
        self.quantity_entry = ctk.CTkEntry(form, placeholder_text="ex: 24")
        self.quantity_entry.grid(row=6, column=0, padx=(20, 8), pady=(2, 16), sticky="ew")

        gui_theme.primary_button(
            scroll, text="⚙ Gerar no CorelDRAW", width=220, height=42,
            font=ctk.CTkFont(size=14, weight="bold"), command=self.generate,
        ).pack(pady=(24, 8))

        self.log_panel = gui_worker.LogPanel(scroll)
        self.log_panel.pack(fill="x", padx=20, pady=(0, 16))

    def on_show(self):
        self._load_catalogs()

    def _load_catalogs(self):
        self._catalogs = db.get_all_catalogs()
        for widget in self._catalogs_list_frame.winfo_children():
            widget.destroy()

        if not self._catalogs:
            ctk.CTkLabel(
                self._catalogs_list_frame, text="Nenhum catálogo importado ainda.",
                font=ctk.CTkFont(size=11), text_color="gray60").pack(anchor="w", padx=8, pady=8)
            return

        for catalog_id, name, _status, _created_at, total_arts, _a, _r, _p in self._catalogs:
            # New default: checked -- an operator hunting REFs across
            # catalogs almost always wants every catalog searched, and can
            # uncheck the odd one out rather than having to check every box
            # by hand first. Existing choices survive a reload (on_show()
            # runs every time this page is opened) since the BooleanVar is
            # kept in self._catalog_check_vars, not recreated from scratch.
            var = self._catalog_check_vars.setdefault(catalog_id, ctk.BooleanVar(value=True))
            ctk.CTkCheckBox(
                self._catalogs_list_frame, text=f"{name}  ({total_arts} figura(s))",
                variable=var, font=ctk.CTkFont(size=12),
            ).pack(anchor="w", padx=8, pady=2)

    def import_images(self):
        paths = file_picker.pick_image_files()
        if not paths:
            return
        self.image_paths = paths
        self.image_labels = [os.path.basename(p) for p in paths]
        self.count_label.configure(
            text=f"{len(paths)} figura(s) importada(s) -- vão pra folha nessa ordem.")
        self._refresh_thumbnails()

    def import_from_catalog(self):
        selected_catalog_ids = [
            catalog_id for catalog_id, var in self._catalog_check_vars.items() if var.get()
        ]
        if not selected_catalog_ids:
            gui_theme.show_message(self, "Montador de Folha", "Marque pelo menos um catálogo da lista.")
            return
        refs_text = self.refs_entry.get().strip()
        if not refs_text:
            gui_theme.show_message(
                self, "Montador de Folha", "Digite as REFs separadas por \"/\", ex: 001/1393/2458.")
            return

        wanted_refs = [_normalize_ref(r) for r in refs_text.split("/") if r.strip()]

        # Order matches the checkbox list (same as db.get_all_catalogs()'s
        # display order): if the same REF number exists in more than one
        # marked catalog, the first one in that order wins -- setdefault
        # never overwrites an already-found path with a later catalog's.
        path_by_ref = {}
        for catalog_id in selected_catalog_ids:
            arts = db.get_arts_with_paths_by_catalog_id(catalog_id)
            for _art_id, reference, _page_number, original_image_path, _preview_path, _review_status in arts:
                if reference and original_image_path:
                    # Keeps the real reference string too (e.g. "REF 90"),
                    # not just the path -- what's typed to find a figure
                    # ("90") isn't necessarily a good label to show back
                    # for it, so the thumbnail shows the catalog's own
                    # reference text instead.
                    path_by_ref.setdefault(_normalize_ref(reference), (original_image_path, reference))

        matched_paths = []
        matched_labels = []
        missing_refs = []
        for ref in wanted_refs:
            entry = path_by_ref.get(ref)
            if entry:
                path, label = entry
                matched_paths.append(path)
                matched_labels.append(label)
            else:
                missing_refs.append(ref)

        if not matched_paths:
            gui_theme.show_message(self, "Nada encontrado", "Nenhuma das REFs digitadas foi encontrada nesse catálogo.")
            return

        self.image_paths = matched_paths
        self.image_labels = matched_labels
        self._refresh_thumbnails()
        message = f"{len(matched_paths)} figura(s) importada(s) do catálogo -- vão pra folha nessa ordem."
        if missing_refs:
            message += f"\n(Não achei: {', '.join(missing_refs)})"
        self.count_label.configure(text=message)

    def _refresh_thumbnails(self):
        for widget in self.thumbs_frame.winfo_children():
            widget.destroy()
        # image_labels not kept in sync (older/unexpected code path) --
        # falls back to filenames rather than crashing on a length mismatch.
        labels = self.image_labels if len(self.image_labels) == len(self.image_paths) \
            else [os.path.basename(p) for p in self.image_paths]
        for path, label in zip(self.image_paths, labels):
            try:
                im = Image.open(path).convert("RGBA")
                im.thumbnail((THUMB_SIZE, THUMB_SIZE))
                thumb = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
            except Exception:
                continue
            card = ctk.CTkFrame(self.thumbs_frame, fg_color="transparent")
            card.pack(side="left", padx=6, pady=6)
            ctk.CTkLabel(card, image=thumb, text="").pack()
            ctk.CTkLabel(
                card, text=label, font=ctk.CTkFont(size=9, weight="bold"),
                text_color="gray60", wraplength=THUMB_SIZE,
            ).pack()
            card._image_ref = thumb  # keep alive

    def _positive_float(self, entry, allow_zero=False):
        try:
            value = float(entry.get().strip().replace(",", "."))
            if value < 0 or (value == 0 and not allow_zero):
                return None
            return value
        except ValueError:
            return None

    def generate(self):
        if not self.image_paths:
            gui_theme.show_message(self, "Montador de Folha", "Importe as figuras primeiro.")
            return

        sheet_width_mm = self._positive_float(self.sheet_width_entry)
        sheet_length_mm = self._positive_float(self.sheet_length_entry)
        figure_size_mm = self._positive_float(self.figure_size_entry)
        gap_mm = self._positive_float(self.gap_entry, allow_zero=True)

        if sheet_width_mm is None or sheet_length_mm is None:
            gui_theme.show_message(self, "Montador de Folha", "Preencha a largura e o comprimento da folha (mm, maiores que zero).")
            return
        if figure_size_mm is None:
            gui_theme.show_message(self, "Montador de Folha", "Preencha o tamanho do lado maior de cada figura (mm, maior que zero).")
            return
        if gap_mm is None:
            gui_theme.show_message(self, "Montador de Folha", "Preencha o espaçamento entre figuras (mm, zero ou maior).")
            return

        try:
            quantity_per_figure = int(self.quantity_entry.get().strip())
            if quantity_per_figure <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self, "Montador de Folha",
                "Preencha \"Quantidade de cada figura\" com um número inteiro maior que zero.")
            return

        save_path = file_picker.pick_save_path("folha.cdr")
        if not save_path:
            return

        self.log_panel.show("Gerando no CorelDRAW...\n\n")

        def task():
            return montador_folha_ia.generate_in_corel(
                self.image_paths, figure_size_mm, sheet_width_mm, sheet_length_mm, gap_mm,
                quantity_per_figure, save_path)

        def on_success(_document):
            self.log_panel.hide_after()
            gui_theme.show_message(self, "Gerado", f"Pronto!\n\nArquivo CorelDRAW:\n{save_path}")

        def on_error(ex):
            gui_theme.show_message(self, "Erro ao gerar", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)


if __name__ == "__main__":
    db.ensure_schema_extensions()
    root = ctk.CTk()
    root.title("Baby Luz - Montador de Folha")
    root.geometry("900x720")

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    SheetAssemblerPage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
