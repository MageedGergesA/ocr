"""High-utilization warning emails for paid users (Pro/Business).

A user who burns >=75% of their monthly credits is a candidate for the next tier up.
Without nudging them, two things happen:
  1. They run out mid-month → bad UX, they may churn.
  2. If they're using `hard` tier heavily, they may be costing us more in Gemini
     than they pay (Pro $59/mo can lose money at 90%+ utilization).

This module is invoked daily (cron / supervisor / systemd timer) via the
`run_high_utilization_check()` entry point, or on-demand via the admin endpoint.

Dedupe within a billing period uses a synthetic `History` row (kind='util_warn_<period>'),
so no schema migration is required.
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import auth, emailer, models


HIGH_UTIL_THRESHOLD = 0.75   # fire at 75% of plan cap
WARNED_USERS_PLANS = ("pro", "business")  # Free/Lite/Starter aren't candidates


def _used_for_user(db: Session, user: models.User, period: str) -> int:
    """Total credits used by all api_keys of this user for the given period."""
    total = (
        db.query(func.coalesce(func.sum(models.Usage.count), 0))
        .join(models.ApiKey, models.Usage.api_key_id == models.ApiKey.id)
        .filter(models.ApiKey.user_id == user.id, models.Usage.period == period)
        .scalar()
    )
    return int(total or 0)


def _already_warned(db: Session, user_id: int, period: str) -> bool:
    return db.query(models.History).filter(
        models.History.user_id == user_id,
        models.History.kind == f"util_warn_{period}",
    ).first() is not None


def maybe_warn_high_utilization(db: Session, user: models.User, force: bool = False) -> bool:
    """Send a high-utilization email if this user qualifies. Idempotent per month."""
    if user.plan not in WARNED_USERS_PLANS:
        return False
    period = auth.current_period()
    limit = auth.PLAN_LIMITS.get(user.plan)
    if not limit:
        return False
    used = _used_for_user(db, user, period)
    if used / limit < HIGH_UTIL_THRESHOLD:
        return False
    if not force and _already_warned(db, user.id, period):
        return False
    next_plan = {"pro": "business", "business": "business"}[user.plan]
    emailer.send_high_utilization_email(user.email, user.plan, used, limit, next_plan)
    db.add(models.History(
        user_id=user.id,
        kind=f"util_warn_{period}",
        document_type=None, layout=None, output_lang=None,
        charged=0, duration_ms=None, result_json={},
    ))
    db.commit()
    return True


def run_high_utilization_check(db: Session) -> dict:
    """Cron entry point — scans Pro/Business users and sends warnings.

    Returns a small summary so the cron caller (or admin endpoint) can log it.
    """
    candidates = db.query(models.User).filter(models.User.plan.in_(WARNED_USERS_PLANS)).all()
    sent = 0
    for user in candidates:
        try:
            if maybe_warn_high_utilization(db, user):
                sent += 1
        except Exception:  # noqa: BLE001 — one user's email shouldn't kill the loop
            continue
    return {"checked": len(candidates), "sent": sent}
