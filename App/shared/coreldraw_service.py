"""Drives CorelDRAW via COM automation (pywin32), mirroring CorelDrawService.cs
method-for-method. Uses win32com.client.gencache so we get the real enum values
(cdrMillimeter, cdrAutoSense, cdrTopLeft, ...) from CorelDRAW's own type library
instead of guessing numbers.
"""
import subprocess
import time
import winreg

import win32com.client

LAYER_NAME = "PRODUÇÃO"


def get_installed_versions() -> list[int]:
    """Public entry point for _detect_installed_versions -- other modules
    (e.g. the version converter tool) need the list too, without reaching
    into a private helper."""
    return _detect_installed_versions()


def _detect_installed_versions():
    """CorelDRAW registers one COM ProgID per installed version
    (CorelDRAW.Application.<N> -- 23 for 2021, 24 for 2022, 27 for 2025,
    etc). There's no version-less ProgID, so a fixed version number only
    works on the one machine that happens to have that exact release --
    on any other computer (a client's machine with an older or newer
    CorelDRAW) it fails outright with "class not registered". Checking
    the registry for what's actually installed makes this work on
    whatever machine it runs on."""
    versions = []
    for version in range(15, 36):
        try:
            winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f"CorelDRAW.Application.{version}").Close()
            versions.append(version)
        except FileNotFoundError:
            pass
    return sorted(versions, reverse=True)


