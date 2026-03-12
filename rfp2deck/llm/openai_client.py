from __future__ import annotations

from openai import OpenAI

from rfp2deck.core.config import settings


def get_client() -> OpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set. Copy .env.example to .env and set it.")
    return OpenAI(api_key=settings.openai_api_key)
