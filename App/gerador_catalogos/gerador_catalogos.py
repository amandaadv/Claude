"""Gerador de Catálogos: a standalone tool, separate from the main
production app (gui_app.py), for producing size variants of a master
catalog .cdr -- opens one, shows every REF's current width/height, lets
the user fix one dimension (largura or altura) to a single value across
every REF at once, and writes a brand-new .cdr with every figure placed
in a fresh grid (image, then its "REF N MED AxB" caption right below it)
on a page sized the way the shop actually prints catalogs. The original
file is never touched -- "Criar Catálogo" always saves to a new,
user-chosen path.

"Criar Catálogo" does NOT resize shapes in place on a copy of the master
file -- an earlier version did, and it broke visually as soon as a
figure's size changed: the master's own row/column positions (and its
caption text sitting right where the ORIGINAL size left room for it)
don't adapt, so a resized figure runs into its own caption or the next
row. Instead, this builds a brand-new blank document at a configurable
page size (largura/altura, defaulting to the shop's usual 270x2000mm)
and lays out each figure from scratch: copy the artwork out of the
master (master_artwork.copy_artwork_shape/coreldraw_service.paste_artwork
-- the same real-vector-copy machinery production_generator.py already
uses), resize it, place it, then create a brand-new caption text shape
right beneath it (coreldraw_service.create_text) -- see
_compute_grid_layout for the row/page-wrapping math, which is pure
Python and deliberately separate from CorelDRAW COM so it's testable
without the real application open.

A page inside gui_app.py (the main production app) -- imports
master_artwork.py and coreldraw_service.py directly instead of
duplicating their already-tested REF/caption-reading and CorelDRAW
automation logic. No database for this tool's own data: everything after
"open the file" lives in a plain Python list (self._rows) until "Criar
Catálogo" writes it out. The one exception is reading (never writing) the
shop's configured target CorelDRAW save version via
pa.get_target_corel_version(), so a catalog generated here still opens on
the same CorelDRAW version the main production app targets.

Also runnable standalone:
    python gerador_catalogos.py
"""
import math
import os
import sys
import tempfile
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "automacao_producao"))

import customtkinter as ctk

import coreldraw_service
import file_picker
import gui_theme
import gui_worker
import master_artwork
import pa
import paths


def _ref_sort_key(ref_number: str) -> tuple[int, int]:
    """Sorts "2212" before "2212/1" before "2212/2" before "2213" -- a plain
    int(ref_number) crashes the moment a REF carries a "/N" variant suffix
    (two different pieces sharing one base number, e.g. "REF.2212/1" and
    "REF.2212/2" -- see master_artwork.REF_CAPTION_PATTERN)."""
    base, _sep, variant = ref_number.partition("/")
    return int(base), int(variant) if variant else 0

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# Grid-layout constants for the from-scratch catalog page -- all in mm.
# Not user-configurable (unlike page width/height): these only affect
# breathing room between figures/captions, not the catalog's actual
# content, so a fixed sensible default avoids cluttering the UI with
# knobs nobody asked for.
PAGE_MARGIN_MM = 10.0
SPACING_H_MM = 5.0
SPACING_V_MM = 5.0
HEADER_GAP_MM = 15.0  # extra breathing room between the header and the first row of figures
FOOTER_GAP_MM = 15.0  # extra breathing room between the last row of figures and the footer
CAPTION_HEIGHT_MM = 7.0  # vertical room reserved below each figure for its caption line
CAPTION_FONT_SIZE_PT = 16.0  # at this size a bold caption renders ~4mm tall -- comfortably under CAPTION_HEIGHT_MM
# A row that misses fitting by under a millimeter (this happens easily
# with real, non-round native figure widths) shouldn't be needlessly
# rejected -- same tolerance idea already used for row-fitting in the
# main production app's production.py (OVERFLOW_TOLERANCE_MM there).
OVERFLOW_TOLERANCE_MM = 5.0

# Rough average advance width of one bold character at CAPTION_FONT_SIZE_PT,
# in mm -- see _slot_width_mm. Deliberately generous (a real bold sans-serif
# character is usually narrower than this on average) since guessing too
# NARROW is exactly the bug this exists to fix (a long/thin figure's caption
# text overlapping its neighbor's -- confirmed live on a catalog of tall
# narrow floral border strips, where every figure's own width was much
# smaller than its "REF NNN MED AxBMM" caption's real rendered width);
# guessing too wide only costs a little extra, harmless breathing room.
_CAPTION_CHAR_WIDTH_MM = CAPTION_FONT_SIZE_PT * 0.3528 * 0.62


