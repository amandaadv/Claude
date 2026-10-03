"""Fixes up the AI vision model's bounding box before cropping: the model
sometimes returns a box that's too tight and cuts off part of the actual
illustration (its numeric estimate assumes a uniform grid instead of looking
at each illustration's real extent). Grows the box outward through connected
non-white pixels, starting from the AI's own box, so it settles onto the
illustration's true edges.

Two passes:
1. Grow each product's box independently (through connected non-white pixels)
   to find its own natural extent -- most products don't touch a neighbor and
   this alone gets them right.
2. Only for a pair whose grown boxes end up overlapping (this catalog packs
   some illustrations close enough, or with anti-aliasing faint enough, that
   pixel-connectivity alone can't tell two touching neighbors apart), clip
   both boxes back to the midpoint between their *original* AI-given
   positions -- a stable reference the conflict can be split around without
   needlessly shrinking pairs that never conflicted in the first place.
"""
import numpy as np
from PIL import Image
from scipy import ndimage

WHITE_THRESHOLD = 245  # a pixel counts as "content" if any RGB channel is below this
PAD_FRACTION = 0.5  # how far past the AI's own box to search, as a fraction of that box's size

Box = tuple[int, int, int, int]  # (left, top, width, height) in pixels


def _grow(page_image: Image.Image, box: Box, page_width_px: int, page_height_px: int) -> Box:
    left, top, width, height = box
    pad_x = max(10, int(width * PAD_FRACTION))
    pad_y = max(10, int(height * PAD_FRACTION))

    search_left = max(0, left - pad_x)
    search_top = max(0, top - pad_y)
    search_right = min(page_width_px, left + width + pad_x)
    search_bottom = min(page_height_px, top + height + pad_y)

    region = page_image.crop((search_left, search_top, search_right, search_bottom)).convert("RGB")
    arr = np.asarray(region)
    content_mask = np.any(arr < WHITE_THRESHOLD, axis=2)

    if not content_mask.any():
        return box

    labeled, _ = ndimage.label(content_mask, structure=np.ones((3, 3)))  # 8-connectivity

    seed_top = max(0, top - search_top)
    seed_left = max(0, left - search_left)
    seed_bottom = min(region.height, seed_top + height)
    seed_right = min(region.width, seed_left + width)

    seed_labels = set(labeled[seed_top:seed_bottom, seed_left:seed_right].flatten().tolist())
    seed_labels.discard(0)
    if not seed_labels:
        return box

    # Drop any touched component too small to plausibly be real content (a
    # stray anti-aliased pixel or compression speck) -- picking those up as
    # part of the seed set could only ever shrink or distort the result,
    # never help it.
    label_list = list(seed_labels)
    areas = dict(zip(label_list, ndimage.sum(content_mask, labeled, label_list)))
    min_real_area = max(200, 0.01 * width * height)
    real_labels = [lbl for lbl in label_list if areas[lbl] >= min_real_area]

    if len(real_labels) > 1:
        # The AI's box sometimes reaches far enough to touch a genuinely
        # different product (seen spanning two whole rows on one page), and
        # a single real illustration can also legitimately split into more
        # than one component (a scarf's color meeting the body can leave a
        # thin near-white seam). Tell them apart by proximity: start from
        # whichever component the *original* box actually covers the most
        # of (the one it was almost certainly drawn around), then only fold
        # in other components that sit right next to it -- a different grid
        # item is always separated by this catalog's much larger inter-item
        # margin, never just a hairline gap.
        slices = ndimage.find_objects(labeled)
        gap_threshold = max(15, 0.08 * min(width, height))

        def intersection_with_seed(lbl):
            sl = slices[lbl - 1]
            iy = max(0, min(sl[0].stop, seed_bottom) - max(sl[0].start, seed_top))
            ix = max(0, min(sl[1].stop, seed_right) - max(sl[1].start, seed_left))
            return iy * ix

        primary = max(real_labels, key=intersection_with_seed)
        primary_slice = slices[primary - 1]

        def gap_to_primary(lbl):
            sl = slices[lbl - 1]
            gap_y = max(0, max(sl[0].start, primary_slice[0].start)
                        - min(sl[0].stop, primary_slice[0].stop))
            gap_x = max(0, max(sl[1].start, primary_slice[1].start)
                        - min(sl[1].stop, primary_slice[1].stop))
            return max(gap_y, gap_x)

        seed_labels = {primary} | {lbl for lbl in real_labels if gap_to_primary(lbl) <= gap_threshold}
    elif real_labels:
        seed_labels = set(real_labels)

    combined_mask = np.isin(labeled, list(seed_labels))
    rows = np.any(combined_mask, axis=1)
    cols = np.any(combined_mask, axis=0)
    top_idx = int(np.argmax(rows))
    bottom_idx = len(rows) - 1 - int(np.argmax(rows[::-1]))
    left_idx = int(np.argmax(cols))
    right_idx = len(cols) - 1 - int(np.argmax(cols[::-1]))

    return (search_left + left_idx, search_top + top_idx,
            right_idx - left_idx + 1, bottom_idx - top_idx + 1)


