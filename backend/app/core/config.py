import base64
import binascii
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(RuntimeError):
    """Raised at startup when a required secret is missing or malformed."""


class Settings(BaseSettings):
    """Application settings, read from the environment (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"

    # Database
    database_url: str = (
        "postgresql+psycopg://processledger_app:processledger_app_dev@127.0.0.1:5545/processledger"
    )
    migration_database_url: str = (
        "postgresql+psycopg://processledger:processledger_dev@127.0.0.1:5545/processledger"
    )
    app_db_password: str = "processledger_app_dev"  # noqa: S105  (local development default)
    db_pool_size: int = 5

    # Secrets (no defaults: validated by require_secrets() when the API starts)
    jwt_secret: SecretStr | None = None
    evidence_encryption_key: SecretStr | None = None  # base64 of 32 random bytes

    # Authentication
    password_min_length: int = 12
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    max_failed_logins: int = 5
    lockout_minutes: int = 15
    cookie_secure: bool = True

    # HTTP hardening
    cors_allowed_origins: list[str] = ["http://localhost:5173"]
    login_rate_limit: str = "5/minute"
    default_rate_limit: str = "120/minute"

    # Evidence uploads
    upload_dir: str = "./data/evidence"
    max_upload_bytes: int = 50 * 1024 * 1024
    evidence_retention_days: int = 365

    # Website observation (server side request forgery protection)
    observation_allowed_hosts: list[str] = []
    observation_allowed_networks: list[str] = []  # the demo network, for example 172.28.0.0/16
    observation_allowed_ports: list[int] = [80, 443]

    # REA discovery (the runner is rea-runner/wrapper.mjs, see docs/architecture.md)
    rea_enabled: bool = True
    rea_transport: Literal["local", "http"] = "local"
    rea_local_command: list[str] = [
        "node",
        str(Path(__file__).resolve().parents[3] / "rea-runner" / "wrapper.mjs"),
    ]
    rea_offline_url: str = "http://rea-offline:8080"
    rea_browser_url: str = "http://rea-browser:8080"
    rea_runner_token: SecretStr | None = None
    rea_input_dir: str = "./data/rea_input"
    rea_timeout_seconds: int = 120
    rea_observation_ms: int = 2500
    sqlite_row_sample: int = 20

    def require_secrets(self) -> None:
        if self.jwt_secret is None or len(self.jwt_secret.get_secret_value()) < 32:
            raise ConfigurationError("JWT_SECRET must be set to at least 32 characters")
        self.encryption_key_bytes()

    def encryption_key_bytes(self) -> bytes:
        if self.evidence_encryption_key is None:
            raise ConfigurationError("EVIDENCE_ENCRYPTION_KEY must be set")
        try:
            key = base64.b64decode(self.evidence_encryption_key.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ConfigurationError("EVIDENCE_ENCRYPTION_KEY must be base64") from exc
        if len(key) != 32:
            raise ConfigurationError("EVIDENCE_ENCRYPTION_KEY must decode to 32 bytes")
        return key


@lru_cache
def get_settings() -> Settings:
    return Settings()
