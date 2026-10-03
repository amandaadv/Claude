"""Pulls the real production-quality vector artwork for a REF out of the
designer's master .cdr file, instead of using the low-res raster crop taken
from the customer-facing PDF catalog (that crop is only good enough for the
"which product is this" identification step -- see clip_embedding.py /
vision_scanner.py -- not for actual print production).

The master file's own convention varies by catalog: some (CATALOGO BABY 1.cdr)
caption each product "REF 055 MED 88X80MM" (reference plus the designer's
recorded size in mm); others (CATALOGO APLIQUE BABY COPA COZINHA) just say
"REF 1350" with no size at all. The MED part is optional in the pattern
below -- when absent, that REF has no locked size and the operator is asked
for width/height same as before. Either way, we find the REF by scanning
every text shape on the page, then take whichever non-text shape sits
closest to it -- same proximity idea PdfPigArtExtractor.cs used for vector
PDF catalogs (FindClosestReference).
"""
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
import zipfile

import win32com.client

REF_CAPTION_PATTERN = re.compile(
    r"REF\.?\s*0*(?P<ref>\d+)(?:\s*/\s*0*(?P<variant>\d+))?(?:\s*MED\s*(?P<med_h>\d+)X(?P<med_w>\d+)MM)?",
    re.IGNORECASE)


GROUP_SHAPE_TYPE = 7  # cdrGroupShape (from enum cdrShapeType)
TEXT_SHAPE_TYPE = 6  # cdrTextShape
BITMAP_SHAPE_TYPE = 5  # cdrBitmapShape
CURVE_SHAPE_TYPE = 3  # cdrCurveShape


def _flatten_shapes(shapes, path_prefix=()):
    """Yields (path, shape_type, text_or_None, center_x, center_y, width, height) for every
    LEAF shape reachable from `shapes` -- recursing into groups (some pages
    put several products in one Group instead of separate top-level shapes,
    e.g. six jam jars sharing a single group with six REF captions next to
    it; matching against the group as a whole would associate all six REFs
    with the same six-jar image). `path` is a tuple of 1-based indices
    describing how to reach the shape (e.g. (8,) for a top-level shape,
    (8, 3) for the 3rd child inside group 8), stored later as "8,3" so
    copy/export can navigate straight back to it without re-scanning."""
    for i in range(1, shapes.Count + 1):
        shape = shapes.Item(i)
        path = path_prefix + (i,)

        if shape.Type == GROUP_SHAPE_TYPE:
            yield from _flatten_shapes(shape.Shapes, path)
            continue

        text = None
        if shape.Type == TEXT_SHAPE_TYPE:
            try:
                text = shape.Text.Story.Text
            except Exception:
                text = None
        try:
            width = shape.SizeWidth
            height = shape.SizeHeight
            center_x = shape.LeftX + width / 2
            center_y = shape.TopY - height / 2
        except Exception:
            center_x = center_y = width = height = None

        yield path, shape.Type, text, center_x, center_y, width, height


def _merge_split_ref_captions(all_shapes):
    """Some master files write each caption as TWO separate text shapes on the same line: the word
    "REF" and, right beside it, the number ("REF" | "241") -- so no single text ever reads "REF 241"
    and REF_CAPTION_PATTERN finds nothing (the whole catalog imported with "Nenhuma REF encontrada").
    This pairs every lone "REF" with the number-only text sitting just to its RIGHT on the same
    baseline and replaces the two by one synthetic "REF N" caption (positioned over both, keyed by
    the REF shape's path). Returns (new_shapes, {ref_shape_path: number_shape_path}) -- the number
    shape's path is remembered so the caption's full shape path can name BOTH pieces.
    Files whose captions are already whole "REF N" texts pass through untouched."""
    refs, nums = [], []
    for index, (path, shape_type, text, cx, cy, width, height) in enumerate(all_shapes):
        if not text or cx is None or width is None or height is None:
            continue
        stripped = text.strip()
        if stripped.upper().rstrip(".") == "REF":
            refs.append(index)
        elif re.fullmatch(r"\d+(?:\s*/\s*\d+)?", stripped):
            nums.append(index)
    if not refs or not nums:
        return all_shapes, {}

    pairs = []
    for r in refs:
        _rp, _rt, _rtext, rcx, rcy, rw, rh = all_shapes[r]
        for n in nums:
            _np, _nt, _ntext, ncx, ncy, nw, nh = all_shapes[n]
            same_line = abs(ncy - rcy) <= max(3.0, 0.6 * max(rh, nh))
            gap = (ncx - nw / 2) - (rcx + rw / 2)       # empty space between "REF" and the number
            if same_line and ncx > rcx and -3.0 <= gap <= max(12.0, 0.6 * rw):
                pairs.append((gap, r, n))
    pairs.sort()

    used_refs, used_nums, merged = set(), set(), {}
    for _gap, r, n in pairs:
        if r in used_refs or n in used_nums:
            continue
        used_refs.add(r)
        used_nums.add(n)
        merged[r] = n

    if not merged:
        return all_shapes, {}
    new_shapes, number_paths = [], {}
    for index, shape in enumerate(all_shapes):
        if index in used_nums:
            continue                                     # absorbed into its "REF"
        if index in merged:
            rpath, rtype, _rtext, rcx, rcy, rw, rh = shape
            npath, _nt, ntext, ncx, ncy, nw, nh = all_shapes[merged[index]]
            left = min(rcx - rw / 2, ncx - nw / 2)
            right = max(rcx + rw / 2, ncx + nw / 2)
            new_shapes.append((rpath, rtype, f"REF {ntext.strip()}", (left + right) / 2, (rcy + ncy) / 2,
                               right - left, max(rh, nh)))
            number_paths[rpath] = npath
        else:
            new_shapes.append(shape)
    return new_shapes, number_paths


