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
from datetime import datetime, timedelta  # noqa: E402

SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "30"))


def create_session(db: Session, user: models.User) -> str:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    expires = datetime.utcnow() + timedelta(days=SESSION_TTL_DAYS)
    db.add(models.Session(token=token, user_id=user.id, csrf_token=csrf, expires_at=expires))
    db.commit()
    return token


def get_session(db: Session, token: str | None):
    """Return the Session row if valid (not expired). Deletes expired rows lazily."""
    if not token:
        return None
    sess = db.get(models.Session, token)
    if not sess:
        return None
    if sess.expires_at and sess.expires_at < datetime.utcnow():
        try:
            db.delete(sess); db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return None
    return sess


def user_from_session(db: Session, token: str | None):
    sess = get_session(db, token)
    if not sess:
        return None
    return db.get(models.User, sess.user_id)


def session_csrf_token(db: Session, token: str | None) -> str | None:
    sess = get_session(db, token)
    return sess.csrf_token if sess else None


def verify_csrf(db: Session, session_token: str | None, submitted_token: str | None) -> bool:
    """Constant-time compare the form-submitted CSRF token against the session's."""
    real = session_csrf_token(db, session_token)
    if not real or not submitted_token:
        return False
    return secrets.compare_digest(real, submitted_token)


def delete_session(db: Session, token: str | None) -> None:
    if not token:
        return
    sess = db.get(models.Session, token)
    if sess:
        db.delete(sess)
        db.commit()


# ---- Login rate-limit (in-memory; production: front with Cloudflare / Redis) ----
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_WINDOW_SEC = 900   # 15 min
_LOGIN_MAX = 5            # attempts per IP per window


def login_rate_limit_check(ip: str | None) -> bool:
    """Return True if this IP is allowed to attempt login now."""
    import time
    if not ip:
        return True
    now = time.time()
    attempts = [t for t in _LOGIN_ATTEMPTS.get(ip, []) if now - t < _LOGIN_WINDOW_SEC]
    _LOGIN_ATTEMPTS[ip] = attempts
    return len(attempts) < _LOGIN_MAX


def login_rate_limit_record(ip: str | None) -> None:
    import time
    if not ip:
        return
    _LOGIN_ATTEMPTS.setdefault(ip, []).append(time.time())


# ---- Password reset tokens (1-hour TTL) ----

def make_password_reset(db: Session, user: models.User) -> str:
    token = secrets.token_urlsafe(32)
    user.password_reset_token = token
    user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
    db.commit()
    return token


def consume_password_reset(db: Session, token: str) -> "models.User | None":
    if not token:
        return None
    user = db.query(models.User).filter_by(password_reset_token=token).first()
    if not user or not user.password_reset_expires:
        return None
    if user.password_reset_expires < datetime.utcnow():
        return None
    return user


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
