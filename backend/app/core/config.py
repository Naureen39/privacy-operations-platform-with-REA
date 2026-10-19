from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from the environment (see .env.example)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = (
        "postgresql+psycopg://processledger_app:processledger_app_dev@127.0.0.1:5545/processledger"
    )
    migration_database_url: str = (
        "postgresql+psycopg://processledger:processledger_dev@127.0.0.1:5545/processledger"
    )
    app_db_password: str = "processledger_app_dev"  # noqa: S105  (local development default)
    db_pool_size: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