def build_ref_index(master_document) -> dict[str, dict]:
    """Scans every page of the master document and returns
    {ref_number_str: {"shape_path": str, "page_index": int, "med_width_mm": float | None,
    "med_height_mm": float | None}}. ref_number_str is normalized (no leading zeros, e.g. "55").
    med_width/height_mm are None when the caption didn't include a "MED WxHMM" size.
    shape_path is a comma-separated index path (e.g. "8" or "8,3" for a shape
    nested inside a group) -- see _flatten_shapes.

    Each caption is matched to whichever artwork shape sits closest to it, but
    globally across the whole page rather than one caption at a time: picking
    each caption's own nearest shape independently can let two captions that
    are both near the same shape both claim it (a design with several
    products close together, one caption slightly closer to its neighbor's
    artwork than to its own) -- every REF still gets *a* size in that case,
    it's just silently the wrong image with the wrong caption's size. Sorting
    every (caption, shape) pair by distance and claiming greedily means a
    shape already taken by a closer caption can never be handed to a second,
    farther one.
    """
    index: dict[str, dict] = {}

    for page_index in range(1, master_document.Pages.Count + 1):
        page = master_document.Pages.Item(page_index)
        all_shapes = list(_flatten_shapes(page.Shapes))
        all_shapes, split_caption_number_paths = _merge_split_ref_captions(all_shapes)

        captions = []
        for path, shape_type, text, cx, cy, _w, _h in all_shapes:
            if not text or cx is None:
                continue
            match = REF_CAPTION_PATTERN.search(text)
            if not match:
                continue
            captions.append((path, cx, cy, match))

        candidate_shapes = [
            (path2, cx2, cy2, w2, h2) for path2, type2, text2, cx2, cy2, w2, h2 in all_shapes
            if type2 != TEXT_SHAPE_TYPE and cx2 is not None
        ]
        # path -> (center_x, center_y, width, height), for the Voronoi
        # assignment below -- a caption's real artwork is sometimes several
        # small LOOSE shapes (not grouped in the .cdr) scattered around it,
        # e.g. a whole decal SHEET made of a center wreath plus a dozen
        # matching mini-bouquets spread across the same square, all sharing
        # one caption. Picking only the single nearest shape (what
        # candidate_shapes/matching above does) exports just one fragment of
        # the sheet instead of the whole thing. shapes_bbox lets
        # _assign_shapes_by_nearest_caption pull in every other unclaimed
        # piece that belongs to this caption.
        shapes_bbox = {
            path2: (cx2, cy2, w2, h2) for path2, type2, text2, cx2, cy2, w2, h2 in all_shapes
            if type2 != TEXT_SHAPE_TYPE and cx2 is not None and w2 is not None
        }

        # Some master files keep captions in a separate numbered legend
        # instead of right next to their own artwork (rows only ~3mm apart,
        # captions in one tight cluster, shapes in another) -- raw distance
        # alone can then be a near-coin-flip between a caption's real shape
        # and its neighbor's. A first pass gives a rough match; the typical
        # caption->shape displacement it reveals (most captions really are
        # closer to their own shape than to a neighbor's) becomes a
        # correction applied before a second, sharper pass -- see
        # _estimate_offset.
        first_pass, _ = _match_captions_to_shapes(captions, candidate_shapes)
        offset = _estimate_offset(captions, candidate_shapes, first_pass)
        if offset is not None:
            dx, dy = offset
            shifted_captions = [(path, cx + dx, cy + dy, match) for path, cx, cy, match in captions]
            assignments, claimed_captions = _match_captions_to_shapes(shifted_captions, candidate_shapes)
        else:
            assignments, claimed_captions = first_pass, {a[0] for a in first_pass}

        # Deliberately the ORIGINAL (unshifted) caption positions here, not
        # shifted_captions -- the offset correction's whole job is to erase
        # a near-tie by nudging captions toward their typical shape
        # displacement, so checking ambiguity on the shifted positions
        # always finds the winner suspiciously alone and never warns (the
        # offset just moved the caption right on top of it). The ambiguity
        # that actually matters is whether the ORIGINAL, real page layout
        # left two candidates close enough together to be a coin flip.
        _warn_ambiguous_assignments(captions, candidate_shapes, assignments, page_index)

        # Every caption's primary shape is claimed up front (before the
        # Voronoi pass runs) so one caption's cluster can never reach into
        # another caption's own dedicated artwork -- that pass only ever
        # picks up shapes nobody else already owns.
        claimed_for_cluster = {shape_path for _cp, shape_path, _m in assignments}

        # Only captions that actually got a primary match -- an orphan
        # caption (no free shape nearby, see the warning below) must never
        # sit in here, or nearby shapes would be pulled toward it and then
        # silently lost when its (nonexistent) index entry is skipped.
        caption_positions = {
            caption_path: (cx, cy)
            for caption_path, cx, cy, _match in (shifted_captions if offset is not None else captions)
            if caption_path in claimed_captions
        }
        extra_shapes_by_caption = _assign_shapes_by_nearest_caption(
            caption_positions, shapes_bbox, claimed_for_cluster)

        for caption_path, shape_path, match in assignments:
            # "REF.2212/1" and "REF.2212/2" caption two DIFFERENT pieces (a
            # base design offered in more than one size/variant, printed
            # with the same base number) -- before the "variant" group
            # existed, both captions' match.group(1) came out as plain
            # "2212", so index["2212"] below silently overwrote the first
            # piece with the second the moment the second was processed:
            # one whole variant vanished from every tool built on
            # build_ref_index (import, production, Gerar Catálogo de 3
            # Medidas...) with no error at all. Appending "/N" to the key
            # keeps them as two separate entries, exactly like the two
            # captions printed on the page.
            ref_number = match.group("ref")
            if match.group("variant"):
                ref_number = f"{ref_number}/{int(match.group('variant'))}"
            # "MED AxB" in the caption is height-by-width, not width-by-
            # height -- confirmed against real exported pixel dimensions
            # across many REFs (e.g. "MED 90X56MM" on a piece whose actual
            # artwork is 561x890px: 90/56 only matches 890/561, not 561/890).
            # Reading it as width-by-height silently squished/stretched
            # every non-square piece's aspect ratio in production.
            med_height_mm = float(match.group("med_h")) if match.group("med_h") else None
            med_width_mm = float(match.group("med_w")) if match.group("med_w") else None

            cluster_paths = _keep_physically_connected(
                shape_path, [shape_path] + extra_shapes_by_caption.get(caption_path, []), shapes_bbox)

            index[ref_number] = {
                "shape_path": ";".join(",".join(str(p) for p in sp) for sp in cluster_paths),
                "caption_shape_path": ",".join(str(p) for p in caption_path) + (
                    ";" + ",".join(str(p) for p in split_caption_number_paths[caption_path])
                    if caption_path in split_caption_number_paths else ""),
                "page_index": page_index,
                "med_width_mm": med_width_mm,
                "med_height_mm": med_height_mm,
            }

        for caption_path, cx, cy, match in captions:
            if caption_path not in claimed_captions:
                warn_ref = match.group("ref")
                if match.group("variant"):
                    warn_ref = f"{warn_ref}/{int(match.group('variant'))}"
                print(f"  AVISO: legenda \"REF {warn_ref}\" (página {page_index}) não tem nenhuma "
                      f"peça livre por perto -- todas as peças próximas já foram usadas por outra legenda "
                      f"mais perto delas. Essa REF ficou de fora da importação; confira o arquivo original.")

    return index


