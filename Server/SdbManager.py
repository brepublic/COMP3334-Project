import logging
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

from Server_db import Base
from config import settings


logger = logging.getLogger(__name__)

class ServerDBManager:
    """
    This class manages the underlying database. It checks if database exists, if not, create one. It then returns the *session* needed to operate database.
    """
    
    def __init__(self, db_name=None):
        configured_name = db_name or settings.SERVER_DB_PATH
        self.db_name = Path(configured_name).expanduser()
        # Automatically create a database if not found.
        self.db_url = f"sqlite:///{db_name}"
        self.engine = None
        self.SessionLocal = None
        #Automatically check and init database        
        self._initialize_database()

    def _initialize_database(self):
        """Chekc and init db"""
        # It's an interest design I copied from other code. SQL Alchemy only verify if the TABLES exist regardless of underlying database. Chaning self.db_url's value won't affect SQL alchemy's reading. 
        self.db_name.parent.mkdir(parents=True, exist_ok=True)
        self.db_url = f"sqlite:///{self.db_name}"
        self.engine = create_engine(self.db_url, connect_args={"check_same_thread": False}, echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        # SQL Alchemy will decide if it needs to create a database.
        Base.metadata.create_all(bind=self.engine)
        self._apply_runtime_migrations()
        logger.debug("Database initialization/verification complete.")

    def _apply_runtime_migrations(self):
        """Apply minimal runtime migrations for SQLite development DB."""
        inspector = inspect(self.engine)
        user_columns = {col["name"] for col in inspector.get_columns("users")}
        if "token_invalid_before" not in user_columns:
            with self.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN token_invalid_before DATETIME"))

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
    session = ServerDBManager().get_session()
