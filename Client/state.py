import base64
import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass
class ClientState:
    access_token: str | None = None
    token_type: str = "bearer"
    user_uuid: str | None = None
    user_name: str | None = None
    local_device_id: str | None = None

    @classmethod
    def load(cls, path: Path, key_path: Path | None = None) -> "ClientState":
        if not path.exists():
            return cls()

        data = json.loads(path.read_text(encoding="utf-8"))
        encrypted_token = data.pop("access_token_encrypted", None)
        nonce = data.pop("access_token_nonce", None)
        if encrypted_token and nonce and key_path:
            state_key = _load_or_create_state_key(key_path)
            cipher = AESGCM(state_key)
            data["access_token"] = cipher.decrypt(
                base64.b64decode(nonce.encode("ascii")),
                base64.b64decode(encrypted_token.encode("ascii")),
                None,
            ).decode("utf-8")
        return cls(**data)

    def save(self, path: Path, key_path: Path | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        if self.access_token and key_path:
            state_key = _load_or_create_state_key(key_path)
            nonce = os.urandom(12)
            cipher = AESGCM(state_key)
            ciphertext = cipher.encrypt(nonce, self.access_token.encode("utf-8"), None)
            payload.pop("access_token", None)
            payload["access_token_encrypted"] = base64.b64encode(ciphertext).decode("ascii")
            payload["access_token_nonce"] = base64.b64encode(nonce).decode("ascii")
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.chmod(path, 0o600)

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


def _load_or_create_state_key(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return base64.b64decode(path.read_text(encoding="utf-8").strip().encode("ascii"))

    key = os.urandom(32)
    path.write_text(base64.b64encode(key).decode("ascii"), encoding="utf-8")
    os.chmod(path, 0o600)
    return key
