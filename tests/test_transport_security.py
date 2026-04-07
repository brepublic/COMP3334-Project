from types import SimpleNamespace

import pytest
import typer


def test_client_rejects_insecure_http_transport():
    import Client.main as client_main

    with pytest.raises(typer.BadParameter, match="server_base_url must use https"):
        client_main._validate_transport_settings(
            SimpleNamespace(
                server_base_url="http://127.0.0.1:8000/api/v1",
                websocket_url="wss://127.0.0.1:8000/ws/chat",
            )
        )


def test_client_rejects_insecure_websocket_transport():
    import Client.main as client_main

    with pytest.raises(typer.BadParameter, match="websocket_url must use wss"):
        client_main._validate_transport_settings(
            SimpleNamespace(
                server_base_url="https://127.0.0.1:8000/api/v1",
                websocket_url="ws://127.0.0.1:8000/ws/chat",
            )
        )


def test_server_requires_tls_configuration_when_not_in_test_mode(monkeypatch):
    from conftest import import_main_server, reset_server_modules

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALLOW_INSECURE_TEST_MODE", "false")
    monkeypatch.delenv("TLS_CERT_FILE", raising=False)
    monkeypatch.delenv("TLS_KEY_FILE", raising=False)

    reset_server_modules()
    main_server = import_main_server()
    monkeypatch.setattr(main_server.settings, "TLS_CERT_FILE", None)
    monkeypatch.setattr(main_server.settings, "TLS_KEY_FILE", None)
    monkeypatch.setattr(main_server.settings, "ALLOW_INSECURE_TEST_MODE", False)

    with pytest.raises(RuntimeError, match="TLS_CERT_FILE and TLS_KEY_FILE must be set"):
        main_server.require_tls_configuration(allow_insecure_override=False)


def test_server_accepts_explicit_tls_cert_and_key(tmp_path, monkeypatch):
    from conftest import import_main_server, reset_server_modules

    cert_file = tmp_path / "server.crt"
    key_file = tmp_path / "server.key"
    cert_file.write_text("dummy cert", encoding="utf-8")
    key_file.write_text("dummy key", encoding="utf-8")

    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALLOW_INSECURE_TEST_MODE", "false")
    monkeypatch.setenv("TLS_CERT_FILE", str(cert_file))
    monkeypatch.setenv("TLS_KEY_FILE", str(key_file))

    reset_server_modules()
    main_server = import_main_server()

    resolved_cert, resolved_key = main_server.require_tls_configuration()
    assert resolved_cert == str(cert_file)
    assert resolved_key == str(key_file)
