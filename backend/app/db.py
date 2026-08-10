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


# --- Alembic schema-revision guard (P0.7) ---------------------------------
import os as _os  # noqa: E402

_BACKEND_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))


def _alembic_config():
    from alembic.config import Config
    cfg = Config(_os.path.join(_BACKEND_DIR, "alembic.ini"))
    # Resolve script_location to an absolute path so this works regardless of CWD.
    cfg.set_main_option("script_location", _os.path.join(_BACKEND_DIR, "alembic"))
    return cfg


def alembic_head_revisions() -> set:
    """The code's Alembic head revision(s). A healthy migration tree has exactly
    one head; more than one means a branch was introduced and must be merged."""
    from alembic.script import ScriptDirectory
    return set(ScriptDirectory.from_config(_alembic_config()).get_heads())


def assert_schema_current(engine_=None) -> None:
    """Fail fast if the database's Alembic revision is not the code's head.

    READ-ONLY: this NEVER migrates automatically — it only verifies and raises a
    RuntimeError telling the operator to run `alembic upgrade head`. Call this at
    startup ONLY against a migration-managed (production) database; a fresh dev/test
    SQLite DB built by create_all() has no alembic_version row and would (correctly)
    look out-of-date here, which is why lifespan gates the call on ENV=prod.
    """
    from alembic.migration import MigrationContext
    eng = engine_ or engine
    heads = alembic_head_revisions()
    with eng.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current not in heads:
        raise RuntimeError(
            f"Database schema revision {current!r} is not the code head {sorted(heads)}. "
            "Run `alembic upgrade head` before starting the app "
            "(startup does NOT auto-migrate, and never runs destructive migrations)."
        )


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