_CURVE_CAPTION_MAX_WIDTH_MM = 60.0
_CURVE_CAPTION_MAX_HEIGHT_MM = 30.0
_CURVE_CAPTION_MAX_GAP_MM = 45.0
_CURVE_CAPTION_PAIR_Y_TOLERANCE_MM = 4.0  # the "ref" word and its number sit at ~identical y
_CURVE_CAPTION_PAIR_MAX_EDGE_GAP_MM = 15.0  # ...side by side with only a small horizontal gap
_PRODUCT_BITMAP_MIN_SIZE_MM = 50.0  # excludes small decorative accents overlapping/near a real piece
                                     # (seen live: two ~25mm sticker overlays on top of a ~110mm real
                                     # piece, both closer to that piece's caption than the piece itself)
_BITMAP_CLUSTER_GAP_MM = 8.0  # how close two bitmaps must sit to count as one physical product
                               # (see _cluster_bitmaps_by_proximity) -- tight enough that two
                               # side-by-side but genuinely separate products (e.g. neighboring
                               # grid columns, or two adjacent full-width rows, always spaced well
                               # clear of each other) never merge, loose enough to bridge the small
                               # overlaps/touches between a scene's own pieces (e.g. a deer standing
                               # in front of a tree). 20mm was tried first and merged two adjacent
                               # rows' artwork into one giant double-height "product" (confirmed
                               # live: the row in between lost its own artwork entirely to its
                               # neighbor); 8mm still correctly reassembles a genuinely one-piece
                               # multi-element scene (confirmed live on the same file) without
                               # bridging across a real gap between two different rows.


def _cluster_bitmaps_by_proximity(bitmaps: list, gap_mm: float) -> list[list]:
    """Groups bitmaps into connected components by physical proximity alone
    (single-linkage: A and B cluster together if A is within gap_mm of B,
    or of anything already clustered with B) -- independent of any caption,
    so a whole multi-piece scene (several touching/overlapping raster
    pieces making up one product) comes out as one cluster regardless of
    how far its own centroid ends up from whatever caption it belongs to,
    while a small decorative element sitting apart from that scene stays
    in its own separate cluster instead of ever being folded into it.
    bitmaps: [(path, cx, cy, w, h), ...]. Returns a list of such lists."""
    n = len(bitmaps)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    boxes = [_bbox(cx, cy, w, h) for _p, cx, cy, w, h in bitmaps]
    for i in range(n):
        for j in range(i + 1, n):
            if _boxes_within_gap(boxes[i], boxes[j], gap_mm):
                union(i, j)

    clusters: dict = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(bitmaps[i])
    return list(clusters.values())


def _iter_leaf_shapes_with_name(shapes, path_prefix=()):
    """Like _flatten_shapes, but also yields the shape's Name -- needed to
    exclude a placed watermark/logo bitmap from find_curve_caption_products
    (a real bitmap shape too, and sometimes close enough in size to a real
    product piece that geometry alone can't tell them apart)."""
    for i in range(1, shapes.Count + 1):
        shape = shapes.Item(i)
        path = path_prefix + (i,)

        if shape.Type == GROUP_SHAPE_TYPE:
            yield from _iter_leaf_shapes_with_name(shape.Shapes, path)
            continue

        try:
            name = shape.Name or ""
        except Exception:
            name = ""
        try:
            width = shape.SizeWidth
            height = shape.SizeHeight
            center_x = shape.LeftX + width / 2
            center_y = shape.TopY - height / 2
        except Exception:
            center_x = center_y = width = height = None

        yield path, shape.Type, name, center_x, center_y, width, height


def _cluster_caption_curves(small_curves: list) -> list[list]:
    """Groups small curve shapes into caption clusters -- each caption is
    "ref" + its number typeset as two separate objects sitting right next to
    each other at ~identical y (see find_curve_caption_products); two
    different captions in the same row-band of a grid are always spaced much
    further apart in x (they belong to different columns) than the two
    pieces of one caption are from each other. Plain union-find over "close
    enough" pairs (small vertical center difference AND small horizontal
    edge gap), so it doesn't hard-code "exactly 2 pieces" -- a caption drawn
    as 1 or 3+ separate curve objects still comes out as one cluster."""
    n = len(small_curves)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(n):
        _p1, cx1, cy1, w1, _h1 = small_curves[i]
        for j in range(i + 1, n):
            _p2, cx2, cy2, w2, _h2 = small_curves[j]
            if abs(cy1 - cy2) > _CURVE_CAPTION_PAIR_Y_TOLERANCE_MM:
                continue
            edge_gap = abs(cx1 - cx2) - (w1 + w2) / 2
            if edge_gap < _CURVE_CAPTION_PAIR_MAX_EDGE_GAP_MM:
                union(i, j)

    clusters: dict = {}
    for i in range(n):
        clusters.setdefault(find(i), []).append(small_curves[i])
    return list(clusters.values())


