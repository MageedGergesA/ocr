"""Single source of truth for paid plans: slug, display name, USD price, credits.

`auth.PLAN_LIMITS` is the runtime credit cap (keyed by slug). This module owns the
billing-facing metadata (price, label, included credits) so the pricing page,
checkout, dashboard and renewal emails all read from one place.

The `free` plan is intentionally absent — it's the default and isn't sold.
"""
from dataclasses import dataclass

from app.config import settings


@dataclass(frozen=True)
class Plan:
    slug: str
    name: str
    name_ar: str
    usd: int       # monthly price in USD (whole dollars; pricing page shows $9/$29/etc.)
    credits: int   # monthly credit allowance (must match auth.PLAN_LIMITS)


PAID_PLANS: dict[str, Plan] = {
    "lite":     Plan("lite",     "Lite",     "Lite",      9,  1200),
    "starter":  Plan("starter",  "Starter",  "Starter",  29,  3500),
    "pro":      Plan("pro",      "Pro",      "Pro",      59,  8500),
    "business": Plan("business", "Business", "Business", 199, 28000),
}


def get_plan(slug: str) -> Plan | None:
    """Return the plan record or None for unknown / free / demo slugs."""
    return PAID_PLANS.get(slug)


def is_paid(slug: str) -> bool:
    return slug in PAID_PLANS


# ----------------------------------------------------------------------------
# Provider-specific lookups — keep external IDs out of the Plan dataclass so
# adding a new provider doesn't churn the registry.
# ----------------------------------------------------------------------------

def paypal_plan_id(slug: str) -> str | None:
    """Return the PayPal Plans-API plan_id (P-xxx) for `slug`, or None if the
    tier isn't yet offered via PayPal. Reads from settings each call so a
    config reload picks it up without restarting the import graph."""
    return {
        "lite":     settings.PAYPAL_PLAN_ID_LITE,
        "starter":  settings.PAYPAL_PLAN_ID_STARTER,
        "pro":      settings.PAYPAL_PLAN_ID_PRO,
        "business": settings.PAYPAL_PLAN_ID_BUSINESS,
    }.get(slug) or None
