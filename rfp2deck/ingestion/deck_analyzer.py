from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional
from pptx import Presentation

@dataclass
class TemplateInfo:
    slide_layout_names: List[str]
    masters: List[str]
    placeholder_map: Dict[str, Any]

def analyze_pptx_template(path: Path) -> TemplateInfo:
    prs = Presentation(str(path))
    layout_names = []
    for layout in prs.slide_layouts:
        name = getattr(layout, "name", None) or "layout"
        layout_names.append(name)

    masters = []
    for m in prs.slide_masters:
        masters.append(getattr(m, "name", "master"))

    # Best-effort placeholder map (layout -> placeholders)
    placeholder_map: Dict[str, Any] = {}
    for layout in prs.slide_layouts:
        lname = getattr(layout, "name", "layout")
        phs = []
        for shape in layout.placeholders:
            phs.append({
                "idx": shape.placeholder_format.idx,
                "type": str(shape.placeholder_format.type),
                "name": shape.name,
            })
        placeholder_map[lname] = phs

    return TemplateInfo(slide_layout_names=layout_names, masters=masters, placeholder_map=placeholder_map)