def find_curve_caption_products(document, page_index: int) -> list[dict]:
    """Most master files this shop actually receives now aren't the
    "vector art + live REF caption" kind build_ref_index expects -- they're
    a single page full of finished, background-removed raster pieces
    (typically named "<something>-removebg-preview.png") with each piece's
    "ref NNN" caption typeset then converted to curves (CorelDRAW's Ctrl+Q,
    a common habit to lock the text in place / dodge font-substitution
    issues). Once converted, the caption is pure vector paths -- there is no
    text left anywhere in the file for build_ref_index's regex to find.

    This finds every {bitmap piece, its curve caption} pair on one page
    instead, purely by geometry, in two steps: first the small curve shapes
    are clustered into whole captions (_cluster_caption_curves) so a
    caption's own two pieces can never be split between two different
    pieces' matches; then each caption is paired with whichever real
    product bitmap sits closest above it (small vertical gap), globally and
    exclusively -- closest pairs claimed first, so a caption already taken
    can never also be handed to a second, farther bitmap (an early version
    of this function matched each bitmap to its own nearest caption
    independently, with no such exclusivity: two tiny ~25mm decorative
    accents overlapping a real ~110mm piece were both slightly closer to
    that piece's own caption than the real piece was, so all three
    "claimed" the same caption and only one survived). A minimum size
    (_PRODUCT_BITMAP_MIN_SIZE_MM) also excludes those small accent bitmaps
    from being treated as products in the first place. The caller still has
    to actually read the number off the caption (it's curves, not text --
    this function only locates it); see pa._import_curve_captioned_refs for
    the OpenAI vision read + ref_index merge.

    Returns [{"page_index":, "artwork_shape_path":, "caption_shape_path":}, ...]
    (shape_path strings in the same "8" / "8,3" / "8;9,2" convention as
    build_ref_index, ready for export_shape_to_png). A watermark/logo
    bitmap (name containing "logo") is excluded; a piece with no caption
    found nearby (e.g. the grid's title bar, or a stray decoration) is
    simply skipped, not returned."""
    page = document.Pages.Item(page_index)
    all_shapes = list(_iter_leaf_shapes_with_name(page.Shapes))

    raw_bitmaps = []
    small_curves = []
    for path, shape_type, name, cx, cy, w, h in all_shapes:
        if cx is None:
            continue
        if shape_type == BITMAP_SHAPE_TYPE:
            if "logo" in name.lower():
                continue
            raw_bitmaps.append((path, cx, cy, w, h))
        elif shape_type == CURVE_SHAPE_TYPE and w < _CURVE_CAPTION_MAX_WIDTH_MM and h < _CURVE_CAPTION_MAX_HEIGHT_MM:
            small_curves.append((path, cx, cy, w, h))

    captions = []
    for cluster in _cluster_caption_curves(small_curves):
        paths = [c[0] for c in cluster]
        top = max(cy + h / 2 for _p, cx, cy, _w, h in cluster)
        cx_avg = sum(cx for _p, cx, _cy, _w, _h in cluster) / len(cluster)
        captions.append((paths, cx_avg, top))

    # Not every product is ONE bitmap: some pages give each REF a whole
    # scene assembled from several touching/overlapping raster pieces
    # (e.g. two deer + an owl + wrapped gifts + a badger, all scattered
    # across an ~800mm-wide row) instead of a single flattened image.
    # Grouping every bitmap into connected-component clusters FIRST (by
    # physical proximity, independent of any caption) turns a whole such
    # scene into one candidate "product" -- and, just as importantly,
    # keeps a small decorative element that ISN'T touching that scene
    # (e.g. a repeating corner ribbon/garland border motif) in its OWN
    # separate, correctly small cluster instead of ever being confused
    # for part of it. Confirmed live: without this, a caption whose real
    # product was exactly this kind of multi-piece scene instead matched
    # a same-sized decorative ribbon sitting nearby, because the single
    # nearest INDIVIDUAL bitmap heuristic had no way to recognize "these
    # five separate pieces are actually one product."
    products = []
    for cluster in _cluster_bitmaps_by_proximity(raw_bitmaps, _BITMAP_CLUSTER_GAP_MM):
        paths = [b[0] for b in cluster]
        lefts = [cx - w / 2 for _p, cx, _cy, w, _h in cluster]
        rights = [cx + w / 2 for _p, cx, _cy, w, _h in cluster]
        bottoms = [cy - h / 2 for _p, _cx, cy, _w, h in cluster]
        tops = [cy + h / 2 for _p, _cx, cy, _w, h in cluster]
        left, right, bottom, top = min(lefts), max(rights), min(bottoms), max(tops)
        width, height = right - left, top - bottom
        if width < _PRODUCT_BITMAP_MIN_SIZE_MM or height < _PRODUCT_BITMAP_MIN_SIZE_MM:
            continue
        products.append((paths, left, right, bottom, top))

    pairs = []
    for p_index, (_paths, left, right, bottom, top) in enumerate(products):
        for c_index, (_cpaths, ccx, ctop) in enumerate(captions):
            gap = bottom - ctop
            # A caption's own bounding box regularly dips 5+mm above a
            # piece's exported bottom edge (seen live: two correct matches
            # at -5.1mm and -5.2mm, both narrowly rejected by an earlier,
            # tighter -5mm floor here) -- some rounding/padding difference
            # between how a bitmap's vs. a curve's bbox gets measured, not
            # an actual different piece. -15mm stays well clear of a real
            # neighboring row (rows are ~150mm apart on every file seen).
            if -15 <= gap < _CURVE_CAPTION_MAX_GAP_MM:
                # Distance from the caption's own point to the PRODUCT's
                # bounding box, not to its centroid -- a wide multi-piece
                # scene's centroid can sit hundreds of mm to the right of
                # its own caption (the caption anchors its left edge, not
                # its middle), which used to make an unrelated small
                # bitmap sitting right next to the caption look "closer"
                # than the real, correct, but wide product.
                dx = 0.0 if left <= ccx <= right else min(abs(ccx - left), abs(ccx - right))
                distance = dx + abs(gap)
                pairs.append((distance, p_index, c_index))
    pairs.sort(key=lambda p: p[0])

    claimed_products = set()
    claimed_captions = set()
    results = []
    for _distance, p_index, c_index in pairs:
        if p_index in claimed_products or c_index in claimed_captions:
            continue
        claimed_products.add(p_index)
        claimed_captions.add(c_index)
        paths = products[p_index][0]
        caption_paths = captions[c_index][0]
        results.append({
            "page_index": page_index,
            "artwork_shape_path": ";".join(",".join(str(p) for p in path) for path in paths),
            "caption_shape_path": ";".join(",".join(str(p) for p in cpath) for cpath in caption_paths),
        })
    return results


