import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from contextlib import contextmanager

from Server_db import Base

class ServerDBManager:
    """
    This class manages the underlying database. It checks if database exists, if not, create one. It then returns the *session* needed to operate database.
    """
    
    def __init__(self, db_name="sdb.db"):
        self.db_name = db_name
        self.db_url = f"sqlite:///{db_name}"
        self.engine = None
        self.SessionLocal = None
        #Automatically check and init database        
        self._initialize_database()

    def _initialize_database(self):
        """Chekc and init db"""
        
        db_exists = os.path.exists(self.db_name)
        
        # Create engine
        self.engine = create_engine(
            self.db_url, 
            connect_args={"check_same_thread": False},
            echo=False
        )
        
        # Create Session
        self.SessionLocal = sessionmaker(
            autocommit=False, 
            autoflush=False, 
            bind=self.engine
        )

        # Check if db already exist
        if not db_exists:
            print(f" Database '{self.db_name}' Doesn't exist, now initialize.")
            Base.metadata.create_all(bind=self.engine)
            print("Database initialization complete.")
        else:
            print(f"Database exists, now create session.")

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