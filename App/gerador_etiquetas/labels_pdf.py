"""Renders a printable sheet of labels (EAN-13 barcode + reference text) as a
PDF, using reportlab -- one label per figure (modo por_desenho) or per
figure+tamanho (modo por_tamanho). Pure layout/rendering: callers resolve
the actual reference/barcode data (db_etiquetas.py) and just hand this
module a flat list to draw; nothing here touches the database.
"""
from dataclasses import dataclass

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.eanbc import Ean13BarcodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

# Layout constants -- all in mm, not user-configurable (same reasoning as
# gerador_catalogos.py's grid constants: these are breathing room/print
# fitting, not content, so a fixed sensible default avoids UI clutter).
# Matches the physical label layout already in use: brand on top, then
# product type, then reference+size, then composition, then barcode at the
# bottom -- no border box (these print on pre-cut label sheets, not cut out
# after printing).
PAGE_MARGIN_MM = 10.0
LABEL_WIDTH_MM = 50.0
LABEL_HEIGHT_MM = 36.0
LABEL_SPACING_MM = 4.0
BARCODE_HEIGHT_MM = 13.0
BARCODE_MARGIN_MM = 3.0
TEXT_FONT_SIZE_PT = 7
BRAND_FONT_SIZE_PT = 8
BRAND_TEXT = "BABY LUZ"
LINE_HEIGHT_MM = 3.2


@dataclass
class LabelItem:
    reference_text: str
    ean13_code: str
    width_mm: float | None = None
    height_mm: float | None = None


def _draw_barcode(c: canvas.Canvas, ean13_code: str, x_mm: float, y_mm: float, target_width_mm: float) -> None:
    barcode = Ean13BarcodeWidget(ean13_code)
    natural_bounds = barcode.getBounds()
    natural_width_pt = natural_bounds[2] - natural_bounds[0]
    barcode.barWidth *= (target_width_mm * mm) / natural_width_pt
    barcode.barHeight = BARCODE_HEIGHT_MM * mm

    drawing = Drawing(target_width_mm * mm, BARCODE_HEIGHT_MM * mm + 12)
    drawing.add(barcode)
    renderPDF.draw(drawing, c, x_mm * mm, y_mm * mm)


def _draw_label(
    c: canvas.Canvas, item: LabelItem, x_mm: float, y_mm: float,
    product_type: str, composition: str,
) -> None:
    """(x_mm, y_mm) is the label's bottom-left corner. Text block on top
    (brand, product type, reference+size, composition), barcode at the
    bottom -- matches the physical label already in use. No border: these
    print on pre-cut/pre-gapped label sheets."""
    center_x_mm = x_mm + LABEL_WIDTH_MM / 2

    reference_line = item.reference_text
    if item.width_mm is not None and item.height_mm is not None:
        reference_line += f"   {item.width_mm:.0f}x{item.height_mm:.0f}mm"

    lines = [(BRAND_TEXT, BRAND_FONT_SIZE_PT)]
    if product_type:
        lines.append((product_type, TEXT_FONT_SIZE_PT))
    lines.append((reference_line, TEXT_FONT_SIZE_PT))
    if composition:
        lines.append((f"COMP. {composition}", TEXT_FONT_SIZE_PT))

    text_top_y_mm = y_mm + LABEL_HEIGHT_MM - LINE_HEIGHT_MM
    for i, (text, font_size) in enumerate(lines):
        c.setFont("Helvetica-Bold", font_size)
        line_y_mm = text_top_y_mm - i * LINE_HEIGHT_MM
        c.drawCentredString(center_x_mm * mm, line_y_mm * mm, text)

    barcode_width_mm = LABEL_WIDTH_MM - 2 * BARCODE_MARGIN_MM
    barcode_y_mm = y_mm + BARCODE_MARGIN_MM
    _draw_barcode(c, item.ean13_code, x_mm + BARCODE_MARGIN_MM, barcode_y_mm, barcode_width_mm)


def generate_label_sheet(
    items: list[LabelItem], output_path: str,
    product_type: str = "", composition: str = "",
) -> None:
    if not items:
        raise ValueError("nenhuma etiqueta pra gerar")

    c = canvas.Canvas(output_path, pagesize=A4)
    page_width_mm = A4[0] / mm
    page_height_mm = A4[1] / mm
    usable_width_mm = page_width_mm - 2 * PAGE_MARGIN_MM
    columns = max(1, int((usable_width_mm + LABEL_SPACING_MM) // (LABEL_WIDTH_MM + LABEL_SPACING_MM)))

    column_index = 0
    y_mm = page_height_mm - PAGE_MARGIN_MM - LABEL_HEIGHT_MM
    for item in items:
        x_mm = PAGE_MARGIN_MM + column_index * (LABEL_WIDTH_MM + LABEL_SPACING_MM)
        _draw_label(c, item, x_mm, y_mm, product_type, composition)

        column_index += 1
        if column_index >= columns:
            column_index = 0
            y_mm -= LABEL_HEIGHT_MM + LABEL_SPACING_MM
            if y_mm < PAGE_MARGIN_MM:
                c.showPage()
                y_mm = page_height_mm - PAGE_MARGIN_MM - LABEL_HEIGHT_MM

    c.save()
