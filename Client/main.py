from dataclasses import dataclass
import base64
import json
import os
import shlex
import sys
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import click
import pyotp
import typer
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from qrcode import QRCode
from sqlalchemy import select
from sqlalchemy.orm import object_session

if __package__:
    from .api import ChatClientAPI, ClientAPIError
    from .CdbManager import ClientDBManager
    from .CLient_db import ContactDevice, Conversation, LocalIdentity, Message, MessageCounter, SeenMessage
    from .config import get_settings
    from .identity import ensure_local_identity, key_fingerprint, derive_session_key
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
    from CLient_db import ContactDevice, Conversation, LocalIdentity, Message, MessageCounter, SeenMessage
    from config import get_settings
    from identity import ensure_local_identity, key_fingerprint, derive_session_key
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


@dataclass
class ContactKeySyncResult:
    changed_devices: list[str]
    synced_devices: int

PROTOCOL_VERSION = 1
ENVELOPE_TYPE_CHAT = "CHAT"
ENVELOPE_TYPE_RECEIPT = "RECEIPT"
DEBUG_LOG_PATH = os.getenv("CLIENT_DEBUG_LOG_PATH")
DEBUG_SESSION_ID = os.getenv("CLIENT_DEBUG_SESSION_ID", "default")


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    if not DEBUG_LOG_PATH:
        return
    # region agent log
    payload = {
        "sessionId": DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    try:
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # endregion


def _dispatch_cli_command(args: list[str]) -> None:
    app(
        args=args,
        prog_name="client",
        standalone_mode=False,
    )


def _run_interactive_shell() -> None:
    typer.echo("Interactive mode started. Type 'help' for usage, 'exit' to quit.")
    while True:
        try:
            runtime = build_runtime()
            prompt_user = runtime.state.user_name or "guest"
            raw = input(f"{prompt_user}@client> ").strip()
        except EOFError:
            typer.echo()
            typer.echo("Exiting interactive mode.")
            return
        except KeyboardInterrupt:
            typer.echo()
            typer.echo("Use 'exit' or Ctrl+D to quit.")
            continue

        if not raw:
            continue

        lowered = raw.lower()
        if lowered in {"exit", "quit"}:
            typer.echo("Exiting interactive mode.")
            return

        try:
            if lowered == "help":
                args = ["--help"]
            elif lowered.startswith("help "):
                args = shlex.split(raw[5:])
                args.append("--help")
            else:
                args = shlex.split(raw)
        except ValueError as exc:
            typer.secho(f"Parse error: {exc}", fg=typer.colors.RED, err=True)
            continue

        try:
            _dispatch_cli_command(args)
        except typer.Exit as exc:
            if exc.exit_code not in (0, None):
                continue
        except click.ClickException as exc:
            exc.show(file=sys.stderr)
        except click.exceptions.Abort:
            typer.secho("Command aborted.", fg=typer.colors.YELLOW, err=True)
        except Exception as exc:
            typer.secho(f"Unexpected error: {exc}", fg=typer.colors.RED, err=True)


def build_runtime() -> ClientRuntime:
    settings = get_settings()
    _validate_transport_settings(settings)
    db_manager = ClientDBManager(str(settings.db_path))
    state = ClientState.load(settings.state_path, settings.state_key_path)
    state.ensure_local_device_id(settings.local_device_id)
    state.save(settings.state_path, settings.state_key_path)
    return ClientRuntime(settings=settings, state=state, db_manager=db_manager)


def build_api(runtime: ClientRuntime) -> ChatClientAPI:
    return ChatClientAPI(
        base_url=runtime.settings.server_base_url,
        access_token=runtime.state.access_token,
    )


def _validate_transport_settings(settings: object) -> None:
    for attr_name, required_scheme in (
        ("server_base_url", "https"),
        ("websocket_url", "wss"),
    ):
        value = getattr(settings, attr_name)
        parsed = urlparse(value)
        if parsed.scheme != required_scheme:
            raise typer.BadParameter(
                f"{attr_name} must use {required_scheme}: {value}"
            )


def _warn_changed_devices(contact_uuid: str, changed_devices: list[str]) -> None:
    if not changed_devices:
        return
    typer.secho(
        "Warning: key changed for device(s): "
        + ", ".join(changed_devices)
        + f" on contact {contact_uuid}. Verification was reset; re-verify fingerprints.",
        fg=typer.colors.YELLOW,
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


def _print_columns(headers: list[str], rows: list[list[str]]) -> None:
    if not headers:
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    header_line = "\t".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers)))
    typer.echo(header_line)
    for row in rows:
        typer.echo("\t".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def _short_text(value: str, limit: int = 40) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _ensure_conversation_exists(db_manager: ClientDBManager, contact_uuid: str) -> None:
    with db_manager.get_session() as db:
        conversation = db.get(Conversation, contact_uuid)
        if conversation:
            return
        db.add(
            Conversation(
                contact_uuid=contact_uuid,
                contact_name=contact_uuid,
                unread_threads=0,
                last_activity=datetime.now(timezone.utc),
            )
        )


def _sync_contact_keys(runtime: ClientRuntime, contact_uuid: str) -> ContactKeySyncResult:
    api = build_api(runtime)
    try:
        response = run_api_call(lambda: api.get_contact_keys(contact_uuid))
    finally:
        api.close()

    _ensure_conversation_exists(runtime.db_manager, contact_uuid)
    changed_devices: list[str] = []

    with runtime.db_manager.get_session() as db:
        existing_devices = db.execute(
            select(ContactDevice).where(ContactDevice.contact_uuid == contact_uuid)
        ).scalars().all()
        by_device_id = {item.contact_device_id: item for item in existing_devices}
        active_device_ids = {device.device_id for device in response.active_devices}

        for device in response.active_devices:
            new_hash = key_fingerprint(device.device_public_key)
            current = by_device_id.get(device.device_id)
            if not current:
                if existing_devices:
                    changed_devices.append(device.device_id)
                db.add(
                    ContactDevice(
                        contact_device_id=device.device_id,
                        contact_uuid=contact_uuid,
                        public_key=device.device_public_key,
                        fingerprint=new_hash,
                        last_seen_key_hash=new_hash,
                        is_verified=False,
                    )
                )
                continue

            if current.last_seen_key_hash and current.last_seen_key_hash != new_hash:
                current.is_verified = False
                changed_devices.append(device.device_id)

            current.public_key = device.device_public_key
            current.fingerprint = new_hash
            current.last_seen_key_hash = new_hash

        # Keep local cache aligned with server active device list to avoid selecting stale device ids.
        db.query(ContactDevice).filter(
            ContactDevice.contact_uuid == contact_uuid,
            ContactDevice.contact_device_id.not_in(active_device_ids),
        ).delete(synchronize_session=False)
        _debug_log(
            "post-fix",
            "H10",
            "Client/main.py:_sync_contact_keys:active-set",
            "Synced and pruned contact device cache by server active devices",
            {
                "contact_uuid": contact_uuid,
                "active_device_ids": sorted(active_device_ids),
                "active_count": len(active_device_ids),
            },
        )

    return ContactKeySyncResult(
        changed_devices=changed_devices,
        synced_devices=len(response.active_devices),
    )


def _aad_metadata_bytes(envelope: dict) -> bytes:
    aad_keys = (
        "v",
        "type",
        "client_msg_id",
        "sender_uuid",
        "receiver_uuid",
        "sender_device_id",
        "receiver_device_id",
        "counter",
        "ttl",
        "created_at",
    )
    payload = {key: envelope[key] for key in aad_keys}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _next_counter(db_manager: ClientDBManager, conversation_id: str, peer_device_id: str, direction: str) -> int:
    with db_manager.get_session() as db:
        record = db.execute(
            select(MessageCounter).where(
                MessageCounter.conversation_id == conversation_id,
                MessageCounter.peer_device_id == peer_device_id,
                MessageCounter.direction == direction,
            )
        ).scalar_one_or_none()
        if not record:
            record = MessageCounter(
                conversation_id=conversation_id,
                peer_device_id=peer_device_id,
                direction=direction,
                counter_value=0,
            )
            db.add(record)
            db.flush()
        record.counter_value += 1
        return record.counter_value


def _accept_inbound_counter(
    db_manager: ClientDBManager,
    conversation_id: str,
    peer_device_id: str,
    counter: int,
    window_size: int = 32,
) -> tuple[bool, str | None]:
    with db_manager.get_session() as db:
        record = db.execute(
            select(MessageCounter).where(
                MessageCounter.conversation_id == conversation_id,
                MessageCounter.peer_device_id == peer_device_id,
                MessageCounter.direction == "INBOUND",
            )
        ).scalar_one_or_none()
        if counter <= 0:
            return False, "invalid-counter"

        if not record:
            db.add(
                MessageCounter(
                    conversation_id=conversation_id,
                    peer_device_id=peer_device_id,
                    direction="INBOUND",
                    counter_value=counter,
                    recent_counters=json.dumps([counter]),
                )
            )
            return True, None

        max_seen = record.counter_value or 0
        recent_counters = set()
        if record.recent_counters:
            recent_counters = {int(value) for value in json.loads(record.recent_counters)}

        if counter in recent_counters:
            return False, f"duplicate-counter={counter}"
        if counter <= max_seen - window_size:
            return False, f"outside-window={counter}\tlatest={max_seen}"
        if counter > max_seen + window_size:
            return False, f"future-counter={counter}\tlatest={max_seen}"

        max_seen = max(max_seen, counter)
        recent_counters.add(counter)
        recent_counters = {value for value in recent_counters if value > max_seen - window_size}
        record.counter_value = max_seen
        record.recent_counters = json.dumps(sorted(recent_counters))
        return True, None


def _is_seen_message(db_manager: ClientDBManager, client_msg_id: str) -> bool:
    with db_manager.get_session() as db:
        return db.get(SeenMessage, client_msg_id) is not None


def _mark_seen_message(db_manager: ClientDBManager, client_msg_id: str, conversation_id: str, sender_device_id: str) -> None:
    with db_manager.get_session() as db:
        if db.get(SeenMessage, client_msg_id):
            return
        db.add(
            SeenMessage(
                client_msg_id=client_msg_id,
                conversation_id=conversation_id,
                sender_device_id=sender_device_id,
            )
        )


def _parse_utc_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _touch_conversation(
    db_manager: ClientDBManager,
    contact_uuid: str,
    *,
    contact_name: str | None = None,
    increase_unread: bool = False,
    clear_unread: bool = False,
    at: datetime | None = None,
) -> None:
    now = at or datetime.now(timezone.utc)
    with db_manager.get_session() as db:
        record = db.get(Conversation, contact_uuid)
        if not record:
            record = Conversation(
                contact_uuid=contact_uuid,
                contact_name=contact_name or contact_uuid,
                unread_threads=0,
                last_activity=now,
            )
            db.add(record)
        if contact_name:
            record.contact_name = contact_name
        record.last_activity = now
        if increase_unread:
            record.unread_threads = (record.unread_threads or 0) + 1
        if clear_unread:
            record.unread_threads = 0


def _save_message(
    db_manager: ClientDBManager,
    *,
    conversation_id: str,
    sender_id: str,
    receiver_id: str,
    content_plaintext: str,
    ttl: int,
    received_at: datetime,
    client_msg_id: str | None,
    message_type: str,
    status: str,
    ack_client_msg_id: str | None = None,
) -> None:
    expires_at = received_at + timedelta(seconds=max(0, int(ttl)))
    with db_manager.get_session() as db:
        db.add(
            Message(
                conversation_id=conversation_id,
                sender_id=sender_id,
                receiver_id=receiver_id,
                content_plaintext=content_plaintext,
                expire_duration=ttl,
                receive_at=received_at,
                client_msg_id=client_msg_id,
                message_type=message_type,
                status=status,
                ack_client_msg_id=ack_client_msg_id,
                expires_at=expires_at,
            )
        )


def _cleanup_expired_local_messages(db_manager: ClientDBManager) -> int:
    now = datetime.now(timezone.utc)
    with db_manager.get_session() as db:
        rows = db.execute(select(Message)).scalars().all()
        expired_ids: list[str] = []
        for row in rows:
            if row.expires_at:
                expires_at = _ensure_utc(row.expires_at)
            else:
                received = _ensure_utc(row.receive_at) or now
                expires_at = received + timedelta(seconds=max(0, int(row.expire_duration or 0)))
            if expires_at <= now:
                expired_ids.append(row.message_id)
        if not expired_ids:
            return 0
        db.query(Message).filter(Message.message_id.in_(expired_ids)).delete(synchronize_session=False)
        return len(expired_ids)


def _mark_outbound_delivered_by_client_msg_id(db_manager: ClientDBManager, conversation_id: str, ack_client_msg_id: str) -> bool:
    with db_manager.get_session() as db:
        msg = db.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.client_msg_id == ack_client_msg_id,
                Message.message_type == ENVELOPE_TYPE_CHAT,
            )
        ).scalars().first()
        if not msg:
            return False
        msg.status = "DELIVERED"
        return True


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
    identity = ensure_local_identity(runtime.db_manager, password)
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
        user_name=response.user_name,
        access_token=response.access_token,
        token_type=response.token_type,
    )
    _debug_log(
        "post-fix",
        "H6",
        "Client/main.py:login:state",
        "Login persisted auth and local device id",
        {
            "user_uuid": response.user_uuid,
            "local_device_id": runtime.state.local_device_id,
        },
    )
    runtime.state.save(runtime.settings.state_path, runtime.settings.state_key_path)

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
    runtime.state.save(runtime.settings.state_path, runtime.settings.state_key_path)
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
    runtime.state.save(runtime.settings.state_path, runtime.settings.state_key_path)
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

    rows: list[list[str]] = []
    for friend in response.friends:
        _touch_conversation(
            runtime.db_manager,
            friend.uuid,
            contact_name=friend.user_name,
        )
        rows.append([friend.user_name, friend.uuid, friend.status, friend.email or "-"])
    _print_columns(["Username", "UUID", "Status", "Email"], rows)


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


