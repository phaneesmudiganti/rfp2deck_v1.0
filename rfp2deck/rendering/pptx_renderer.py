from __future__ import annotations

from pathlib import Path
import math

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


def _find_blank_layout(prs: Presentation):
    for layout in prs.slide_layouts:
        name = (getattr(layout, "name", "") or "").lower()
        if "blank" in name:
            return layout
    return prs.slide_layouts[len(prs.slide_layouts) - 1]


def _apply_chrome(slide, prs, footer_text: str, slide_no: int, slide_total: int):
    banner = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.55))
    banner.fill.solid()
    banner.fill.fore_color.rgb = RGBColor(0x0B, 0x2D, 0x5B)
    banner.line.fill.background()

    footer_y = prs.slide_height - Inches(0.30)
    footer = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, footer_y, prs.slide_width, Inches(0.30))
    footer.fill.solid()
    footer.fill.fore_color.rgb = RGBColor(0xF2, 0xF4, 0xF7)
    footer.line.fill.background()

    ft = slide.shapes.add_textbox(Inches(0.4), footer_y + Inches(0.02), prs.slide_width - Inches(1.6), Inches(0.28))
    p = ft.text_frame.paragraphs[0]
    p.text = footer_text
    p.font.size = Pt(10)
    p.font.color.rgb = RGBColor(0x44, 0x44, 0x44)
    p.alignment = PP_ALIGN.LEFT

    sn = slide.shapes.add_textbox(prs.slide_width - Inches(1.2), footer_y + Inches(0.02), Inches(0.8), Inches(0.28))
    p2 = sn.text_frame.paragraphs[0]
    p2.text = f"{slide_no}/{slide_total}"
    p2.font.size = Pt(10)
    p2.font.color.rgb = RGBColor(0x44, 0x44, 0x44)
    p2.alignment = PP_ALIGN.RIGHT


def _fit_image(slide, image_path: Path, x, y, w, h):
    pic = slide.shapes.add_picture(str(image_path), x, y)
    img_w, img_h = pic.width, pic.height
    if img_w == 0 or img_h == 0:
        return pic
    scale = min(w / img_w, h / img_h)
    pic.width = int(img_w * scale)
    pic.height = int(img_h * scale)
    pic.left = x + int((w - pic.width) / 2)
    pic.top = y + int((h - pic.height) / 2)
    return pic


def _font_for_bullets(bullets: list[str], base: int = 18) -> int:
    total_chars = sum(len(b or "") for b in bullets)
    n = len(bullets)
    if n <= 3 and total_chars <= 220:
        return base
    if n <= 4 and total_chars <= 320:
        return max(16, base - 2)
    if total_chars <= 420:
        return max(15, base - 3)
    return max(14, base - 4)


def _clear_text_placeholders(slide):
    """Clear template placeholder text to avoid overlap with generated shapes."""
    for sh in slide.shapes:
        try:
            if getattr(sh, "is_placeholder", False) and sh.has_text_frame:
                sh.text_frame.clear()
        except Exception:
            continue

def _add_title(slide, prs, title: str, size: int = 28, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(Inches(0.6), Inches(0.7), prs.slide_width - Inches(1.2), Inches(0.75))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = title or ""
    p.font.size = Pt(size)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0x11, 0x11, 0x11)
    p.alignment = align
    return box



def _estimate_lines(text: str, approx_chars_per_line: int) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    return max(1, math.ceil(len(text) / max(1, approx_chars_per_line)))

def _estimate_bullets_height(bullets: list[str], font_pt: int, box_w_in: float) -> float:
    # Heuristic: approximate wrapped lines based on width and font
    chars_per_inch_at_18 = 10
    chars_per_inch = chars_per_inch_at_18 * (18 / max(8, font_pt))
    approx_chars_per_line = int(max(18, box_w_in * chars_per_inch))
    lines = 0
    for b in bullets or []:
        lines += _estimate_lines(str(b), approx_chars_per_line)
    line_h_in = (font_pt * 1.25) / 72.0
    return lines * line_h_in + 0.15

def _fit_bullets_font(bullets: list[str], box_w_in: float, box_h_in: float, start_pt: int = 18, min_pt: int = 12) -> int:
    pt = start_pt
    while pt > min_pt:
        if _estimate_bullets_height(bullets, pt, box_w_in) <= box_h_in:
            return pt
        pt -= 1
    return min_pt

