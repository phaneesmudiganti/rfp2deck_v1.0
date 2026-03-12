from __future__ import annotations
from dataclasses import dataclass

EMU_PER_INCH = 914400


@dataclass
class OverflowResult:
    fits: bool
    font_pt: int
    est_lines: int
    max_lines: int
    max_chars_per_line: int


def _emu_to_inches(emu: int) -> float:
    return emu / EMU_PER_INCH


def estimate_fit(
    box_width_emu: int, box_height_emu: int, text: str, font_pt: int
) -> OverflowResult:
    """Heuristic overflow estimator (no PowerPoint rendering engine available)."""
    width_in = _emu_to_inches(int(box_width_emu))
    height_in = _emu_to_inches(int(box_height_emu))

    width_pt = width_in * 72.0 * 0.92
    height_pt = height_in * 72.0 * 0.92

    avg_char_w = max(4.0, 0.52 * font_pt)
    line_h = max(8.0, 1.2 * font_pt)

    max_chars_per_line = max(10, int(width_pt / avg_char_w))
    max_lines = max(1, int(height_pt / line_h))

    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    est_lines = 0
    for p in paragraphs:
        est_lines += max(1, (len(p) + max_chars_per_line - 1) // max_chars_per_line)

    fits = est_lines <= max_lines
    return OverflowResult(
        fits=fits,
        font_pt=font_pt,
        est_lines=est_lines,
        max_lines=max_lines,
        max_chars_per_line=max_chars_per_line,
    )


def find_fitting_font(
    box_width_emu: int,
    box_height_emu: int,
    text: str,
    start_font_pt: int = 18,
    min_font_pt: int = 10,
) -> OverflowResult:
    font = start_font_pt
    last = estimate_fit(box_width_emu, box_height_emu, text, font)
    if last.fits:
        return last
    while font > min_font_pt:
        font -= 1
        last = estimate_fit(box_width_emu, box_height_emu, text, font)
        if last.fits:
            return last
    return last