def _not_responding_corel_pids() -> list[int]:
    """PIDs of CorelDRW.exe windows Windows currently flags "Não respondendo".
    GetActiveObject can hand back exactly that frozen instance, and the very
    next COM call (app.Visible = True) then blocks forever with no error --
    an import/production would sit there silently until the app got closed.
    Failing up front with a clear message is the only useful behavior."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq CorelDRW.exe", "/FI", "STATUS eq NOT RESPONDING", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:
        return []  # can't check -- don't block the real work over a failed check
    pids = []
    for line in result.stdout.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].strip('"').lower() == "coreldrw.exe" and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


class CorelDrawService:
    def __init__(self):
        self._application = None

    def connect(self):
        frozen = _not_responding_corel_pids()
        if frozen:
            raise RuntimeError(
                "O CorelDRAW está TRAVADO (janela \"Não respondendo\", PID "
                f"{', '.join(map(str, frozen))}). O programa não consegue usar ele assim -- "
                "salve o que puder, feche esse CorelDRAW pelo Gerenciador de Tarefas e tente de novo.")

        versions = _detect_installed_versions()
        if not versions:
            raise RuntimeError(
                "Nenhuma instalação do CorelDRAW foi encontrada nesse computador.")

        last_error = None
        for version in versions:
            prog_id = f"CorelDRAW.Application.{version}"
            try:
                try:
                    app = win32com.client.GetActiveObject(prog_id)
                    app = win32com.client.gencache.EnsureDispatch(app)
                except Exception:
                    app = win32com.client.gencache.EnsureDispatch(prog_id)
                app.Visible = True
                self._application = app
                return
            except Exception as ex:
                last_error = ex

        raise RuntimeError(
            f"Falha ao conectar ao CorelDRAW (versões instaladas: {versions}). Último erro: {last_error}")

    def create_production_document(self):
        if self._application is None:
            raise RuntimeError("Chame connect() antes de create_production_document().")
        return self._application.CreateDocument()

    def set_units(self, document):
        document.Unit = win32com.client.constants.cdrMillimeter

    def get_active_page(self, document):
        return document.ActivePage

    def add_page(self, document):
        return document.AddPages(1)

    def set_page_size(self, page, width_mm, height_mm):
        page.SetSize(width_mm, height_mm)

    def create_layer(self, page, name):
        return page.CreateLayer(name)

    def open_document(self, file_path):
        if self._application is None:
            raise RuntimeError("Chame connect() antes de open_document().")
        return self._application.OpenDocument(file_path)

    def paste_artwork(self, layer):
        """Pastes whatever was last Copy()'d onto the clipboard (see
        master_artwork.copy_artwork_shape) into this layer -- the real vector
        artwork from the designer's master file, not a raster import.

        copy_artwork_shape sometimes copies several loose pieces at once
        (a "kit" product made of multiple ungrouped shapes -- see
        master_artwork._cluster_shapes), so Paste() can come back with a
        ShapeRange instead of a single Shape. Every caller downstream
        (positioning/sizing the pasted product on the production sheet)
        already assumes one Shape, exactly like a normal single-piece
        paste -- Group()-ing a multi-piece paste keeps that assumption true
        instead of pushing the distinction onto every caller."""
        layer.Activate()
        shape = layer.Paste()
        if shape is None:
            raise RuntimeError("PASTE_FAILED: nada para colar (Copy() não foi chamado antes?).")
        try:
            shape.Type  # a real Shape has this; a ShapeRange doesn't
        except Exception:
            shape = shape.Group()
        return shape

    def import_artwork(self, layer, file_path):
        layer.Import(file_path, win32com.client.constants.cdrAutoSense, None)
        shape = self._application.ActiveShape
        if shape is None:
            raise RuntimeError(f"IMPORT_FAILED: falha ao importar a arte de '{file_path}'.")
        return shape

    def resize_artwork(self, shape, width_mm, height_mm):
        shape.SetSize(width_mm, height_mm)

    def copy_shapes(self, document, shapes, max_attempts=4) -> None:
        """Copies several shapes to the clipboard as ONE unit -- their
        positions relative to each other are preserved when later pasted
        (confirmed live: a 16-shape catalog header pasted back with its
        combined bounding box matching the original to sub-mm precision).
        Used by gerador_catalogos.py to lift a whole header/footer cluster
        out of the master file without computing each shape's offset by
        hand.

        Goes through ClearSelection()/AddToSelection()/Selection().Copy(),
        NOT CreateShapeRangeFromArray(shapes).Copy() (what this used to do)
        -- the array-based call was seen to fail on a footer cluster
        (photos of the applied product, heavier than the header's logo/
        text) deep into a long catalog-generation run, consistently, even
        freshly re-resolving the Shape objects and retrying right here.
        master_artwork.copy_artwork_shape's Selection-based Copy() never
        failed once across the exact same run, hundreds of calls in, so
        this mirrors that path instead of trusting CreateShapeRangeFromArray
        to hold up under the same conditions.

        Retries on failure too, same reasoning as export_current_page_to_png
        and master_artwork.copy_artwork_shape: worth ruling out ordinary
        Windows clipboard contention from repeated Copy() calls before
        concluding it's something structural."""
        last_error = None
        for attempt in range(max_attempts):
            try:
                document.ClearSelection()
                for shape in shapes:
                    shape.AddToSelection()
                document.Selection().Copy()
                return
            except Exception as ex:
                last_error = ex
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"COPY_FAILED após {max_attempts} tentativas: {last_error}")

    def paste_shapes(self, document, layer) -> list:
        """Pastes whatever was last copied (possibly several shapes at
        once -- see copy_shapes) onto `layer`, and returns every newly
        added Shape. layer.Paste()'s own return value only ever gives back
        ONE shape even when the clipboard holds several (confirmed live).

        An earlier version tracked layer.Shapes.Count before/after Paste()
        to recover the rest, indexing Item(before_count+1..after_count) --
        that undercounting theory turned out to be wrong (the counts were
        always right), but a LATER paste (e.g. the footer, after several
        unrelated shapes were pasted in between for products) could still
        end up grabbing the WRONG shapes at those index positions: some of
        an EARLIER paste's own shapes (confirmed live: several of a
        16-shape header's own letters) apparently shift to different index
        positions once more shapes are added to the same layer afterward,
        so a later before/after-count read can silently re-capture them
        instead of the shapes actually just pasted -- corrupting both (the
        earlier paste's shapes get dragged into the later one's transform).
        document.SelectionRange -- what Paste() leaves selected -- doesn't
        have this problem (confirmed live against the same real file: the
        same scenario that scattered header letters into the footer's
        transform, using SelectionRange instead, placed all of them
        correctly)."""
        layer.Activate()
        layer.Paste()
        selection = document.SelectionRange
        return [selection.Shapes.Item(i) for i in range(1, selection.Shapes.Count + 1)]

    def group_shapes(self, document, shapes: list):
        """Groups several shapes into one -- selects each via
        AddToSelection (same reliable selection pattern copy_shapes
        already uses, rather than CreateShapeRangeFromArray, which this
        codebase already found unreliable for a similar bulk operation)
        then calls Selection().Group(). Used by pa.do_join_pages to
        collapse each joined page's hundreds of individually pasted
        shapes into ONE group -- CorelDRAW was seen live to struggle
        (slow generation, glitchy redraws while zooming) with thousands
        of loose top-level shapes sitting on one huge page."""
        document.ClearSelection()
        for shape in shapes:
            shape.AddToSelection()
        return document.Selection().Group()

    def ungroup_shape(self, shape) -> None:
        """Reverses group_shapes -- expands one group back into its loose
        member shapes IN PLACE (their positions don't change). Used by
        pa.do_join_pages/do_join_pages_from_files: grouping is only ever
        a means to move a whole page's worth of shapes in one COM call
        instead of hundreds, not something wanted in the final result --
        the operator needs every piece loose and individually editable
        in the joined production file, same as it was on its own
        original page."""
        shape.Ungroup()

    def shift_shapes(self, shapes: list, dx_mm: float, dy_mm: float = 0.0) -> None:
        """Moves every shape by a fixed offset from its OWN current
        position -- unlike position_artwork (which sets one absolute
        position), this keeps every shape's position relative to the
        others in the group exactly as-is, just slid sideways/up-down as
        one rigid block. Used by pa.do_join_pages to slide a whole
        just-pasted page's worth of shapes (copy_shapes/paste_shapes)
        into its own slot on the joined page, without needing to know or
        reconstruct each shape's individual absolute position first."""
        for shape in shapes:
            shape.SetPositionEx(win32com.client.constants.cdrTopLeft, shape.LeftX + dx_mm, shape.TopY + dy_mm)

    def fit_and_position_shapes(self, shapes, width_mm, height_mm, x_mm, y_mm) -> None:
        """Scales and moves a group of shapes together as ONE rigid unit
        to a target width/height and top-left corner (x_mm/y_mm, same
        bottom-up page coordinate + cdrTopLeft convention as
        position_artwork) -- their sizes/positions relative to each other
        are preserved. Used to fit a copied header/footer cluster to a new
        page's width.

        Transforms each shape individually (its own SetSize +
        SetPositionEx, scaled/offset from the cluster's own top-left
        corner) rather than building a ShapeRange and calling SetSize/
        SetPositionEx on the RANGE as one operation -- the range-level
        version is what exhibited the corruption above (some shapes,
        chosen inconsistently, silently kept their pre-transform size/
        position while contributing to the range's bounding box, or ended
        up transformed relative to a different anchor -- confirmed live
        the range-level call was the point at which good shapes went bad,
        not the copy/paste). Transforming shapes one at a time uses the
        exact same SetSize/SetPositionEx calls already proven reliable for
        every individual product figure and caption in this file."""
        lefts = [s.LeftX for s in shapes]
        rights = [s.LeftX + s.SizeWidth for s in shapes]
        tops = [s.TopY for s in shapes]
        orig_left = min(lefts)
        orig_top = max(tops)
        orig_width = max(rights) - orig_left
        scale = width_mm / orig_width
        for shape in shapes:
            rel_left_mm = shape.LeftX - orig_left
            rel_top_from_top_mm = orig_top - shape.TopY
            new_width_mm = shape.SizeWidth * scale
            new_height_mm = shape.SizeHeight * scale
            new_left_mm = x_mm + rel_left_mm * scale
            new_top_y_mm = y_mm - (rel_top_from_top_mm * scale)
            shape.SetSize(new_width_mm, new_height_mm)
            shape.SetPositionEx(win32com.client.constants.cdrTopLeft, new_left_mm, new_top_y_mm)

    def create_text(self, layer, x_mm, y_mm, text: str, size_pt: float = 8.0, bold: bool = False):
        """Creates a brand-new artistic text shape on `layer`, via
        Layer.CreateArtisticText (NOT Shapes.AddArtisticText -- that method
        doesn't exist on the Shapes collection; shape-creation methods live
        on Layer itself, confirmed live against a real CorelDRAW 2026
        install). x_mm/y_mm are in the document's page coordinate system, y
        measured bottom-up like every other position in this codebase (see
        production_generator's `corel_y = profile.height_mm - row.y_mm`
        conversion, which callers of this method must apply the same way)
        -- but unlike position_artwork's cdrTopLeft anchor, CreateArtisticText
        anchors the text's BOTTOM-left corner at (x_mm, y_mm), confirmed by
        reading back a created shape's TopY/SizeHeight live (TopY - SizeHeight
        landed within 0.03mm of the y_mm passed in). Callers must place the
        text's Y as where its BOTTOM edge should sit, not its top. The
        resulting shape is never centered under anything by this call --
        its width depends on the rendered text, so a caller wanting it
        centered under a figure must read it back (get_shape_size) and
        reposition (position_artwork) afterward.
        size_pt is the font size in points (CorelDRAW's Size parameter is
        always points, regardless of the document's ruler unit) -- passed
        explicitly rather than left at the method's own default (which
        produced an inconsistent ~6mm-tall caption using whatever font size
        was last active in the CorelDRAW session) so caption height is
        predictable regardless of the operator's last-used text settings.
        bold=True passes CreateArtisticText's Bold=-1 (VBA's True), matching
        its own tri-state convention (confirmed live: -1 creates bold text,
        no error)."""
        layer.Activate()
        return layer.CreateArtisticText(x_mm, y_mm, text, Size=size_pt, Bold=-1 if bold else 0)

    def get_shape_size(self, shape) -> tuple[float, float]:
        """The shape's current (native, pre-resize) size in mm -- used to
        scale it proportionally to a target size instead of stretching it to
        two independent width/height numbers (see
        production_generator._compute_proportional_size)."""
        return shape.SizeWidth, shape.SizeHeight

    def get_shape_position(self, shape) -> tuple[float, float]:
        """The shape's current (LeftX, TopY) in mm -- the read-side
        counterpart to position_artwork's cdrTopLeft write. Used to
        recenter a just-created caption under its figure once its actual
        rendered width is known (see gerador_catalogos.py)."""
        return shape.LeftX, shape.TopY

    def rotate_artwork(self, shape, angle_degrees):
        shape.Rotate(angle_degrees)

    def duplicate_artwork(self, shape):
        return shape.Duplicate(0, 0)

    def position_artwork(self, shape, x_mm, y_mm):
        shape.SetPositionEx(win32com.client.constants.cdrTopLeft, x_mm, y_mm)

    def get_page_count(self, document) -> int:
        return document.Pages.Count

    def get_shape_count_on_layer(self, layer) -> int:
        return layer.Shapes.Count

    def save_document(self, document, file_path, target_version: int | None = None):
        """Saves the document. When target_version is given (a CorelDRAW file
        version number, e.g. 22 for CorelDRAW 2021), saves down to that older
        format instead of this machine's own version -- otherwise the file
        can't be opened at all on a machine running an older CorelDRAW (it
        shows "you must update your program version"). Newer CorelDRAW can
        always read older files, so saving down is always safe; there's no
        reason to ever save at a version newer than the oldest CorelDRAW
        actually used to open these files."""
        if target_version is None:
            document.SaveAs(file_path, None)
            return

        options = self._application.CreateStructSaveAsOptions()
        options.Version = target_version
        options.Filter = win32com.client.constants.cdrCDR
        document.SaveAs(file_path, options)

    def export_current_page_to_png(self, document, output_path, resolution=300, max_attempts=4):
        """Exports the document's whole current page as a standalone PNG
        (transparent background). Meant to be called on a throwaway document
        holding nothing but one pasted-in shape (see export_shape_as_png) --
        exporting cdrCurrentPage on that is equivalent to a tight crop of just
        that shape, and far more reliable in practice than exporting
        cdrSelection directly against a big master document: that mode was
        seen to fail consistently with a bare COM E_FAIL (no useful message)
        even for shapes/files that opened and copy/pasted just fine."""
        last_error = None
        for attempt in range(max_attempts):
            try:
                export_filter = document.ExportBitmap(
                    output_path, win32com.client.constants.cdrPNG, win32com.client.constants.cdrCurrentPage,
                    4, 0, 0, resolution, resolution, 1, False, True, True, False, 0, None, None,
                )
                export_filter.Finish()
                return
            except Exception as ex:
                last_error = ex
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"EXPORT_FAILED após {max_attempts} tentativas: {last_error}")

    def export_shape_as_png(self, source_document, page_index, shape_path, output_path,
                             resolution=300, max_attempts=4):
        """Copies the shape(s) out of source_document into a fresh throwaway
        document and exports that whole (otherwise empty) document's page --
        see export_current_page_to_png for why this indirection instead of
        exporting the selection directly. shape_path is a comma-separated
        1-based index path (e.g. "8" or "8,3" for a shape nested inside a
        group), or several of those joined with ";" when the product is
        made of multiple loose pieces -- see master_artwork._flatten_shapes
        and master_artwork._cluster_shapes/iter_shape_paths.

        Verifies the pasted result's combined size roughly matches the
        shape(s)' own real size before exporting, retrying the whole
        copy+paste cycle if not -- Selection().Copy() succeeding (no
        exception) is not the same as Paste() actually landing THIS call's
        shape: a Copy() that silently loses to Windows clipboard contention
        (the same contention already documented and retried on the copy
        side elsewhere in this codebase) was seen live to leave the
        PREVIOUS call's shape sitting on the clipboard, which then pastes
        totally fine -- no error anywhere -- just as the wrong REF's
        artwork. A big batch import going one REF after another in a tight
        loop is exactly the pattern that triggers it."""
        source_document.Activate()
        source_document.ClearSelection()
        shapes = []
        for piece in str(shape_path).split(";"):
            indices = [int(p) for p in piece.split(",")]
            shape = source_document.Pages.Item(page_index).Shapes.Item(indices[0])
            for idx in indices[1:]:
                shape = shape.Shapes.Item(idx)
            shapes.append(shape)

        lefts = [s.LeftX for s in shapes]
        rights = [s.LeftX + s.SizeWidth for s in shapes]
        tops = [s.TopY for s in shapes]
        bottoms = [s.TopY - s.SizeHeight for s in shapes]
        expected_width = max(rights) - min(lefts)
        expected_height = max(tops) - min(bottoms)

        last_error = None

        # Legenda/peça de VÁRIAS partes soltas (caminho com ";"): Copy()+Paste() pode colar só UMA delas
        # (ver a explicação mais abaixo), e cada tentativa dessas custa segundos num arquivo pesado. Aqui a
        # exportação direta da seleção vai PRIMEIRO; se ela não sair com o tamanho esperado, cai no
        # caminho de sempre (copiar/colar) logo abaixo.
        if len(shapes) > 1:
            try:
                self._export_selection_directly(
                    source_document, shapes, output_path, resolution, expected_width, expected_height)
                return
            except Exception as ex:
                last_error = f"exportar a seleção direto falhou: {ex}"

        for attempt in range(max_attempts):
            matched = False
            source_document.ClearSelection()
            for shape in shapes:
                shape.AddToSelection()
            try:
                source_document.Selection().Copy()
            except Exception as ex:
                # The same transient coVGShape::Copy COM exception documented
                # on copy_artwork_shape's own retry -- here it was escaping
                # this function entirely on the FIRST attempt, before the
                # retry loop below (meant for exactly this) ever got a
                # chance to run again, silently dropping whatever piece hit
                # it (seen live: a catalog import that kept only its first
                # page's pieces and skipped the rest with no error at all).
                last_error = f"Copy() falhou: {ex}"
                time.sleep(0.5 * (attempt + 1))
                continue

            temp_document = self._application.CreateDocument()
            try:
                self.set_units(temp_document)
                layer = temp_document.ActivePage.ActiveLayer
                pasted = layer.Paste()
                try:
                    pasted_width, pasted_height = pasted.SizeWidth, pasted.SizeHeight
                except Exception:
                    pasted_width, pasted_height = pasted.Shapes.SizeWidth, pasted.Shapes.SizeHeight

                if (abs(pasted_width - expected_width) > max(expected_width, 1) * 0.15
                        or abs(pasted_height - expected_height) > max(expected_height, 1) * 0.15):
                    last_error = (f"esperava {expected_width:.1f}x{expected_height:.1f}mm, "
                                   f"colou {pasted_width:.1f}x{pasted_height:.1f}mm")
                else:
                    temp_document.Activate()
                    self.export_current_page_to_png(temp_document, output_path, resolution)
                    matched = True
            finally:
                try:
                    temp_document.Close()
                except Exception:
                    pass

            if matched:
                return
            time.sleep(0.5 * (attempt + 1))

        # Última tentativa: exporta a SELEÇÃO direto do documento de origem, sem passar pela área de
        # transferência. Necessário pra legenda feita de VÁRIAS letras em curva (ex.: "REF 1901" com cada
        # dígito uma curva solta): Copy()+Paste() cola só UMA das peças (visto ao vivo: sempre "2.0x3.0mm"
        # quando a legenda inteira mede ~17x3mm, em 5 tentativas seguidas) enquanto a exportação da
        # seleção sai completa. Confere o tamanho do PNG contra o esperado antes de aceitar.
        try:
            self._export_selection_directly(
                source_document, shapes, output_path, resolution, expected_width, expected_height)
            return
        except Exception as ex:
            last_error = f"{last_error}; exportar a seleção direto também falhou: {ex}"
        raise RuntimeError(f"EXPORT_SHAPE_FAILED após {max_attempts} tentativas: {last_error}")

    def _export_selection_directly(self, source_document, shapes, output_path, resolution,
                                    expected_width_mm, expected_height_mm):
        from PIL import Image
        # Esse ExportBitmap da seleção falha com um E_FAIL "cego" nas primeiras vezes e passa na 2ª/3ª
        # (medido ao vivo: cada tentativa leva ~0,1s) -- então tenta várias vezes RÁPIDO, reselecionando a
        # cada uma, em vez de cair direto no caminho lento de copiar/colar.
        last_error = None
        for attempt in range(8):
            try:
                source_document.Activate()
                source_document.ClearSelection()
                for shape in shapes:
                    shape.AddToSelection()
                export_filter = source_document.ExportBitmap(
                    output_path, win32com.client.constants.cdrPNG, win32com.client.constants.cdrSelection,
                    4, 0, 0, resolution, resolution, 1, False, True, True, False, 0, None, None,
                )
                export_filter.Finish()
                last_error = None
                break
            except Exception as ex:
                last_error = ex
                time.sleep(0.3 * (attempt + 1))
        try:
            source_document.ClearSelection()
        except Exception:
            pass
        if last_error is not None:
            raise RuntimeError(f"ExportBitmap da seleção falhou em 8 tentativas: {last_error}")
        with Image.open(output_path) as image:
            width_mm = image.size[0] / resolution * 25.4
            height_mm = image.size[1] / resolution * 25.4
        if (abs(width_mm - expected_width_mm) > max(expected_width_mm, 1) * 0.15
                or abs(height_mm - expected_height_mm) > max(expected_height_mm, 1) * 0.15):
            raise RuntimeError(f"PNG saiu {width_mm:.1f}x{height_mm:.1f}mm, esperava "
                               f"{expected_width_mm:.1f}x{expected_height_mm:.1f}mm")

    def dispose(self):
        self._application = None
