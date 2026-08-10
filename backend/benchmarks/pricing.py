"""Versioned provider pricing — BENCHMARK-ONLY unit economics.

This is NOT customer billing and must never be mixed with Mostakhles credits. It
estimates the provider-side USD cost of a benchmark run so we can compare models on
a quality/cost frontier. Numbers are ASSUMPTIONS until verified against the current
provider price list; every estimate carries the pricing config version + effective
date so a stale estimate is never mistaken for fact.
"""
from __future__ import annotations

PRICING_VERSION = "gemini-assumed-2026-08"
EFFECTIVE_DATE = "2026-08-01"
VERIFIED = False  # flip only after confirming against the official price list

# USD per 1,000,000 tokens. UNVERIFIED placeholders — do not quote to customers.
_USD_PER_MTOK: dict[str, dict] = {
    # model_id: {"input": $/Mtok, "output": $/Mtok}
    "gemini-3.1-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-3.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-3.5-flash":      {"input": 0.30, "output": 2.50},
    "gemini-3.6-flash":      {"input": 0.30, "output": 2.50},
}


def cost_estimate(model_id: str, input_tokens: int, output_tokens: int) -> dict:
    """Return {usd, pricing_version, effective_date, verified}. usd is None if the
    model isn't in the (unverified) table — we never invent a number."""
    rates = _USD_PER_MTOK.get(model_id)
    usd = None
    if rates and input_tokens is not None and output_tokens is not None:
        usd = round((input_tokens / 1e6) * rates["input"]
                    + (output_tokens / 1e6) * rates["output"], 6)
    return {"usd": usd, "pricing_version": PRICING_VERSION,
            "effective_date": EFFECTIVE_DATE, "verified": VERIFIED,
            "model_id": model_id}