def _warn_ambiguous_assignments(captions, candidate_shapes, assignments, page_index: int) -> None:
    """Prints a warning for any caption whose winning shape was a near-tie
    against some other candidate shape on the page -- e.g. the same base
    design offered in two very different physical sizes, stacked close
    together, where the WRONG shape can end up only a couple mm farther
    than the right one. Confirmed live on a real catalog: even the
    distance-optimal assignment (this module's own offset-corrected second
    pass) still occasionally lands on the wrong piece when two candidates
    are this close -- there's no purely geometric signal left to break the
    tie reliably. This never changes which shape gets picked; it only
    surfaces which REFs are worth a human's eyes before trusting a big
    batch import blindly instead of failing (or worse, succeeding wrong)
    silently."""
    cap_pos = {path: (cx, cy) for path, cx, cy, _match in captions}
    NEAR_TIE_MARGIN = 1.5  # runner-up within 50% of the winner's own distance counts as a near-tie
    for caption_path, shape_path, match in assignments:
        cx, cy = cap_pos[caption_path]
        winner_distance = None
        runner_up_distance = None
        for shape_path2, cx2, cy2, w2, h2 in candidate_shapes:
            if shape_path2 == caption_path:
                continue
            distance = _distance_to_bbox(cx, cy, cx2, cy2, w2, h2)
            if shape_path2 == shape_path:
                winner_distance = distance
            elif runner_up_distance is None or distance < runner_up_distance:
                runner_up_distance = distance
        if winner_distance is None or runner_up_distance is None:
            continue
        if runner_up_distance <= winner_distance * NEAR_TIE_MARGIN:
            ref_label = match.group("ref")
            if match.group("variant"):
                ref_label = f"{ref_label}/{int(match.group('variant'))}"
            print(f"  AVISO: legenda \"REF {ref_label}\" (página {page_index}) tem outra peça quase tão "
                  f"perto quanto a escolhida ({winner_distance:.1f}mm vs {runner_up_distance:.1f}mm) -- "
                  f"confira essa arte manualmente, pode ter pego a peça errada.")


def _distance_to_bbox(cx: float, cy: float, cx2: float, cy2: float, w2: float, h2: float) -> float:
    """Distance from point (cx, cy) to the NEAREST EDGE of shape2's
    bounding box (0 if the point falls inside it) -- not center-to-center.
    Center distance silently favors a smaller candidate shape over a much
    bigger one even when the caption sits flush against the big one's own
    edge: confirmed live on a catalog where each REF prints in two very
    different sizes (e.g. 490mm and 290mm wide) stacked in the same
    column -- every caption's raw center distance was closer to whichever
    small (290mm) shape happened to be nearby, because a narrower shape's
    center sits closer to the shared left margin the captions all live on,
    regardless of which shape the caption was actually next to. That
    silently swapped which physical artwork export_shape_to_png pulled for
    half the REFs on the page -- no error, no warning, just the wrong
    picture (and size) under a perfectly correct-looking REF number."""
    half_w, half_h = (w2 or 0) / 2, (h2 or 0) / 2
    left, right = cx2 - half_w, cx2 + half_w
    bottom, top = cy2 - half_h, cy2 + half_h
    dx = max(left - cx, 0.0, cx - right)
    dy = max(bottom - cy, 0.0, cy - top)
    return (dx ** 2 + dy ** 2) ** 0.5


def _match_captions_to_shapes(captions, candidate_shapes):
    """captions: [(caption_path, cx, cy, regex_match), ...].
    candidate_shapes: [(shape_path, cx, cy, width, height), ...].
    Returns (assignments, claimed_caption_paths) where assignments is
    [(caption_path, shape_path, regex_match), ...] -- one entry per caption
    that found a free shape, closest pairs claimed first (see build_ref_index
    for why this has to be global instead of per-caption nearest-neighbor).
    Pure function of plain data (no COM objects) so it's directly testable.
    """
    pairs = []
    for caption_path, cx, cy, match in captions:
        for shape_path, cx2, cy2, w2, h2 in candidate_shapes:
            if shape_path == caption_path:
                continue
            distance = _distance_to_bbox(cx, cy, cx2, cy2, w2, h2)
            pairs.append((distance, caption_path, shape_path, match))
    pairs.sort(key=lambda p: p[0])

    claimed_shapes = set()
    claimed_captions = set()
    assignments = []
    for distance, caption_path, shape_path, match in pairs:
        if caption_path in claimed_captions or shape_path in claimed_shapes:
            continue
        claimed_captions.add(caption_path)
        claimed_shapes.add(shape_path)
        assignments.append((caption_path, shape_path, match))

    return assignments, claimed_captions


_CLUSTER_MAX_SHAPES = 300
_CLUSTER_RADIUS_FALLBACK_MM = 45.0  # only used when a page has just 1 caption, so there's no spacing to measure


def _median_nearest_caption_distance_mm(caption_positions):
    """Median distance from each caption to its closest OTHER caption on
    this page -- a proxy for how big one product's own "cell" is, whether
    that's a tight grid of small stickers a couple cm apart or a handful of
    big pieces spread far across the page. None when there's only one
    caption (nothing to measure against)."""
    positions = list(caption_positions.values())
    if len(positions) < 2:
        return None
    nearest = []
    for i, (x1, y1) in enumerate(positions):
        best = min(
            ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
            for j, (x2, y2) in enumerate(positions) if j != i
        )
        nearest.append(best)
    nearest.sort()
    mid = len(nearest) // 2
    if len(nearest) % 2:
        return nearest[mid]
    return (nearest[mid - 1] + nearest[mid]) / 2