@app.command("remove-friend")
def remove_friend(username: str):
    """Remove a friend by username (with duplicate disambiguation)."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(api.list_friends)
        matches = [f for f in response.friends if f.user_name == username]
        if not matches:
            typer.echo(f"No friend found with username: {username}")
            return
        selected = matches[0] if len(matches) == 1 else _select_friend_interactively(
            matches, "Multiple users share this username:"
        )
        remove_response = run_api_call(lambda: api.remove_friend(selected.uuid))
    finally:
        api.close()
    typer.echo(remove_response.message)


@app.command()
def pending(direction: str = typer.Option("incoming", "--direction", case_sensitive=False)):
    """List pending friend requests."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        requests = run_api_call(lambda: api.pending_requests(direction.lower()))
    finally:
        api.close()

    if not requests:
        typer.echo("No pending requests.")
        return

    rows = [[req.request_id, req.direction, req.counterparty_name, req.counterparty_uuid] for req in requests]
    _print_columns(["RequestID", "Direction", "Counterparty", "CounterpartyUUID"], rows)


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
def decline(request_id: str):
    """Decline a pending friend request."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(
            lambda: api.respond_to_request(
                FriendRequestAction(request_id=request_id, action="REJECT")
            )
        )
    finally:
        api.close()
    typer.echo(response.message)


@app.command("cancel-request")
def cancel_request(request_id: str):
    """Cancel an outgoing pending friend request."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(lambda: api.cancel_friend_request(request_id))
    finally:
        api.close()
    typer.echo(response.message)


