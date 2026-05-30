"""Database setup. Postgres in dev + prod via DATABASE_URL; falls back to
SQLite only when DATABASE_URL is unset (handy for unit tests)."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mostakhles.db")

# check_same_thread is a SQLite-only quirk; harmless to omit for Postgres.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    """Create tables on a fresh database. Alembic owns schema migrations from
    here on — this is just a safety net for first-boot / unit tests."""
    from app import models  # noqa: F401 — register models on Base before create_all
    Base.metadata.create_all(bind=engine)
