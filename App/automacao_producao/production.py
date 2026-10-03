"""Port of ProductionLayoutCalculator.cs: given a list of arts (width/height in mm)
and a production profile (roll/sheet width/height, margins, spacing), packs them
in their original (unrotated) orientation into rows, and rows into pages. Never
rotates a piece to fit more copies per row -- these are printed appliqué designs,
not blank rectangles, so a 90°-rotated placement would print the artwork sideways.
"""
import math
from dataclasses import dataclass


@dataclass
class ProductionProfile:
    name: str
    width_mm: float
    height_mm: float
    margin_left_mm: float = 0.0
    margin_right_mm: float = 0.0
    margin_top_mm: float = 0.0
    margin_bottom_mm: float = 0.0
    spacing_h_mm: float = 0.0
    spacing_v_mm: float = 0.0

    @property
    def usable_width_mm(self) -> float:
        return self.width_mm - self.margin_left_mm - self.margin_right_mm

    @property
    def usable_height_mm(self) -> float:
        return self.height_mm - self.margin_top_mm - self.margin_bottom_mm


@dataclass
class LayoutRequestItem:
    catalog_art_id: int
    reference: str | None
    width_mm: float
    height_mm: float
    # None (default): fill one row with as many copies as fit the profile's
    # width -- the original behavior. A number: place exactly that many
    # copies total, across as many rows as it takes.
    quantity: int | None = None
    # None (default): a row keeps filling with whatever comes next --
    # possibly a DIFFERENT figure -- as long as it still fits the width
    # (see calculate_layout's row-packing pass). A number: this item's own
    # copies never share a row with a different item's, and never exceed
    # this many in one row even if more would still fit by width -- e.g.
    # "12 cópias por linha" for a whole-catalog production run, where
    # every figure needs its own clean, uniform rows instead of packing
    # for maximum width efficiency.
    max_per_row: int | None = None


@dataclass
class ProductionPiece:
    catalog_art_id: int
    reference: str | None
    orientation: str  # "Normal" or "Rotated90"
    width_mm: float
    height_mm: float
    x_mm: float


@dataclass
class ProductionRow:
    y_mm: float
    height_mm: float
    pieces: list[ProductionPiece]

    @property
    def quantity(self) -> int:
        return len(self.pieces)


@dataclass
class ProductionPage:
    page_number: int
    rows: list[ProductionRow]


@dataclass
class ProductionPlan:
    pages: list[ProductionPage]

    @property
    def total_art_count(self) -> int:
        return sum(row.quantity for page in self.pages for row in page.rows)


# A row/page that would only barely miss fitting (by a sliver) used to get
# pushed out entirely -- one fewer copy per row, or a whole extra page for
# one row -- even though a few mm past the strict usable edge is fine in
# practice. Letting the fit checks go this far over recovers those
# almost-fit cases without meaningfully risking the actual printable area.
OVERFLOW_TOLERANCE_MM = 5.0

# When a row's pieces stop short of the full usable width -- the next piece
# just didn't fit -- every piece in that row gets stretched a little wider
# to close the gap instead of leaving a strip of material unused. Same
# manual fix an operator already does in CorelDRAW: select the whole row,
# drag it a bit wider. Height is left alone, spacing between pieces is left
# alone -- only each piece's own width grows. Capped so a row that would
# need a big jump to fill (few/wide pieces leaving most of the row empty)
# is left as-is instead of getting visibly stretched out of shape -- that's
# not the "a little wider" an operator would actually do by hand.
ROW_FILL_MAX_STRETCH = 1.20