def _overlaps(a: Box, b: Box) -> bool:
    al, at, aw, ah = a
    bl, bt, bw, bh = b
    return al < bl + bw and bl < al + aw and at < bt + bh and bt < at + ah


def _resolve_overlap(original_a: Box, original_b: Box, grown_a: Box, grown_b: Box) -> tuple[Box, Box]:
    oa_cx = original_a[0] + original_a[2] / 2
    ob_cx = original_b[0] + original_b[2] / 2
    oa_cy = original_a[1] + original_a[3] / 2
    ob_cy = original_b[1] + original_b[3] / 2

    # Which axis the two products are laid out along (side-by-side vs stacked)
    # comes from their original AI-given positions -- that part of the AI's
    # estimate (rough grid position) is reliable even when its exact box size
    # isn't. But WHERE to draw the split line uses the two *grown* boxes' own
    # overlap range, not the original boxes' midpoint: the original boxes
    # assumed a uniform grid, so a plain original-center split systematically
    # starves whichever illustration is naturally wider (it consistently lost
    # a sliver to its narrower neighbor in testing). Splitting the actual
    # contested (overlapping) range down the middle instead credits each side
    # with exactly how far it really grew.
    if abs(oa_cx - ob_cx) >= abs(oa_cy - ob_cy):
        left_box, right_box = (grown_a, grown_b) if oa_cx < ob_cx else (grown_b, grown_a)
        l_left, l_top, l_w, l_h = left_box
        r_left, r_top, r_w, r_h = right_box
        l_right_edge = l_left + l_w
        r_left_edge = r_left
        mid = (l_right_edge + r_left_edge) / 2 if r_left_edge < l_right_edge else l_right_edge
        l_right = min(l_left + l_w, mid)
        r_left_clamped = max(r_left, mid)
        left_box = (l_left, l_top, max(1, int(l_right - l_left)), l_h)
        right_box = (int(r_left_clamped), r_top, max(1, int(r_left + r_w - r_left_clamped)), r_h)
        return (left_box, right_box) if oa_cx < ob_cx else (right_box, left_box)
    else:
        top_box, bottom_box = (grown_a, grown_b) if oa_cy < ob_cy else (grown_b, grown_a)
        t_left, t_top, t_w, t_h = top_box
        b_left, b_top, b_w, b_h = bottom_box
        t_bottom_edge = t_top + t_h
        b_top_edge = b_top
        mid = (t_bottom_edge + b_top_edge) / 2 if b_top_edge < t_bottom_edge else t_bottom_edge
        t_bottom = min(t_top + t_h, mid)
        b_top_clamped = max(b_top, mid)
        top_box = (t_left, t_top, t_w, max(1, int(t_bottom - t_top)))
        bottom_box = (b_left, int(b_top_clamped), b_w, max(1, int(b_top + b_h - b_top_clamped)))
        return (top_box, bottom_box) if oa_cy < ob_cy else (bottom_box, top_box)


def refine_page(page_image: Image.Image, raw_boxes: list[Box],
                 page_width_px: int, page_height_px: int) -> list[Box]:
    """Refines every product box on a page at once (needed so pass 2 can compare
    each pair). Returns one box per entry in raw_boxes, same order."""
    grown = [_grow(page_image, box, page_width_px, page_height_px) for box in raw_boxes]

    n = len(grown)
    for i in range(n):
        for j in range(i + 1, n):
            if _overlaps(grown[i], grown[j]):
                grown[i], grown[j] = _resolve_overlap(raw_boxes[i], raw_boxes[j], grown[i], grown[j])

    return grown
