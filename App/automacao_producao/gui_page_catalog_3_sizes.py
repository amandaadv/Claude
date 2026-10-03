"""Gerar Catálogo de 3 Medidas: reads a master catalog's REFs the same way
Gerador de Catálogos does, then splits them into up to 3 fixed output sizes
(altura x largura) instead of one value shared/scaled across every REF --
e.g. a P/M/G-style catalog, where every REF typed into a group prints at
that group's exact size regardless of its own native proportions. Figures
are placed exactly as they sit in the master file (landscape/"deitada"),
no rotation -- an earlier version rotated them "em pé" (portrait), but
that was dropped per explicit correction; this only changes each figure's
size, never its orientation.

As soon as a catalog is picked, the 3 REFs fields are auto-filled by
cycling every REF found, in order, across the 3 Medida groups one at a
time (1st REF -> Medida 1, 2nd -> Medida 2, 3rd -> Medida 3, 4th -> Medida
1 again, and so on) -- this is the shop's own standard pattern for a
3-size catalog (explicitly confirmed: she typed exactly this by hand
before asking for it to be automatic), so typing it out REF by REF for a
198-REF catalog is no longer needed; Altura/Largura per group are still
typed by hand, since those are a real per-catalog business decision.

Reuses gerador_catalogos's grid-layout math (_compute_grid_layout) and
its constants directly instead of duplicating that already-tested code.
"""
import os
import re
import tempfile
import time
import uuid

import customtkinter as ctk

import coreldraw_service
import file_picker
import gerador_catalogos
import gui_theme
import gui_worker
import master_artwork
import pa
import paths


def _orient_to_group_size(native_width_mm, native_height_mm, group_altura_mm, group_largura_mm):
    """Assigns the Medida group's two typed numbers to width/height by
    matching the LONGER one to whichever side is natively longer for
    THIS specific REF -- same idea as production_generator.py's
    _orient_to_native_shape. Needed because a Medida's altura/largura
    (e.g. 488x105mm) doesn't say which axis a given figure should use
    them on: blindly mapping largura->width and altura->height squashed
    a naturally wide/short garland strip into a tall/narrow box,
    stretching it into an unrecognizable vertical smear (confirmed live,
    screenshot). This keeps every figure in its OWN original orientation
    (a figure that's wide in the master file stays wide here) while
    still landing on the two measurements typed for its group."""
    target_long_mm = max(group_altura_mm, group_largura_mm)
    target_short_mm = min(group_altura_mm, group_largura_mm)
    if native_width_mm >= native_height_mm:
        return target_long_mm, target_short_mm
    return target_short_mm, target_long_mm


def _parse_ref_codes(text: str) -> list[str]:
    """Splits a typed list like "001, 002, 2212/1" (semicolons, spaces and
    newlines also accepted as separators between codes) into normalized ref
    codes -- "001" and "1" both become "1", matching the un-padded keys
    build_ref_index/_import_curve_captioned_refs produce. Comma is the
    separator BETWEEN codes here, not "/" -- unlike Montar Pedido's REF
    list, "/" can be part of a single code's own identity ("REF.2212/1" and
    "REF.2212/2" caption two different variants of the same base design,
    see REF_CAPTION_PATTERN), so treating it as a separator would slice
    "2212/1" into two unrelated codes "2212" and "1"."""
    raw = text.replace(";", ",").replace("\n", ",")
    codes = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        match = re.match(r"0*(\d+)(?:\s*/\s*0*(\d+))?$", token)
        if not match:
            continue
        base = str(int(match.group(1)))
        codes.append(f"{base}/{int(match.group(2))}" if match.group(2) else base)
    return codes


def _ref_sort_key(ref_code: str) -> tuple[int, int]:
    """Sorts "2212" before "2212/1" before "2212/2" before "2213" -- a plain
    int(ref_code) crashes the moment any ref carries a "/N" variant suffix."""
    base, _sep, variant = ref_code.partition("/")
    return int(base), int(variant) if variant else 0


