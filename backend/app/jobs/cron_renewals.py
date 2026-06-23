"""Daily billing-housekeeping cron.

Run with:
    python -m app.jobs.cron_renewals

Or via a systemd timer / crontab:
    # /etc/cron.d/mostakhles-renewals
    15 6 * * *  www-data  cd /srv/mostakhles/backend && \\
        ../venv/bin/python -m app.jobs.cron_renewals >> /var/log/mostakhles/cron.log 2>&1

What it does (in one DB session, in this order):

  1. Find ACTIVE subscriptions with current_period_end ∈ (now, now+REMINDER_DAYS]
     and send a renewal reminder email — once per period (idempotent via
     PaymentEvent log).

  2. Find CANCELLED subscriptions whose current_period_end has passed and
     whose user.plan is still on the paid tier — downgrade to free.

The cron is **idempotent**: re-running on the same day is a no-op (no double
emails, no double downgrades). Safe to run hourly if needed.

Exit codes:
  0  success (reminders sent and/or downgrades applied)
  1  DB or transport error (cron should alert)
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta

from app import db, emailer, models
from app.config import settings
from app.services import plans

log = logging.getLogger("mostakhles.cron.renewals")

# Send the reminder when the period ends within N days.
REMINDER_DAYS = int(os.getenv("RENEWAL_REMINDER_DAYS", "7"))

# PaymentEvent.external_id format for reminder idempotency. One per period,
# so re-running the cron on day-6 / day-5 / day-4 doesn't spam the user.
_REMINDER_EVENT_TYPE = "renewal.reminder.sent"


def _reminder_external_id(sub_id: int, period_end: datetime) -> str:
    """Stable key: (subscription, period). One reminder per period max."""
    return f"reminder-{sub_id}-{period_end.date().isoformat()}"


def _public_url() -> str:
    return os.getenv("PUBLIC_URL", "").rstrip("/") or "https://mostakhles.ai"


def send_due_reminders(session) -> int:
    """Step 1: send renewal reminders for subs nearing period end."""
    now = datetime.utcnow()
    window_end = now + timedelta(days=REMINDER_DAYS)

    candidates = (session.query(models.Subscription)
                  .filter(models.Subscription.status == "active",
                          models.Subscription.current_period_end != None,  # noqa: E711
                          models.Subscription.current_period_end > now,
                          models.Subscription.current_period_end <= window_end)
                  .all())

    sent = 0
    for sub in candidates:
        period_end = sub.current_period_end
        if not period_end:
            continue
        # Idempotency: skip if we've already sent a reminder for this period.
        ext = _reminder_external_id(sub.id, period_end)
        already = (session.query(models.PaymentEvent)
                   .filter_by(provider=sub.provider, external_id=ext).first())
        if already:
            continue

        user = session.query(models.User).filter_by(id=sub.user_id).first()
        if not user or not user.email:
            log.warning("cron: sub=%s has no user/email; skipping reminder", sub.id)
            continue

        plan_cfg = plans.get_plan(sub.plan)
        amount = float(sub.amount_usd) if sub.amount_usd is not None else \
            float(plan_cfg.usd) if plan_cfg else 0.0
        days_remaining = max(1, (period_end - now).days)

        try:
            emailer.send_renewal_reminder_email(
                to=user.email,
                plan=sub.plan,
                renews_on=period_end.date().isoformat(),
                amount_usd=amount,
                days_remaining=days_remaining,
                provider=sub.provider,
                manage_url=f"{_public_url()}/account?focus=subscription",
            )
        except Exception:
            log.exception("cron: reminder email failed for user=%s sub=%s",
                          user.id, sub.id)
            continue

        # Write the idempotency marker AFTER the email actually went out.
        evt = models.PaymentEvent(
            provider=sub.provider,
            external_id=ext,
            event_type=_REMINDER_EVENT_TYPE,
            subscription_id=sub.id,
            user_id=user.id,
            amount_usd=sub.amount_usd,
            raw_payload=f'{{"period_end": "{period_end.isoformat()}", '
                        f'"days_remaining": {days_remaining}}}',
            processed_at=datetime.utcnow(),
        )
        session.add(evt)
        session.commit()
        sent += 1
        log.info("cron: reminder sent user=%s sub=%s plan=%s renews_on=%s",
                 user.id, sub.id, sub.plan, period_end.date())
    return sent


def expire_cancelled(session) -> int:
    """Step 2: downgrade users whose cancelled sub has reached period end.
    They get to use the paid tier until the end of the billing cycle, then we
    flip user.plan back to free."""
    now = datetime.utcnow()
    expired = (session.query(models.Subscription)
               .filter(models.Subscription.status == "cancelled",
                       models.Subscription.current_period_end != None,  # noqa: E711
                       models.Subscription.current_period_end < now)
               .all())

    downgraded = 0
    for sub in expired:
        user = session.query(models.User).filter_by(id=sub.user_id).first()
        if not user:
            continue
        if user.plan == "free":
            continue  # already downgraded — nothing to do
        # Only downgrade if THIS sub matches the user's current plan. If they
        # cancelled and re-subscribed on a different tier, leave them alone.
        if user.plan != sub.plan:
            continue
        log.info("cron: downgrade user=%s from %s -> free (sub=%s period_end=%s)",
                 user.id, user.plan, sub.id, sub.current_period_end)
        user.plan = "free"
        sub.updated_at = now
        downgraded += 1

    if downgraded:
        session.commit()
    return downgraded


def main() -> int:
    logging.basicConfig(
        level=os.getenv("CRON_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log.info("cron start: db=%s", settings.DATABASE_URL.split("@")[-1])

    session = db.SessionLocal()
    try:
        reminders = send_due_reminders(session)
        downgrades = expire_cancelled(session)
        log.info("cron done: reminders=%s downgrades=%s", reminders, downgrades)
        return 0
    except Exception:
        session.rollback()
        log.exception("cron failed")
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