def _assign_shapes_by_nearest_caption(caption_positions, shapes_bbox, claimed):
    """Voronoi-style: every shape not already claimed (as some caption's own
    primary match) joins whichever caption's center is nearest to it --
    exactly like _match_captions_to_shapes' global-nearest-first claiming,
    just many-shapes-per-caption instead of one. This is what lets a whole
    decal SHEET (a center wreath plus a dozen matching mini-bouquets
    scattered around the same square, all sharing one caption) get pulled in
    as one piece instead of just the single closest fragment -- and because
    every shape only ever goes to its own truly-nearest caption, it can
    never bleed into a neighboring product's sheet.

    Capped at a radius derived from _median_nearest_caption_distance_mm so a
    shape that isn't near ANY caption (page furniture, a leftover guide
    object) doesn't get force-assigned to whatever happens to be least far;
    the radius scales with this page's own product spacing instead of a
    fixed guess, since that varies wildly catalog to catalog. Also capped at
    _CLUSTER_MAX_SHAPES per caption (keeping the nearest ones) so a
    degenerate page can't balloon one "product" into hundreds of pieces."""
    spacing = _median_nearest_caption_distance_mm(caption_positions)
    max_radius = spacing if spacing is not None else _CLUSTER_RADIUS_FALLBACK_MM

    pairs = []
    for shape_path, dims in shapes_bbox.items():
        if shape_path in claimed:
            continue
        cx, cy = dims[0], dims[1]
        for caption_path, (kcx, kcy) in caption_positions.items():
            distance = ((cx - kcx) ** 2 + (cy - kcy) ** 2) ** 0.5
            if distance > max_radius:
                continue
            pairs.append((distance, shape_path, caption_path))
    pairs.sort(key=lambda p: p[0])

    result: dict = {caption_path: [] for caption_path in caption_positions}
    result_distances: dict = {caption_path: [] for caption_path in caption_positions}
    assigned_shapes = set()
    for distance, shape_path, caption_path in pairs:
        if shape_path in assigned_shapes:
            continue
        if len(result[caption_path]) >= _CLUSTER_MAX_SHAPES:
            continue
        assigned_shapes.add(shape_path)
        result[caption_path].append(shape_path)
        result_distances[caption_path].append(distance)

    return result


_CONNECT_GAP_MM = 30.0


def _bbox(cx, cy, width, height):
    half_w, half_h = width / 2, height / 2
    return (cx - half_w, cx + half_w, cy - half_h, cy + half_h)  # left, right, bottom, top


def _boxes_within_gap(box1, box2, gap_mm):
    left1, right1, bottom1, top1 = box1
    left2, right2, bottom2, top2 = box2
    return not (
        right1 + gap_mm < left2 or right2 + gap_mm < left1
        or top1 + gap_mm < bottom2 or top2 + gap_mm < bottom1
    )


def _keep_physically_connected(seed_path, shape_paths, shapes_bbox, gap_mm=_CONNECT_GAP_MM):
    """Within one caption's Voronoi-assigned shapes, keeps only the ones
    that physically chain-connect (single-linkage, within gap_mm) back to
    the caption's own primary/seed shape -- drops anything else, even
    though the Voronoi pass already put it in this caption's "own nearest"
    bucket. Exists because a leftover duplicate design element (e.g. a
    second, unwrapped copy of a decorative headline the designer left
    sitting elsewhere on the page instead of deleting) can still end up
    geometrically nearest to some caption's center without being anywhere
    near that product's actual artwork -- the real artwork (a wreath plus
    its scattered matching bouquets) is always one connected visual blob,
    so anything that doesn't chain-connect to it isn't really part of the
    product, whichever caption Voronoi happened to hand it to."""
    boxes = {sp: _bbox(*shapes_bbox[sp][:4]) for sp in shape_paths}
    if seed_path not in boxes:
        boxes[seed_path] = _bbox(*shapes_bbox[seed_path][:4])
    connected = {seed_path}
    frontier = [seed_path]
    remaining = set(shape_paths) - {seed_path}
    while frontier:
        current_box = boxes[frontier.pop()]
        newly = {sp for sp in remaining if _boxes_within_gap(current_box, boxes[sp], gap_mm)}
        if not newly:
            continue
        remaining -= newly
        connected |= newly
        frontier.extend(newly)
    return [sp for sp in shape_paths if sp in connected]


