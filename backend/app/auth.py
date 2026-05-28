"""API-key resolution + monthly usage metering.

Free tier is enforced here: each successful extraction increments a per-key,
per-month counter; when it reaches the plan limit the caller gets a 429.
"""
import hashlib
import os
import secrets
from datetime import datetime

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models
from app.db import SessionLocal

# Common disposable-email domains. Not exhaustive — Turnstile catches most bots — but blocks
# the obvious ones with zero infrastructure.
DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "tempmail.com", "tempmail.net", "10minutemail.com", "10minutemail.net",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "guerrillamail.biz",
    "sharklasers.com", "trashmail.com", "trashmail.net", "throwaway.email", "yopmail.com",
    "yopmail.net", "yopmail.fr", "getnada.com", "nada.email", "spam4.me", "fakeinbox.com",
    "mintemail.com", "dispostable.com", "maildrop.cc", "mailcatch.com", "tmail.ws",
    "mvrht.com", "moakt.com", "binkmail.com", "tempr.email", "tempmailo.com", "emailondeck.com",
    "mailnesia.com", "harakirimail.com", "discard.email", "20minutemail.com", "33mail.com",
    "mailcatch.org", "spambox.us", "spamgourmet.com", "anonbox.net", "deadaddress.com",
    "burnermail.io", "tempinbox.com", "owlymail.com", "linshiyou.com", "byom.de",
    "boximail.com", "letthemeatspam.com", "instant-mail.de", "fakemail.net", "tempemail.net",
    "tempemail.co", "tempemail.us", "tempm.com", "1secmail.com", "1secmail.net", "1secmail.org",
})


def is_disposable_email(email: str) -> bool:
    domain = (email.rsplit("@", 1)[-1] if "@" in email else "").strip().lower()
    return domain in DISPOSABLE_DOMAINS


def verify_turnstile(token: str | None, remote_ip: str | None = None) -> bool:
    """Validate a Cloudflare Turnstile token. Skipped (returns True) when not configured."""
    secret = os.getenv("CF_TURNSTILE_SECRET")
    if not secret:
        return True  # not configured — don't break local dev
    if not token:
        return False
    try:
        r = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": remote_ip or ""},
            timeout=8,
        )
        return bool(r.ok and r.json().get("success"))
    except requests.RequestException:
        return False


def turnstile_sitekey() -> str:
    """Public sitekey for the frontend widget; empty string means widget is hidden."""
    return os.getenv("CF_TURNSTILE_SITEKEY", "")

# Plans are metered in CREDITS. A page costs 1 credit on the fast model (Haiku)
# or STRONG_UNITS credits on the high-accuracy model (Sonnet + thinking), since
# the strong model costs ~8x more. Quota then tracks real cost, so the gross
# margin (~70%) holds regardless of which model customers use.
STRONG_UNITS = int(os.getenv("STRONG_UNITS", "8"))

PLAN_LIMITS = {  # credits / month
    "free": 300,
    "starter": 1500,
    "pro": 5000,
    "business": 15000,
    "demo": int(os.getenv("DEMO_MONTHLY_LIMIT", "2000")),  # public /app demo
}


def credits_for(hard: bool) -> int:
    """Credits one page consumes: 8 on the strong path, 1 on the fast path."""
    return STRONG_UNITS if hard else 1

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


# ---- Passwords (stdlib pbkdf2, no extra deps) ----

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return f"pbkdf2_sha256$200000${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt, expected = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return secrets.compare_digest(dk.hex(), expected)
    except Exception:  # noqa: BLE001
        return False


# ---- Web sessions (cookie token -> server-side row) ----

def create_session(db: Session, user: models.User) -> str:
    token = secrets.token_urlsafe(32)
    db.add(models.Session(token=token, user_id=user.id))
    db.commit()
    return token


def user_from_session(db: Session, token: str | None):
    if not token:
        return None
    sess = db.get(models.Session, token)
    return db.get(models.User, sess.user_id) if sess else None


def delete_session(db: Session, token: str | None) -> None:
    if not token:
        return
    sess = db.get(models.Session, token)
    if sess:
        db.delete(sess)
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