def _stretch_row_to_fill(
    row: list[tuple], row_width_mm: float, usable_width_mm: float, spacing_h_mm: float,
) -> tuple[list[tuple], float]:
    piece_count = len(row)
    if piece_count == 0:
        return row, row_width_mm
    total_spacing_mm = spacing_h_mm * (piece_count - 1)
    current_pieces_width_mm = row_width_mm - total_spacing_mm
    if current_pieces_width_mm <= 0 or row_width_mm >= usable_width_mm:
        return row, row_width_mm  # nothing to fill, or already at/over width

    target_pieces_width_mm = usable_width_mm - total_spacing_mm
    stretch_factor = target_pieces_width_mm / current_pieces_width_mm
    if stretch_factor <= 1.0 or stretch_factor > ROW_FILL_MAX_STRETCH:
        return row, row_width_mm  # gap too big to close with a small stretch

    stretched_row = []
    x_mm = 0.0
    for art_id, reference, orientation, width_mm, height_mm, _old_x_mm in row:
        new_width_mm = width_mm * stretch_factor
        stretched_row.append((art_id, reference, orientation, new_width_mm, height_mm, x_mm))
        x_mm += new_width_mm + spacing_h_mm
    return stretched_row, x_mm - spacing_h_mm


def _units_that_fit(usable_width_mm: float, item_width_mm: float, spacing_h_mm: float) -> int:
    tolerant_width_mm = usable_width_mm + OVERFLOW_TOLERANCE_MM
    return math.floor((tolerant_width_mm + spacing_h_mm) / (item_width_mm + spacing_h_mm))


def _choose_orientation(width_mm: float, height_mm: float, usable_width_mm: float, spacing_h_mm: float):
    normal_units = _units_that_fit(usable_width_mm, width_mm, spacing_h_mm)
    return "Normal", normal_units, width_mm, height_mm


def units_per_row(width_mm: float, height_mm: float, profile: ProductionProfile, rotated: bool) -> int:
    """How many copies of one piece fit side by side in a row of this profile, in its ORIGINAL
    orientation (rotated=False) or lying on its other side (rotated=True, as if force_orientation
    had rotated it 90°) -- used to tell the operator, before generating, which way actually fits
    more (see gui_page_queue.py's "Orientação das peças" question)."""
    effective_width_mm = height_mm if rotated else width_mm
    return _units_that_fit(profile.usable_width_mm, effective_width_mm, profile.spacing_h_mm)




