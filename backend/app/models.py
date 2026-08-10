"""Data models: users, API keys, monthly usage counters, billing audit trail."""
import secrets
from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, Numeric,
    String, Text, UniqueConstraint,
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
    """A reusable named field schema saved by a user. When `source_kind` is set
    (xlsx/docx/pdf/html), `source_bytes` holds the original uploaded template so
    extraction results can later be filled back into the same file format."""
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    schema_json = Column(JsonCol, nullable=False)  # {field: description}
    source_kind = Column(String(8), nullable=True)   # 'xlsx' | 'docx' | 'pdf' | 'html'
    source_bytes = Column(LargeBinary, nullable=True)  # original template file
    source_name = Column(String, nullable=True)        # original filename for download
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
    field_count = Column(Integer, nullable=True)     # # fields extracted (for metrics)
    avg_confidence = Column(Integer, nullable=True)  # 0-100 mean confidence (for metrics)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Composite index for the dashboard's per-user/per-day aggregations.
    __table_args__ = (
        Index("ix_history_user_created", "user_id", "created_at"),
        Index("ix_history_created", "created_at"),
    )


# ---- Workflow Engine v1 (rules → approvals → audit) ----

class WorkflowRule(Base):
    """A per-user business rule evaluated after every extraction. v1 supports a
    single condition (field/operator/value) that, when it matches, routes the
    document to a human approval queue before it can be posted to the ERP.
    """
    __tablename__ = "workflow_rules"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    # Condition — v1 is a single clause: <field> <op> <value>.
    field = Column(String, nullable=False)          # 'total' | 'confidence' | 'document_type' | any extracted key
    op = Column(String, nullable=False)             # 'gt' | 'lt' | 'gte' | 'lte' | 'eq' | 'contains'
    value = Column(String, nullable=False)          # compared numerically when both sides parse as numbers
    action = Column(String, default="require_approval", nullable=False)  # v1: always require_approval
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_workflow_rules_user", "user_id", "active"),)


class Approval(Base):
    """A document held for human review because a WorkflowRule matched. Moves
    pending → approved | rejected. On approval it is marked ready for ERP posting.
    """
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    history_id = Column(Integer, ForeignKey("history.id"), nullable=False)
    rule_id = Column(Integer, ForeignKey("workflow_rules.id"), nullable=True)
    rule_name = Column(String, nullable=True)       # snapshot so deleting a rule keeps the audit readable
    document_type = Column(String, nullable=True)
    amount = Column(Numeric, nullable=True)         # extracted total, if any — for the queue display/sort
    status = Column(String, default="pending", nullable=False)  # 'pending' | 'approved' | 'rejected'
    decided_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    note = Column(Text, nullable=True)              # reviewer note on reject/approve
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_approvals_user_status", "user_id", "status"),)


class AuditLog(Base):
    """Append-only trail of workflow events for enterprise traceability."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    approval_id = Column(Integer, ForeignKey("approvals.id"), nullable=True)
    event = Column(String, nullable=False)          # 'rule_matched' | 'approved' | 'rejected' | 'erp_export'
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_audit_user_created", "user_id", "created_at"),)


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


class OpsEvent(Base):
    """One row per extraction attempt — success OR failure. The observability
    spine: powers real error-rate, latency percentiles, and request-volume
    metrics (GET /v1/observability). Never bill or block on writing this."""
    __tablename__ = "ops_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    kind = Column(String, nullable=True)         # 'auto' | 'schema' | 'auto_multi' | service slug
    status = Column(String, nullable=False)      # 'ok' | 'error'
    http_status = Column(Integer, nullable=True) # for errors (429/502/503/…)
    tier = Column(String, nullable=True)         # 'hard' | 'fast'
    error_type = Column(String, nullable=True)   # exception class name, if any
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class IdempotencyKey(Base):
    """A client-supplied Idempotency-Key mapped to the stored response, so a
    retried request replays the same result without re-running or re-charging."""
    __tablename__ = "idempotency_keys"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    response_json = Column(JsonCol)
    created_at = Column(DateTime, default=datetime.utcnow)


class CorrectionMemory(Base):
    """Aggregated reviewer corrections — the learning store. One row per
    (user, document_type, field): the value the user keeps correcting a field TO.
    Re-injected as prompt hints on future extractions so the model stops
    repeating the same mistake. correction → learning → higher confidence."""
    __tablename__ = "correction_memory"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(String, nullable=True, index=True)
    field_key = Column(String, nullable=False)
    # Vendor / party identity of the document the correction came from, normalized.
    # A learned correction is only re-applied to documents from the SAME source
    # (or globally when this is empty) — stops one vendor's fix bleeding onto another.
    scope_key = Column(String, nullable=True, index=True)
    original_value = Column(Text, nullable=True)     # what the model produced last time
    corrected_value = Column(Text, nullable=True)    # what the reviewer changed it to
    count = Column(Integer, nullable=False, default=1)  # times this fix was applied
    updated_at = Column(DateTime, default=datetime.utcnow)


class ExtractionVersion(Base):
    """Append-only version log for a document's extracted data. v1 = the initial
    extraction; each reviewer correction appends a version capturing field/from/to.
    Makes every extraction versioned, auditable, and reproducible by replay."""
    __tablename__ = "extraction_versions"

    id = Column(Integer, primary_key=True)
    history_id = Column(Integer, ForeignKey("history.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    version = Column(Integer, nullable=False)
    source = Column(String, nullable=False)   # 'extracted' | 'corrected'
    field = Column(String, nullable=True)      # which field changed (None for the initial extraction)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class DocumentEvent(Base):
    """Delivery-side lifecycle events for a document — the stages that aren't
    already timestamped in a source-of-truth table. `exported` (a plain download)
    and `erp` (an Odoo-ready xlsx_columns export) are stamped here; the earlier
    stages (uploaded / extracted / validated / reviewed / approved) are DERIVED at
    read time from History, ExtractionVersion, and Approval so there is no drift.
    Powers GET /v1/history/{hid}/timeline — the per-document audit timeline."""
    __tablename__ = "document_events"

    id = Column(Integer, primary_key=True)
    history_id = Column(Integer, ForeignKey("history.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    stage = Column(String, nullable=False)    # 'exported' | 'erp'
    detail = Column(String, nullable=True)    # e.g. the export format
    created_at = Column(DateTime, default=datetime.utcnow)
