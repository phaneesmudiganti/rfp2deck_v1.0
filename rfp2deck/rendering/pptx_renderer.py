from __future__ import annotations

from pathlib import Path
import math

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt


# -------------------------------------------------
# Geometry + Layout Constants (Consistent)
# -------------------------------------------------

LEFT_MARGIN = 0.75
RIGHT_MARGIN = 0.75
TOP_Y = 1.55
BOTTOM_MARGIN = 0.55
SIDE_BY_SIDE_TEXT_RATIO = 0.45  # smaller text region
SIDE_BY_SIDE_IMAGE_RATIO = 0.55  # larger image region
GAP = 0.25


# -------------------------------------------------
# Helpers
# -------------------------------------------------

def _clear_text_placeholders(slide):
    for shape in slide.shapes:
        try:
            if getattr(shape, "is_placeholder", False) and shape.has_text_frame:
                shape.text_frame.clear()
        except Exception:
            continue


def _estimate_lines(text: str, approx_chars_per_line: int) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / max(1, approx_chars_per_line)))


def _estimate_bullets_height(bullets: list[str], font_pt: int, box_w_in: float) -> float:
    chars_per_inch_at_18 = 10
    chars_per_inch = chars_per_inch_at_18 * (18 / max(8, font_pt))
    approx_chars_per_line = int(max(18, box_w_in * chars_per_inch))

    lines = 0
    for b in bullets or []:
        lines += _estimate_lines(str(b), approx_chars_per_line)

    line_height_in = (font_pt * 1.25) / 72.0
    return lines * line_height_in + 0.2


def _fit_font(bullets, box_w_in, box_h_in, start=18, minimum=12):
    size = start
    while size > minimum:
        if _estimate_bullets_height(bullets, size, box_w_in) <= box_h_in:
            return size
        size -= 1
    return minimum


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


# -------------------------------------------------
# Core Rendering
# -------------------------------------------------

def _add_title(slide, prs, title: str):
    box = slide.shapes.add_textbox(
        Inches(LEFT_MARGIN),
        Inches(0.7),
        prs.slide_width - Inches(LEFT_MARGIN + RIGHT_MARGIN),
        Inches(0.8),
    )
    tf = box.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(28)
    p.font.bold = True
    p.alignment = PP_ALIGN.LEFT


def _add_bullets(slide, x, y, w, h, bullets, font_pt):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True

    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = str(b)
        p.font.size = Pt(font_pt)
        p.level = 0


def _render_standard(slide, prs, title, bullets, diagram=None):
    _add_title(slide, prs, title)

    approved = bool(diagram and getattr(diagram, "approved", False))
    image_path = getattr(diagram, "image_path", None) if diagram else None
    has_diagram = bool(approved and image_path)

    slide_w_in = prs.slide_width / 914400.0
    slide_h_in = prs.slide_height / 914400.0

    content_h = slide_h_in - TOP_Y - BOTTOM_MARGIN

    bullets = [b for b in bullets if str(b).strip()]
    if len(bullets) > 8:
        bullets = bullets[:8] + ["…"]

    # ---------------------------------
    # Side-by-side layout (consistent)
    # ---------------------------------

    if has_diagram:
        text_w = slide_w_in * SIDE_BY_SIDE_TEXT_RATIO
        image_w = slide_w_in * SIDE_BY_SIDE_IMAGE_RATIO - GAP

        font_pt = _fit_font(bullets, text_w, content_h)

        _add_bullets(
            slide,
            Inches(LEFT_MARGIN),
            Inches(TOP_Y),
            Inches(text_w),
            Inches(content_h),
            bullets,
            font_pt,
        )

        img_path = Path(image_path)
        if img_path.exists():
            _fit_image(
                slide,
                img_path,
                Inches(LEFT_MARGIN + text_w + GAP),
                Inches(TOP_Y),
                Inches(image_w),
                Inches(content_h),
            )
        return

    # ---------------------------------
    # Full-width text layout
    # ---------------------------------

    text_w = slide_w_in - (LEFT_MARGIN + RIGHT_MARGIN)
    font_pt = _fit_font(bullets, text_w, content_h)

    _add_bullets(
        slide,
        Inches(LEFT_MARGIN),
        Inches(TOP_Y),
        Inches(text_w),
        Inches(content_h),
        bullets,
        font_pt,
    )


def render_deck_from_template(deck_plan, template_path: Path, out_path: Path) -> Path:
    prs = Presentation(str(template_path))

    for slide_spec in deck_plan.slides:
        slide = prs.slides.add_slide(prs.slide_layouts[-1])
        _clear_text_placeholders(slide)

        _render_standard(
            slide,
            prs,
            slide_spec.title or "",
            slide_spec.bullets or [],
            diagram=getattr(slide_spec, "diagram", None),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path