class Catalog3SizesPage(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app

        self._rows_by_ref: dict[str, dict] = {}
        self._master_path: str | None = None
        self._corel = coreldraw_service.CorelDrawService()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(24, 8))
        gui_theme.back_button(header, self.app).pack(anchor="w", pady=(0, 10))
        gui_theme.section_title(header, "Gerar Catálogo de 3 Medidas").pack(anchor="w")
        ctk.CTkLabel(
            header,
            text="Abre um catálogo master e gera uma versão nova separando as figuras em até 3 "
                 "grupos de medida -- cada REF entra no tamanho do grupo em que ela foi colocada. "
                 "Cada medida pode ser \"exata\" (você digita altura E largura, do jeito exato que "
                 "digitar) ou \"proporcional\" (você digita só um número, que vira o lado maior de "
                 "cada figura -- o outro lado é ajustado sozinho, mantendo a proporção original "
                 "dela). As REFs de cada grupo já vêm preenchidas sozinhas (1ª REF na Medida 1, 2ª "
                 "na Medida 2, 3ª na Medida 3, 4ª na Medida 1 de novo, e assim por diante) -- só "
                 "ajuste se quiser. As figuras saem deitadas, do mesmo jeito que estão no arquivo "
                 "original.",
            font=ctk.CTkFont(size=12), text_color="gray60", wraplength=860, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        pick_row = ctk.CTkFrame(self, fg_color="transparent")
        pick_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            pick_row, text="Escolher catálogo", width=200, height=36, command=self._pick_catalog,
        ).pack(side="left")
        self.status_label = ctk.CTkLabel(
            pick_row, text="Nenhum catálogo aberto ainda.", font=ctk.CTkFont(size=12), text_color="gray60")
        self.status_label.pack(side="left", padx=(16, 0))

        body = ctk.CTkScrollableFrame(self, fg_color="transparent", **gui_theme.SCROLLBAR_KWARGS)
        body.grid(row=2, column=0, sticky="nsew", padx=28, pady=(0, 8))
        body.grid_columnconfigure(0, weight=1)

        # Fixed height and its OWN internal scroll (not the page's) -- a
        # catalog with a couple hundred REFs listed inline as a normal
        # wrapping label pushed the 3 Medida groups down below the
        # visible window, forcing a scroll just to see Medida 1's fields.
        self.refs_box = ctk.CTkTextbox(body, height=64, font=ctk.CTkFont(size=12), wrap="word")
        self.refs_box.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.refs_box.insert("1.0", "Escolha um catálogo pra ver as REFs disponíveis.")
        self.refs_box.configure(state="disabled")

        self.group_widgets = []
        for i in range(3):
            # Everything for one Medida on a SINGLE row (not a title line
            # plus two stacked rows) -- with 3 of these plus the header,
            # ref list and page-size box, the taller stacked version
            # pushed Medida 1 off the top of the window on anything but a
            # tall screen, forcing a scroll just to see it.
            group_frame = ctk.CTkFrame(body, fg_color=("gray92", "gray17"), corner_radius=8)
            group_frame.grid(row=i + 1, column=0, sticky="ew", pady=(0, 6))
            group_frame.grid_columnconfigure(4, weight=2)

            ctk.CTkLabel(
                group_frame, text=f"Medida {i + 1}", font=ctk.CTkFont(size=13, weight="bold"), width=70,
            ).grid(row=0, column=0, padx=(12, 8), pady=10, sticky="w")

            mode_var = ctk.StringVar(value="Medida exata")
            size_fields = ctk.CTkFrame(group_frame, fg_color="transparent")
            size_fields.grid(row=0, column=2, padx=(0, 12), sticky="w")

            # Both sets of size inputs are built up front (never rebuilt on
            # toggle) -- only whichever one matches the current mode is
            # actually gridded into size_fields; the other stays gridded
            # nowhere (created but not shown) so switching modes back and
            # forth never loses whatever was already typed in either one.
            exact_frame = ctk.CTkFrame(size_fields, fg_color="transparent")
            ctk.CTkLabel(exact_frame, text="Altura (mm):", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
            altura_entry = ctk.CTkEntry(exact_frame, width=65)
            altura_entry.pack(side="left", padx=(0, 12))
            ctk.CTkLabel(exact_frame, text="Largura (mm):", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 4))
            largura_entry = ctk.CTkEntry(exact_frame, width=65)
            largura_entry.pack(side="left")

            proportional_frame = ctk.CTkFrame(size_fields, fg_color="transparent")
            ctk.CTkLabel(proportional_frame, text="Medida (mm):", font=ctk.CTkFont(size=12)).pack(
                side="left", padx=(0, 4))
            proportional_entry = ctk.CTkEntry(proportional_frame, width=65)
            proportional_entry.pack(side="left")

            def on_mode_change(_choice=None, exact_frame=exact_frame, proportional_frame=proportional_frame):
                if mode_var.get() == "Proporcional":
                    exact_frame.pack_forget()
                    proportional_frame.pack(side="left")
                else:
                    proportional_frame.pack_forget()
                    exact_frame.pack(side="left")

            mode_toggle = ctk.CTkSegmentedButton(
                group_frame, values=["Medida exata", "Proporcional"], variable=mode_var,
                width=190, height=28, font=ctk.CTkFont(size=11), command=on_mode_change,
            )
            mode_toggle.grid(row=0, column=1, padx=(0, 12), sticky="w")
            exact_frame.pack(side="left")  # starting mode is "Medida exata"

            ctk.CTkLabel(group_frame, text="REFs:", font=ctk.CTkFont(size=12)).grid(
                row=0, column=3, padx=(0, 4), sticky="e")
            refs_entry = ctk.CTkEntry(group_frame, placeholder_text="001, 002, 2212/1")
            refs_entry.grid(row=0, column=4, padx=(0, 12), pady=10, sticky="ew")

            self.group_widgets.append({
                "mode": mode_var, "altura": altura_entry, "largura": largura_entry,
                "proportional": proportional_entry, "refs": refs_entry,
            })

        page_size_frame = ctk.CTkFrame(self, fg_color=("gray92", "gray17"), corner_radius=10)
        page_size_frame.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 8))
        ctk.CTkLabel(
            page_size_frame, text="Tamanho da folha do catálogo novo",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(anchor="w", padx=16, pady=(12, 4))
        size_inner = ctk.CTkFrame(page_size_frame, fg_color="transparent")
        size_inner.pack(anchor="w", padx=16, pady=(0, 14))
        ctk.CTkLabel(size_inner, text="Largura (mm):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.page_width_entry = ctk.CTkEntry(size_inner, width=90)
        self.page_width_entry.insert(0, "270")
        self.page_width_entry.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(size_inner, text="Altura (mm):", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 8))
        self.page_height_entry = ctk.CTkEntry(size_inner, width=90)
        self.page_height_entry.insert(0, "2000")
        self.page_height_entry.pack(side="left")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 8))
        gui_theme.primary_button(
            footer, text="Gerar Catálogo", width=200, height=36, command=self._create_catalog,
        ).pack(side="left")

        self.log_panel = gui_worker.LogPanel(self)
        self.log_panel.grid(row=5, column=0, sticky="sew", padx=28, pady=(0, 20))

    def on_show(self):
        pass

    def _set_refs_text(self, text: str) -> None:
        self.refs_box.configure(state="normal")
        self.refs_box.delete("1.0", "end")
        self.refs_box.insert("1.0", text)
        self.refs_box.configure(state="disabled")

    # -- escolher catálogo -------------------------------------------------

    def _pick_catalog(self):
        path = file_picker.pick_master_file()
        if not path:
            return

        self._rows_by_ref = {}
        self._master_path = None
        self._set_refs_text("Abrindo catálogo...")
        self.status_label.configure(text="Abrindo catálogo...")
        self.log_panel.show("Abrindo catálogo no CorelDRAW...\n\n")

        def task():
            # Unique filename per pick -- a fixed name reused across picks
            # risked one pick's temp file being read while a DIFFERENT
            # pick's data was still showing (same reasoning as
            # gerador_catalogos.py's own _pick_catalog).
            temp_path = os.path.join(tempfile.gettempdir(), f"catalog_3_sizes_master_{uuid.uuid4().hex}.cdr")
            normalized_path = master_artwork.ensure_valid_cdr_file(path, temp_path)
            self._corel.connect()
            document = self._corel.open_document(normalized_path)
            self._corel.set_units(document)
            try:
                ref_index = master_artwork.build_ref_index(document)
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

                # Native width/height read here (same call gerador_catalogos.py
                # uses) purely to know each REF's own orientation -- whichever
                # side is naturally longer -- NOT to use as its output size
                # (that always comes from whichever Medida group it's typed
                # into below). See _orient_to_group_size in _create_catalog.
                rows_by_ref = {}
                for ref_number, entry in ref_index.items():
                    native_width_mm, native_height_mm = master_artwork.get_shape_bbox_size(
                        document, entry["page_index"], entry["shape_path"])
                    rows_by_ref[ref_number] = {
                        "ref_number": ref_number,
                        "shape_path": entry["shape_path"],
                        "caption_shape_path": entry["caption_shape_path"],
                        "page_index": entry["page_index"],
                        "native_width_mm": native_width_mm,
                        "native_height_mm": native_height_mm,
                    }
                print(f"{len(rows_by_ref)} REF(s) encontrada(s).")
            finally:
                document.Close()
            return normalized_path, rows_by_ref

        def on_success(result):
            normalized_path, rows_by_ref = result
            self._master_path = normalized_path
            self._rows_by_ref = rows_by_ref
            self.status_label.configure(text=f"{len(rows_by_ref)} REF(s) carregada(s).")
            ordered_refs = sorted(rows_by_ref.keys(), key=_ref_sort_key)
            self._set_refs_text(f"{len(ordered_refs)} REF(s) nesse catálogo: " + ", ".join(ordered_refs))

            # Round-robin, cycling through the 3 groups one REF at a time
            # in catalog order: 1st->Medida 1, 2nd->Medida 2, 3rd->Medida
            # 3, 4th->Medida 1 again... -- the shop's own standard pattern
            # for a 3-size catalog, typed out by hand before, now filled
            # in automatically.
            for group_index, widgets in enumerate(self.group_widgets):
                group_refs = ordered_refs[group_index::3]
                widgets["refs"].delete(0, "end")
                # "," (não "/") -- uma REF pode ela mesma conter "/" (ver
                # _parse_ref_codes), então juntar com "/" tornaria
                # "2212/1" e "2213/2" indistinguíveis de "2212", "1",
                # "2213", "2" na hora de reler o campo.
                widgets["refs"].insert(0, ", ".join(group_refs))

            self.log_panel.hide_after()

        def on_error(ex):
            self.status_label.configure(text="Falha ao abrir o catálogo.")
            gui_theme.show_message(self, "Não deu pra abrir", str(ex))

        gui_worker.run_task(self, task, on_success=on_success, on_error=on_error, on_log=self.log_panel.append)

    # -- gerar catálogo --------------------------------------------------------

    def _create_catalog(self):
        if not self._rows_by_ref or self._master_path is None:
            gui_theme.show_message(self, "Nada pra gerar", "Escolha um catálogo primeiro.")
            return

        groups = []
        for i, widgets in enumerate(self.group_widgets, start=1):
            refs_text = widgets["refs"].get().strip()
            if not refs_text:
                continue
            is_proportional = widgets["mode"].get() == "Proporcional"
            try:
                if is_proportional:
                    target_long_mm = float(widgets["proportional"].get().strip().replace(",", "."))
                    if target_long_mm <= 0:
                        raise ValueError
                    spec = ("proportional", target_long_mm)
                else:
                    altura_mm = float(widgets["altura"].get().strip().replace(",", "."))
                    largura_mm = float(widgets["largura"].get().strip().replace(",", "."))
                    if altura_mm <= 0 or largura_mm <= 0:
                        raise ValueError
                    spec = ("exact", altura_mm, largura_mm)
            except ValueError:
                if is_proportional:
                    gui_theme.show_message(
                        self, "Medida inválida", f"Medida {i}: preencha a medida com um número maior que zero (em mm).")
                else:
                    gui_theme.show_message(
                        self, "Medida inválida",
                        f"Medida {i}: preencha altura e largura com números maiores que zero (em mm).")
                return
            ref_codes = _parse_ref_codes(refs_text)
            if not ref_codes:
                gui_theme.show_message(self, "REFs inválidas", f"Medida {i}: não consegui ler nenhuma REF.")
                return
            groups.append({"index": i, "spec": spec, "refs": ref_codes})

        if not groups:
            gui_theme.show_message(
                self, "Nada pra gerar", "Preencha pelo menos uma das 3 medidas com altura, largura e REFs.")
            return

        ref_to_spec: dict[str, tuple] = {}
        duplicate_refs = []
        for group in groups:
            for ref_code in group["refs"]:
                if ref_code in ref_to_spec:
                    duplicate_refs.append(ref_code)
                    continue
                ref_to_spec[ref_code] = group["spec"]
        if duplicate_refs:
            gui_theme.show_message(
                self, "REF repetida",
                "Essas REFs estão em mais de uma medida -- só a primeira medida em que aparecem vale: "
                + ", ".join(sorted(set(duplicate_refs), key=_ref_sort_key)))

        rows = []
        missing_refs = []
        for ref_code, spec in ref_to_spec.items():
            base_row = self._rows_by_ref.get(ref_code)
            if base_row is None:
                missing_refs.append(ref_code)
                continue
            row = dict(base_row)
            if spec[0] == "exact":
                _kind, group_altura_mm, group_largura_mm = spec
                # caption_altura_mm/caption_largura_mm: the group's numbers
                # exactly as typed, always shown on the printed "MED AxB"
                # caption as-is (every piece in the group prints the same
                # pair, regardless of its own orientation). largura_mm/
                # altura_mm (used for actual placement/resize/layout below)
                # are those same two numbers instead matched to THIS
                # figure's own native orientation -- see _orient_to_group_size.
                row["caption_altura_mm"] = group_altura_mm
                row["caption_largura_mm"] = group_largura_mm
                row["largura_mm"], row["altura_mm"] = _orient_to_group_size(
                    row["native_width_mm"], row["native_height_mm"], group_altura_mm, group_largura_mm)
            else:
                _kind, target_long_mm = spec
                # Proporcional: the group's single typed number becomes THIS
                # figure's own longer side, the other side follows its own
                # native aspect ratio -- pa._scale_to_long_side already does
                # exactly this (same rule Gerador de Catálogos' "Alterar em
                # lote" and Gerar Produção's size-override use elsewhere).
                # Each piece's own resulting numbers go on ITS OWN caption,
                # since there's no single shared pair to print here (they
                # genuinely differ piece to piece, unlike "exact" above).
                row["largura_mm"], row["altura_mm"] = pa._scale_to_long_side(
                    row["native_width_mm"], row["native_height_mm"], target_long_mm)
                row["caption_altura_mm"] = row["altura_mm"]
                row["caption_largura_mm"] = row["largura_mm"]
            rows.append(row)

        if missing_refs:
            gui_theme.show_message(
                self, "REF não encontrada",
                "Essas REFs não existem nesse catálogo e ficaram de fora: "
                + ", ".join(sorted(missing_refs, key=_ref_sort_key)))

        if not rows:
            gui_theme.show_message(
                self, "Nada pra gerar", "Nenhuma REF válida sobrou depois de conferir as medidas.")
            return

        rows.sort(key=lambda r: _ref_sort_key(r["ref_number"]))

        try:
            page_width_mm = float(self.page_width_entry.get().strip().replace(",", "."))
            page_height_mm = float(self.page_height_entry.get().strip().replace(",", "."))
            if page_width_mm <= 0 or page_height_mm <= 0:
                raise ValueError
        except ValueError:
            gui_theme.show_message(
                self, "Tamanho de folha inválido",
                "Largura e altura da folha precisam ser números maiores que zero (em mm).")
            return

        usable_width_mm = page_width_mm - 2 * gerador_catalogos.PAGE_MARGIN_MM
        widest_item = max(rows, key=lambda item: item["largura_mm"])
        if widest_item["largura_mm"] > usable_width_mm + gerador_catalogos.OVERFLOW_TOLERANCE_MM:
            page_width_mm = widest_item["largura_mm"] + 2 * gerador_catalogos.PAGE_MARGIN_MM
            usable_width_mm = page_width_mm - 2 * gerador_catalogos.PAGE_MARGIN_MM
            self.page_width_entry.delete(0, "end")
            self.page_width_entry.insert(0, f"{page_width_mm:g}")

        try:
            layout_pages = gerador_catalogos._compute_grid_layout(rows, page_width_mm, page_height_mm)
        except ValueError as ex:
            gui_theme.show_message(self, "Não deu pra organizar a folha", str(ex))
            return

        save_path = file_picker.pick_save_path("catalogo_3_medidas.cdr")
        if not save_path:
            return

        self.log_panel.show("Gerando o catálogo novo...\n\n")
        master_path = self._master_path

        def task():
            self._corel.connect()
            master_document = self._corel.open_document(master_path)
            self._corel.set_units(master_document)
            try:
                new_document = self._corel.create_production_document()
                self._corel.set_units(new_document)
                # Deliberately NOT closed afterward (same as gerador_catalogos.py) --
                # left open in CorelDRAW to look at/adjust right away.
                for output_page_index, page_items in enumerate(layout_pages):
                    page = self._corel.get_active_page(new_document) if output_page_index == 0 \
                        else self._corel.add_page(new_document)
                    self._corel.set_page_size(page, page_width_mm, page_height_mm)
                    layer = self._corel.create_layer(page, "CATALOGO")

                    for item in page_items:
                        last_error = None
                        shape = None
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
                                if shape is not None:
                                    try:
                                        shape.Delete()
                                    except Exception:
                                        pass
                                    shape = None
                                if attempt < len(RETRY_WAITS_S):
                                    time.sleep(RETRY_WAITS_S[attempt])
                        if last_error is not None:
                            raise RuntimeError(
                                f"REF {item['ref_number']}: falhou ao colar a arte após tentar de novo várias "
                                f"vezes ({last_error}).") from last_error

                        shape_corel_y = page_height_mm - item["y_mm"]
                        self._corel.position_artwork(shape, item["x_mm"], shape_corel_y)

                        caption_text = (
                            f"REF {item['ref_number']} MED "
                            f"{round(item['caption_altura_mm'])}X{round(item['caption_largura_mm'])}MM")
                        caption_bottom_from_top = (
                            item["y_mm"] + item["altura_mm"] + gerador_catalogos.CAPTION_HEIGHT_MM)
                        caption_corel_y = page_height_mm - caption_bottom_from_top
                        caption_shape = self._corel.create_text(
                            layer, item["x_mm"], caption_corel_y, caption_text,
                            size_pt=gerador_catalogos.CAPTION_FONT_SIZE_PT, bold=True)

                        caption_width_mm, _caption_height_mm = self._corel.get_shape_size(caption_shape)
                        centered_x_mm = item["x_mm"] + (item["largura_mm"] - caption_width_mm) / 2
                        _current_x_mm, current_top_y_mm = self._corel.get_shape_position(caption_shape)
                        self._corel.position_artwork(caption_shape, centered_x_mm, current_top_y_mm)

                        print(f"REF {item['ref_number']}: {item['largura_mm']:g}mm x {item['altura_mm']:g}mm")

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
