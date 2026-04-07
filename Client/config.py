from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


CLIENT_DIR = Path(__file__).resolve().parent


def _default_profile() -> str:
    # Use terminal-shell parent PID as default profile so parallel terminals
    # do not override each other's local state/db files.
    return f"sh{os.getppid()}"


def _default_db_path() -> Path:
    profile = _default_profile()
    return CLIENT_DIR / f"cdb.{profile}.db"


def _default_state_path() -> Path:
    profile = _default_profile()
    return CLIENT_DIR / f".client_state.{profile}.json"


class ClientSettings(BaseSettings):
    server_base_url: str = Field(default="http://127.0.0.1:8000/api/v1")
    websocket_url: str = Field(default="ws://127.0.0.1:8000/ws/chat")
    db_path: Path = Field(default_factory=_default_db_path)
    state_path: Path = Field(default_factory=_default_state_path)
    local_device_id: str | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_prefix="CLIENT_",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> ClientSettings:
    return ClientSettings()
