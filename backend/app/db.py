"""Database setup. SQLite locally (zero-config); swap to Postgres in prod by
setting DATABASE_URL — SQLAlchemy handles the rest, no code changes."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mostakhles.db")

# check_same_thread is a SQLite-only quirk; harmless to omit for Postgres.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    """Create tables if they don't exist."""
    from app import models  # noqa: F401 — register models on Base before create_all
    Base.metadata.create_all(bind=engine)
