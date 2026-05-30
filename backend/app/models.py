"""Data models: users, API keys, monthly usage counters, billing audit trail."""
import secrets
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.db import Base

# JSON columns: use Postgres JSONB (indexed, queryable) and fall back to
# generic JSON on SQLite for local-test compatibility.
JsonCol = JSON().with_variant(JSONB(), "postgresql")


def generate_key() -> str:
    return "mk_" + secrets.token_urlsafe(32)


def generate_webhook_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)  # null for the seeded demo user
    plan = Column(String, default="free", nullable=False)  # free/lite/starter/pro/business/demo
    webhook_url = Column(String, nullable=True)  # POST results here when async jobs finish
    webhook_secret = Column(String, nullable=True)  # HMAC shared secret for outbound webhooks
    # Preferred UI + extraction-output language. Null means "auto-detect from browser".
    preferred_lang = Column(String(2), nullable=True)  # 'ar' | 'en'
    email_verified = Column(Boolean, default=False, nullable=False)
    verification_token = Column(String, nullable=True, index=True)
    password_reset_token = Column(String, nullable=True, index=True)
    password_reset_expires = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("ApiKey", back_populates="user")

    @property
    def is_admin(self) -> bool:
        """True if this user's email is in the ADMIN_EMAILS env var (or default)."""
        from app import auth  # local import to avoid circular
        return auth.is_admin(self)


class Session(Base):
    """Server-side web session — token lives in an httponly cookie."""
    __tablename__ = "sessions"

    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    expires_at = Column(DateTime, nullable=True)  # cleaned up on read after expiry
    csrf_token = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True, nullable=False, default=generate_key)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="api_keys")


class Usage(Base):
    """One row per (api_key, month). Incremented on each successful extraction."""
    __tablename__ = "usage"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    period = Column(String, nullable=False)  # 'YYYY-MM'
    count = Column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("api_key_id", "period", name="uq_key_period"),)


class Template(Base):
    """A reusable named field schema saved by a user."""
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    schema_json = Column(JsonCol, nullable=False)  # {field: description}
    created_at = Column(DateTime, default=datetime.utcnow)


class History(Base):
    """A record of every successful extraction, per user."""
    __tablename__ = "history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String)              # service slug or 'extract'
    document_type = Column(String, nullable=True)
    layout = Column(String, nullable=True)   # 'form' | 'table' | 'narrative' | 'mixed' | 'prescription'
    output_lang = Column(String(2), nullable=True)  # 'ar' | 'en' — language of extracted values
    charged = Column(Integer, default=0)
    duration_ms = Column(Integer, nullable=True)  # extraction wall-clock; null for historical
    result_json = Column(JsonCol)             # JSONB on Postgres — queryable
    corrected_json = Column(JsonCol, nullable=True)  # user corrections from inline edits
    created_at = Column(DateTime, default=datetime.utcnow)

    # Composite index for the dashboard's per-user/per-day aggregations.
    __table_args__ = (
        Index("ix_history_user_created", "user_id", "created_at"),
        Index("ix_history_created", "created_at"),
    )


# ---- Billing audit trail (Paymob + PayPal) ----

class Subscription(Base):
    """One row per (user, plan, provider) — denormalised cache of provider state.
    User.plan is the trust-on-read cache; this is the source of truth for "when does
    it renew, what's the provider's subscription ID, what's its status."
    """
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String, nullable=False)        # 'paypal' | 'paymob'
    external_id = Column(String, nullable=False)     # provider's subscription/agreement ID
    plan = Column(String, nullable=False)            # lite/starter/pro/business
    status = Column(String, nullable=False)          # active | past_due | cancelled | trialing
    current_period_end = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    amount_usd = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_subscription_provider_external"),
    )


class PaymentEvent(Base):
    """Append-only log of every webhook we accept from Paymob or PayPal.
    The UNIQUE(provider, external_id) is the idempotency key — providers retry
    webhooks; we must not double-credit users."""
    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True)
    provider = Column(String, nullable=False)         # 'paypal' | 'paymob'
    external_id = Column(String, nullable=False)      # provider's event ID
    event_type = Column(String, nullable=False)       # e.g. 'BILLING.SUBSCRIPTION.ACTIVATED'
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    amount_usd = Column(Numeric(10, 2), nullable=True)
    raw_payload = Column(Text, nullable=False)        # original body (for audit + reconcile)
    received_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "external_id", name="uq_payment_event_provider_external"),
        Index("ix_payment_event_subscription", "subscription_id"),
    )


class WebhookDelivery(Base):
    """One row per outbound webhook attempt (Mostakhles -> customer URL).
    Lets the admin dashboard surface 'X webhook deliveries failed in the last hour'
    and lets us re-drive failed deliveries from a background worker."""
    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        Integer,
        # ondelete=CASCADE so "delete my account" doesn't FK-violate on Postgres.
        # The application-level sweep in /account/delete also covers this for
        # belt-and-braces.
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    target_url = Column(String, nullable=False)
    event_kind = Column(String, nullable=False)       # 'job.completed' | 'job.partial_failed' | etc.
    payload = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending|delivered|failed|gave_up
    attempt_count = Column(Integer, nullable=False, default=0)
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    next_attempt_at = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
