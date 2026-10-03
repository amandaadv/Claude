"""Batch-resizes a set of already-cut figure PNGs (see separador_figuras/)
into one or more target sizes, each into its own numbered folder -- e.g. a
sticker sold in both a small and a large size needs the exact same artwork
exported twice, once per size, ready to hand off for production.

Sizes are in millimeters (matching every other size field in this project --
see gui_theme.SizeDialog, master_artwork's "MED WxHMM" captions) and resized
proportionally to FIT WITHIN that height/width box, never stretched to it --
same convention production_generator.py uses when placing artwork at a
locked size (a piece scaled to two independent numbers instead of one,
proportional factor comes out looking squished/stretched, which is exactly
what a customer would notice first on a printed decal).
"""
from __future__ import annotations

import os

from PIL import Image

DPI = 300  # matches coreldraw_service.export_shape_as_png's own default resolution
MM_PER_INCH = 25.4


def mm_to_px(mm: float) -> float:
    return mm / MM_PER_INCH * DPI


def resize_to_fit(image: Image.Image, height_mm: float, width_mm: float) -> Image.Image:
    """Scales `image` by ONE factor (never two independent ones) so it fits
    within height_mm x width_mm without exceeding either -- the resulting
    image's own pixel size is whichever of the two the aspect ratio allows,
    not necessarily an exact height_mm x width_mm canvas."""
    target_h_px = mm_to_px(height_mm)
    target_w_px = mm_to_px(width_mm)
    orig_w, orig_h = image.size
    scale = min(target_w_px / orig_w, target_h_px / orig_h)
    new_w = max(1, round(orig_w * scale))
    new_h = max(1, round(orig_h * scale))
    return image.resize((new_w, new_h), Image.LANCZOS)


def folder_name_for_size(height_mm: float, width_mm: float) -> str:
    """"MED WxHMM" elsewhere in this project always reads height-by-width
    (see master_artwork.REF_CAPTION_PATTERN's comment) -- kept the same way
    here so a folder named e.g. "90x56mm" means the same thing a designer
    reading "MED 90X56MM" on a master file would expect."""
    def fmt(n):
        return f"{n:g}"
    return f"{fmt(height_mm)}x{fmt(width_mm)}mm"


def generate_batch(image_paths: list[str], size_profiles: list[tuple[float, float]], output_dir: str) -> dict[str, int]:
    """size_profiles: [(height_mm, width_mm), ...]. Creates one subfolder of
    output_dir per profile (see folder_name_for_size) and saves every image
    in image_paths into each, resized for that profile. Returns
    {folder_name: count_saved}."""
    results = {}
    for height_mm, width_mm in size_profiles:
        folder_name = folder_name_for_size(height_mm, width_mm)
        folder_path = os.path.join(output_dir, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        count = 0
        for path in image_paths:
            image = Image.open(path).convert("RGBA")
            resized = resize_to_fit(image, height_mm, width_mm)
            out_name = os.path.basename(path)
            resized.save(os.path.join(folder_path, out_name))
            count += 1
        results[folder_name] = count
    return results