@app.command("block-user")
def block_user(target_uuid: str):
    """Block a user by UUID."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        response = run_api_call(lambda: api.block_user(target_uuid))
    finally:
        api.close()
    typer.echo(response.message)


def _select_friend_interactively(options: list, title: str) -> object | None:
    if not options:
        return None
    rows = []
    for idx, item in enumerate(options, start=1):
        rows.append([str(idx), item.user_name, item.email or "-", item.uuid])
    typer.echo(title)
    _print_columns(["No", "Username", "Email", "UUID"], rows)
    selected = typer.prompt("Select by number", type=int)
    if selected < 1 or selected > len(options):
        raise typer.BadParameter("Invalid selection.")
    return options[selected - 1]


def _show_recent_chat(runtime: ClientRuntime, contact_uuid: str, limit: int = 12) -> None:
    _cleanup_expired_local_messages(runtime.db_manager)
    with runtime.db_manager.get_session() as db:
        rows = db.execute(
            select(Message)
            .where(Message.conversation_id == contact_uuid, Message.message_type == ENVELOPE_TYPE_CHAT)
            .order_by(Message.receive_at.desc())
            .limit(limit)
        ).scalars().all()
    if not rows:
        typer.echo("No local history for this chat.")
        return
    output = []
    for row in reversed(rows):
        direction = "OUT" if row.sender_id == runtime.state.user_uuid else "IN"
        ts = row.receive_at.isoformat() if row.receive_at else "-"
        output.append(
            [ts, direction, row.status, "N/A", str(row.expire_duration), _short_text(row.content_plaintext, 72)]
        )
    _print_columns(["Time", "Dir", "Delivery", "Read", "TTL", "Message"], output)


def _send_chat_payload(runtime: ClientRuntime, receiver_uuid: str, message: str, ttl: int, password: str) -> None:
    if not runtime.state.user_uuid:
        raise typer.BadParameter("No saved user UUID found. Run login first.")
    identity = ensure_local_identity(runtime.db_manager, password)
    _ensure_conversation_exists(runtime.db_manager, receiver_uuid)
    sync_result = _sync_contact_keys(runtime, receiver_uuid)
    _warn_changed_devices(receiver_uuid, sync_result.changed_devices)
    with runtime.db_manager.get_session() as db:
        device = db.execute(
            select(ContactDevice).where(ContactDevice.contact_uuid == receiver_uuid)
        ).scalars().first()
    if not device:
        raise typer.BadParameter("No contact device key found. Run sync-contact-keys first.")

    counter = _next_counter(runtime.db_manager, receiver_uuid, device.contact_device_id, "OUTBOUND")
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    session_key = derive_session_key(
        local_private_key_b64=identity.private_key,
        peer_public_key_b64=device.public_key,
        sender_uuid=runtime.state.user_uuid,
        receiver_uuid=receiver_uuid,
        sender_device_id=runtime.state.local_device_id,
        receiver_device_id=device.contact_device_id,
        protocol_version=PROTOCOL_VERSION,
    )
    nonce = os.urandom(12)
    client_msg_id = str(uuid.uuid4())
    envelope = {
        "v": PROTOCOL_VERSION,
        "type": ENVELOPE_TYPE_CHAT,
        "client_msg_id": client_msg_id,
        "sender_uuid": runtime.state.user_uuid,
        "receiver_uuid": receiver_uuid,
        "sender_device_id": runtime.state.local_device_id,
        "receiver_device_id": device.contact_device_id,
        "counter": counter,
        "ttl": ttl,
        "created_at": created_at,
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    aad = _aad_metadata_bytes(envelope)
    ciphertext = AESGCM(session_key).encrypt(nonce, message.encode("utf-8"), aad)
    envelope["ciphertext"] = base64.b64encode(ciphertext).decode("ascii")
    envelope_blob = json.dumps(envelope, separators=(",", ":"))

    api = build_api(runtime)
    try:
        response = run_api_call(
            lambda: api.send_message(
                SendMessageRequest(
                    receiver_uuid=receiver_uuid,
                    ciphertext=envelope_blob,
                    expire_duration=ttl,
                )
            )
        )
    finally:
        api.close()

    created_at_dt = _parse_utc_ts(created_at)
    _save_message(
        runtime.db_manager,
        conversation_id=receiver_uuid,
        sender_id=runtime.state.user_uuid,
        receiver_id=receiver_uuid,
        content_plaintext=message,
        ttl=ttl,
        received_at=created_at_dt,
        client_msg_id=client_msg_id,
        message_type=ENVELOPE_TYPE_CHAT,
        status="SENT",
    )
    _touch_conversation(runtime.db_manager, receiver_uuid, at=created_at_dt)
    typer.echo(f"Server message ID: {response.message_id}")
    typer.echo(f"Server status: {response.status}")


@app.command()
def chat(
    username: str | None = typer.Argument(None, help="Friend username to chat with."),
):
    """Open interactive chat session."""
    runtime = build_runtime()
    require_login(runtime)
    api = build_api(runtime)
    try:
        friends_response = run_api_call(api.list_friends)
    finally:
        api.close()
    if not friends_response.friends:
        typer.echo("No friends found.")
        return

    if username:
        matches = [f for f in friends_response.friends if f.user_name == username]
        if not matches:
            typer.echo(f"No friend found with username: {username}")
            return
        selected = matches[0] if len(matches) == 1 else _select_friend_interactively(
            matches, "Multiple users share this username:"
        )
    else:
        with runtime.db_manager.get_session() as db:
            latest_by_contact = {}
            for msg in db.execute(select(Message).order_by(Message.receive_at.desc())).scalars().all():
                latest_by_contact.setdefault(msg.conversation_id, msg.content_plaintext)
        rows = []
        for idx, friend in enumerate(friends_response.friends, start=1):
            rows.append([str(idx), friend.user_name, _short_text(latest_by_contact.get(friend.uuid, "-"), 60)])
        _print_columns(["No", "Username", "LastMessage"], rows)
        pick = typer.prompt("Select chat by number", type=int)
        if pick < 1 or pick > len(friends_response.friends):
            raise typer.BadParameter("Invalid selection.")
        selected = friends_response.friends[pick - 1]

    if not selected:
        return
    _cleanup_expired_local_messages(runtime.db_manager)
    _touch_conversation(runtime.db_manager, selected.uuid, contact_name=selected.user_name, clear_unread=True)
    password = typer.prompt("Password", hide_input=True)
    default_ttl = 86400
    typer.echo(f"Entering chat with {selected.user_name} ({selected.uuid})")
    typer.echo("Commands: /back | /refresh | /ttl <seconds> <message> ; plain text sends with default ttl.")
    _show_recent_chat(runtime, selected.uuid)
    while True:
        line = input(f"chat:{selected.user_name}> ").strip()
        if not line:
            continue
        if line == "/back":
            return
        if line == "/refresh":
            _show_recent_chat(runtime, selected.uuid)
            continue
        if line.startswith("/ttl "):
            parts = line.split(" ", 2)
            if len(parts) != 3 or not parts[1].isdigit():
                typer.secho("Usage: /ttl <seconds> <message>", fg=typer.colors.YELLOW)
                continue
            send_ttl = int(parts[1])
            send_body = parts[2].strip()
        else:
            send_ttl = default_ttl
            send_body = line
        if not send_body:
            typer.secho("Message cannot be empty.", fg=typer.colors.YELLOW)
            continue
        _send_chat_payload(runtime, selected.uuid, send_body, send_ttl, password)


@app.command()
def pull(
    ack: bool = typer.Option(True, "--ack/--no-ack", help="Acknowledge pulled messages."),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Login password to unlock local identity key."),
):
    """Pull offline messages and optionally ACK them."""
    runtime = build_runtime()
    require_login(runtime)
    expired = _cleanup_expired_local_messages(runtime.db_manager)
    if expired:
        typer.secho(f"Cleaned {expired} expired local message(s).", fg=typer.colors.BLUE)
    if not runtime.state.user_uuid:
        raise typer.BadParameter("No saved user UUID found. Run login first.")
    identity = ensure_local_identity(runtime.db_manager, password)
    api = build_api(runtime)
    try:
        response = run_api_call(api.pull_messages)
        if not response.messages:
            typer.echo("No offline messages.")
            return

        message_ids = []
        for item in response.messages:
            try:
                envelope = json.loads(item.ciphertext)
            except json.JSONDecodeError:
                typer.secho(f"{item.message_id}\tinvalid-envelope-json", fg=typer.colors.YELLOW)
                message_ids.append(item.message_id)
                continue

            required_fields = {
                "v",
                "type",
                "client_msg_id",
                "sender_uuid",
                "receiver_uuid",
                "sender_device_id",
                "receiver_device_id",
                "counter",
                "ttl",
                "created_at",
                "nonce",
                "ciphertext",
            }
            if not required_fields.issubset(envelope.keys()):
                typer.secho(f"{item.message_id}\tmissing-envelope-fields", fg=typer.colors.YELLOW)
                message_ids.append(item.message_id)
                continue

            if envelope["type"] not in {ENVELOPE_TYPE_CHAT, ENVELOPE_TYPE_RECEIPT}:
                typer.secho(f"{item.message_id}\tunsupported-type={envelope['type']}", fg=typer.colors.YELLOW)
                message_ids.append(item.message_id)
                continue
            if envelope["receiver_uuid"] != runtime.state.user_uuid:
                typer.secho(f"{item.message_id}\treceiver-mismatch", fg=typer.colors.YELLOW)
                _debug_log(
                    "post-fix",
                    "H8",
                    "Client/main.py:pull:receiver-mismatch",
                    "Pulled message receiver_uuid mismatch",
                    {
                        "message_id": item.message_id,
                        "envelope_receiver_uuid": envelope.get("receiver_uuid"),
                        "local_user_uuid": runtime.state.user_uuid,
                    },
                )
                message_ids.append(item.message_id)
                continue
            if envelope["receiver_device_id"] != runtime.state.local_device_id:
                typer.secho(f"{item.message_id}\treceiver-device-mismatch", fg=typer.colors.YELLOW)
                _debug_log(
                    "post-fix",
                    "H9",
                    "Client/main.py:pull:receiver-device-mismatch",
                    "Pulled message receiver_device_id mismatch",
                    {
                        "message_id": item.message_id,
                        "envelope_receiver_device_id": envelope.get("receiver_device_id"),
                        "local_device_id": runtime.state.local_device_id,
                        "envelope_sender_uuid": envelope.get("sender_uuid"),
                    },
                )
                message_ids.append(item.message_id)
                _debug_log(
                    "post-fix",
                    "H12",
                    "Client/main.py:pull:receiver-device-mismatch-ack",
                    "Acking mismatched-device message to prevent permanent retry",
                    {
                        "message_id": item.message_id,
                        "receiver_uuid": envelope.get("receiver_uuid"),
                    },
                )
                continue

            client_msg_id = envelope["client_msg_id"]
            sender_uuid = envelope["sender_uuid"]
            sender_device_id = envelope["sender_device_id"]
            incoming_counter = int(envelope["counter"])

            _ensure_conversation_exists(runtime.db_manager, sender_uuid)
            if _is_seen_message(runtime.db_manager, client_msg_id):
                typer.secho(f"{item.message_id}\treplayed-client-msg-id={client_msg_id}", fg=typer.colors.YELLOW)
                message_ids.append(item.message_id)
                continue

            sync_result = _sync_contact_keys(runtime, sender_uuid)
            _warn_changed_devices(sender_uuid, sync_result.changed_devices)
            with runtime.db_manager.get_session() as db:
                sender_device = db.get(ContactDevice, sender_device_id)
            if not sender_device or sender_device.contact_uuid != sender_uuid:
                typer.secho(
                    f"{item.message_id}\tmissing-sender-device-key={sender_device_id}",
                    fg=typer.colors.YELLOW,
                )
                message_ids.append(item.message_id)
                continue

            accepted_counter, counter_reason = _accept_inbound_counter(
                runtime.db_manager,
                sender_uuid,
                sender_device_id,
                incoming_counter,
            )
            if not accepted_counter:
                typer.secho(
                    f"{item.message_id}\t{counter_reason}",
                    fg=typer.colors.YELLOW,
                )
                if counter_reason and (
                    counter_reason.startswith("duplicate-counter")
                    or counter_reason.startswith("outside-window")
                ):
                    message_ids.append(item.message_id)
                continue

            session_key = derive_session_key(
                local_private_key_b64=identity.private_key,
                peer_public_key_b64=sender_device.public_key,
                sender_uuid=sender_uuid,
                receiver_uuid=runtime.state.user_uuid,
                sender_device_id=sender_device_id,
                receiver_device_id=runtime.state.local_device_id,
                protocol_version=PROTOCOL_VERSION,
            )
            aad = _aad_metadata_bytes(envelope)
            try:
                plaintext = AESGCM(session_key).decrypt(
                    base64.b64decode(envelope["nonce"].encode("ascii")),
                    base64.b64decode(envelope["ciphertext"].encode("ascii")),
                    aad,
                ).decode("utf-8")
            except Exception:
                typer.secho(f"{item.message_id}\tdecrypt-failed", fg=typer.colors.YELLOW)
                message_ids.append(item.message_id)
                continue

            _mark_seen_message(runtime.db_manager, client_msg_id, sender_uuid, sender_device_id)
            created_at_dt = _parse_utc_ts(envelope["created_at"])
            ttl = int(envelope["ttl"])
            _touch_conversation(runtime.db_manager, sender_uuid, increase_unread=envelope["type"] == ENVELOPE_TYPE_CHAT, at=created_at_dt)

            if envelope["type"] == ENVELOPE_TYPE_CHAT:
                _save_message(
                    runtime.db_manager,
                    conversation_id=sender_uuid,
                    sender_id=sender_uuid,
                    receiver_id=runtime.state.user_uuid,
                    content_plaintext=plaintext,
                    ttl=ttl,
                    received_at=created_at_dt,
                    client_msg_id=client_msg_id,
                    message_type=ENVELOPE_TYPE_CHAT,
                    status="DELIVERED",
                )
                typer.echo(
                    f"{item.message_id}\tfrom={sender_uuid}\tcounter={incoming_counter}\tttl={ttl}\tmessage={plaintext}"
                )

                receipt_counter = _next_counter(
                    runtime.db_manager,
                    sender_uuid,
                    sender_device_id,
                    "OUTBOUND",
                )
                receipt_created = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                receipt_nonce = os.urandom(12)
                receipt_session_key = derive_session_key(
                    local_private_key_b64=identity.private_key,
                    peer_public_key_b64=sender_device.public_key,
                    sender_uuid=runtime.state.user_uuid,
                    receiver_uuid=sender_uuid,
                    sender_device_id=runtime.state.local_device_id,
                    receiver_device_id=sender_device_id,
                    protocol_version=PROTOCOL_VERSION,
                )
                receipt_envelope = {
                    "v": PROTOCOL_VERSION,
                    "type": ENVELOPE_TYPE_RECEIPT,
                    "client_msg_id": str(uuid.uuid4()),
                    "sender_uuid": runtime.state.user_uuid,
                    "receiver_uuid": sender_uuid,
                    "sender_device_id": runtime.state.local_device_id,
                    "receiver_device_id": sender_device_id,
                    "counter": receipt_counter,
                    "ttl": ttl,
                    "created_at": receipt_created,
                    "nonce": base64.b64encode(receipt_nonce).decode("ascii"),
                }
                receipt_payload = json.dumps({"ack_client_msg_id": client_msg_id}, separators=(",", ":")).encode("utf-8")
                receipt_aad = _aad_metadata_bytes(receipt_envelope)
                receipt_cipher = AESGCM(receipt_session_key).encrypt(receipt_nonce, receipt_payload, receipt_aad)
                receipt_envelope["ciphertext"] = base64.b64encode(receipt_cipher).decode("ascii")
                run_api_call(
                    lambda: api.send_message(
                        SendMessageRequest(
                            receiver_uuid=sender_uuid,
                            ciphertext=json.dumps(receipt_envelope, separators=(",", ":")),
                            expire_duration=ttl,
                        )
                    )
                )
            else:
                try:
                    receipt_data = json.loads(plaintext)
                except json.JSONDecodeError:
                    typer.secho(f"{item.message_id}\tinvalid-receipt-body", fg=typer.colors.YELLOW)
                    message_ids.append(item.message_id)
                    continue
                ack_client_msg_id = receipt_data.get("ack_client_msg_id")
                if not ack_client_msg_id:
                    typer.secho(f"{item.message_id}\treceipt-missing-ack-id", fg=typer.colors.YELLOW)
                    message_ids.append(item.message_id)
                    continue
                updated = _mark_outbound_delivered_by_client_msg_id(runtime.db_manager, sender_uuid, ack_client_msg_id)
                _save_message(
                    runtime.db_manager,
                    conversation_id=sender_uuid,
                    sender_id=sender_uuid,
                    receiver_id=runtime.state.user_uuid,
                    content_plaintext=f"receipt:{ack_client_msg_id}",
                    ttl=ttl,
                    received_at=created_at_dt,
                    client_msg_id=client_msg_id,
                    message_type=ENVELOPE_TYPE_RECEIPT,
                    status="DELIVERED",
                    ack_client_msg_id=ack_client_msg_id,
                )
                if updated:
                    typer.secho(
                        f"{item.message_id}\treceipt-ack={ack_client_msg_id}\tstatus=DELIVERED",
                        fg=typer.colors.GREEN,
                    )
                else:
                    typer.secho(
                        f"{item.message_id}\treceipt-ack={ack_client_msg_id}\tlocal-message-not-found",
                        fg=typer.colors.YELLOW,
                    )
            message_ids.append(item.message_id)

        if ack and message_ids:
            ack_response = run_api_call(
                lambda: api.acknowledge_messages(AckMessagesRequest(message_ids=message_ids))
            )
            typer.echo(ack_response.message)
    finally:
        api.close()


@app.command("sync-contact-keys")
def sync_contact_keys(contact_uuid: str):
    """Fetch contact keys, store fingerprints, and detect key changes."""
    runtime = build_runtime()
    require_login(runtime)
    result = _sync_contact_keys(runtime, contact_uuid)
    typer.echo(f"Synced {result.synced_devices} active device key(s) for contact {contact_uuid}.")
    _warn_changed_devices(contact_uuid, result.changed_devices)


@app.command("show-fingerprints")
def show_fingerprints(contact_uuid: str, refresh: bool = typer.Option(True, "--refresh/--no-refresh")):
    """Show device fingerprints and verification state for a contact."""
    runtime = build_runtime()
    require_login(runtime)
    if refresh:
        result = _sync_contact_keys(runtime, contact_uuid)
        _warn_changed_devices(contact_uuid, result.changed_devices)

    with runtime.db_manager.get_session() as db:
        rows = db.execute(
            select(ContactDevice).where(ContactDevice.contact_uuid == contact_uuid)
        ).scalars().all()

    if not rows:
        typer.echo("No device keys found. Run sync-contact-keys first.")
        return

    output_rows = []
    for item in rows:
        status = "VERIFIED" if item.is_verified else "UNVERIFIED"
        output_rows.append([item.contact_device_id, status, item.fingerprint or "-"])
    _print_columns(["DeviceID", "Status", "Fingerprint"], output_rows)


@app.command("verify-device")
def verify_device(contact_uuid: str, device_id: str):
    """Mark one contact device as verified."""
    runtime = build_runtime()
    require_login(runtime)
    with runtime.db_manager.get_session() as db:
        record = db.get(ContactDevice, device_id)
        if not record or record.contact_uuid != contact_uuid:
            raise typer.BadParameter("Device not found for the specified contact.")
        record.is_verified = True
    typer.echo(f"Marked device {device_id} as verified.")


@app.command("unverified-keys")
def unverified_keys():
    """List all unverified contact devices."""
    runtime = build_runtime()
    require_login(runtime)
    with runtime.db_manager.get_session() as db:
        rows = db.execute(
            select(ContactDevice).where(ContactDevice.is_verified.is_(False))
        ).scalars().all()

    if not rows:
        typer.echo("All known contact devices are verified.")
        return

    output_rows = [[item.contact_uuid, item.contact_device_id, item.fingerprint or "-"] for item in rows]
    _print_columns(["ContactUUID", "DeviceID", "Fingerprint"], output_rows)


@app.command("my-fingerprint")
def my_fingerprint():
    """Show current user's local device fingerprint."""
    runtime = build_runtime()
    require_login(runtime)

    with runtime.db_manager.get_session() as db:
        identity = db.query(LocalIdentity).first()

    if not identity:
        typer.secho("No local identity key found. Please login first.", fg=typer.colors.YELLOW)
        return

    fingerprint = key_fingerprint(identity.public_key)
    typer.echo(f"user_uuid={runtime.state.user_uuid}")
    typer.echo(f"device_id={runtime.state.local_device_id}")
    typer.echo(f"fingerprint={fingerprint}")


