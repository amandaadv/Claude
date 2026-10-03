"""Saves/deletes art images under the same storage/catalogs/<id>/ layout
FileArtImageStorage.cs uses, so the WPF app can read images this CLI writes
(and vice versa).
"""
import io
import os
import shutil

import numpy as np
from PIL import Image
from scipy import ndimage

import paths

PREVIEW_MAX_DIMENSION_PX = 300
# For the website's zoom/lightbox popup specifically -- confirmed live
# that stretching the small PREVIEW_MAX_DIMENSION_PX=300 thumbnail up to
# fill a phone screen looked visibly blurry. Big enough to look sharp
# zoomed in, still far smaller than a real original (which can be a
# multi-megapixel export straight off the master .cdr) so publishing a
# whole catalog's worth of these doesn't blow up the publish payload/time
# the same way sending real originals for every REF would.
ZOOM_MAX_DIMENSION_PX = 900


def save_art_images(catalog_id: int, page_number: int, art_index_on_page: int, image_bytes: bytes):
    catalog_folder = os.path.join(paths.STORAGE_FOLDER, "catalogs", str(catalog_id))
    originals_folder = os.path.join(catalog_folder, "originals")
    previews_folder = os.path.join(catalog_folder, "previews")
    os.makedirs(originals_folder, exist_ok=True)
    os.makedirs(previews_folder, exist_ok=True)

    base_file_name = f"p{page_number}-{art_index_on_page}"
    original_path = os.path.join(originals_folder, f"{base_file_name}.png")
    with open(original_path, "wb") as f:
        f.write(image_bytes)

    preview_path = os.path.join(previews_folder, f"{base_file_name}.jpg")
    _save_preview(image_bytes, preview_path)

    return original_path, preview_path


def _flatten_and_resize(image_bytes: bytes, max_dimension: int) -> Image.Image:
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        # Flatten onto white first -- a plain .convert("RGB") on a transparent
        # source (e.g. artwork exported straight from the master .cdr) fills
        # transparent areas with black instead, which looks broken as a preview.
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        image = background
    else:
        image = image.convert("RGB")
    scale = min(1.0, max_dimension / max(image.width, image.height))
    target_size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(target_size, Image.BILINEAR)


def _save_preview(image_bytes: bytes, preview_path: str) -> None:
    _flatten_and_resize(image_bytes, PREVIEW_MAX_DIMENSION_PX).save(preview_path, "JPEG", quality=85)


def generate_zoom_jpeg_bytes(original_path: str) -> bytes:
    """A bigger, higher-quality JPEG made from an art's REAL original file
    -- built specifically for do_publish_catalog to send alongside the
    small preview, for the website's zoom popup. Not persisted to disk:
    generated fresh at publish time straight from the on-disk original,
    since it's only ever needed as part of that one HTTP payload."""
    with open(original_path, "rb") as f:
        image_bytes = f.read()
    image = _flatten_and_resize(image_bytes, ZOOM_MAX_DIMENSION_PX)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


_WHITE_THRESHOLD = 248  # so alto pra nao confundir uma cor clara real do desenho (creme, gelo) com fundo


