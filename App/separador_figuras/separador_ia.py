"""Core figure-splitting logic for one AI-generated "sheet" image (several
Santa Clauses, snowmen, ornaments, etc. drawn together in a grid) -- pulled
out of the interactive back-and-forth that solved this live for a real batch
of images (see conversation): plain connected-component segmentation on the
alpha channel gets most sheets right on its own, but two real failure modes
showed up on real files and needed a second pass each:

  1. Two neighboring figures with no transparent gap between them (touching)
     collapse into one connected component -- caught here by comparing each
     piece's own size against the sheet's typical piece size and, when it's
     roughly double, finding the "pinch" row/column (least opaque pixels)
     and splitting there.
  2. Some exports have no real alpha channel at all -- a flat gray/white
     checkerboard is baked into the RGB pixels to *look* transparent in a
     preview. detect_fake_checkerboard()/remove_fake_checkerboard() catch
     that up front so the rest of the pipeline sees real transparency.

Neither pass is perfect (a single design with a large detached decorative
flourish -- a star above a text banner, say -- can still get read as two
separate pieces). That's why the GUI on top of this lets a person merge,
split, or drop a piece by hand: this module gets the common cases right
without help, and stays out of the way for a person to fix the rest.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from scipy import ndimage

MAIN_SIZE_FRACTION = 0.02  # a component bigger than 2% of the biggest one counts as its own piece
NOISE_MIN_PX = 30          # components smaller than this are pure noise, not even a decorative extra
FUSED_SIZE_RATIO = 1.6     # a piece whose bbox is this much taller/wider than the sheet's median is suspect
MIN_PIECES_FOR_FUSION_CHECK = 4  # below this, "median piece size" is too noisy to trust (see _auto_fix_fused_pieces)
WHOLE_BLOB_FRACTION = 0.6  # a single component this big a chunk of the opaque area might really be N touching figures
PADDING_PX = 18


class Piece:
    """One figure on the sheet -- a set of connected-component labels (the
    main blob plus whichever small decorative extras got attached to it)
    that together crop out to one clean image. Nothing here is pixel data;
    render() below does that on demand so merge/split/undo in the GUI only
    ever move label ids around, which is cheap."""

    def __init__(self, labels: set[int]):
        self.labels = set(labels)

    def bbox(self, bbox_by_label: dict[int, tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
        lefts, tops, rights, bottoms = zip(*(bbox_by_label[lb] for lb in self.labels))
        return min(lefts), min(tops), max(rights), max(bottoms)


class Sheet:
    """One imported source image plus everything the pieces are computed
    from -- the pixel array and the labeled connected-component map. Kept
    around (not thrown away after the initial split) so the GUI can re-crop
    on demand whenever pieces are merged or split further."""

    def __init__(self, path: str, rgba: np.ndarray, labeled: np.ndarray,
                 bbox_by_label: dict[int, tuple[int, int, int, int]], pieces: list[Piece]):
        self.path = path
        self.rgba = rgba
        self.labeled = labeled
        self.bbox_by_label = bbox_by_label
        self.pieces = pieces

    @property
    def height(self):
        return self.rgba.shape[0]

    @property
    def width(self):
        return self.rgba.shape[1]

    def render(self, piece: Piece) -> Image.Image:
        return render_piece(self.rgba, self.labeled, piece, self.bbox_by_label)

    def split_piece(self, piece: Piece) -> list[Piece]:
        return split_fused_piece(self.labeled, piece, self.bbox_by_label)


def detect_fake_checkerboard(rgba: np.ndarray) -> bool:
    """True when the image has NO real transparency (fully opaque) and its
    background looks like a flat gray/white checker pattern baked into the
    RGB pixels -- some export tools draw that as a stand-in for "this will
    be transparent" instead of an actual alpha channel. Sampling the four
    corners is enough: a real sheet's corners are either genuinely
    transparent already or hold actual artwork, never this specific
    checker-gray."""
    alpha = rgba[:, :, 3]
    if not np.all(alpha == 255):
        return False
    h, w = alpha.shape
    corners = [rgba[0:20, 0:20, :3], rgba[0:20, w - 20:w, :3],
               rgba[h - 20:h, 0:20, :3], rgba[h - 20:h, w - 20:w, :3]]
    for corner in corners:
        r, g, b = corner[:, :, 0].astype(int), corner[:, :, 1].astype(int), corner[:, :, 2].astype(int)
        grayish = (np.abs(r - g) <= 6) & (np.abs(g - b) <= 6)
        in_range = (np.minimum(r, b) >= 160) & (np.maximum(r, b) <= 235)
        if not (grayish & in_range).mean() > 0.5:
            return False
    return True


def remove_fake_checkerboard(rgba: np.ndarray) -> np.ndarray:
    """Turns transparent every pixel that matches the checker's flat gray
    palette (low color saturation, mid-range brightness) -- real artwork,
    even white/gray parts of it, almost never sits exactly in that narrow a
    band across a big contiguous area the way a repeating checker does."""
    arr = rgba.copy()
    r, g, b = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    maxc, minc = np.maximum(np.maximum(r, g), b), np.minimum(np.minimum(r, g), b)
    background = (maxc - minc <= 6) & (minc >= 160) & (maxc <= 235)
    arr[:, :, 3] = np.where(background, 0, arr[:, :, 3])
    return arr


def _try_watershed_split(opaque: np.ndarray) -> np.ndarray | None:
    """When (almost) the whole opaque area is ONE connected blob -- no gap
    at all between neighboring figures, the same problem _auto_fix_fused_pieces
    handles for a *pair* of touching figures, just total instead of partial
    -- repeatedly erodes the mask until the figures' own cores finally pull
    apart into >=2 pieces, then grows each core back out to its full extent
    by nearest-seed assignment (a distance-transform watershed) so no pixel
    is lost. Returns a fresh label map covering the whole opaque area, or
    None if even heavy erosion never finds more than one core (a real
    single-figure sheet, not a fused one)."""
    for iters in (6, 10, 15, 20, 28, 35):
        eroded = ndimage.binary_erosion(opaque, iterations=iters)
        seed_labeled, n = ndimage.label(eroded, structure=np.ones((3, 3)))
        if n < 2:
            continue
        sizes = ndimage.sum(eroded, seed_labeled, range(1, n + 1))
        # A real seed core has to be a sizeable fraction of the biggest one
        # found -- otherwise a small decorative accent (a snowflake, a
        # berry cluster) that happens to survive erosion as its own little
        # island becomes its own watershed seed, and being a seed means it
        # then claims a whole pie-slice of nearby space by nearest-distance,
        # not just its own few pixels -- silently carving a real figure's
        # territory down and creating a bogus extra "piece" out of nothing.
        biggest = sizes.max()
        keep_ids = [i + 1 for i, s in enumerate(sizes) if s > 200 and s >= biggest * 0.15]
        if len(keep_ids) < 2:
            continue
        seed_mask = np.isin(seed_labeled, keep_ids)
        seed_map = np.where(seed_mask, seed_labeled, 0)
        _, (iy, ix) = ndimage.distance_transform_edt(seed_map == 0, return_indices=True)
        nearest = seed_map[iy, ix]
        new_labeled = np.zeros(opaque.shape, dtype=np.int32)
        for new_id, sid in enumerate(keep_ids, start=1):
            new_labeled[opaque & (nearest == sid)] = new_id
        return new_labeled
    return None


def _label_components(rgba: np.ndarray, try_watershed: bool = False):
    alpha = rgba[:, :, 3]
    opaque = alpha > 10
    labeled, n = ndimage.label(opaque, structure=np.ones((3, 3)))

    # Only attempted when the caller already knows this sheet had no real
    # alpha and had a fake checkerboard background removed (see
    # detect_fake_checkerboard) -- that reliably means "several figures
    # merged into one blob with the background gone", so it's worth hunting
    # for separate cores. A real single design just as often has a natural
    # narrow waist of its own (a totem-style stack, a banner's swirl flowing
    # into its text) that erosion would "find" and wrongly slice apart, so
    # this is deliberately NOT tried on every big blob, only this one known
    # cause of it.
    if try_watershed and n:
        sizes = ndimage.sum(opaque, labeled, range(1, n + 1))
        if sizes.max() >= WHOLE_BLOB_FRACTION * opaque.sum():
            split = _try_watershed_split(opaque)
            if split is not None:
                labeled = split
                n = int(labeled.max())

    sizes = ndimage.sum(opaque, labeled, range(1, n + 1)) if n else np.array([])
    slices = ndimage.find_objects(labeled) if n else []
    bbox_by_label = {}
    center_by_label = {}
    size_by_label = {}
    for i, size in enumerate(sizes, start=1):
        sy, sx = slices[i - 1]
        bbox_by_label[i] = (sx.start, sy.start, sx.stop, sy.stop)
        center_by_label[i] = ((sx.start + sx.stop) / 2, (sy.start + sy.stop) / 2)
        size_by_label[i] = size
    return labeled, bbox_by_label, center_by_label, size_by_label


def _cluster_into_pieces(bbox_by_label, center_by_label, size_by_label) -> list[Piece]:
    labels = [lb for lb, s in size_by_label.items() if s >= NOISE_MIN_PX]
    if not labels:
        return []
    biggest = max(size_by_label[lb] for lb in labels)
    mains = [lb for lb in labels if size_by_label[lb] >= biggest * MAIN_SIZE_FRACTION]
    extras = [lb for lb in labels if lb not in mains]
    mains.sort(key=lambda lb: (center_by_label[lb][1], center_by_label[lb][0]))

    groups = {m: {m} for m in mains}
    for e in extras:
        ecx, ecy = center_by_label[e]
        best, best_d = None, None
        for m in mains:
            mcx, mcy = center_by_label[m]
            d = (ecx - mcx) ** 2 + (ecy - mcy) ** 2
            if best_d is None or d < best_d:
                best_d, best = d, m
        groups[best].add(e)

    return [Piece(labels) for labels in groups.values()]


def _split_fused_by_density(labeled, bbox_by_label, piece: Piece, axis: str):
    """axis: 'row' cuts horizontally (for two pieces stacked vertically),
    'col' cuts vertically (for two side by side). Finds the row/column with
    the fewest of THIS piece's own opaque pixels within its bounding box --
    the "pinch" between two touching figures -- and splits there.

    Two touching figures are usually still just ONE connected component (one
    label): there's nothing to regroup by existing label membership, so the
    split has to happen at the pixel level and mint two brand-new label ids
    for the two sides, mutating the shared `labeled` array and bbox map in
    place (every other Piece's `.labels` stays a valid reference into it
    either way, since ids are only ever added here, never reused)."""
    left, top, right, bottom = piece.bbox(bbox_by_label)
    region = labeled[top:bottom, left:right]
    own = np.isin(region, list(piece.labels))
    counts = own.sum(axis=1 if axis == "row" else 0)
    n = len(counts)
    lo, hi = int(n * 0.25), int(n * 0.75)
    if hi <= lo:
        return None
    band = counts[lo:hi]
    cut = lo + int(np.argmin(band))

    # Require an actual pinch -- meaningfully thinner than typical, not just
    # whatever row happens to be the (still-substantial) minimum -- so a
    # genuinely single figure with some natural waviness in its silhouette
    # doesn't get sliced in two for no real reason (matters most for the
    # GUI's manual "Dividir" button, which can be clicked on anything).
    typical = float(np.median(counts[counts > 0])) if (counts > 0).any() else 0
    if typical <= 0 or counts[cut] > 0.5 * typical:
        return None

    side_a_mask = np.zeros(region.shape, dtype=bool)
    side_b_mask = np.zeros(region.shape, dtype=bool)
    if axis == "row":
        side_a_mask[:cut, :] = True
        side_b_mask[cut:, :] = True
    else:
        side_a_mask[:, :cut] = True
        side_b_mask[:, cut:] = True
    area_a, area_b = own & side_a_mask, own & side_b_mask
    if not area_a.any() or not area_b.any():
        return None

    new_id_a, new_id_b = int(labeled.max()) + 1, int(labeled.max()) + 2
    region[area_a] = new_id_a
    region[area_b] = new_id_b
    labeled[top:bottom, left:right] = region

    for new_id in (new_id_a, new_id_b):
        ys, xs = np.where(labeled == new_id)
        bbox_by_label[new_id] = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)

    return Piece({new_id_a}), Piece({new_id_b})


def split_fused_piece(labeled, piece: Piece, bbox_by_label) -> list[Piece]:
    """Tries a horizontal split first (the common case: two figures stacked
    in the same grid column), then vertical, then gives up and returns the
    piece unchanged. Used both by the automatic fused-pair pass below and by
    the GUI's manual "dividir" button."""
    for axis in ("row", "col"):
        result = _split_fused_by_density(labeled, bbox_by_label, piece, axis)
        if result:
            return list(result)
    return [piece]


