from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

# -------------------------------------------------
# Consulting-style constants (16:9 safe)
# -------------------------------------------------
LEFT_MARGIN_IN = 0.75
RIGHT_MARGIN_IN = 0.75

TITLE_X_IN = LEFT_MARGIN_IN
TITLE_Y_IN = 0.60
TITLE_H_IN = 0.75

CONTENT_TOP_Y_IN = 1.45
BOTTOM_MARGIN_IN = 0.45

# 3-zone layout when diagram exists:
#   Title (top band)
#   Diagram (big middle)
#   Bullets (bottom band)
DIAGRAM_Y_IN = 1.55
DIAGRAM_H_IN = 3.75
BULLETS_Y_IN = 5.45
BULLETS_H_IN = 1.60

MAX_BULLETS = 6
MAX_BULLET_CHARS = 120

FONT_TITLE_PT = 28
FONT_BODY_START_PT = 18
FONT_BODY_MIN_PT = 12


# -------------------------------------------------
# Layout helpers
# -------------------------------------------------
def _find_blank_layout(prs: Presentation):
    """Pick a layout that won't bring master/layout marker text into edit mode."""
    # Try common names first
    for layout in prs.slide_layouts:
        name = (getattr(layout, "name", "") or "").lower()
        if "blank" in name or "empty" in name:
            return layout

    # Fallback: fewest placeholders
    best = prs.slide_layouts[0]
    best_cnt = 10**9
    for layout in prs.slide_layouts:
        try:
            cnt = len(layout.placeholders)
        except Exception:
            cnt = 999
        if cnt < best_cnt:
            best = layout
            best_cnt = cnt
    return best


def _clear_all_text(slide):
    """Clear any text frames on the newly created slide to avoid template markers."""
    for shape in slide.shapes:
        try:
            if getattr(shape, "has_text_frame", False):
                shape.text_frame.clear()
        except Exception:
            continue


def _remove_marker_shapes(slide):
    """
    Remove obvious marker text boxes like {{TITLE}}, {{CONTENT}} if present on the slide itself.
    Note: master/layout markers can’t be safely removed by python-pptx; blank layout selection handles those.
    """
    to_remove = []
    for shape in slide.shapes:
        try:
            if getattr(shape, "has_text_frame", False):
                txt = (shape.text_frame.text or "").strip()
                if ("{{" in txt and "}}" in txt) or txt.upper().startswith("TEMPLATE:"):
                    to_remove.append(shape)
        except Exception:
            continue

    for shape in to_remove:
        try:
            el = shape._element  # pylint: disable=protected-access
            el.getparent().remove(el)
        except Exception:
            try:
                shape.text_frame.clear()
            except Exception:
                pass


# -------------------------------------------------
# Text + fit helpers
# -------------------------------------------------
def _trim_bullets(bullets):
    out = []
    for b in bullets or []:
        s = str(b).strip()
        if not s:
            continue
        if len(s) > MAX_BULLET_CHARS:
            s = s[: MAX_BULLET_CHARS - 1].rstrip() + "…"
        out.append(s)
        if len(out) >= MAX_BULLETS:
            break
    return out


def _estimate_lines(text: str, chars_per_line: int) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / max(1, chars_per_line)))


def _estimate_bullets_height_in(bullets, font_pt: int, box_w_in: float) -> float:
    # rough: chars/inch scales inversely with font size
    chars_per_inch_at_18 = 10
    chars_per_inch = chars_per_inch_at_18 * (18 / max(8, font_pt))
    chars_per_line = max(18, int(box_w_in * chars_per_inch))

    total_lines = 0
    for b in bullets:
        total_lines += _estimate_lines(b, chars_per_line)

    line_h_in = (font_pt * 1.20) / 72.0
    return total_lines * line_h_in + 0.20


def _fit_font_for_box(
    bullets, box_w_in, box_h_in, start_pt=FONT_BODY_START_PT, min_pt=FONT_BODY_MIN_PT
) -> int:
    size = start_pt
    while size > min_pt:
        if _estimate_bullets_height_in(bullets, size, box_w_in) <= box_h_in:
            return size
        size -= 1
    return min_pt