def _estimate_offset(captions, candidate_shapes, first_pass_assignments):
    """Median (dx, dy) from caption position to its first-pass-matched
    shape's position, across every caption on the page -- most captions'
    nearest shape really is their own even when a few near-ties are wrong,
    so the median (robust to those few outliers, unlike a mean) approximates
    the page's typical caption->shape offset. Returns None when there are
    too few captions to make that median meaningful (under 4)."""
    if len(first_pass_assignments) < 4:
        return None
    cap_pos = {path: (cx, cy) for path, cx, cy, match in captions}
    shape_pos = {path: (cx, cy) for path, cx, cy, _w, _h in candidate_shapes}

    dxs, dys = [], []
    for caption_path, shape_path, match in first_pass_assignments:
        cx, cy = cap_pos[caption_path]
        sx, sy = shape_pos[shape_path]
        dxs.append(sx - cx)
        dys.append(sy - cy)

    dxs.sort()
    dys.sort()
    return dxs[len(dxs) // 2], dys[len(dys) // 2]


def _resolve_shape(master_document, page_index: int, shape_path: str):
    """Navigates a "8,3"-style path (see _flatten_shapes) back to the actual
    Shape object, descending into groups as needed."""
    indices = [int(p) for p in shape_path.split(",")]
    shapes = master_document.Pages.Item(page_index).Shapes
    shape = shapes.Item(indices[0])
    for idx in indices[1:]:
        shape = shape.Shapes.Item(idx)
    return shape


def get_shape(master_document, page_index: int, shape_path: str):
    """Public entry point for _resolve_shape -- other modules (e.g. the
    standalone catalog generator) need to navigate a "8,3"-style path back
    to a real Shape object too, without reaching into a private helper."""
    return _resolve_shape(master_document, page_index, shape_path)


def iter_shape_paths(shape_path: str):
    """A stored shape_path is usually one "8,3"-style path, but is
    "8,3;9;10,2"-style (semicolon-joined) when build_ref_index clustered
    several loose shapes into one product (see _cluster_shapes) -- this is
    the one place that split is defined, so every caller agrees on it."""
    return shape_path.split(";")


def resolve_shapes(master_document, page_index: int, shape_path: str):
    """Like _resolve_shape, but returns a list -- one real Shape per
    semicolon-separated piece in shape_path (a single-piece shape_path
    still comes back as a one-item list)."""
    return [_resolve_shape(master_document, page_index, p) for p in iter_shape_paths(shape_path)]


def get_shape_bbox_size(master_document, page_index: int, shape_path: str) -> tuple[float, float]:
    """(width_mm, height_mm) of shape_path's overall bounding box -- for a
    single-piece shape_path that's just that shape's own size; for a
    multi-piece one (a clustered "kit", see _cluster_shapes) it's the union
    of every piece, i.e. the size of the whole kit as it'll actually be
    copy/pasted together, not just whichever piece happens to be first."""
    shapes = resolve_shapes(master_document, page_index, shape_path)
    lefts = [s.LeftX for s in shapes]
    rights = [s.LeftX + s.SizeWidth for s in shapes]
    tops = [s.TopY for s in shapes]
    bottoms = [s.TopY - s.SizeHeight for s in shapes]
    return max(rights) - min(lefts), max(tops) - min(bottoms)


def find_header_footer_shapes(document, ref_index: dict[str, dict], margin_mm: float = 20.0) -> dict[int, dict]:
    """Infers which top-level shapes on each page are the catalog's own
    header (logo/title, above every product) and footer (application
    photos, below every product) -- purely by position, not manual
    selection: a shape counts as header/footer if it lies (almost)
    entirely above/below the page's product zone (the tightest box
    containing every product and caption shape_index/build_ref_index
    already found). margin_mm allows some overlap into the product
    zone -- confirmed necessary against a real catalog file, where the
    footer's own application-photo shapes physically overlapped the last
    product row's bottom edge by up to ~18mm without being product
    content themselves; a strict zero-overlap boundary silently dropped
    them. Shapes that are neither clearly above nor clearly below (small
    decorative fragments sitting inside/near the product grid) are left
    out of both, silently -- including them risks pulling unrelated
    confetti into the header/footer.

    Returns {page_index: {"header": [shape_path, ...], "footer": [...]}}
    for every page that has at least one product from ref_index."""
    product_paths_by_page: dict[int, set[str]] = {}
    for entry in ref_index.values():
        page_index = entry["page_index"]
        paths_here = product_paths_by_page.setdefault(page_index, set())
        # shape_path is "8,3" for a single-piece product, or "8,3;9;10,2"
        # (semicolon-joined) for a "kit" clustered from several loose
        # pieces (see _cluster_shapes) -- split so every individual piece
        # gets excluded from header/footer consideration, and resolves
        # cleanly below (a joined string isn't a valid path on its own).
        paths_here.update(iter_shape_paths(entry["shape_path"]))
        # A caption can be several pieces too ("102;96": a lone "REF" text + its number, see
        # _merge_split_ref_captions) -- every piece is excluded, none is resolved as one joined path.
        paths_here.update(iter_shape_paths(entry["caption_shape_path"]))

    result: dict[int, dict] = {}
    for page_index, product_paths in product_paths_by_page.items():
        page = document.Pages.Item(page_index)

        product_tops = []
        product_bottoms = []
        for shape_path in product_paths:
            shape = _resolve_shape(document, page_index, shape_path)
            try:
                product_tops.append(shape.TopY)
                product_bottoms.append(shape.TopY - shape.SizeHeight)
            except Exception:
                continue
        if not product_tops:
            continue
        products_top_y = max(product_tops)
        products_bottom_y = min(product_bottoms)

        header_paths = []
        footer_paths = []
        for i in range(1, page.Shapes.Count + 1):
            path_str = str(i)
            if path_str in product_paths:
                continue
            shape = page.Shapes.Item(i)
            try:
                top = shape.TopY
                bottom = shape.TopY - shape.SizeHeight
            except Exception:
                continue

            # A leftover "REF NNNN" caption sitting just outside the
            # product zone (seen live: an old, un-updated copy of 3
            # pieces' captions, orphaned above the grid after the designer
            # repositioned/relabeled those pieces with a new "MED" caption
            # elsewhere) must never be pulled in as header/footer -- that
            # duplicated it onto every single generated page instead of
            # leaving it out entirely. Real header/footer content (logo,
            # title, application photos) never happens to read "REF ...".
            if shape.Type == TEXT_SHAPE_TYPE:
                try:
                    text = shape.Text.Story.Text
                except Exception:
                    text = None
                if text and REF_CAPTION_PATTERN.search(text):
                    continue

            if bottom >= products_top_y - margin_mm:
                header_paths.append(path_str)
            elif top <= products_bottom_y + margin_mm:
                footer_paths.append(path_str)

        result[page_index] = {"header": header_paths, "footer": footer_paths}

    return result


def normalize_ref_number(reference: str) -> str:
    """"REF. 2406" / "REF 055" / "2406" -> "2406" / "55" (matches build_ref_index's keys).
    "REF 2212/1" / "REF.2212/2" -> "2212/1" / "2212/2" -- a base design offered
    in more than one size/variant keeps its "/N" suffix as part of the key,
    same as build_ref_index; without this, "REF 2212/1" and "REF 2212/2"
    would both normalize down to the same "2212" and become indistinguishable
    again downstream (get_locked_size_for_art, get_master_ref_entry) even
    after build_ref_index itself learned to tell them apart."""
    match = re.search(r"(\d+)(?:\s*/\s*0*(\d+))?", reference)
    if not match:
        return reference
    base = str(int(match.group(1)))  # int() strips leading zeros
    if match.group(2):
        return f"{base}/{int(match.group(2))}"
    return base


def export_shape_to_png(corel, master_document, page_index: int, shape_path: str, output_path: str) -> None:
    """Exports a clean, tight, transparent-background PNG of one shape --
    this is what gets embedded (CLIP) for photo identification, straight from
    the real artwork instead of a PDF raster crop. See
    CorelDrawService.export_shape_as_png for how (copy into a throwaway
    document, export that whole page) and why not a direct selection export."""
    corel.export_shape_as_png(master_document, page_index, shape_path, output_path)


def copy_artwork_shape(master_document, page_index: int, shape_path: str, max_attempts: int = 4):
    """Copies the shape(s) to the clipboard (via CorelDRAW's own Copy, same
    as a user pressing Ctrl+C) so they can be Paste()'d into a different
    document. shape_path can name several loose pieces (see
    _cluster_shapes/iter_shape_paths) -- all of them get selected together
    first so the single Copy() carries every piece, keeping their relative
    position to each other intact (CorelDrawService.paste_artwork groups
    them back into one shape after pasting).

    Retries on failure (same pattern as
    CorelDrawService.export_current_page_to_png) -- Selection().Copy() was
    seen to throw a bare coVGShape::Copy COM exception partway through a big
    batch (Windows clipboard contention from calling Copy() many times in a
    tight loop, not a problem with any specific shape), and it reliably
    succeeds on a retry a moment later."""
    shapes = resolve_shapes(master_document, page_index, shape_path)
    last_error = None
    for attempt in range(max_attempts):
        try:
            master_document.ClearSelection()
            for shape in shapes:
                shape.AddToSelection()
            master_document.Selection().Copy()
            return
        except Exception as ex:
            last_error = ex
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"COPY_FAILED após {max_attempts} tentativas (REF na página {page_index}): {last_error}")