@app.command("conversations")
def conversations():
    """List local conversations ordered by recent activity."""
    runtime = build_runtime()
    require_login(runtime)
    expired = _cleanup_expired_local_messages(runtime.db_manager)
    if expired:
        typer.secho(f"Cleaned {expired} expired local message(s).", fg=typer.colors.BLUE)
    with runtime.db_manager.get_session() as db:
        rows = db.execute(
            select(Conversation).order_by(Conversation.last_activity.desc())
        ).scalars().all()
        _debug_log(
            "pre-fix",
            "H1",
            "Client/main.py:conversations:query",
            "Fetched conversation rows in active session",
            {
                "rows_count": len(rows),
                "db_expire_on_commit": bool(getattr(db, "expire_on_commit", False)),
                "first_row_bound_before_close": object_session(rows[0]) is not None if rows else False,
            },
        )
    _debug_log(
        "pre-fix",
        "H1",
        "Client/main.py:conversations:after-session-close",
        "Conversation rows state after session context",
        {
            "rows_count": len(rows),
            "first_row_bound_after_close": object_session(rows[0]) is not None if rows else False,
        },
    )
    if not rows:
        typer.echo("No local conversations.")
        return
    output_rows: list[list[str]] = []
    for row in rows:
        try:
            ts = row.last_activity.isoformat() if row.last_activity else "-"
            output_rows.append([row.contact_uuid, row.contact_name, str(row.unread_threads), ts])
        except Exception as exc:
            _debug_log(
                "pre-fix",
                "H1",
                "Client/main.py:conversations:row-access-error",
                "Conversation row attribute access failed",
                {"error": str(exc)},
            )
            raise
    _print_columns(["ContactUUID", "ContactName", "Unread", "LastActivity"], output_rows)