def calculate_layout(
    items: list[LayoutRequestItem], profile: ProductionProfile, fill_rows: bool = True,
) -> ProductionPlan:
    """fill_rows=True (default, the original behavior): a row that ends short of the sheet width has its pieces
    stretched WIDER (up to ROW_FILL_MAX_STRETCH) to fill it -- so a piece can come out wider than its
    catalog size. fill_rows=False keeps every piece at exactly its own width/height."""
    if not items:
        raise ValueError("At least one item is required.")

    usable_width_mm = profile.usable_width_mm
    usable_height_mm = profile.usable_height_mm
    if usable_width_mm <= 0:
        raise ValueError("Profile usable width must be positive after margins.")
    if usable_height_mm <= 0:
        raise ValueError("Profile usable height must be positive after margins.")

    # Expand every item into one entry per individual copy first (still in
    # item order -- a figure's own copies stay grouped together, they just
    # no longer force a fresh row for the NEXT figure). Validated per item
    # up front, same checks and messages as before.
    pending: list[tuple] = []  # (catalog_art_id, reference, orientation, width_mm, height_mm, max_per_row)
    for item in items:
        if item.width_mm <= 0 or item.height_mm <= 0:
            raise ValueError(f"Item dimensions must be positive (CatalogArtId={item.catalog_art_id}).")

        orientation, units, placed_width_mm, placed_height_mm = _choose_orientation(
            item.width_mm, item.height_mm, usable_width_mm, profile.spacing_h_mm)

        if units <= 0:
            raise ValueError(
                f"{item.reference or f'id={item.catalog_art_id}'}: largura {item.width_mm}mm não cabe na "
                f"área útil da folha ({usable_width_mm}mm) -- confira se essa medida não tem um erro de "
                f"digitação na legenda do catálogo.")
        if placed_height_mm > usable_height_mm:
            raise ValueError(
                f"{item.reference or f'id={item.catalog_art_id}'}: altura {item.height_mm}mm não cabe na "
                f"área útil da folha ({usable_height_mm}mm) -- confira se essa medida não tem um erro de "
                f"digitação na legenda do catálogo.")

        # None means "one row, auto-filled" (the original behavior) -- a
        # real quantity means "place exactly that many" copies of this item.
        count = units if item.quantity is None else item.quantity
        for _ in range(count):
            pending.append((
                item.catalog_art_id, item.reference, orientation, placed_width_mm, placed_height_mm,
                item.max_per_row))

    # Row-packing pass, left to right across the WHOLE pending list --
    # wraps to a new row only when the next piece truly doesn't fit what's
    # left of the current one, regardless of whether it's the same figure
    # as the piece before it. This is the one real behavior change from the
    # old per-item loop (which always started a fresh row per figure, even
    # with plenty of width left over from the previous one) -- same idea
    # already proven in montador_folha_ia._pack_rows, just inlined here so
    # this shared engine (real customer production, not just that one
    # tool) gets it too.
    rows: list[tuple[float, list[tuple]]] = []  # (row_height_mm, [(art_id, ref, orient, w, h, x_mm), ...])
    row: list[tuple] = []
    row_width_mm = 0.0
    row_height_mm = 0.0
    row_item_id = None
    row_item_count = 0

    for catalog_art_id, reference, orientation, width_mm, height_mm, max_per_row in pending:
        candidate_width_mm = width_mm if not row else row_width_mm + profile.spacing_h_mm + width_mm
        width_overflow = bool(row) and candidate_width_mm > usable_width_mm + OVERFLOW_TOLERANCE_MM
        # These two only ever trigger when max_per_row is actually set (see
        # LayoutRequestItem) -- a normal call (max_per_row=None everywhere)
        # behaves exactly as before, mixing figures freely by width alone.
        item_changed = bool(row) and max_per_row is not None and catalog_art_id != row_item_id
        row_full = bool(row) and max_per_row is not None and row_item_count >= max_per_row
        if row and (width_overflow or item_changed or row_full):
            if fill_rows:
                filled_row, _ = _stretch_row_to_fill(row, row_width_mm, usable_width_mm, profile.spacing_h_mm)
            else:
                filled_row = row
            rows.append((row_height_mm, filled_row))
            row, row_width_mm, row_height_mm = [], 0.0, 0.0
            row_item_id, row_item_count = None, 0
            candidate_width_mm = width_mm

        x_mm = 0.0 if not row else row_width_mm + profile.spacing_h_mm
        row.append((catalog_art_id, reference, orientation, width_mm, height_mm, x_mm))
        row_width_mm = candidate_width_mm
        row_height_mm = max(row_height_mm, height_mm)
        if row_item_id == catalog_art_id:
            row_item_count += 1
        else:
            row_item_id, row_item_count = catalog_art_id, 1

    if row:
        if fill_rows:
            filled_row, _ = _stretch_row_to_fill(row, row_width_mm, usable_width_mm, profile.spacing_h_mm)
        else:
            filled_row = row
        rows.append((row_height_mm, filled_row))

    # Page-packing pass, vertical axis -- every row's height is already
    # final by now, so this is the same bin-packing idea turned 90 degrees.
    pages: list[ProductionPage] = []
    current_page_rows: list[ProductionRow] = []
    current_page_number = 1
    bottom_usable_y_mm = 0.0

    for row_height_mm, row_pieces in rows:
        if not current_page_rows:
            top_usable_y_mm = 0.0
        else:
            candidate_top_usable_y_mm = bottom_usable_y_mm + profile.spacing_v_mm
            if candidate_top_usable_y_mm + row_height_mm > usable_height_mm + OVERFLOW_TOLERANCE_MM:
                pages.append(ProductionPage(current_page_number, current_page_rows))
                current_page_rows = []
                current_page_number += 1
                top_usable_y_mm = 0.0
            else:
                top_usable_y_mm = candidate_top_usable_y_mm

        absolute_y_mm = profile.margin_top_mm + top_usable_y_mm
        pieces = [
            ProductionPiece(art_id, reference, orientation, width_mm, height_mm, profile.margin_left_mm + x_mm)
            for art_id, reference, orientation, width_mm, height_mm, x_mm in row_pieces
        ]
        current_page_rows.append(ProductionRow(absolute_y_mm, row_height_mm, pieces))
        bottom_usable_y_mm = top_usable_y_mm + row_height_mm

    pages.append(ProductionPage(current_page_number, current_page_rows))
    return ProductionPlan(pages)
