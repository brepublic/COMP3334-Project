from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


CLIENT_DIR = Path(__file__).resolve().parent


class ClientSettings(BaseSettings):
    server_base_url: str = Field(default="http://127.0.0.1:8000/api/v1")
    websocket_url: str = Field(default="ws://127.0.0.1:8000/ws/chat")
    db_path: Path = Field(default=CLIENT_DIR / "cdb.db")
    state_path: Path = Field(default=CLIENT_DIR / ".client_state.json")
    local_device_id: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_prefix="CLIENT_",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> ClientSettings:
    return ClientSettings()
