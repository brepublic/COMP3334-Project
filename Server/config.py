from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_DAYS: int = 7
    SERVER_DB_PATH: Path = Path("sdb.db")
    SERVER_HOST: str = "127.0.0.1"
    SERVER_PORT: int = 8000
    TLS_CERT_FILE: Path | None = None
    TLS_KEY_FILE: Path | None = None
    ALLOW_INSECURE_TEST_MODE: bool = False
    LOG_LEVEL: str = "warning"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
