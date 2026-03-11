from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from docx import Document

@dataclass
class ParsedDoc:
    text: str
    paragraph_count: int

def parse_docx(path: Path) -> ParsedDoc:
    d = Document(path)
    paras = [p.text.strip() for p in d.paragraphs if p.text and p.text.strip()]
    return ParsedDoc(text="\n".join(paras), paragraph_count=len(paras))
