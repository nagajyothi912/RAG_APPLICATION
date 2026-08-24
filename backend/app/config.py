from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"

    embed_model_name: str = "all-MiniLM-L6-v2"
    chunk_size: int = 500
    chunk_overlap: int = 50
    top_k: int = 3
    score_threshold: float = 0.08

    docs_dir: Path = BACKEND_ROOT / "data" / "docs"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def api_key(self) -> str:
        return self.groq_api_key.strip()

    @property
    def origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_docs_dir(self) -> Path:
        path = Path(self.docs_dir)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path


settings = Settings()
