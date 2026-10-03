"""Lays out a sequence of figures directly inside a CorelDRAW document --
reuses automacao_producao's own production layout engine (production.py /
production_generator.py), the same one that drives real production runs,
instead of building flattened PNG sheets: each figure gets resized so its
LONGER side matches one target size, tiled across a row until the sheet's
width is used up, that same row repeated a chosen number of times (stacked
down the sheet) before moving to the next figure -- continuing straight
down the same CorelDRAW page across figures, and automatically starting a
new PAGE (exactly like a multi-page catalog) whenever the current one runs
out of room.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "automacao_producao"))

import numpy as np
from PIL import Image
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

import coreldraw_service

BACKGROUND_COLOR_TOLERANCE = 24  # per-channel; see _remove_edge_background

# Same tolerance production.py uses for its own row/page fit checks -- a
# row/page that would only barely miss fitting (by a sliver) shouldn't be
# pushed out entirely just for that.
OVERFLOW_TOLERANCE_MM = 5.0


def _remove_edge_background(image: Image.Image, tolerance: int = BACKGROUND_COLOR_TOLERANCE) -> Image.Image:
    """Makes transparent whichever region(s) touch the image's four CORNERS
    in a graph where two ADJACENT pixels are linked only when their colors
    are within `tolerance` of each other -- a real flood fill/paint-bucket
    (each link is a purely LOCAL comparison to a neighbor), not a single
    global comparison against the corner's exact color. That distinction
    matters a lot here: several of these AI-generated figures have no real
    transparency around them at all, just a flat white OR a soft
    vignette/gradient canvas baked in as fully opaque pixels (alpha 255,
    same as the real artwork, so a plain alpha-channel crop can't see
    through it either way) -- and a gradient can easily drift well past any
    fixed tolerance from corner to edge while every single step along the
    way stays gentle. Chaining local links follows that drift; comparing
    everything straight back to the corner's own fixed color couldn't.
    Built as one sparse graph + scipy's connected_components (same
    building block separador_ia.py's figure-splitter already relies on)
    rather than a Python-level pixel-by-pixel walk -- confirmed live that a
    naive walk is far too slow on a multi-megapixel image; this is a
    vectorized formulation of the identical idea. Never touches anything
    not actually connected to an edge -- real artwork deep inside the
    figure that happens to share a similar tone stays untouched.

    Links compare all FOUR channels (RGB + alpha), not just color -- a
    genuinely transparent pixel (alpha 0, whatever leftover/undefined RGB
    it happens to carry) must never link to an opaque one just because
    their RGB triplets happen to be close (confirmed live: real dark
    artwork -- boots, shadows -- sitting near alpha-0 background pixels
    that both happened to store near-black RGB was getting swept in as
    "background" when only RGB was compared)."""
    arr = np.array(image.convert("RGBA"))
    rgba = arr.astype(np.int16)
    h, w = rgba.shape[:2]
    n = h * w
    idx = np.arange(n).reshape(h, w)

    h_linked = np.all(np.abs(rgba[:, :-1] - rgba[:, 1:]) <= tolerance, axis=2)
    v_linked = np.all(np.abs(rgba[:-1, :] - rgba[1:, :]) <= tolerance, axis=2)
    rows = np.concatenate([idx[:, :-1][h_linked], idx[:-1, :][v_linked]])
    cols = np.concatenate([idx[:, 1:][h_linked], idx[1:, :][v_linked]])

    graph = coo_matrix((np.ones(len(rows), dtype=np.uint8), (rows, cols)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    labels = labels.reshape(h, w)

    corner_labels = {labels[0, 0], labels[0, w - 1], labels[h - 1, 0], labels[h - 1, w - 1]}
    mask = np.isin(labels, list(corner_labels))

    if mask.any():
        arr[mask, 3] = 0
    return Image.fromarray(arr, "RGBA")


def _trim_to_content(image: Image.Image) -> Image.Image:
    """Crops away any blank margin around the real artwork -- transparent
    already, or made transparent just above by _remove_edge_background.
    Confirmed live to matter a lot in practice: a figure straight out of an
    AI image generator often doesn't fill its own canvas symmetrically (or
    at all, on some side) -- left untrimmed, that dead space counts toward
    the figure's measured size here, so it gets scaled down along with the
    real artwork and wastes real sheet space fitting fewer copies per row
    than the artwork itself would actually allow."""
    if image.mode != "RGBA":
        return image
    bbox = image.split()[-1].getbbox()
    return image.crop(bbox) if bbox else image


OPAQUE_FRACTION_FOR_BACKGROUND_REMOVAL = 0.98


def _is_mostly_opaque(image: Image.Image) -> bool:
    """True when the image has essentially no real transparency of its own
    (background baked in as flat/near-flat fully-opaque pixels rather than
    real alpha=0) -- the only case _remove_edge_background should ever run
    for. A file that already has a real transparent background must skip
    it: confirmed live that comparing RGBA across the soft anti-aliased
    ring every real transparent edge has (alpha ramping gradually from 0 to
    255 over a few pixels, each step small enough to stay under
    `tolerance`) lets the flood fill "bridge" straight through that ring
    and eat into the real opaque artwork just past it -- not a risk an
    already-mostly-transparent image needs to take at all, since its
    existing alpha channel is already trustworthy on its own for
    _trim_to_content."""
    alpha = np.array(image.convert("RGBA"))[:, :, 3]
    return (alpha > 250).mean() >= OPAQUE_FRACTION_FOR_BACKGROUND_REMOVAL


def _trimmed_copy(image_path: str, index: int, temp_dir: str) -> str:
    """Saves a content-trimmed copy of image_path into temp_dir and returns
    its path -- this trimmed version (not the original file) is what
    actually gets measured AND imported into CorelDRAW, so the two stay in
    sync (importing the original file but sizing it to the trimmed
    figure's aspect ratio would silently stretch it).

    Named with `index` prefixed, NOT just the original basename -- two
    different source figures picked from different folders can easily
    share a filename (a generic "1.png"/"image.png" a browser or another
    tool handed out, or the same sheet split twice into differently-named
    folders). Saving plain basenames into one shared temp_dir let a later
    image silently overwrite an earlier one still waiting to be imported:
    the earlier item's SIZE had already been measured from its own real
    content, but by the time CorelDRAW actually opened that path the file
    on disk was the LATER image instead -- importing the wrong artwork
    AND stretching it to a size computed for a different picture's aspect
    ratio (confirmed live: exactly the "figure comes out distorted /
    doesn't match what I imported" symptom)."""
    with Image.open(image_path) as im:
        cleaned = im.convert("RGBA")
        if _is_mostly_opaque(cleaned):
            cleaned = _remove_edge_background(cleaned)
        trimmed = _trim_to_content(cleaned)
        out_path = os.path.join(temp_dir, f"{index:04d}_{os.path.basename(image_path)}")
        trimmed.save(out_path)
    return out_path


def _native_size_mm(image_path: str, target_long_mm: float) -> tuple[float, float]:
    """Reads just the pixel aspect ratio (these are plain digital PNGs with
    no physical size of their own -- already trimmed to content by
    _trimmed_copy) and scales it so the longer side (whichever that is)
    becomes target_long_mm, same "never stretch" rule as
    redimensionador_ia.resize_to_fit."""
    with Image.open(image_path) as im:
        w_px, h_px = im.size
    if w_px >= h_px:
        return target_long_mm, target_long_mm * h_px / w_px
    return target_long_mm * w_px / h_px, target_long_mm


def _pack_rows(pieces: list[tuple[int, str, float, float]], usable_width_mm: float, spacing_h_mm: float):
    """pieces: (piece_id, path, width_mm, height_mm), already expanded to one
    entry per COPY (a figure with quantity 7 appears here 7 times in a row,
    before the next figure's entries) -- packs them left to right, wrapping
    to a new row only when the next piece truly doesn't fit what's left of
    the current one. Deliberately doesn't care whether the next piece is
    the same figure as the last one in the row or a different one: the
    point of this (vs. production.calculate_layout, which always starts a
    fresh row per figure) is exactly to let a figure's leftover partial row
    get finished off by whatever comes next, instead of that space going
    empty.

    Returns rows: list of (row_height_mm, [(piece_id, path, w, h, x_mm), ...]).
    """
    rows = []
    row: list[tuple[int, str, float, float, float]] = []
    row_width_mm = 0.0
    row_height_mm = 0.0

    for piece_id, path, width_mm, height_mm in pieces:
        candidate_width_mm = width_mm if not row else row_width_mm + spacing_h_mm + width_mm
        if row and candidate_width_mm > usable_width_mm + OVERFLOW_TOLERANCE_MM:
            rows.append((row_height_mm, row))
            row, row_width_mm, row_height_mm = [], 0.0, 0.0
            candidate_width_mm = width_mm

        x_mm = 0.0 if not row else row_width_mm + spacing_h_mm
        row.append((piece_id, path, width_mm, height_mm, x_mm))
        row_width_mm = candidate_width_mm
        row_height_mm = max(row_height_mm, height_mm)

    if row:
        rows.append((row_height_mm, row))
    return rows


def _pack_pages(rows, usable_height_mm: float, spacing_v_mm: float):
    """rows: as returned by _pack_rows. Separate pass, vertical axis only --
    by the time this runs every row's height is already final, so this is
    plain bin-packing, no different from row-packing's own logic just
    turned 90 degrees.

    Returns pages: list of [(top_y_mm, row_height_mm, row_pieces), ...]."""
    pages = []
    page_rows = []
    bottom_y_mm = 0.0

    for row_height_mm, row_pieces in rows:
        top_y_mm = bottom_y_mm + spacing_v_mm if page_rows else 0.0
        if page_rows and top_y_mm + row_height_mm > usable_height_mm + OVERFLOW_TOLERANCE_MM:
            pages.append(page_rows)
            page_rows = []
            top_y_mm = 0.0
        page_rows.append((top_y_mm, row_height_mm, row_pieces))
        bottom_y_mm = top_y_mm + row_height_mm

    if page_rows:
        pages.append(page_rows)
    return pages


def build_plan(image_paths: list[str], target_long_mm: float, sheet_width_mm: float,
               sheet_length_mm: float, gap_mm: float, quantity_per_figure: int, temp_dir: str):
    usable_width_mm = sheet_width_mm
    usable_height_mm = sheet_length_mm

    pieces = []
    paths_by_id = {}
    for i, original_path in enumerate(image_paths):
        path = _trimmed_copy(original_path, i, temp_dir)
        width_mm, height_mm = _native_size_mm(path, target_long_mm)
        if width_mm > usable_width_mm + OVERFLOW_TOLERANCE_MM:
            raise ValueError(
                f"\"{os.path.basename(path)}\": mesmo com {target_long_mm}mm no lado maior, não cabe nem "
                f"uma cópia na largura da folha ({sheet_width_mm}mm).")
        if height_mm > usable_height_mm + OVERFLOW_TOLERANCE_MM:
            raise ValueError(
                f"\"{os.path.basename(path)}\": com {target_long_mm}mm no lado maior, a altura "
                f"({height_mm:.0f}mm) não cabe no comprimento da folha ({sheet_length_mm}mm).")
        paths_by_id[i] = path
        for _copy in range(quantity_per_figure):
            pieces.append((i, path, width_mm, height_mm))

    rows = _pack_rows(pieces, usable_width_mm, gap_mm)
    pages = _pack_pages(rows, usable_height_mm, gap_mm)
    return pages, paths_by_id


def _place_pages_in_corel(corel: coreldraw_service.CorelDrawService, pages, sheet_width_mm, sheet_length_mm):
    document = corel.create_production_document()
    corel.set_units(document)
    shapes_created = 0

    for page_index, page_rows in enumerate(pages):
        page = corel.get_active_page(document) if page_index == 0 else corel.add_page(document)
        corel.set_page_size(page, sheet_width_mm, sheet_length_mm)
        layer = corel.create_layer(page, "MONTAGEM")
        # Reused only within this same page/layer -- Duplicate() is only
        # ever confirmed (by the shared production_generator.py, which this
        # mirrors) to land copies on the same page as the original, so a
        # cache kept across pages could silently place a later page's
        # pieces on an earlier page instead.
        shape_cache: dict[str, object] = {}

        for top_y_mm, _row_height_mm, row_pieces in page_rows:
            corel_y = sheet_length_mm - top_y_mm
            for _piece_id, path, width_mm, height_mm, x_mm in row_pieces:
                cached = shape_cache.get(path)
                shape = corel.duplicate_artwork(cached) if cached is not None else corel.import_artwork(layer, path)
                if cached is None:
                    shape_cache[path] = shape
                corel.resize_artwork(shape, width_mm, height_mm)
                corel.position_artwork(shape, x_mm, corel_y)
                shapes_created += 1

    return document, shapes_created


def generate_in_corel(image_paths: list[str], target_long_mm: float, sheet_width_mm: float,
                       sheet_length_mm: float, gap_mm: float, quantity_per_figure: int, save_path: str):
    temp_dir = tempfile.mkdtemp(prefix="montador_folha_")
    try:
        print("Recortando a margem vazia de cada figura...")
        print(f"Calculando layout para {len(image_paths)} figura(s)...")
        pages, _paths_by_id = build_plan(
            image_paths, target_long_mm, sheet_width_mm, sheet_length_mm, gap_mm, quantity_per_figure, temp_dir)
        total_pieces = sum(len(row_pieces) for page_rows in pages for _y, _h, row_pieces in page_rows)
        print(f"Layout calculado: {len(pages)} página(s), {total_pieces} peça(s) no total.")

        print("Conectando ao CorelDRAW (abra o CorelDRAW antes se quiser acompanhar ao vivo)...")
        corel = coreldraw_service.CorelDrawService()
        corel.connect()

        print("Montando no CorelDRAW...")
        document, shapes_created = _place_pages_in_corel(corel, pages, sheet_width_mm, sheet_length_mm)

        print(f"Salvando em '{save_path}'...")
        corel.save_document(document, save_path)

        print(f"Pronto: {len(pages)} página(s), {shapes_created} figura(s) no total.")
        return document
    finally:
        # CorelDRAW's Import() reads and embeds the file's pixels into the
        # document right away -- once generate() above returns, the
        # trimmed copies have already done their job and nothing keeps
        # needing them on disk.
        shutil.rmtree(temp_dir, ignore_errors=True)