def _slot_width_mm(item: dict) -> float:
    """How much horizontal room one figure actually needs during layout --
    its own width, or its caption's estimated width, whichever is bigger.
    Most figures are wide enough that their own width already wins (no
    change from before); a long/thin figure (much taller than wide) is
    exactly the case where the caption needs more room than the figure
    itself does, and this is what reserves that extra room between it and
    its neighbor instead of letting the two captions collide. Only affects
    SPACING during packing (see _compute_grid_layout) -- the figure image
    itself is still placed and sized at its own real width, just centered
    within this wider slot when the two differ."""
    caption_text = f"REF {item['ref_number']} MED {round(item['altura_mm'])}X{round(item['largura_mm'])}MM"
    estimated_caption_width_mm = len(caption_text) * _CAPTION_CHAR_WIDTH_MM
    return max(item["largura_mm"], estimated_caption_width_mm)


def _compute_grid_layout(rows, page_width_mm, page_height_mm,
                          top_reserved_mm=0.0, bottom_reserved_mm=0.0):
    """Places every row (REF) into rows that fill the page's usable width
    as completely as possible: figures are added to the current row while
    they still fit (spacing included), and only wrap to a new row once
    the next figure no longer fits -- there's no "número de colunas" for
    her to set or retype. Native figure widths vary a lot from REF to REF
    (more so now that batch-apply keeps each figure's own proportion
    instead of forcing a shared MED value), so a FIXED number of figures
    per row either wastes space or overflows depending on which REFs land
    in which chunk; filling by actual width instead always uses the page
    as fully as the figures allow.

    Each row's reserved cell height is the TALLEST figure in that row
    PLUS CAPTION_HEIGHT_MM, so the next row never lands on top of a
    caption.

    top_reserved_mm/bottom_reserved_mm carve out extra space at the top/
    bottom of EVERY page (below the normal margin) before any product is
    placed -- used to make room for a header/footer repeated on each page
    (see _create_catalog); 0.0 (the default) behaves exactly like no
    header/footer at all.

    Returns a list of pages, each a list of the input row dicts with two
    extra keys added: "x_mm" and "y_mm" (the figure's top-left corner,
    measured from the page's top-left -- callers convert to CorelDRAW's
    bottom-up coordinate system, same as production_generator.py already
    does for production sheets). Raises ValueError (message meant to be
    shown to the user as-is) if the page is too small for its margins
    (plus header/footer), if a single figure is wider than the page
    allows, or if a single figure is taller than the page allows."""
    usable_width_mm = page_width_mm - 2 * PAGE_MARGIN_MM
    usable_height_mm = page_height_mm - 2 * PAGE_MARGIN_MM - top_reserved_mm - bottom_reserved_mm
    top_start_mm = PAGE_MARGIN_MM + top_reserved_mm
    if usable_width_mm <= 0 or usable_height_mm <= 0:
        raise ValueError(
            f"A folha configurada ({page_width_mm:g}mm x {page_height_mm:g}mm) é pequena demais pras "
            f"margens (e pro cabeçalho/rodapé, se tiver).")
    if not rows:
        return [[]]

    # Pre-check the single widest figure up front -- with width-fill
    # packing that's the only way a figure can fail to fit (a fixed
    # column count could fail on a whole row; here every row shrinks or
    # grows to whatever actually fits).
    widest_item = max(rows, key=lambda item: item["largura_mm"])
    if widest_item["largura_mm"] > usable_width_mm + OVERFLOW_TOLERANCE_MM:
        needed_page_width_mm = widest_item["largura_mm"] + 2 * PAGE_MARGIN_MM
        raise ValueError(
            f"REF {widest_item['ref_number']}: largura {widest_item['largura_mm']:g}mm não cabe na "
            f"folha -- a folha atual só tem {usable_width_mm:g}mm úteis. Aumenta a largura da folha "
            f"pra pelo menos {needed_page_width_mm:g}mm.")

    pages = [[]]
    y_mm = top_start_mm
    index = 0
    total = len(rows)

    while index < total:
        row_items = [rows[index]]
        row_width_mm = _slot_width_mm(rows[index])
        index += 1
        while index < total:
            candidate_width_mm = row_width_mm + SPACING_H_MM + _slot_width_mm(rows[index])
            if candidate_width_mm > usable_width_mm + OVERFLOW_TOLERANCE_MM:
                break
            row_items.append(rows[index])
            row_width_mm = candidate_width_mm
            index += 1

        row_height_mm = max(item["altura_mm"] for item in row_items)

        if row_height_mm > usable_height_mm + OVERFLOW_TOLERANCE_MM:
            tallest = max(row_items, key=lambda item: item["altura_mm"])
            raise ValueError(
                f"REF {tallest['ref_number']}: altura {row_height_mm:g}mm não cabe na folha "
                f"({usable_height_mm:g}mm úteis, descontando cabeçalho/rodapé). Diminui a altura ou "
                f"aumenta a folha.")

        cell_height_mm = row_height_mm + CAPTION_HEIGHT_MM
        if y_mm != top_start_mm and y_mm + cell_height_mm > top_start_mm + usable_height_mm + OVERFLOW_TOLERANCE_MM:
            pages.append([])
            y_mm = top_start_mm

        x_mm = PAGE_MARGIN_MM
        for item in row_items:
            slot_width_mm = _slot_width_mm(item)
            placed = dict(item)
            # Centered within its slot -- when the caption needed more
            # room than the figure itself, this is what keeps the figure
            # (and its caption, centered under IT the same way as always)
            # in the middle of that extra room instead of jammed against
            # its left edge.
            placed["x_mm"] = x_mm + (slot_width_mm - item["largura_mm"]) / 2
            placed["y_mm"] = y_mm
            pages[-1].append(placed)
            x_mm += slot_width_mm + SPACING_H_MM

        y_mm += row_height_mm + CAPTION_HEIGHT_MM + SPACING_V_MM

    return pages


class CatalogGeneratorPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._rows: list[dict] = []
        self._master_path: str | None = None
        # (page_index, shape_path) pairs for the master catalog's own
        # header (logo/title) and footer (application photos), auto-
        # detected by find_header_footer_shapes -- see _pick_catalog.
        self._header_refs: list[tuple[int, str]] = []
        self._footer_refs: list[tuple[int, str]] = []
        # Native (width_mm, height_mm) of the header/footer as a whole
        # cluster, or None if nothing was detected -- used to scale it to
        # fit whatever page width is configured at generate time.
        self._header_bbox: tuple[float, float] | None = None
        self._footer_bbox: tuple[float, float] | None = None
        self._corel = coreldraw_service.CorelDrawService()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Gerador de Catálogos").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Abre um catálogo master, mostra a medida de cada figura, e gera uma "
                 "versão nova em outro tamanho -- o arquivo original nunca é alterado.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=820, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        pick_row = ctk.CTkFrame(self, fg_color="transparent")
        pick_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            pick_row, text="Escolher catálogo", width=200, height=36, command=self._pick_catalog,
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(
            pick_row, text="Nenhum catálogo aberto ainda.", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(side="left", padx=(16, 0))

        self.table_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        self.table_frame.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 8))
        self.table_frame.grid_columnconfigure(0, weight=1)

        batch_row = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        batch_row.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(
            batch_row, text="Alterar em lote", font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(
            batch_row,
            text="O valor entra no lado que já é maior em cada figura (mais alta -> altura; "
                 "mais larga -> largura); o outro lado é ajustado na mesma proporção.",
            font=ctk.CTkFont(size=11), text_color="gray60",
        ).pack(anchor="w", padx=16, pady=(0, 4))

        controls = ctk.CTkFrame(batch_row, fg_color="transparent")
        controls.pack(anchor="w", padx=16, pady=(0, 14))
        self.batch_value_entry = ctk.CTkEntry(controls, width=100, placeholder_text="ex: 90")
        self.batch_value_entry.pack(side="left", padx=(0, 8))
        gui_theme.secondary_button(
            controls, text="Aplicar em lote", width=160, height=32, command=self._apply_batch,
        ).pack(side="left")

        ctk.CTkLabel(
            batch_row, text="Medida completa (largura x altura)",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(4, 0))
        ctk.CTkLabel(
            batch_row,
            text="Preencha os DOIS (largura e altura) e TODAS as figuras ficam exatamente nessa medida, "
                 "sem manter a proporção. Se preencher só um, esse lado vira o valor e o outro se ajusta "
                 "na proporção de cada figura.",
            font=ctk.CTkFont(size=11), text_color="gray60", wraplength=820, justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 4))

        full_controls = ctk.CTkFrame(batch_row, fg_color="transparent")
        full_controls.pack(anchor="w", padx=16, pady=(0, 14))
        ctk.CTkLabel(full_controls, text="Largura (mm):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.full_width_entry = ctk.CTkEntry(full_controls, width=90, placeholder_text="ex: 110")
        self.full_width_entry.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(full_controls, text="Altura (mm):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.full_height_entry = ctk.CTkEntry(full_controls, width=90, placeholder_text="ex: 100")
        self.full_height_entry.pack(side="left", padx=(0, 16))
        gui_theme.secondary_button(
            full_controls, text="Aplicar largura x altura", width=200, height=32, command=self._apply_full_measure,
        ).pack(side="left")

        ctk.CTkLabel(
            batch_row, text="Tamanho da folha do catálogo novo",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(4, 4))
        page_size_row = ctk.CTkFrame(batch_row, fg_color="transparent")
        page_size_row.pack(anchor="w", padx=16, pady=(0, 14))
        ctk.CTkLabel(page_size_row, text="Largura (mm):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.page_width_entry = ctk.CTkEntry(page_size_row, width=90)
        self.page_width_entry.insert(0, "270")
        self.page_width_entry.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(page_size_row, text="Altura (mm):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.page_height_entry = ctk.CTkEntry(page_size_row, width=90)
        self.page_height_entry.insert(0, "2000")
        self.page_height_entry.pack(side="left")

        gui_theme.primary_button(
            batch_row, text="Criar Catálogo", width=200, height=36, command=self._create_catalog,
        ).pack(anchor="w", padx=16, pady=(0, 16))

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=4, column=0, sticky="sew", padx=28, pady=(0, 20))

        self._refresh_table()

    # -- escolher catálogo -------------------------------------------------

    def _pick_catalog(self):
        path = file_picker.pick_master_file()
        if not path:
            return

        # Clear any previously loaded catalog's data up front -- otherwise a
        # failed second pick would leave the table/state pointing at the
        # FIRST catalog's rows while a later "Criar Catálogo" click could
        # act on a mismatched document.
        self._rows = []
        self._master_path = None
        self._header_refs = []
        self._footer_refs = []
        self._header_bbox = None
        self._footer_bbox = None
        self._refresh_table()
        self.status_label.configure(text="Abrindo catálogo...")
        self.log_panel.show("Abrindo catálogo no CorelDRAW...\n\n")

        def task():
            # Unique filename per pick -- a fixed name reused across picks
            # risked one pick's temp file being read while a DIFFERENT
            # pick's data was still showing.
            temp_path = os.path.join(tempfile.gettempdir(), f"gerador_catalogos_master_{uuid.uuid4().hex}.cdr")
            normalized_path = master_artwork.ensure_valid_cdr_file(path, temp_path)
            self._corel.connect()
            document = self._corel.open_document(normalized_path)
            self._corel.set_units(document)
            try:
                ref_index = master_artwork.build_ref_index(document)

                # Most master files this shop receives now aren't the
                # "vector art + live REF caption" kind build_ref_index
                # expects -- they're a page of finished raster pieces with
                # each one's "ref NNN" caption converted to curves (see
                # master_artwork.find_curve_caption_products for why
                # build_ref_index can't read those at all). Same fallback
                # pa.do_import_from_master uses: find every such piece not
                # already claimed by a live-text REF, read its caption via
                # OpenAI vision, merge into ref_index. Every REF gets its
                # MED written from the artwork's own real measured size
                # below either way (get_shape_bbox_size), regardless of
                # whether it arrived this way or via a live caption.
                try:
                    vision_api_key = paths.read_openai_api_key()
                except OSError:
                    vision_api_key = None
                if vision_api_key:
                    added = pa._import_curve_captioned_refs(self._corel, document, ref_index, vision_api_key)
                    if added:
                        print(f"{added} referência(s) adicional(is) lida(s) por IA (legendas convertidas em curva).")

                if not ref_index:
                    raise RuntimeError(
                        "Nenhuma REF encontrada nesse arquivo (confira se as legendas estão no "
                        "formato \"REF N\" ou \"REF N MED AxBMM\").")

                rows = []
                for ref_number, entry in ref_index.items():
                    # Deliberately the REAL, selected size of the artwork
                    # (get_shape_size), not the "REF N MED AxBMM" caption's
                    # recorded number -- confirmed explicitly by her after
                    # she compared the two side by side in CorelDRAW (the
                    # caption often records a larger "intended" size than
                    # the artwork's own tight bounding box). This is the
                    # opposite of the main production app's rule (which
                    # deliberately uses the recorded MED numbers verbatim,
                    # per her own earlier explicit instruction there) --
                    # a real, confirmed difference between the two tools.
                    largura_mm, altura_mm = master_artwork.get_shape_bbox_size(
                        document, entry["page_index"], entry["shape_path"])
                    rows.append({
                        "ref_number": ref_number,
                        # Kept at full precision (e.g. 75.329, not rounded
                        # to 75) -- rounding was tried and explicitly
                        # rejected: it visibly threw off how snugly the
                        # figures fit compared to the original catalog's
                        # own precise measurements.
                        "largura_mm": largura_mm,
                        "altura_mm": altura_mm,
                        "shape_path": entry["shape_path"],
                        "caption_shape_path": entry["caption_shape_path"],
                        "page_index": entry["page_index"],
                    })
                rows.sort(key=lambda r: _ref_sort_key(r["ref_number"]))
                print(f"{len(rows)} REF(s) encontrada(s).")

                header_footer = master_artwork.find_header_footer_shapes(document, ref_index)
                header_refs = []
                footer_refs = []
                for page_index, found in header_footer.items():
                    header_refs.extend((page_index, shape_path) for shape_path in found["header"])
                    footer_refs.extend((page_index, shape_path) for shape_path in found["footer"])

                def bbox_of(refs):
                    if not refs:
                        return None
                    lefts, rights, tops, bottoms = [], [], [], []
                    for page_index, shape_path in refs:
                        shape = master_artwork.get_shape(document, page_index, shape_path)
                        lefts.append(shape.LeftX)
                        rights.append(shape.LeftX + shape.SizeWidth)
                        tops.append(shape.TopY)
                        bottoms.append(shape.TopY - shape.SizeHeight)
                    return max(rights) - min(lefts), max(tops) - min(bottoms)

                header_bbox = bbox_of(header_refs)
                footer_bbox = bbox_of(footer_refs)
                if header_refs:
                    print(f"Cabeçalho do catálogo detectado ({len(header_refs)} forma(s)).")
                if footer_refs:
                    print(f"Rodapé do catálogo detectado ({len(footer_refs)} forma(s)).")
            finally:
                # Only plain Python data (rows, refs, bboxes) needs to
                # survive past this call -- the COM document itself must
                # not leak into a later background thread (see the note
                # above self._master_path's declaration in __init__).
                # _create_catalog reopens the file fresh, inside its own
                # single call, when it's actually time to resize/save.
                document.Close()
            return normalized_path, rows, header_refs, header_bbox, footer_refs, footer_bbox

        def on_success(result):
            normalized_path, rows, header_refs, header_bbox, footer_refs, footer_bbox = result
            self._master_path = normalized_path
            self._rows = rows
            self._header_refs = header_refs
            self._header_bbox = header_bbox
            self._footer_refs = footer_refs
            self._footer_bbox = footer_bbox
            self.status_label.configure(text=f"{len(rows)} REF(s) carregada(s).")
            self._refresh_table()
            self.log_panel.hide_after()

        def on_error(ex):
            self.status_label.configure(text="Falha ao abrir o catálogo.")
            gui_theme.show_message(self, "Não deu pra abrir", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    def _apply_batch(self):
        if not self._rows:
            gui_theme.show_message(self, "Nada pra alterar", "Escolha um catálogo primeiro.")
            return
        try:
            value_mm = float(self.batch_value_entry.get().strip().replace(",", "."))
            if not math.isfinite(value_mm) or value_mm <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(self, "Valor inválido", "Informe um número maior que zero (em mm).")
            return

        for row in self._rows:
            altura, largura = row["altura_mm"], row["largura_mm"]
            if altura >= largura:
                scale = value_mm / altura if altura else 1.0
                row["altura_mm"] = value_mm
                row["largura_mm"] = largura * scale
            else:
                scale = value_mm / largura if largura else 1.0
                row["largura_mm"] = value_mm
                row["altura_mm"] = altura * scale
        self._refresh_table()

    def _create_catalog(self):
        if not self._rows or self._master_path is None:
            gui_theme.show_message(self, "Nada pra gerar", "Escolha um catálogo primeiro.")
            return

        try:
            page_width_mm = float(self.page_width_entry.get().strip().replace(",", "."))
            page_height_mm = float(self.page_height_entry.get().strip().replace(",", "."))
            if not math.isfinite(page_width_mm) or not math.isfinite(page_height_mm) \
                    or page_width_mm <= 0 or page_height_mm <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self, "Tamanho de folha inválido", "Largura e altura da folha precisam ser números maiores que zero (em mm).")
            return

        usable_width_mm = page_width_mm - 2 * PAGE_MARGIN_MM
        if usable_width_mm <= 0:
            gui_theme.show_message(
                self, "Não deu pra organizar a folha",
                f"A folha configurada ({page_width_mm:g}mm) é pequena demais pras margens de "
                f"{PAGE_MARGIN_MM:g}mm.")
            return

        # If the configured width isn't enough for even the single widest
        # figure this catalog will actually produce, widen it
        # automatically (rather than making her retype a number and click
        # "Criar Catálogo" again) -- rows fill by actual width now, so
        # this is the only way a figure could fail to fit.
        widest_item = max(self._rows, key=lambda item: item["largura_mm"])
        if widest_item["largura_mm"] > usable_width_mm + OVERFLOW_TOLERANCE_MM:
            page_width_mm = widest_item["largura_mm"] + 2 * PAGE_MARGIN_MM
            usable_width_mm = page_width_mm - 2 * PAGE_MARGIN_MM
            self.page_width_entry.delete(0, "end")
            self.page_width_entry.insert(0, f"{page_width_mm:g}")

        # Header/footer are scaled (keeping their own aspect ratio) to fit
        # the configured page's usable width -- their height is only known
        # AFTER that scaling, but the grid layout needs to know it BEFORE
        # placing any product, to reserve room at the top/bottom of every
        # page. Pure arithmetic, no CorelDRAW needed for this part.
        header_height_mm = 0.0
        if self._header_bbox:
            header_width_native_mm, header_height_native_mm = self._header_bbox
            header_height_mm = header_height_native_mm * (usable_width_mm / header_width_native_mm)
        footer_height_mm = 0.0
        if self._footer_bbox:
            footer_width_native_mm, footer_height_native_mm = self._footer_bbox
            footer_height_mm = footer_height_native_mm * (usable_width_mm / footer_width_native_mm)

        top_reserved_mm = header_height_mm + HEADER_GAP_MM if header_height_mm else 0.0
        bottom_reserved_mm = footer_height_mm + FOOTER_GAP_MM if footer_height_mm else 0.0

        try:
            layout_pages = _compute_grid_layout(
                self._rows, page_width_mm, page_height_mm, top_reserved_mm, bottom_reserved_mm)
        except ValueError as ex:
            gui_theme.show_message(self, "Não deu pra organizar a folha", str(ex))
            return

        save_path = file_picker.pick_save_path("catalogo_novo.cdr")
        if not save_path:
            return

        self.log_panel.show("Gerando o catálogo novo...\n\n")
        master_path = self._master_path
        header_refs = list(self._header_refs)
        footer_refs = list(self._footer_refs)

        def task():
            self._corel.connect()
            master_document = self._corel.open_document(master_path)
            self._corel.set_units(master_document)
            try:
                new_document = self._corel.create_production_document()
                self._corel.set_units(new_document)
                # Deliberately NOT closed after generating (unlike
                # master_document below) -- she wants to see/keep working
                # on the result in CorelDRAW right away instead of having
                # to reopen the saved file herself.
                for output_page_index, page_items in enumerate(layout_pages):
                    page = self._corel.get_active_page(new_document) if output_page_index == 0 \
                        else self._corel.add_page(new_document)
                    self._corel.set_page_size(page, page_width_mm, page_height_mm)
                    layer = self._corel.create_layer(page, "CATALOGO")

                    if header_refs:
                        # Resolved fresh right before use, not once up front
                        # -- a Shape reference resolved long before (e.g.
                        # the footer's, only used after ~70 unrelated
                        # copy/paste cycles for that page's REFs) was seen
                        # to go stale and make Copy() fail even after
                        # retrying, so there's nothing to gain from holding
                        # onto it across all that intervening activity.
                        header_shapes_master = [
                            master_artwork.get_shape(master_document, page_index, shape_path)
                            for page_index, shape_path in header_refs
                        ]
                        self._corel.copy_shapes(master_document, header_shapes_master)
                        pasted_header = self._corel.paste_shapes(new_document, layer)
                        header_top_corel_y = page_height_mm - PAGE_MARGIN_MM
                        self._corel.fit_and_position_shapes(
                            pasted_header, usable_width_mm, header_height_mm,
                            PAGE_MARGIN_MM, header_top_corel_y)

                    for item in page_items:
                        # copy_artwork_shape/paste_artwork can both come back
                        # without raising anything and still not actually
                        # have placed real artwork -- a Paste() landing a
                        # moment before the clipboard actually finished
                        # updating (Windows clipboard contention, same root
                        # cause already documented on the Copy() side in
                        # master_artwork.copy_artwork_shape) was seen live to
                        # paste a stray near-zero-size shape instead of
                        # raising PASTE_FAILED: the caption still got created
                        # right after with the correct REF and MED (it
                        # doesn't depend on the pasted shape at all), so the
                        # figure looked simply missing, not failed. Retrying
                        # the whole copy+paste+resize cycle (not just the
                        # copy) when the resulting shape's size doesn't match
                        # what was asked for catches this the same way the
                        # main production app's import loop retries a failed
                        # REF instead of aborting the whole batch.
                        last_error = None
                        RETRY_WAITS_S = (2, 4, 8, 16, 24)
                        for attempt in range(1 + len(RETRY_WAITS_S)):
                            try:
                                master_artwork.copy_artwork_shape(
                                    master_document, item["page_index"], item["shape_path"])
                                shape = self._corel.paste_artwork(layer)
                                self._corel.resize_artwork(shape, item["largura_mm"], item["altura_mm"])
                                actual_w, actual_h = self._corel.get_shape_size(shape)
                                if actual_w < item["largura_mm"] * 0.5 or actual_h < item["altura_mm"] * 0.5:
                                    raise RuntimeError(
                                        f"PASTE_INCOMPLETO: pedi {item['largura_mm']:.1f}x{item['altura_mm']:.1f}mm, "
                                        f"saiu {actual_w:.1f}x{actual_h:.1f}mm")
                                last_error = None
                                break
                            except Exception as ex:
                                last_error = ex
                                try:
                                    shape.Delete()
                                except Exception:
                                    pass
                                if attempt < len(RETRY_WAITS_S):
                                    time.sleep(RETRY_WAITS_S[attempt])
                        if last_error is not None:
                            raise RuntimeError(
                                f"REF {item['ref_number']}: falhou ao colar a arte após tentar de novo várias "
                                f"vezes ({last_error}).") from last_error

                        shape_corel_y = page_height_mm - item["y_mm"]
                        self._corel.position_artwork(shape, item["x_mm"], shape_corel_y)

                        # Rounded for DISPLAY only -- the figure itself
                        # (resize_artwork above) keeps the full precise
                        # measurement; only the printed caption drops
                        # the decimals, since "MED 74.5967X75.3295MM"
                        # reads as clutter on an actual catalog page.
                        caption_text = (
                            f"REF {item['ref_number']} MED "
                            f"{round(item['altura_mm'])}X{round(item['largura_mm'])}MM")
                        # create_text anchors the text's BOTTOM edge (not
                        # top) at the y given to it -- so anchoring at
                        # the bottom of the whole reserved caption band
                        # (not right below the image) guarantees the
                        # text, whatever its actual rendered height,
                        # lands inside that band without touching either
                        # the image above it or the next row below it.
                        caption_bottom_from_top = item["y_mm"] + item["altura_mm"] + CAPTION_HEIGHT_MM
                        caption_corel_y = page_height_mm - caption_bottom_from_top
                        caption_shape = self._corel.create_text(
                            layer, item["x_mm"], caption_corel_y, caption_text,
                            size_pt=CAPTION_FONT_SIZE_PT, bold=True)

                        # Center the caption under its figure -- its
                        # actual rendered width is only known now, after
                        # creation, so it can't be computed up front.
                        caption_width_mm, _caption_height_mm = self._corel.get_shape_size(caption_shape)
                        centered_x_mm = item["x_mm"] + (item["largura_mm"] - caption_width_mm) / 2
                        _current_x_mm, current_top_y_mm = self._corel.get_shape_position(caption_shape)
                        self._corel.position_artwork(caption_shape, centered_x_mm, current_top_y_mm)

                        print(f"REF {item['ref_number']}: {item['largura_mm']:g}mm x {item['altura_mm']:g}mm")

                    if footer_refs:
                        # Same reasoning as header_refs above -- resolved
                        # fresh right here, right before this page's footer
                        # Copy(), not held onto since the top of the task.
                        footer_shapes_master = [
                            master_artwork.get_shape(master_document, page_index, shape_path)
                            for page_index, shape_path in footer_refs
                        ]
                        self._corel.copy_shapes(master_document, footer_shapes_master)
                        pasted_footer = self._corel.paste_shapes(new_document, layer)
                        footer_top_corel_y = PAGE_MARGIN_MM + footer_height_mm
                        self._corel.fit_and_position_shapes(
                            pasted_footer, usable_width_mm, footer_height_mm,
                            PAGE_MARGIN_MM, footer_top_corel_y)

                self._corel.save_document(new_document, save_path, pa.get_target_corel_version())
                print(f"Catálogo salvo em: {save_path}")
            finally:
                master_document.Close()

        def on_success(_result):
            self.log_panel.hide_after()
            gui_theme.show_message(self, "Catálogo criado", f"Novo catálogo salvo em:\n{save_path}")

        def on_error(ex):
            gui_theme.show_message(self, "Erro ao gerar", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    # -- tabela --------------------------------------------------------------

    def _apply_full_measure(self):
        """Medida completa: largura E altura informadas -> todas as figuras exatamente nessa medida (sem
        proporção). Só uma informada -> esse lado vira o valor e o outro acompanha a proporção de CADA figura."""
        if not self._rows:
            gui_theme.show_message(self, "Nada pra alterar", "Escolha um catálogo primeiro.")
            return

        def read_mm(entry):
            raw = entry.get().strip().replace(",", ".")
            if not raw:
                return None
            value = float(raw)
            if not math.isfinite(value) or value <= 0:
                raise ValueError
            return value

        try:
            width_mm = read_mm(self.full_width_entry)
            height_mm = read_mm(self.full_height_entry)
        except ValueError:
            gui_theme.show_message(self, "Valor inválido", "Informe números maiores que zero (em mm).")
            return
        if width_mm is None and height_mm is None:
            gui_theme.show_message(self, "Falta a medida", "Informe a largura, a altura, ou as duas.")
            return

        for row in self._rows:
            largura, altura = row["largura_mm"], row["altura_mm"]
            if width_mm is not None and height_mm is not None:
                row["largura_mm"], row["altura_mm"] = width_mm, height_mm
            elif width_mm is not None:
                row["largura_mm"] = width_mm
                row["altura_mm"] = altura * (width_mm / largura if largura else 1.0)
            else:
                row["altura_mm"] = height_mm
                row["largura_mm"] = largura * (height_mm / altura if altura else 1.0)
        self._refresh_table()

    def _refresh_table(self):
        for child in self.table_frame.winfo_children():
            child.destroy()

        if not self._rows:
            ctk.CTkLabel(
                self.table_frame, text="Escolha um catálogo pra ver as medidas.", text_color="gray60",
            ).grid(row=0, column=0, sticky="w")
            return

        header = ctk.CTkFrame(self.table_frame, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ctk.CTkLabel(header, text="REF", font=ctk.CTkFont(size=12, weight="bold"), width=100).pack(side="left")
        ctk.CTkLabel(header, text="Largura (mm)", font=ctk.CTkFont(size=12, weight="bold"), width=120).pack(
            side="left")
        ctk.CTkLabel(header, text="Altura (mm)", font=ctk.CTkFont(size=12, weight="bold"), width=120).pack(
            side="left")

        for row_index, row in enumerate(self._rows, start=1):
            row_frame = ctk.CTkFrame(self.table_frame, fg_color=("gray95", "gray17"), corner_radius=6)
            row_frame.grid(row=row_index, column=0, sticky="ew", pady=1)
            ctk.CTkLabel(row_frame, text=f"REF {row['ref_number']}", width=100).pack(side="left", padx=(6, 0))
            ctk.CTkLabel(row_frame, text=f"{row['largura_mm']:g}", width=120).pack(side="left")
            ctk.CTkLabel(row_frame, text=f"{row['altura_mm']:g}", width=120).pack(side="left")


if __name__ == "__main__":
    root = ctk.CTk()
    root.title("Baby Luz — Gerador de Catálogos")
    root.geometry("900x720")
    root.minsize(760, 560)

    class _StandaloneApp:
        def show_page(self, _key):
            root.destroy()

    CatalogGeneratorPage(root, _StandaloneApp()).pack(fill="both", expand=True)
    root.mainloop()
