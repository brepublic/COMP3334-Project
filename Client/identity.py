import base64
import hashlib
import json
import os
from dataclasses import dataclass

from sqlalchemy import text
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

if __package__:
    from .CdbManager import ClientDBManager
    from .CLient_db import LocalIdentity
else:
    from CdbManager import ClientDBManager
    from CLient_db import LocalIdentity


@dataclass
class IdentityMaterial:
    uuid: str
    public_key: str
    private_key: str


def _encode_public_key(public_key) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def _encode_private_key(private_key) -> str:
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode("ascii")


def _decode_public_key(public_key_b64: str) -> bytes:
    return base64.b64decode(public_key_b64.encode("ascii"))


def _decode_private_key(private_key_b64: str) -> bytes:
    return base64.b64decode(private_key_b64.encode("ascii"))


def load_private_key(private_key_b64: str) -> X25519PrivateKey:
    return X25519PrivateKey.from_private_bytes(_decode_private_key(private_key_b64))


def load_public_key(public_key_b64: str) -> X25519PublicKey:
    return X25519PublicKey.from_public_bytes(_decode_public_key(public_key_b64))


def derive_session_key(
    local_private_key_b64: str,
    peer_public_key_b64: str,
    sender_uuid: str,
    receiver_uuid: str,
    sender_device_id: str,
    receiver_device_id: str,
    protocol_version: int = 1,
) -> bytes:
    local_private_key = load_private_key(local_private_key_b64)
    peer_public_key = load_public_key(peer_public_key_b64)
    shared_secret = local_private_key.exchange(peer_public_key)

    info = (
        f"comp3334-e2ee-v{protocol_version}|"
        f"sender={sender_uuid}|receiver={receiver_uuid}|"
        f"sender_device={sender_device_id}|receiver_device={receiver_device_id}"
    ).encode("utf-8")
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=info,
    )
    return hkdf.derive(shared_secret)


def derive_kek_from_login_password(password: str, salt: bytes, kdf_params: dict | None = None) -> tuple[bytes, dict]:
    params = kdf_params or {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
    key = hashlib.scrypt(
        password=password.encode("utf-8"),
        salt=salt,
        n=params["n"],
        r=params["r"],
        p=params["p"],
        dklen=params["dklen"],
    )
    return key, params


def encrypt_private_key(raw_private_key_b64: str, kek: bytes) -> tuple[str, str]:
    nonce = os.urandom(12)
    cipher = AESGCM(kek)
    ciphertext = cipher.encrypt(nonce, raw_private_key_b64.encode("utf-8"), None)
    return (
        base64.b64encode(ciphertext).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
    )


def decrypt_private_key(ciphertext_b64: str, nonce_b64: str, kek: bytes) -> str:
    cipher = AESGCM(kek)
    plaintext = cipher.decrypt(
        base64.b64decode(nonce_b64.encode("ascii")),
        base64.b64decode(ciphertext_b64.encode("ascii")),
        None,
    )
    return plaintext.decode("utf-8")


def key_fingerprint(public_key_b64: str) -> str:
    return hashlib.sha256(_decode_public_key(public_key_b64)).hexdigest()


def ensure_local_identity(db_manager: ClientDBManager, login_password: str) -> IdentityMaterial:
    with db_manager.get_session() as db:
        identity = db.query(LocalIdentity).first()
        if identity:
            if identity.private_key_encrypted and identity.private_key_salt and identity.private_key_nonce:
                salt = base64.b64decode(identity.private_key_salt.encode("ascii"))
                params = (
                    json.loads(identity.private_key_kdf_params)
                    if identity.private_key_kdf_params
                    else None
                )
                kek, _ = derive_kek_from_login_password(login_password, salt, params)
                private_key = decrypt_private_key(identity.private_key_encrypted, identity.private_key_nonce, kek)
                return IdentityMaterial(
                    uuid=identity.uuid,
                    public_key=identity.public_key,
                    private_key=private_key,
                )

            # Legacy migration path from plaintext private key.
            if not identity.private_key:
                raise RuntimeError("Local identity exists but private key is missing.")

            schema_rows = db.execute(text("PRAGMA table_info(local_identity)")).fetchall()
            private_key_schema = next((row for row in schema_rows if row[1] == "private_key"), None)
            salt = os.urandom(16)
            kek, params = derive_kek_from_login_password(login_password, salt)
            encrypted_private_key, nonce = encrypt_private_key(identity.private_key, kek)
            identity.private_key_encrypted = encrypted_private_key
            identity.private_key_salt = base64.b64encode(salt).decode("ascii")
            identity.private_key_nonce = nonce
            identity.private_key_kdf = "scrypt"
            identity.private_key_kdf_params = json.dumps(params)
            plaintext_private_key = identity.private_key
            if not (private_key_schema and private_key_schema[3] == 1):
                identity.private_key = None
            return IdentityMaterial(
                uuid=identity.uuid,
                public_key=identity.public_key,
                private_key=plaintext_private_key,
            )

        private_key = X25519PrivateKey.generate()
        private_key_b64 = _encode_private_key(private_key)
        salt = os.urandom(16)
        kek, params = derive_kek_from_login_password(login_password, salt)
        encrypted_private_key, nonce = encrypt_private_key(private_key_b64, kek)
        identity = LocalIdentity(
            public_key=_encode_public_key(private_key.public_key()),
            private_key=None,
            private_key_encrypted=encrypted_private_key,
            private_key_salt=base64.b64encode(salt).decode("ascii"),
            private_key_kdf="scrypt",
            private_key_kdf_params=json.dumps(params),
            private_key_nonce=nonce,
        )
        db.add(identity)
        db.flush()

        return IdentityMaterial(
            uuid=identity.uuid,
            public_key=identity.public_key,
            private_key=private_key_b64,
        )
