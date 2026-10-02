from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.db.models import EMBEDDING_DIM


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Postgres (Supabase session pooler). Must use the asyncpg driver: postgresql+asyncpg://...
    database_url: SecretStr
    # Database used by pytest. Tests create throwaway clinics and never touch seed data.
    test_database_url: SecretStr | None = None

    # Supabase project
    supabase_url: str
    supabase_service_role_key: SecretStr
    # Legacy HS256 JWT secret. Only needed if the project still signs tokens with it;
    # asymmetric keys are verified via the project's JWKS endpoint.
    supabase_jwt_secret: SecretStr | None = None
    jwt_audience: str = "authenticated"

    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    clinic_timezone: str = "Asia/Kolkata"

    # Inbound booking channels (WhatsApp / voice bots)
    inbound_api_key: SecretStr
    inbound_clinic_id: UUID | None = None
    inbound_rate_limit: str = "30/minute"

    # Patient-record chatbot (RAG). Keys stay server-side; they never reach the frontend.
    groq_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None
    llm_model: str = "openai/gpt-oss-120b"
    llm_reasoning_effort: str = "low"
    llm_max_tokens: int = Field(default=1024, ge=64, le=8192)
    llm_timeout_seconds: float = 60.0
    embedding_model: str = "voyage-4"
    # Must equal the vector(n) column in patient_record_chunks (checked below).
    embedding_dim: int = EMBEDDING_DIM
    # Client-side pacing for the embedding API (Voyage free tier: 3/min). 0 = no limit.
    embedding_requests_per_minute: int = Field(default=3, ge=0, le=10_000)
    rag_top_k: int = Field(default=6, ge=1, le=30)
    rag_chunk_size: int = Field(default=1000, ge=200, le=8000)
    rag_chunk_overlap: int = Field(default=150, ge=0, le=2000)
    rag_max_history_turns: int = Field(default=4, ge=0, le=20)
    # Fake chat model + fake embeddings: tests and E2E run without API keys.
    rag_fake_llm: bool = False
    chat_rate_limit: str = "6/minute"

    # Report uploads. The Storage bucket's file_size_limit must match REPORT_MAX_MB.
    report_max_mb: int = Field(default=10, ge=1, le=50)
    # PDFs averaging fewer extracted characters per page are treated as scanned (no_text).
    min_text_chars_per_page: int = Field(default=50, ge=0)
    signed_url_ttl_seconds: int = Field(default=60, ge=10, le=3600)

    # Ingestion worker (asyncio task started in the FastAPI lifespan).
    ingestion_worker_enabled: bool = True
    ingestion_max_attempts: int = Field(default=5, ge=1, le=20)
    ingestion_poll_seconds: float = Field(default=2.0, gt=0)

    @field_validator("embedding_dim")
    @classmethod
    def _match_vector_column(cls, value: int) -> int:
        if value != EMBEDDING_DIM:
            raise ValueError(
                f"EMBEDDING_DIM={value} does not match the database column "
                f"vector({EMBEDDING_DIM}); add a migration before changing it"
            )
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _require_asyncpg(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must start with postgresql+asyncpg://")
        return value

    @property
    def jwks_url(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"

    @property
    def jwt_issuer(self) -> str:
        return f"{self.supabase_url.rstrip('/')}/auth/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()
