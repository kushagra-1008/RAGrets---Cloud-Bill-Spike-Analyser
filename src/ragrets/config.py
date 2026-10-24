from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path(os.getenv("RAGRETS_DATABASE_PATH", "ragrets.db"))
    reconciliation_tolerance: float = 0.01
    llm_provider: str | None = os.getenv("RAGRETS_LLM_PROVIDER") or None
    groq_api_key: str | None = os.getenv("RAGRETS_GROQ_API_KEY") or None
    groq_model: str = os.getenv("RAGRETS_GROQ_MODEL", "openai/gpt-oss-20b")
    dashboard_url: str | None = os.getenv("RAGRETS_DASHBOARD_URL") or None
