from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class ParsedDoc:
    text: str
    page_count: int


def parse_pdf(path: Path) -> ParsedDoc:
    doc = fitz.open(path)
    texts = []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        texts.append(f"\n\n--- PAGE {i+1} ---\n\n" + page.get_text("text"))
    return ParsedDoc(text="\n".join(texts).strip(), page_count=doc.page_count)
