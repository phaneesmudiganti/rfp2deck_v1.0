from __future__ import annotations
from pathlib import Path
import base64
from rfp2deck.llm.openai_client import get_client

def generate_diagram_png(prompt: str, out_path: Path, model: str = "gpt-image-1", size: str = "1024x1024") -> Path:
    client = get_client()
    resp = client.images.generate(model=model, prompt=prompt, size=size)
    b64 = resp.data[0].b64_json
    png = base64.b64decode(b64)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png)
    return out_path
