import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

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


def ensure_local_identity(db_manager: ClientDBManager) -> IdentityMaterial:
    with db_manager.get_session() as db:
        identity = db.query(LocalIdentity).first()
        if identity:
            return IdentityMaterial(
                uuid=identity.uuid,
                public_key=identity.public_key,
                private_key=identity.private_key,
            )

        private_key = X25519PrivateKey.generate()
        identity = LocalIdentity(
            public_key=_encode_public_key(private_key.public_key()),
            private_key=_encode_private_key(private_key),
        )
        db.add(identity)
        db.flush()

        return IdentityMaterial(
            uuid=identity.uuid,
            public_key=identity.public_key,
            private_key=identity.private_key,
        )
