from dataclasses import dataclass

import pyotp
import typer
from qrcode import QRCode

if __package__:
    from .api import ChatClientAPI, ClientAPIError
    from .CdbManager import ClientDBManager
    from .config import get_settings
    from .identity import ensure_local_identity
    from .Schema import (
        AckMessagesRequest,
        FriendRequestAction,
        FriendRequestPayload,
        LoginRequest,
        RegisterRequest,
        SendMessageRequest,
    )
    from .state import ClientState
else:
    from api import ChatClientAPI, ClientAPIError
    from CdbManager import ClientDBManager
    from config import get_settings
    from identity import ensure_local_identity
    from Schema import (
        AckMessagesRequest,
        FriendRequestAction,
        FriendRequestPayload,
        LoginRequest,
        RegisterRequest,
        SendMessageRequest,
    )
    from state import ClientState


app = typer.Typer(help="Phase 1 CLI client for the COMP3334 chat server.")


@dataclass
class ClientRuntime:
    settings: object
    state: ClientState
    db_manager: ClientDBManager


def build_runtime() -> ClientRuntime:
    settings = get_settings()
    db_manager = ClientDBManager(str(settings.db_path))
    state = ClientState.load(settings.state_path)
    state.ensure_local_device_id(settings.local_device_id)
    state.save(settings.state_path)
    return ClientRuntime(settings=settings, state=state, db_manager=db_manager)


def build_api(runtime: ClientRuntime) -> ChatClientAPI:
    return ChatClientAPI(
        base_url=runtime.settings.server_base_url,
        access_token=runtime.state.access_token,
    )


def require_login(runtime: ClientRuntime) -> None:
    if not runtime.state.access_token:
        raise typer.BadParameter("No saved login token found. Run the login command first.")


def run_api_call(callback):
    try:
        return callback()
    except ClientAPIError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)


def render_otp_qr_code(email: str, otp_secret: str) -> None:
    """Render a TOTP provisioning QR code in terminal-friendly ASCII."""
    provisioning_uri = pyotp.TOTP(otp_secret).provisioning_uri(
        name=email,
        issuer_name="COMP3334 Secure IM",
    )
    qr = QRCode(border=1)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    typer.echo("Scan this QR code with your authenticator app:")
    qr.print_ascii(invert=True)
    typer.echo(f"Provisioning URI: {provisioning_uri}")


@app.command()
def register(
    email: str = typer.Option(..., prompt=True),
    user_name: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True),
):
    """Register a new user and print OTP setup info."""
    runtime = build_runtime()
    api = build_api(runtime)
    try:
        response = run_api_call(
            lambda: api.register(
                RegisterRequest(email=email, user_name=user_name, password=password)
            )
        )
    finally:
        api.close()

    typer.echo(f"Registered user UUID: {response.user_uuid}")
    typer.echo(f"OTP secret: {response.otp_secret}")
    render_otp_qr_code(email=email, otp_secret=response.otp_secret)
    typer.echo("Store the OTP secret in your authenticator app before logging in.")


@app.command()
def login(
    email: str = typer.Option(..., prompt=True),
    password: str = typer.Option(..., prompt=True, hide_input=True),
    otp_code: str = typer.Option(..., prompt=True),
):
    """Login and persist the token plus local device ID."""
    runtime = build_runtime()
    identity = ensure_local_identity(runtime.db_manager)
    api = build_api(runtime)
    try:
        response = run_api_call(
            lambda: api.login(
                LoginRequest(
                    email=email,
                    password=password,
                    otp_code=otp_code,
                    device_hash=runtime.state.local_device_id,
                    device_public_key=identity.public_key,
                )
            )
        )
    finally:
        api.close()

    runtime.state.set_auth(
        user_uuid=response.user_uuid,
        access_token=response.access_token,
        token_type=response.token_type,
    )
    runtime.state.save(runtime.settings.state_path)

    typer.echo(f"Logged in as user UUID: {response.user_uuid}")
    typer.echo(f"Local device ID: {runtime.state.local_device_id}")
    typer.echo(f"WebSocket URL: {runtime.settings.websocket_url}")


@app.command()
def logout():
    """Logout current session and revoke current token on server."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(api.logout)
    finally:
        api.close()

    runtime.state.clear_auth()
    runtime.state.save(runtime.settings.state_path)
    typer.echo(response.message)


@app.command("logout-all")
def logout_all():
    """Invalidate all existing sessions for current account."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(api.logout_all)
    finally:
        api.close()

    runtime.state.clear_auth()
    runtime.state.save(runtime.settings.state_path)
    typer.echo(response.message)


@app.command("friends")
def friends_list():
    """List current friends from the server."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(api.list_friends)
    finally:
        api.close()

    if not response.friends:
        typer.echo("No friends found.")
        return

    for friend in response.friends:
        typer.echo(f"{friend.user_name}\t{friend.uuid}\t{friend.status}")


@app.command("add-friend")
def add_friend(target_email: str):
    """Send a friend request to an email."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(
            lambda: api.add_friend(FriendRequestPayload(target_email=target_email))
        )
    finally:
        api.close()

    typer.echo(response.message)


@app.command()
def pending():
    """List pending incoming friend requests."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        requests = run_api_call(api.pending_requests)
    finally:
        api.close()

    if not requests:
        typer.echo("No pending requests.")
        return

    for request in requests:
        typer.echo(f"{request.request_id}\t{request.sender_name}\t{request.sender_uuid}")


@app.command()
def accept(request_id: str):
    """Accept a pending friend request."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(
            lambda: api.respond_to_request(
                FriendRequestAction(request_id=request_id, action="ACCEPT")
            )
        )
    finally:
        api.close()

    typer.echo(response.message)


@app.command()
def chat(
    receiver_uuid: str,
    message: str,
    ttl: int = typer.Option(86400, "--ttl", min=1, help="Expiry in seconds."),
):
    """Send a plaintext placeholder payload through the current message API."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(
            lambda: api.send_message(
                SendMessageRequest(
                    receiver_uuid=receiver_uuid,
                    ciphertext=message,
                    expire_duration=ttl,
                )
            )
        )
    finally:
        api.close()

    typer.echo(f"Server message ID: {response.message_id}")
    typer.echo(f"Server status: {response.status}")


@app.command()
def pull(
    ack: bool = typer.Option(True, "--ack/--no-ack", help="Acknowledge pulled messages."),
):
    """Pull offline messages and optionally ACK them."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(api.pull_messages)
        if not response.messages:
            typer.echo("No offline messages.")
            return

        message_ids = []
        for item in response.messages:
            typer.echo(
                f"{item.message_id}\tfrom={item.sender_uuid}\tttl={item.expire_duration}\tciphertext={item.ciphertext}"
            )
            message_ids.append(item.message_id)

        if ack and message_ids:
            ack_response = run_api_call(
                lambda: api.acknowledge_messages(AckMessagesRequest(message_ids=message_ids))
            )
            typer.echo(ack_response.message)
    finally:
        api.close()


if __name__ == "__main__":
    app()
