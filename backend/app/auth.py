"""API-key resolution + monthly usage metering.

Free tier is enforced here: each successful extraction increments a per-key,
per-month counter; when it reaches the plan limit the caller gets a 429.
"""
import hashlib
import hmac
import ipaddress
import os
import secrets
from datetime import datetime
from urllib.parse import urlparse

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

PLAN_LIMITS = {  # credits / month — must match the marketing copy on /pricing
    "free": 30,
    "lite": 1200,
    "starter": 3500,
    "pro": 8500,
    "business": 28000,
    "demo": int(os.getenv("DEMO_MONTHLY_LIMIT", "2000")),  # public /app demo
}


# Admin/owner emails — comma-separated env var; defaults to your founder email.
ADMIN_EMAILS = frozenset(
    e.strip().lower()
    for e in os.getenv("ADMIN_EMAILS", "mageed.gerges28@gmail.com").split(",")
    if e.strip()
)


def is_admin(user) -> bool:
    return bool(user and (user.email or "").lower() in ADMIN_EMAILS)


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
    limit = PLAN_LIMITS.get(api_key.user.plan, 30)
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
    # 600_000 iterations is OWASP 2023's minimum for pbkdf2-sha256. Existing 200k
    # hashes verify fine because the iteration count is encoded in the stored string.
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000)
    return f"pbkdf2_sha256$600000${salt}${dk.hex()}"


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


# ---- In-memory rate-limit (production: front with Cloudflare / Redis) ----
# Per-process, per-key. Wipe on restart. Acceptable for MVP behind a single worker
# + Cloudflare edge limit; replace with Redis when scaling out workers.
_RATE_BUCKETS: dict[str, list[float]] = {}


def rate_limit_check(key: str | None, max_attempts: int, window_sec: int) -> bool:
    """Return True if this `key` is allowed another attempt now."""
    import time
    if not key:
        return True  # no key → don't rate limit (caller has no IP, e.g. CLI)
    now = time.time()
    bucket = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window_sec]
    _RATE_BUCKETS[key] = bucket
    return len(bucket) < max_attempts


def rate_limit_record(key: str | None) -> None:
    """Record an attempt for the given key."""
    import time
    if not key:
        return
    _RATE_BUCKETS.setdefault(key, []).append(time.time())


# Legacy names for the login flow — keep the public API stable.
def login_rate_limit_check(ip: str | None) -> bool:
    return rate_limit_check(f"login:{ip}", max_attempts=5, window_sec=900)


def login_rate_limit_record(ip: str | None) -> None:
    rate_limit_record(f"login:{ip}")


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


# ---- Webhook URL safety (SSRF prevention) ----

_BLOCKED_HOSTS = frozenset({
    "localhost", "metadata", "metadata.google.internal",
    "169.254.169.254",  # AWS / Azure / GCP instance metadata
    "100.100.100.200",  # Alibaba Cloud metadata
})


def is_safe_webhook_url(url: str | None) -> bool:
    """Reject SSRF targets. Allow only https + public-routable hosts.

    Rejects: http, file://, ftp://, loopback, link-local, private CIDRs, multicast,
    reserved, instance-metadata endpoints. Hostnames are allowed without DNS resolution
    here — the production deploy should enforce egress filtering at the network layer
    to defeat DNS rebinding (out of scope for app-layer code)."""
    if not url:
        return True  # empty means "no webhook" — fine
    try:
        p = urlparse(url.strip())
    except Exception:  # noqa: BLE001
        return False
    if p.scheme != "https":
        return False
    host = (p.hostname or "").strip().lower()
    if not host or host in _BLOCKED_HOSTS:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # public hostname; egress filter is the second layer
    if (ip.is_loopback or ip.is_private or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
        return False
    return True


def sign_webhook_payload(secret: str, body: bytes, timestamp: str) -> str:
    """HMAC-SHA256 over `timestamp.body`. Customers verify with the same secret."""
    msg = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def ensure_demo_user() -> None:
    """Seed the demo user + fixed demo key so the public /app page works.

    Production guard: refuses to seed if (a) ENV=prod AND (b) DEMO_API_KEY is the
    publicly-known default 'mk_demo_public'. Operators must override the key in
    prod .env or accept that no public demo runs. Without this guard, a
    prod deploy that forgets to set DEMO_API_KEY would publish a 2000-credit/month
    free key with a guessable name.
    """
    import logging
    _log = logging.getLogger("mostakhles")
    if os.getenv("ENV", "local") == "prod" and DEMO_API_KEY == "mk_demo_public":
        _log.warning(
            "ensure_demo_user: refusing to seed demo key 'mk_demo_public' in prod. "
            "Set DEMO_API_KEY to a non-default secret to enable the public demo."
        )
        return
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
