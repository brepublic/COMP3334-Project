from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager
from sqlalchemy import text

if __package__:
    from .CLient_db import Base
else:
    from CLient_db import Base

class ClientDBManager:
    """
    This class manages the underlying database. It checks if database exists, if not, create one. It then returns the *session* needed to operate database.
    """

    def __init__(self, db_name="cdb.db"):
        self.db_name = Path(db_name).expanduser()
        self.db_url = f"sqlite:///{self.db_name}"
        self.engine = None
        self.SessionLocal = None
        #Automatically check and init database        
        self._initialize_database()

    def _initialize_database(self):
        """Chekc and init db"""
        self.db_name.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(self.db_url, connect_args={"check_same_thread": False}, echo=False)
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
            expire_on_commit=False,
        )

        # SQL Alchemy will decide if it needs to create a database.
        Base.metadata.create_all(bind=self.engine)
        self._run_schema_migrations()
        print("Database initialization/verification complete.")

    def _column_exists(self, table_name: str, column_name: str) -> bool:
        with self.engine.connect() as conn:
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            return any(row[1] == column_name for row in rows)

    def _add_column_if_missing(self, table_name: str, column_name: str, column_type: str) -> None:
        if self._column_exists(table_name, column_name):
            return
        with self.engine.begin() as conn:
            conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))

    def _run_schema_migrations(self) -> None:
        self._add_column_if_missing("local_identity", "private_key_encrypted", "TEXT")
        self._add_column_if_missing("local_identity", "private_key_salt", "TEXT")
        self._add_column_if_missing("local_identity", "private_key_kdf", "TEXT")
        self._add_column_if_missing("local_identity", "private_key_kdf_params", "TEXT")
        self._add_column_if_missing("local_identity", "private_key_nonce", "TEXT")

        self._add_column_if_missing("contact_devices", "fingerprint", "TEXT")
        self._add_column_if_missing("contact_devices", "last_seen_key_hash", "TEXT")
        self._add_column_if_missing("conversations", "last_activity", "TEXT")
        self._add_column_if_missing("messages", "client_msg_id", "TEXT")
        self._add_column_if_missing("messages", "message_type", "TEXT DEFAULT 'CHAT'")
        self._add_column_if_missing("messages", "status", "TEXT DEFAULT 'SENT'")
        self._add_column_if_missing("messages", "ack_client_msg_id", "TEXT")
        self._add_column_if_missing("messages", "expires_at", "TEXT")
        self._ensure_table_seen_messages()
        self._ensure_table_message_counters()
        self._ensure_counter_index()
        self._ensure_message_indexes()

    def _table_exists(self, table_name: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = :name"
                ),
                {"name": table_name},
            ).first()
            return row is not None

    def _ensure_table_seen_messages(self) -> None:
        if self._table_exists("seen_messages"):
            return
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE seen_messages (
                        client_msg_id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        sender_device_id TEXT NOT NULL,
                        received_at TEXT
                    )
                    """
                )
            )

    def _ensure_table_message_counters(self) -> None:
        if self._table_exists("message_counters"):
            return
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE message_counters (
                        id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        peer_device_id TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        counter_value INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
            )

    def _ensure_counter_index(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE UNIQUE INDEX IF NOT EXISTS ux_message_counters_scope
                    ON message_counters(conversation_id, peer_device_id, direction)
                    """
                )
            )

    def _ensure_message_indexes(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_messages_conversation_receive_at
                    ON messages(conversation_id, receive_at DESC)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_messages_client_msg_id
                    ON messages(client_msg_id)
                    """
                )
            )

    def _get_session(self):
        """
        Create and return a session.
        """
        if self.SessionLocal is None:
            raise RuntimeError("Database uninitialized!")
        return self.SessionLocal()

    @contextmanager
    def get_session(self):
        """
        Create and return a session that close on its own.
        """
        session = self._get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

if __name__ == "__main__":
    session = ClientDBManager()
