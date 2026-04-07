from dataclasses import dataclass
import base64
import json
import os
import uuid
from datetime import datetime, timezone

import pyotp
import typer
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from qrcode import QRCode
from sqlalchemy import select

if __package__:
    from .api import ChatClientAPI, ClientAPIError
    from .CdbManager import ClientDBManager
    from .CLient_db import ContactDevice, Conversation, MessageCounter, SeenMessage
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
    from CLient_db import ContactDevice, Conversation, MessageCounter, SeenMessage
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

        for device in response.active_devices:
            new_hash = key_fingerprint(device.device_public_key)
            current = by_device_id.get(device.device_id)
            if not current:
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


def _latest_inbound_counter(db_manager: ClientDBManager, conversation_id: str, peer_device_id: str) -> int:
    with db_manager.get_session() as db:
        record = db.execute(
            select(MessageCounter).where(
                MessageCounter.conversation_id == conversation_id,
                MessageCounter.peer_device_id == peer_device_id,
                MessageCounter.direction == "INBOUND",
            )
        ).scalar_one_or_none()
        return record.counter_value if record else 0


def _update_inbound_counter(db_manager: ClientDBManager, conversation_id: str, peer_device_id: str, counter: int) -> None:
    with db_manager.get_session() as db:
        record = db.execute(
            select(MessageCounter).where(
                MessageCounter.conversation_id == conversation_id,
                MessageCounter.peer_device_id == peer_device_id,
                MessageCounter.direction == "INBOUND",
            )
        ).scalar_one_or_none()
        if not record:
            db.add(
                MessageCounter(
                    conversation_id=conversation_id,
                    peer_device_id=peer_device_id,
                    direction="INBOUND",
                    counter_value=counter,
                )
            )
            return
        record.counter_value = max(record.counter_value, counter)


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
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Login password to unlock local identity key."),
):
    """Send an E2EE payload through the current message API."""
    runtime = build_runtime()
    require_login(runtime)
    if not runtime.state.user_uuid:
        raise typer.BadParameter("No saved user UUID found. Run login first.")

    identity = ensure_local_identity(runtime.db_manager, password)
    _ensure_conversation_exists(runtime.db_manager, receiver_uuid)
    _sync_contact_keys(runtime, receiver_uuid)
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
    envelope = {
        "v": PROTOCOL_VERSION,
        "type": ENVELOPE_TYPE_CHAT,
        "client_msg_id": str(uuid.uuid4()),
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

    typer.echo(f"Server message ID: {response.message_id}")
    typer.echo(f"Server status: {response.status}")


@app.command()
def pull(
    ack: bool = typer.Option(True, "--ack/--no-ack", help="Acknowledge pulled messages."),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Login password to unlock local identity key."),
):
    """Pull offline messages and optionally ACK them."""
    runtime = build_runtime()
    require_login(runtime)
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
                continue

            if envelope["type"] != ENVELOPE_TYPE_CHAT:
                typer.secho(f"{item.message_id}\tunsupported-type={envelope['type']}", fg=typer.colors.YELLOW)
                continue
            if envelope["receiver_uuid"] != runtime.state.user_uuid:
                typer.secho(f"{item.message_id}\treceiver-mismatch", fg=typer.colors.YELLOW)
                continue
            if envelope["receiver_device_id"] != runtime.state.local_device_id:
                typer.secho(f"{item.message_id}\treceiver-device-mismatch", fg=typer.colors.YELLOW)
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

            latest_counter = _latest_inbound_counter(runtime.db_manager, sender_uuid, sender_device_id)
            if incoming_counter <= latest_counter:
                typer.secho(
                    f"{item.message_id}\tstale-counter={incoming_counter}\tlatest={latest_counter}",
                    fg=typer.colors.YELLOW,
                )
                message_ids.append(item.message_id)
                continue

            _sync_contact_keys(runtime, sender_uuid)
            with runtime.db_manager.get_session() as db:
                sender_device = db.get(ContactDevice, sender_device_id)
            if not sender_device or sender_device.contact_uuid != sender_uuid:
                typer.secho(
                    f"{item.message_id}\tmissing-sender-device-key={sender_device_id}",
                    fg=typer.colors.YELLOW,
                )
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
                continue

            _mark_seen_message(runtime.db_manager, client_msg_id, sender_uuid, sender_device_id)
            _update_inbound_counter(runtime.db_manager, sender_uuid, sender_device_id, incoming_counter)
            typer.echo(
                f"{item.message_id}\tfrom={sender_uuid}\tcounter={incoming_counter}\tttl={envelope['ttl']}\tmessage={plaintext}"
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
    if result.changed_devices:
        typer.secho(
            "Warning: key changed for device(s): "
            + ", ".join(result.changed_devices)
            + ". Verification was reset; re-verify fingerprints.",
            fg=typer.colors.YELLOW,
        )


@app.command("show-fingerprints")
def show_fingerprints(contact_uuid: str, refresh: bool = typer.Option(True, "--refresh/--no-refresh")):
    """Show device fingerprints and verification state for a contact."""
    runtime = build_runtime()
    require_login(runtime)
    if refresh:
        _sync_contact_keys(runtime, contact_uuid)

    with runtime.db_manager.get_session() as db:
        rows = db.execute(
            select(ContactDevice).where(ContactDevice.contact_uuid == contact_uuid)
        ).scalars().all()

    if not rows:
        typer.echo("No device keys found. Run sync-contact-keys first.")
        return

    for item in rows:
        status = "VERIFIED" if item.is_verified else "UNVERIFIED"
        typer.echo(f"{item.contact_device_id}\t{status}\t{item.fingerprint}")


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

    for item in rows:
        typer.secho(
            f"{item.contact_uuid}\t{item.contact_device_id}\t{item.fingerprint}",
            fg=typer.colors.YELLOW,
        )


if __name__ == "__main__":
    app()