def trim_transparent_border(image_bytes: bytes, margin_px: int = 2) -> bytes | None:
    """Crops away any margin of padding around the real content -- either
    truly transparent (alpha near 0) or a plain near-white background that
    was never actually made transparent (confirmed live: some figures in a
    batch go through AI background removal and end up with real
    transparency, others don't and just sit on a white canvas -- the two
    look identical in a normal preview, but only the first kind had
    anything for an alpha-only crop to find).

    An AI-generated figure is often exported on a canvas much bigger than
    its own drawn content. That padding is invisible in a normal preview,
    but it's still part of the shape's bounding box everywhere a size gets
    applied to it: at production time (production_generator.py resizes
    the WHOLE imported bitmap to the piece's recorded width_mm/height_mm,
    so the padding eats into that box and the visible motif prints
    smaller than intended) and in "Montar Pedido"/catalog layout (the
    padding counts toward how much row width one copy takes, so fewer
    copies fit per row than the real content would need). Trimming the
    file itself fixes both at once, with no other code needing to change.

    Only a near-white/transparent region actually CONNECTED to the
    canvas's outer edge counts as background -- flood-filled in from the
    four sides, not just any pixel that happens to be pale (see
    _WHITE_THRESHOLD). A plain per-pixel color check would just as
    happily eat into the artwork's own white fur/snow/lace sitting well
    inside the canvas; requiring the connection to the border means only
    genuine padding -- the part a real crop tool would actually trim --
    ever gets removed.

    margin_px keeps a small cushion around the tightest possible crop --
    0 risks nicking a soft/anti-aliased edge pixel that's barely part of
    the background color but still visually part of the artwork's edge.

    Returns the cropped PNG bytes, or None when there's nothing worth
    doing: the whole image is background (no real content), or the
    content already fills the canvas edge to edge."""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    arr = np.asarray(image)
    alpha = arr[:, :, 3]
    rgb = arr[:, :, :3]

    is_background_color = (alpha < 10) | (np.all(rgb >= _WHITE_THRESHOLD, axis=2) & (alpha >= 245))
    if not is_background_color.any():
        return None  # nada de fundo pra recortar (imagem 100% opaca e nao-branca ate a borda)

    labeled, _ = ndimage.label(is_background_color, structure=np.ones((3, 3)))
    border_labels = set(labeled[0, :]) | set(labeled[-1, :]) | set(labeled[:, 0]) | set(labeled[:, -1])
    border_labels.discard(0)
    if not border_labels:
        return None  # a borda da imagem ja e conteudo (nada de fundo encostando nela)

    background_mask = np.isin(labeled, list(border_labels))
    content_mask = ~background_mask
    if not content_mask.any():
        return None  # imagem inteira e fundo -- sem conteudo real pra recortar

    rows = np.any(content_mask, axis=1)
    cols = np.any(content_mask, axis=0)
    top = int(np.argmax(rows))
    bottom = len(rows) - 1 - int(np.argmax(rows[::-1]))
    left = int(np.argmax(cols))
    right = len(cols) - 1 - int(np.argmax(cols[::-1]))

    left = max(0, left - margin_px)
    top = max(0, top - margin_px)
    right = min(image.width - 1, right + margin_px)
    bottom = min(image.height - 1, bottom + margin_px)
    if (left, top, right + 1, bottom + 1) == (0, 0, image.width, image.height):
        return None  # ja esta justo, nada pra fazer

    cropped = image.crop((left, top, right + 1, bottom + 1))
    buffer = io.BytesIO()
    cropped.save(buffer, "PNG")
    return buffer.getvalue()


def backup_and_replace_art_image(
    catalog_id: int, original_path: str, preview_path: str, new_image_bytes: bytes, backup_tag: str,
) -> None:
    """Used by the batch image enhancer: keeps the pre-enhancement original
    (and its preview) under backups/catalogs/<id>/<backup_tag>/ -- same
    layout as the live originals/previews folders, just one level deeper --
    before overwriting both with the AI-edited version. backup_tag is one
    timestamp per batch run, so every figure touched in the same run lands
    together and a bad run can be told apart from other runs."""
    backup_folder = os.path.join(paths.BACKUPS_FOLDER, "catalogs", str(catalog_id), backup_tag)
    os.makedirs(backup_folder, exist_ok=True)
    if os.path.exists(original_path):
        shutil.copy2(original_path, os.path.join(backup_folder, os.path.basename(original_path)))
    if os.path.exists(preview_path):
        shutil.copy2(preview_path, os.path.join(backup_folder, os.path.basename(preview_path)))

    with open(original_path, "wb") as f:
        f.write(new_image_bytes)
    _save_preview(new_image_bytes, preview_path)


def delete_catalog_images(catalog_id: int) -> None:
    catalog_folder = os.path.join(paths.STORAGE_FOLDER, "catalogs", str(catalog_id))
    if os.path.isdir(catalog_folder):
        shutil.rmtree(catalog_folder)