def _add_bullets(slide, x, y, w, h, bullets: list[str], base_font: int = 18, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    fs = _font_for_bullets(bullets or [], base=base_font)
    for i, b in enumerate((bullets or [])[:10]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = str(b)
        p.level = 0
        p.font.size = Pt(fs)
        p.font.color.rgb = RGBColor(0x22, 0x22, 0x22)
        p.alignment = align
    return box


def _render_title_slide(slide, prs, title: str, bullets: list[str]):
    _add_title(slide, prs, title, size=36, align=PP_ALIGN.CENTER)
    sub = slide.shapes.add_textbox(Inches(1.0), Inches(1.8), prs.slide_width - Inches(2.0), Inches(2.2))
    tf = sub.text_frame
    tf.clear()
    tf.word_wrap = True
    for i, b in enumerate((bullets or [])[:3]):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = str(b)
        p.font.size = Pt(18)
        p.alignment = PP_ALIGN.CENTER


def _render_section_divider(slide, prs, title: str, subtitle: str = "Delivering Business Value and Governance Confidence"):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(2.0), Inches(1.1), Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor(0x0B, 0x2D, 0x5B)
    bar.line.fill.background()

    box = slide.shapes.add_textbox(Inches(0.6), Inches(2.15), prs.slide_width - Inches(1.2), Inches(1.2))
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = title or ""
    p.font.size = Pt(42)
    p.font.bold = True
    p.font.color.rgb = RGBColor(0x11, 0x11, 0x11)

    sub = slide.shapes.add_textbox(Inches(0.6), Inches(3.25), prs.slide_width - Inches(1.2), Inches(0.6))
    tf2 = sub.text_frame
    tf2.clear()
    p2 = tf2.paragraphs[0]
    p2.text = subtitle
    p2.font.size = Pt(16)
    p2.font.color.rgb = RGBColor(0x55, 0x55, 0x55)


def _render_agenda(slide, prs, title: str, bullets: list[str]):
    _add_title(slide, prs, title or "Agenda", size=30)
    items = bullets or []
    mid = (len(items) + 1) // 2
    left = items[:mid]
    right = items[mid:]
    _add_bullets(slide, Inches(0.9), Inches(1.6), Inches(4.4), prs.slide_height - Inches(2.2), left, base_font=18)
    if right:
        _add_bullets(slide, Inches(5.3), Inches(1.6), Inches(4.4), prs.slide_height - Inches(2.2), right, base_font=18)


def _render_team(slide, prs, title: str, bullets: list[str]):
    _add_title(slide, prs, title or "Team", size=30)
    roles = bullets or []
    mid = (len(roles) + 1) // 2
    left = roles[:mid]
    right = roles[mid:]
    _add_bullets(slide, Inches(0.9), Inches(1.65), Inches(4.4), prs.slide_height - Inches(2.2), left, base_font=18)
    if right:
        _add_bullets(slide, Inches(5.3), Inches(1.65), Inches(4.4), prs.slide_height - Inches(2.2), right, base_font=18)


def _render_commercials(slide, prs, title: str, bullets: list[str]):
    _add_title(slide, prs, title or "Commercials", size=30)
    options = bullets or []
    cards = min(3, len(options))
    if cards == 0:
        return
    card_w = (prs.slide_width - Inches(1.6) - Inches(0.4) * (cards - 1)) / cards
    y = Inches(1.75)
    h = Inches(3.0)
    for i in range(cards):
        x = Inches(0.8) + i * (card_w + Inches(0.4))
        rect = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, card_w, h)
        rect.fill.solid()
        rect.fill.fore_color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        rect.line.color.rgb = RGBColor(0xDD, 0xDD, 0xDD)

        tb = slide.shapes.add_textbox(x + Inches(0.25), y + Inches(0.25), card_w - Inches(0.5), h - Inches(0.5))
        tf = tb.text_frame
        tf.clear()
        p = tf.paragraphs[0]
        p.text = options[i]
        p.font.size = Pt(16)
        p.font.color.rgb = RGBColor(0x22, 0x22, 0x22)

    tail = options[cards:]
    if tail:
        _add_bullets(slide, Inches(0.9), Inches(4.9), prs.slide_width - Inches(1.8), prs.slide_height - Inches(5.5), tail[:3], base_font=16)



def _render_table(slide, prs, title: str, table: dict):
    _add_title(slide, prs, title, size=28, align=PP_ALIGN.LEFT)
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    n_cols = max(1, len(headers) if headers else (len(rows[0]) if rows else 1))
    n_rows = len(rows) + (1 if headers else 0)

    x = Inches(0.8)
    y = Inches(1.55)
    w = prs.slide_width - Inches(1.6)
    h = prs.slide_height - Inches(2.2)

    shape = slide.shapes.add_table(n_rows, n_cols, x, y, w, h)
    tbl = shape.table

    # column widths (simple heuristic)
    col_w = int(w / n_cols)
    for c in range(n_cols):
        tbl.columns[c].width = col_w

    r0 = 0
    if headers:
        for c in range(n_cols):
            cell = tbl.cell(0, c)
            cell.text = str(headers[c]) if c < len(headers) else ""
            for p in cell.text_frame.paragraphs:
                p.font.bold = True
                p.font.size = Pt(12)
        r0 = 1

    for r, row in enumerate(rows):
        for c in range(n_cols):
            cell = tbl.cell(r + r0, c)
            cell.text = str(row[c]) if c < len(row) else ""
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(11)

def _render_standard(slide, prs, title: str, bullets: list[str], diagram=None, *, diagram_dominant: bool = False):
    _add_title(slide, prs, title, size=28, align=PP_ALIGN.LEFT)

    approved = bool(diagram and getattr(diagram, "approved", False))
    image_path = getattr(diagram, "image_path", None) if diagram else None
    has_diagram = bool(approved and image_path)

    bullets = [b for b in (bullets or []) if str(b).strip()]
    if len(bullets) > 10:
        bullets = bullets[:10] + ["…"]

    # Geometry (inches)
    margin_l = 0.75
    margin_r = 0.75
    top_y = 1.55
    bottom_margin = 0.55
    slide_w_in = prs.slide_width / 914400.0
    content_h_in = (prs.slide_height / 914400.0) - top_y - bottom_margin

    # Diagram-dominant layout (Architecture)
    if diagram_dominant and has_diagram:
        img_path = Path(image_path)
        if img_path.exists():
            _fit_image(
                slide,
                img_path,
                Inches(margin_l),
                Inches(top_y),
                prs.slide_width - Inches(margin_l + margin_r),
                prs.slide_height - Inches(3.0),
            )

        if bullets:
            box_w = slide_w_in - (margin_l + margin_r)
            box_h = 1.25
            font_pt = _fit_bullets_font(bullets[:4], box_w, box_h, start_pt=16, min_pt=12)
            _add_bullets(
                slide,
                Inches(margin_l),
                prs.slide_height - Inches(2.55),
                prs.slide_width - Inches(margin_l + margin_r),
                Inches(box_h),
                bullets[:4],
                base_font=font_pt,
            )
        return

    # Side-by-side layout with auto-fit to avoid overlap
    if has_diagram:
        left_w = slide_w_in * 0.58
        gap = 0.25
        right_x = margin_l + left_w + gap
        right_w = slide_w_in - right_x - margin_r

        font_pt = _fit_bullets_font(bullets, left_w, content_h_in, start_pt=18, min_pt=12)
        _add_bullets(slide, Inches(margin_l), Inches(top_y), Inches(left_w), Inches(content_h_in), bullets, base_font=font_pt)

        img_path = Path(image_path)
        if img_path.exists() and right_w > 1.0 and content_h_in > 1.0:
            _fit_image(slide, img_path, Inches(right_x), Inches(top_y), Inches(right_w), Inches(content_h_in))
        return

    # Full-width text with auto-fit
    box_w = slide_w_in - (margin_l + margin_r)
    font_pt = _fit_bullets_font(bullets, box_w, content_h_in, start_pt=18, min_pt=12)
    _add_bullets(slide, Inches(margin_l), Inches(top_y), Inches(box_w), Inches(content_h_in), bullets, base_font=font_pt)
def render_deck_from_template(deck_plan, template_path: Path, out_path: Path) -> Path:
    prs = Presentation(str(template_path))
    blank = _find_blank_layout(prs)
    footer_text = "Confidential | Generated by rfp2deck"

    total = len(deck_plan.slides)
    for idx, slide_spec in enumerate(deck_plan.slides, start=1):
        slide = prs.slides.add_slide(blank)
        _apply_chrome(slide, prs, footer_text=footer_text, slide_no=idx, slide_total=total)

        title = getattr(slide_spec, "title", "") or ""
        bullets = getattr(slide_spec, "bullets", None) or []
        archetype = (getattr(slide_spec, "archetype", "") or "").strip()
        slide_id = (getattr(slide_spec, "slide_id", "") or "").strip()
        table = getattr(slide_spec, "table", None)

        if table:
            _render_table(slide, prs, title, table)
        elif archetype == "Title":
            _render_title_slide(slide, prs, title, bullets)
        elif slide_id.startswith("divider_"):
            _render_section_divider(slide, prs, title)
        elif archetype == "Agenda":
            _render_agenda(slide, prs, title, bullets)
        elif archetype == "Team":
            _render_team(slide, prs, title, bullets)
        elif archetype == "Commercials":
            _render_commercials(slide, prs, title, bullets)
        else:
            _render_standard(slide, prs, title, bullets, diagram=getattr(slide_spec, "diagram", None), diagram_dominant=(archetype == "Architecture"))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path
