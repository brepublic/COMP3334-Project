import base64
import importlib
import json
import re
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pyotp
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient
from typer.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "Server"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


SERVER_MODULES = [
    "MainServer",
    "Dependency",
    "Server_db",
    "SdbManager",
    "Schema",
    "config",
    "limitor",
    "task",
    "ws_manager",
    "routers",
    "routers.Register",
    "routers.Login",
    "routers.Contacts",
    "routers.Message",
    "routers.ChatWS",
]


def reset_server_modules() -> None:
    for name in SERVER_MODULES:
        sys.modules.pop(name, None)


def import_main_server():
    return importlib.import_module("MainServer")


def new_device_material() -> tuple[str, str]:
    private_key = X25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return str(uuid.uuid4()), base64.b64encode(public_key).decode("ascii")


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def server_context(tmp_path, monkeypatch):
    db_path = tmp_path / "server.db"
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("SERVER_DB_PATH", str(db_path))
    monkeypatch.setenv("LOG_LEVEL", "error")
    monkeypatch.setenv("SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("SERVER_PORT", "8001")
    monkeypatch.setenv("ALLOW_INSECURE_TEST_MODE", "true")
    monkeypatch.delenv("TLS_CERT_FILE", raising=False)
    monkeypatch.delenv("TLS_KEY_FILE", raising=False)

    reset_server_modules()
    main_server = importlib.import_module("MainServer")
    dependency = importlib.import_module("Dependency")
    server_db = importlib.import_module("Server_db")

    with TestClient(main_server.app) as client:
        yield SimpleNamespace(
            app=main_server.app,
            client=client,
            dependency=dependency,
            models=server_db,
            db_path=db_path,
        )


@pytest.fixture
def server_helpers(server_context):
    def register(email: str, user_name: str, password: str = "Password123") -> dict:
        response = server_context.client.post(
            "/api/v1/register",
            json={
                "email": email,
                "user_name": user_name,
                "password": password,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()

    def login(
        email: str,
        otp_secret: str,
        password: str = "Password123",
        device_hash: str | None = None,
        device_public_key: str | None = None,
    ) -> dict:
        device_hash = device_hash or str(uuid.uuid4())
        if device_public_key is None:
            _, device_public_key = new_device_material()
        response = server_context.client.post(
            "/api/v1/login",
            json={
                "email": email,
                "password": password,
                "otp_code": pyotp.TOTP(otp_secret).now(),
                "device_hash": device_hash,
                "device_public_key": device_public_key,
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        payload["device_hash"] = device_hash
        payload["device_public_key"] = device_public_key
        return payload

    def make_friends(
        sender_token: str,
        target_email: str,
        receiver_token: str,
    ) -> str:
        request_response = server_context.client.post(
            "/api/v1/friends/request",
            headers=auth_headers(sender_token),
            json={"target_email": target_email},
        )
        assert request_response.status_code == 200, request_response.text

        pending_response = server_context.client.get(
            "/api/v1/friends/pending?direction=incoming",
            headers=auth_headers(receiver_token),
        )
        assert pending_response.status_code == 200, pending_response.text
        request_id = pending_response.json()[0]["request_id"]

        accept_response = server_context.client.post(
            "/api/v1/friends/action",
            headers=auth_headers(receiver_token),
            json={"request_id": request_id, "action": "ACCEPT"},
        )
        assert accept_response.status_code == 200, accept_response.text
        return request_id

    def db_session():
        return server_context.dependency.db_manager.get_session()

    return SimpleNamespace(
        register=register,
        login=login,
        make_friends=make_friends,
        db_session=db_session,
    )


@pytest.fixture
def client_harness(server_context, monkeypatch, tmp_path):
    import Client.config as client_config
    import Client.main as client_main
    from Client import Schema as client_schema
    from pydantic import TypeAdapter

    class TestClientAPIAdapter:
        def __init__(self, access_token: str | None = None):
            self._access_token = access_token

        def close(self) -> None:
            return None

        def _headers(self, require_auth: bool) -> dict[str, str]:
            headers = {"Content-Type": "application/json"}
            if require_auth:
                if not self._access_token:
                    raise client_main.ClientAPIError("This command requires a saved login token.")
                headers["Authorization"] = f"Bearer {self._access_token}"
            return headers

        def _request(self, method: str, path: str, *, require_auth: bool = False, json_data=None):
            response = server_context.client.request(
                method,
                f"/api/v1{path}",
                headers=self._headers(require_auth),
                json=json_data,
            )
            if response.is_error:
                try:
                    detail = response.json().get("detail", response.json())
                except ValueError:
                    detail = response.text
                raise client_main.ClientAPIError(
                    f"{response.status_code} {response.reason_phrase} for {method} {path}: {detail}"
                )
            if not response.content:
                return None
            return response.json()

        def register(self, payload):
            return client_schema.RegisterResponse.model_validate(
                self._request("POST", "/register", json_data=payload.model_dump())
            )

        def login(self, payload):
            return client_schema.LoginResponse.model_validate(
                self._request("POST", "/login", json_data=payload.model_dump())
            )

        def logout(self):
            return client_schema.StandardResponse.model_validate(
                self._request("POST", "/logout", require_auth=True)
            )

        def logout_all(self):
            return client_schema.StandardResponse.model_validate(
                self._request("POST", "/logout-all", require_auth=True)
            )

        def list_friends(self):
            return client_schema.FriendListResponse.model_validate(
                self._request("GET", "/friends", require_auth=True)
            )

        def add_friend(self, payload):
            return client_schema.StandardResponse.model_validate(
                self._request("POST", "/friends/request", require_auth=True, json_data=payload.model_dump())
            )

        def pending_requests(self, direction: str = "incoming"):
            return TypeAdapter(list[client_schema.PendingRequestInfo]).validate_python(
                self._request("GET", f"/friends/pending?direction={direction}", require_auth=True)
            )

        def respond_to_request(self, payload):
            return client_schema.StandardResponse.model_validate(
                self._request("POST", "/friends/action", require_auth=True, json_data=payload.model_dump())
            )

        def send_message(self, payload):
            return client_schema.SendMessageResponse.model_validate(
                self._request("POST", "/messages/send", require_auth=True, json_data=payload.model_dump())
            )

        def pull_messages(self):
            return client_schema.OfflineMessageResponse.model_validate(
                self._request("GET", "/messages/offline", require_auth=True)
            )

        def acknowledge_messages(self, payload):
            return client_schema.StandardResponse.model_validate(
                self._request("POST", "/messages/ack", require_auth=True, json_data=payload.model_dump())
            )

        def get_contact_keys(self, contact_uuid: str):
            return client_schema.ContactKeysResponse.model_validate(
                self._request("GET", f"/friends/{contact_uuid}/keys", require_auth=True)
            )

        def remove_friend(self, friend_uuid: str):
            return client_schema.StandardResponse.model_validate(
                self._request("DELETE", f"/friends/{friend_uuid}", require_auth=True)
            )

        def cancel_friend_request(self, request_id: str):
            return client_schema.StandardResponse.model_validate(
                self._request("DELETE", f"/friends/request/{request_id}", require_auth=True)
            )

        def block_user(self, target_uuid: str):
            return client_schema.StandardResponse.model_validate(
                self._request(
                    "POST",
                    "/friends/block",
                    require_auth=True,
                    json_data={"target_uuid": target_uuid},
                )
            )

    def fake_build_api(runtime):
        return TestClientAPIAdapter(runtime.state.access_token)

    monkeypatch.setattr(client_main, "build_api", fake_build_api)
    runner = CliRunner()

    def profile_env(name: str) -> dict[str, str]:
        base_dir = tmp_path / name
        return {
            "CLIENT_SERVER_BASE_URL": "https://testserver/api/v1",
            "CLIENT_WEBSOCKET_URL": "wss://testserver/ws/chat",
            "CLIENT_DB_PATH": str(base_dir / "client.db"),
            "CLIENT_STATE_PATH": str(base_dir / "state.json"),
            "CLIENT_STATE_KEY_PATH": str(base_dir / "state.key"),
        }

    def activate(env: dict[str, str]) -> None:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        client_config.get_settings.cache_clear()

    def run(env: dict[str, str], args: list[str], input_text: str | None = None):
        activate(env)
        return runner.invoke(client_main.app, args, input=input_text, catch_exceptions=False)

    def register(env: dict[str, str], email: str, user_name: str, password: str = "Password123") -> str:
        result = run(
            env,
            ["register", "--email", email, "--user-name", user_name, "--password", password],
        )
        assert result.exit_code == 0, result.output
        match = re.search(r"OTP secret:\s+([A-Z0-9]+)", result.output)
        assert match, result.output
        return match.group(1)

    def login(env: dict[str, str], email: str, otp_secret: str, password: str = "Password123"):
        result = run(
            env,
            [
                "login",
                "--email",
                email,
                "--password",
                password,
                "--otp-code",
                pyotp.TOTP(otp_secret).now(),
            ],
        )
        assert result.exit_code == 0, result.output
        match = re.search(r"Logged in as user UUID:\s+([0-9a-f-]+)", result.output)
        assert match, result.output
        return match.group(1), result.output

    def send_message(env: dict[str, str], receiver_uuid: str, message: str, ttl: int = 300, password: str = "Password123"):
        activate(env)
        runtime = client_main.build_runtime()
        client_main._send_chat_payload(runtime, receiver_uuid, message, ttl, password)

    def read_state(env: dict[str, str]) -> dict:
        return json.loads(Path(env["CLIENT_STATE_PATH"]).read_text(encoding="utf-8"))

    return SimpleNamespace(
        client_main=client_main,
        run=run,
        profile_env=profile_env,
        register=register,
        login=login,
        send_message=send_message,
        read_state=read_state,
        activate=activate,
    )
