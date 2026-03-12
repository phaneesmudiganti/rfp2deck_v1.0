from __future__ import annotations

from typing import List

import numpy as np

from rfp2deck.core.config import settings
from rfp2deck.llm.openai_client import get_client


def embed_texts(texts: List[str]) -> np.ndarray:
    client = get_client()
    resp = client.embeddings.create(model=settings.embeddings_model, input=texts)
    vectors = [d.embedding for d in resp.data]
    return np.array(vectors, dtype="float32")
