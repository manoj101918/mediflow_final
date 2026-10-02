from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"

    # Postgres (Supabase session pooler). Must use the asyncpg driver: postgresql+asyncpg://...
    database_url: SecretStr

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
