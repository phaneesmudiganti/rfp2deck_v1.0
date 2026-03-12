from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    model_reasoning: str = os.getenv("OPENAI_MODEL_REASONING", "gpt-5.2")
    model_fast: str = os.getenv("OPENAI_MODEL_FAST", "gpt-5-mini")
    embeddings_model: str = os.getenv(
        "OPENAI_EMBEDDINGS_MODEL", "text-embedding-3-large"
    )
    data_dir: Path = Path(os.getenv("APP_DATA_DIR", ".data"))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "indexes").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "outputs").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "reports").mkdir(parents=True, exist_ok=True)


settings = Settings()
