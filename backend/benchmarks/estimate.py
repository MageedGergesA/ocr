"""Pre-run cost/volume estimate for a benchmark plan (Section 4).

This produces an ORDER-OF-MAGNITUDE estimate BEFORE any request is sent, so a live
run never surprises us with its bill. It multiplies documented per-page token
assumptions by the plan size and prices them with benchmarks.pricing (which is
itself UNVERIFIED). Every number carries its assumptions; nothing here is a
measured fact. After a real run the actual provider usage metadata replaces these.
"""
from __future__ import annotations

from benchmarks import pricing

# Documented assumptions (NOT measurements). A page image sent to Gemini is billed
# as a fixed block of vision tokens plus the prompt; output is the JSON we ask for.
# These are deliberately generous so the estimate errs high.
ASSUMED_INPUT_TOKENS_PER_PAGE = 1600      # vision tiles + prompt, per page
ASSUMED_OUTPUT_TOKENS_PER_DOC = 400       # structured JSON reply
ASSUMPTIONS_NOTE = (
    f"assumes ~{ASSUMED_INPUT_TOKENS_PER_PAGE} input tok/page + "
    f"~{ASSUMED_OUTPUT_TOKENS_PER_DOC} output tok/doc; UNVERIFIED — replaced by "
    "real provider usage after a live run")


def estimate_plan(*, n_cases: int, total_pages: int, repeats: int,
                  model_ids: list) -> dict:
    """Estimate requests + approximate USD for running `model_ids` over a plan.

    requests = n_cases * repeats (one request per document per repeat).
    Cost is per-model; total sums the models that have (unverified) pricing.
    """
    repeats = max(1, repeats)
    requests_per_model = n_cases * repeats
    pages_per_model = total_pages * repeats
    in_tok = pages_per_model * ASSUMED_INPUT_TOKENS_PER_PAGE
    out_tok = requests_per_model * ASSUMED_OUTPUT_TOKENS_PER_DOC

    per_model = []
    total_usd = 0.0
    any_priced = False
    for mid in model_ids:
        ce = pricing.cost_estimate(mid, in_tok, out_tok)
        per_model.append({
            "model_id": mid,
            "requests": requests_per_model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "usd": ce["usd"],
            "priced": ce["usd"] is not None,
        })
        if ce["usd"] is not None:
            total_usd += ce["usd"]
            any_priced = True

    return {
        "requests_total": requests_per_model * len(model_ids),
        "requests_per_model": requests_per_model,
        "pages_per_model": pages_per_model,
        "repeats": repeats,
        "n_models": len(model_ids),
        "per_model": per_model,
        "estimated_usd_total": round(total_usd, 4) if any_priced else None,
        "pricing_version": pricing.PRICING_VERSION,
        "pricing_verified": pricing.VERIFIED,
        "assumptions": ASSUMPTIONS_NOTE,
    }
