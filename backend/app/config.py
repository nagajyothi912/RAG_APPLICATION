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
    # The app leaves this None so the request stays byte-for-byte what it has
    # always been, and Groq runs at its own default. That default is also why a
    # production trace is not byte-replayable: the same prompt comes back
    # differently worded on each call. The Week 5 trace-collection run sets
    # GROQ_TEMPERATURE=0 for exactly the reason evaluate_week4.py pins it.
    groq_temperature: float | None = None

    embed_model_name: str = "all-MiniLM-L6-v2"
    chunk_strategy: str = "heading"  # fixed | recursive | heading
    chunk_size: int = 1000
    chunk_overlap: int = 100
    top_k: int = 5
    score_threshold: float = 0.15

    docs_dir: Path = BACKEND_ROOT / "data" / "docs"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Week 5 request tracing. OFF by default: the test suite and both
    # evaluation scripts must run without producing a byte of trace output.
    trace_enabled: bool = False
    trace_path: Path = BACKEND_ROOT / "data" / "traces" / "chat_traces.jsonl"
    trace_include_prompts: bool = True

    # Langfuse is a second sink for the same trace record, not a replacement.
    # The JSONL is what the committed error analysis is pinned to; this is where
    # the traces are read. Independent of TRACE_ENABLED on purpose, so a server
    # can ship traces to Langfuse without also writing a local file, or both.
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://us.cloud.langfuse.com"
    langfuse_environment: str = "development"

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

    @property
    def resolved_trace_path(self) -> Path:
        path = Path(self.trace_path)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path


settings = Settings()
