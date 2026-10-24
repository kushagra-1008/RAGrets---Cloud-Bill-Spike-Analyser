from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    database_path: Path = Path(os.getenv("RAGRETS_DATABASE_PATH", "ragrets.db"))
    reconciliation_tolerance: float = 0.01
    llm_provider: str = (os.getenv("RAGRETS_LLM_PROVIDER") or "groq").strip().lower()
    groq_api_key: str | None = (
        os.getenv("ASI_ONE_API_KEY")
        or os.getenv("RAGRETS_LLM_API_KEY")
        or os.getenv("RAGRETS_GROQ_API_KEY")
        or None
    )
    groq_model: str = (
        os.getenv("ASI_ONE_MODEL")
        or os.getenv("RAGRETS_LLM_MODEL")
        or os.getenv("RAGRETS_GROQ_MODEL")
        or "openai/gpt-oss-20b"
    ).strip()
    dashboard_url: str | None = os.getenv("RAGRETS_DASHBOARD_URL") or None
