"""API-key resolution + monthly usage metering.

Free tier is enforced here: each successful extraction increments a per-key,
per-month counter; when it reaches the plan limit the caller gets a 429.
"""
import os
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal

# Monthly extraction quota per plan. Mirrors the pricing tiers.
PLAN_LIMITS = {
    "free": 50,
    "starter": 500,
    "pro": 2500,
    "business": 10000,
    "demo": int(os.getenv("DEMO_MONTHLY_LIMIT", "500")),  # public /app demo
}

# Fixed key used by the public demo page when no x-api-key is supplied.
DEMO_API_KEY = os.getenv("DEMO_API_KEY", "mk_demo_public")


def current_period() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def resolve_key(db: Session, raw_key: str) -> models.ApiKey:
    api_key = db.query(models.ApiKey).filter_by(key=raw_key, active=True).first()
    if not api_key:
        raise HTTPException(401, "invalid or inactive API key")
    return api_key


def get_usage(db: Session, api_key: models.ApiKey):
    """Return (used, limit, usage_row_or_None) for the current month."""
    row = (
        db.query(models.Usage)
        .filter_by(api_key_id=api_key.id, period=current_period())
        .first()
    )
    used = row.count if row else 0
    limit = PLAN_LIMITS.get(api_key.user.plan, 50)
    return used, limit, row


def enforce_limit(db: Session, api_key: models.ApiKey, needed: int = 1) -> None:
    """Raise 429 if this request (which costs `needed` units) would exceed quota."""
    used, limit, _ = get_usage(db, api_key)
    if used + needed > limit:
        raise HTTPException(
            429,
            f"monthly limit reached ({used}/{limit} for plan '{api_key.user.plan}'); "
            f"this request needs {needed}. Upgrade your plan or wait until next month.",
        )


def increment_usage(db: Session, api_key: models.ApiKey, count: int = 1) -> None:
    row = (
        db.query(models.Usage)
        .filter_by(api_key_id=api_key.id, period=current_period())
        .first()
    )
    if row is None:
        row = models.Usage(api_key_id=api_key.id, period=current_period(), count=0)
        db.add(row)
    row.count += count
    db.commit()


def ensure_demo_user() -> None:
    """Seed the demo user + fixed demo key so the public /app page works."""
    db = SessionLocal()
    try:
        if db.query(models.ApiKey).filter_by(key=DEMO_API_KEY).first():
            return
        user = db.query(models.User).filter_by(email="demo@mostakhles.local").first()
        if not user:
            user = models.User(email="demo@mostakhles.local", plan="demo")
            db.add(user)
            db.commit()
            db.refresh(user)
        db.add(models.ApiKey(key=DEMO_API_KEY, user_id=user.id))
        db.commit()
    finally:
        db.close()