def open_master_document(app, master_file_path: str):
    return app.OpenDocument(master_file_path)


def ensure_valid_cdr_file(input_path: str, output_path: str) -> str:
    """Accepts whatever shape the master file happens to arrive in and produces
    a real, openable .cdr at output_path:

    - An already-extracted folder (some tool on this machine auto-extracts
      modern .cdr files -- themselves a zip package, mimetype
      application/x-vnd.corel.zcf.draw.document+zip -- instead of leaving
      them alone): re-zips it (mimetype stored first, uncompressed, same
      convention the original package uses).
    - A plain "compress to zip" wrapper around a .cdr (right-click > send to
      compressed folder): extracts the .cdr member from inside it.
    - A .cdr file whose own zip IS the top-level structure already (as when
      it's renamed to .zip for sending, e.g. over WhatsApp): copied through
      as-is, since it's already valid, just extension-renamed.
    - A real, ordinary .cdr file: copied through unchanged.

    Either way returns output_path."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if os.path.isdir(input_path):
        mimetype_path = os.path.join(input_path, "mimetype")
        if not os.path.isfile(mimetype_path):
            raise ValueError(
                f"'{input_path}' é uma pasta mas não parece ser um .cdr descompactado "
                f"(falta o arquivo 'mimetype' dentro dela).")

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
            for root, _dirs, files in os.walk(input_path):
                for file_name in files:
                    full_path = os.path.join(root, file_name)
                    arcname = os.path.relpath(full_path, input_path).replace(os.sep, "/")
                    if arcname == "mimetype":
                        continue
                    zf.write(full_path, arcname)
        return output_path

    if zipfile.is_zipfile(input_path):
        with zipfile.ZipFile(input_path) as zf:
            names = zf.namelist()
            if "mimetype" in names:
                # The zip's own top level IS the .cdr package -- already valid,
                # just needs the right extension.
                shutil.copyfile(input_path, output_path)
                return output_path

            cdr_members = [n for n in names if n.lower().endswith(".cdr")]
            if not cdr_members:
                raise ValueError(
                    f"'{input_path}' é um .zip mas não encontrei nenhum arquivo .cdr dentro dele "
                    f"(nem parece ser o próprio .cdr zipado).")
            with zf.open(cdr_members[0]) as member, open(output_path, "wb") as out:
                shutil.copyfileobj(member, out)
        return output_path

    shutil.copyfile(input_path, output_path)
    return output_path


_CDR_METADATA_NAMESPACE = {"cdr": "http://namespace.corel.com/cdr/metadata/1.0/"}


def detect_cdr_app_version(input_path: str) -> int | None:
    """Best-effort: reads the exact CorelDRAW version a modern (2021+,
    "ZCF" zip-packaged) .cdr file was last saved with, straight from its
    own META-INF/metadata.xml -- <cdr:AppVersion>2300</cdr:AppVersion>
    means "saved by CorelDRAW.Application.23" (CorelDRAW 2021), confirmed
    against a real file here: matches the <cdr:ProductName>CorelDRAW
    2021</cdr:ProductName> recorded right next to it, and the version
    number convention (year - 1998) gui_page_settings.py's own version
    field already documents. Accepts the same input shapes as
    ensure_valid_cdr_file (a real .cdr, or a .zip wrapping/being one).

    Returns None for anything this can't read a version out of -- an
    older, plain-binary (pre-ZCF) .cdr has no such metadata at all, and
    there's no reliable, safely-guessed equivalent for those worth risking
    a wrong answer over. The caller should treat that as "unknown", not
    silently fall back to guessing."""
    zip_path = input_path
    if not zipfile.is_zipfile(zip_path):
        return None

    try:
        with zipfile.ZipFile(zip_path) as zf:
            with zf.open("META-INF/metadata.xml") as f:
                xml_bytes = f.read()
    except KeyError:
        return None

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None

    element = root.find(".//cdr:AppVersion", _CDR_METADATA_NAMESPACE)
    if element is None or not element.text:
        return None
    try:
        raw_version = int(element.text.strip())
    except ValueError:
        return None
    return raw_version // 100
