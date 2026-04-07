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
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

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
