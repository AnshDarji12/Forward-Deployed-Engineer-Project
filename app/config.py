from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8-sig",  # strip BOM so first key still parses
        extra="ignore",
    )

    google_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    reference_date: str = "2026-08-04"
    host: str = "127.0.0.1"
    port: int = 8080

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "trendly-support-agent"
    langchain_endpoint: str = "https://api.smith.langchain.com"

    @property
    def has_gemini(self) -> bool:
        return bool(self.google_api_key)

    @property
    def has_langsmith(self) -> bool:
        return bool(self.langchain_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