# -------------------------------------------------
# Drawing helpers
# -------------------------------------------------
def _add_title(slide, prs: Presentation, title: str):
    w = prs.slide_width / 914400.0
    box_w = w - LEFT_MARGIN_IN - RIGHT_MARGIN_IN

    tb = slide.shapes.add_textbox(
        Inches(TITLE_X_IN), Inches(TITLE_Y_IN), Inches(box_w), Inches(TITLE_H_IN)
    )
    tf = tb.text_frame
    tf.clear()
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title or ""
    p.font.size = Pt(FONT_TITLE_PT)
    p.font.bold = True
    p.alignment = PP_ALIGN.LEFT


def _add_bullets(slide, x_in: float, y_in: float, w_in: float, h_in: float, bullets, font_pt: int):
    tb = slide.shapes.add_textbox(Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in))
    tf = tb.text_frame
    tf.clear()
    tf.word_wrap = True

    for i, b in enumerate(bullets):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = b
        p.font.size = Pt(font_pt)
        p.level = 0


def _place_image_contain(
    slide, image_path: Path, x_in: float, y_in: float, w_in: float, h_in: float
):
    """
    Place image inside a bounding box using contain semantics (no cropping),
    centered and scaled to fit.
    """
    x = Inches(x_in)
    y = Inches(y_in)
    w = Inches(w_in)
    h = Inches(h_in)

    pic = slide.shapes.add_picture(str(image_path), x, y)

    img_w, img_h = pic.width, pic.height
    if not img_w or not img_h:
        return

    scale = min(w / img_w, h / img_h)
    pic.width = int(img_w * scale)
    pic.height = int(img_h * scale)

    pic.left = x + int((w - pic.width) / 2)
    pic.top = y + int((h - pic.height) / 2)


# -------------------------------------------------
# Rendering
# -------------------------------------------------
def _render_consulting_slide(slide, prs: Presentation, title: str, bullets, diagram=None):
    """
    Consulting standard:
      - Title band at top
      - Big diagram in middle (if approved)
      - Bullets at bottom
    """
    _add_title(slide, prs, title)

    slide_w_in = prs.slide_width / 914400.0
    slide_h_in = prs.slide_height / 914400.0
    content_w_in = slide_w_in - LEFT_MARGIN_IN - RIGHT_MARGIN_IN

    # normalize bullets
    bullets = _trim_bullets(bullets or [])
    if not bullets:
        bullets = [
            "Key objectives and measurable outcomes aligned to the RFP.",
            "Our approach and assumptions for delivery and governance.",
            "Acceptance evidence and success criteria.",
        ]

    # approved diagram?
    approved = bool(diagram and getattr(diagram, "approved", False))
    image_path = getattr(diagram, "image_path", None) if diagram else None
    has_diagram = bool(approved and image_path and str(image_path).strip())

    if has_diagram:
        img = Path(str(image_path))
        if img.exists():
            # big middle image
            _place_image_contain(
                slide,
                img,
                LEFT_MARGIN_IN,
                DIAGRAM_Y_IN,
                content_w_in,
                DIAGRAM_H_IN,
            )

        # bottom bullets (short and fitted)
        font_pt = _fit_font_for_box(bullets, content_w_in, BULLETS_H_IN)
        _add_bullets(
            slide,
            LEFT_MARGIN_IN,
            BULLETS_Y_IN,
            content_w_in,
            BULLETS_H_IN,
            bullets,
            font_pt,
        )
        return

    # no diagram => make content occupy the main content area (not side-by-side)
    body_y = CONTENT_TOP_Y_IN
    body_h = slide_h_in - body_y - BOTTOM_MARGIN_IN
    font_pt = _fit_font_for_box(bullets, content_w_in, body_h)
    _add_bullets(slide, LEFT_MARGIN_IN, body_y, content_w_in, body_h, bullets, font_pt)


def render_deck_from_template(deck_plan, template_path: Path, out_path: Path) -> Path:
    prs = Presentation(str(template_path))
    blank = _find_blank_layout(prs)

    for slide_spec in deck_plan.slides:
        slide = prs.slides.add_slide(blank)
        _clear_all_text(slide)
        _remove_marker_shapes(slide)

        _render_consulting_slide(
            slide,
            prs,
            slide_spec.title or "",
            slide_spec.bullets or [],
            diagram=getattr(slide_spec, "diagram", None),
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return out_path
