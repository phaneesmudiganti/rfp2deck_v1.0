from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

import fitz  # PyMuPDF


@dataclass
class ParsedDoc:
    text: str
    page_count: int


def parse_pdf(path_or_bytes: Union[Path, bytes]) -> ParsedDoc:
    if isinstance(path_or_bytes, bytes):
        doc = fitz.open(stream=path_or_bytes, filetype="pdf")
    else:
        doc = fitz.open(path_or_bytes)
    texts = []
    for i in range(doc.page_count):
        page = doc.load_page(i)
        texts.append(f"\n\n--- PAGE {i+1} ---\n\n" + page.get_text("text"))
    return ParsedDoc(text="\n".join(texts).strip(), page_count=doc.page_count)