@app.command("history")
def history(
    contact_uuid: str,
    limit: int = typer.Option(20, "--limit", min=1, max=200),
    before: str | None = typer.Option(None, "--before", help="RFC3339 timestamp; load messages older than this value."),
):
    """Show paged local message history for one conversation."""
    runtime = build_runtime()
    require_login(runtime)
    expired = _cleanup_expired_local_messages(runtime.db_manager)
    if expired:
        typer.secho(f"Cleaned {expired} expired local message(s).", fg=typer.colors.BLUE)
    before_dt = _parse_utc_ts(before) if before else None
    with runtime.db_manager.get_session() as db:
        query = select(Message).where(Message.conversation_id == contact_uuid)
        if before_dt:
            query = query.where(Message.receive_at < before_dt)
        rows = db.execute(query.order_by(Message.receive_at.desc()).limit(limit)).scalars().all()
    if not rows:
        typer.echo("No local history for this conversation.")
        _touch_conversation(runtime.db_manager, contact_uuid, clear_unread=True)
        return
    output_rows: list[list[str]] = []
    for row in rows:
        ts = row.receive_at.isoformat() if row.receive_at else "-"
        client_id = row.client_msg_id or "-"
        output_rows.append(
            [
                ts,
                row.message_type,
                row.status,
                client_id,
                row.ack_client_msg_id or "-",
                _short_text(row.content_plaintext, 80),
            ]
        )
    _print_columns(["Time", "Type", "Status", "ClientMsgID", "AckClientMsgID", "Message"], output_rows)
    _touch_conversation(runtime.db_manager, contact_uuid, clear_unread=True)


@app.command("interactive")
def interactive():
    """Run an interactive shell for executing multiple commands."""
    _run_interactive_shell()


if __name__ == "__main__":
    app()