def _auto_fix_fused_pieces(labeled, pieces: list[Piece], bbox_by_label) -> list[Piece]:
    # Below this many pieces, there aren't enough of them for "the median
    # piece size" to mean anything -- a small design with one big detached
    # decoration (e.g. a text banner with a star above it) would otherwise
    # get its own main blob mistaken for "double size, must be fused" and
    # sliced in two for no reason. A real grid of touching figures always
    # has several pieces to begin with, so this never blocks the case it's
    # meant to catch.
    if len(pieces) < MIN_PIECES_FOR_FUSION_CHECK:
        return pieces
    heights, widths = [], []
    for p in pieces:
        l, t, r, b = p.bbox(bbox_by_label)
        widths.append(r - l)
        heights.append(b - t)
    med_h, med_w = float(np.median(heights)), float(np.median(widths))

    fixed = []
    for p, h, w in zip(pieces, heights, widths):
        is_fused = (med_h > 0 and h >= med_h * FUSED_SIZE_RATIO) or (med_w > 0 and w >= med_w * FUSED_SIZE_RATIO)
        if is_fused:
            fixed.extend(split_fused_piece(labeled, p, bbox_by_label))
        else:
            fixed.append(p)
    return fixed


def render_piece(rgba: np.ndarray, labeled: np.ndarray, piece: Piece,
                  bbox_by_label: dict[int, tuple[int, int, int, int]], padding=PADDING_PX) -> Image.Image:
    h, w = rgba.shape[:2]
    left, top, right, bottom = piece.bbox(bbox_by_label)
    left, top = max(0, left - padding), max(0, top - padding)
    right, bottom = min(w, right + padding), min(h, bottom + padding)

    region = rgba[top:bottom, left:right].copy()
    region_labels = labeled[top:bottom, left:right]
    foreign = (region_labels != 0) & ~np.isin(region_labels, list(piece.labels))
    region[foreign, 3] = 0
    return Image.fromarray(region, "RGBA")


def load_sheet(path: str) -> Sheet:
    im = Image.open(path).convert("RGBA")
    rgba = np.array(im)
    was_fake_checkerboard = detect_fake_checkerboard(rgba)
    if was_fake_checkerboard:
        rgba = remove_fake_checkerboard(rgba)

    labeled, bbox_by_label, center_by_label, size_by_label = _label_components(
        rgba, try_watershed=was_fake_checkerboard)
    pieces = _cluster_into_pieces(bbox_by_label, center_by_label, size_by_label)
    pieces = _auto_fix_fused_pieces(labeled, pieces, bbox_by_label)
    return Sheet(path, rgba, labeled, bbox_by_label, pieces)
