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
    _ensure_columns()


def _ensure_columns() -> None:
    """Idempotently add newer nullable columns that create_all() won't ALTER onto
    an existing table (dev only — prod schema changes go through Alembic).
    Keep this list in sync with post-v1 additive columns."""
    from sqlalchemy import text
    additions = {
        "history": {"field_count": "INTEGER", "avg_confidence": "INTEGER"},
        "correction_memory": {"scope_key": "VARCHAR"},
    }
    try:
        with engine.begin() as conn:
            for table, cols in additions.items():
                if engine.dialect.name == "sqlite":
                    existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
                else:
                    existing = {r[0] for r in conn.execute(text(
                        "SELECT column_name FROM information_schema.columns WHERE table_name=:t"),
                        {"t": table})}
                for col, typ in cols.items():
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {typ}"))
    except Exception:  # noqa: BLE001 — never block startup on a best-effort migration
        pass
