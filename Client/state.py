import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ClientState:
    access_token: str | None = None
    token_type: str = "bearer"
    user_uuid: str | None = None
    user_name: str | None = None
    local_device_id: str | None = None

    @classmethod
    def load(cls, path: Path) -> "ClientState":
        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def ensure_local_device_id(self, preferred_device_id: str | None = None) -> str:
        if preferred_device_id:
            self.local_device_id = preferred_device_id
        elif not self.local_device_id:
            self.local_device_id = str(uuid.uuid4())
        return self.local_device_id

    def set_auth(
        self,
        user_uuid: str,
        access_token: str,
        token_type: str = "bearer",
        user_name: str | None = None,
    ) -> None:
        self.user_uuid = user_uuid
        self.access_token = access_token
        self.token_type = token_type
        self.user_name = user_name

    def clear_auth(self) -> None:
        self.user_uuid = None
        self.access_token = None
        self.token_type = "bearer"
        self.user_name = None
