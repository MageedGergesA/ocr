"""LLM layer — Gemini (single key, paid tier).

The rest of the app talks to two functions only:
  - generate_from_document(file_bytes, media_type, prompt, hard) -> (text, truncated)
  - generate_text(system, user, hard, max_tokens, history)       -> text

One API key for everyone (free + paid Mostakhles users). The free Gemini tier is too
restricted (e.g. 20 requests/day on gemini-3.5-flash) to support a SaaS at any scale,
so we run on Google's paid tier — same models, billing enabled, full data privacy.

Config (.env):
  GEMINI_API_KEY                          (required)
  GEMINI_MODEL_EASY / GEMINI_MODEL_HARD   (defaults below)
  GEMINI_TIMEOUT_MS                       (per-call, default 60_000)
  MAX_DAILY_GEMINI_USD                    (global circuit breaker, default 50.0)
"""
import logging
import os
import threading
from datetime import datetime, timedelta

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

log = logging.getLogger("mostakhles.llm")

GEMINI_EASY = os.getenv("GEMINI_MODEL_EASY", "gemini-3.1-flash-lite")
GEMINI_HARD = os.getenv("GEMINI_MODEL_HARD", "gemini-3.5-flash")
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "60000"))
MAX_DAILY_GEMINI_USD = float(os.getenv("MAX_DAILY_GEMINI_USD", "50.0"))

# Estimated cost per credit (weighted average). Used by the spend ceiling.
# Hard call ≈ $0.015, fast call ≈ $0.0025; 8:1 credit weight gives ~$0.0019/credit avg.
EST_COST_PER_CREDIT_USD = float(os.getenv("EST_COST_PER_CREDIT_USD", "0.0019"))

_client = None
_spend_lock = threading.Lock()
_daily_spend = {"date": None, "usd": 0.0}


class GeminiDailyQuotaExhausted(Exception):
    """Daily Gemini quota is gone — retrying won't help; surface a clean message."""


class GeminiBudgetExhausted(Exception):
    """Our internal MAX_DAILY_GEMINI_USD ceiling is hit; refuse non-essential calls."""


def _today_key() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def record_spend(credits: int) -> None:
    """Add this call's estimated cost to today's running total. Thread-safe."""
    with _spend_lock:
        if _daily_spend["date"] != _today_key():
            _daily_spend["date"] = _today_key()
            _daily_spend["usd"] = 0.0
        _daily_spend["usd"] += credits * EST_COST_PER_CREDIT_USD


def daily_spend_usd() -> float:
    with _spend_lock:
        if _daily_spend["date"] != _today_key():
            return 0.0
        return _daily_spend["usd"]


def enforce_daily_budget(credits_for_this_call: int) -> None:
    """Refuse the call if it would push today's estimated spend over MAX_DAILY_GEMINI_USD.
    This is a circuit breaker against runaway loops / abusive users — NOT a hard
    accounting figure. Google Cloud billing alerts are the backstop."""
    projected = daily_spend_usd() + credits_for_this_call * EST_COST_PER_CREDIT_USD
    if projected > MAX_DAILY_GEMINI_USD:
        raise GeminiBudgetExhausted(
            "خدمة الذكاء الاصطناعي مشغولة مؤقتاً — تجاوزنا حد التشغيل اليومي. "
            "حاول بعد قليل أو راسل الدعم."
        )


def _is_daily_quota(err: Exception) -> bool:
    """Detect Gemini's RESOURCE_EXHAUSTED / quota-exceeded errors. Structured check first
    (via google.genai.errors), substring fallback for SDK versions we don't recognise."""
    try:
        from google.genai import errors as genai_errors  # type: ignore
        if isinstance(err, getattr(genai_errors, "APIError", ())) and getattr(err, "code", None) == 429:
            details = getattr(err, "details", None) or []
            for d in details:
                reason = (d.get("reason") or "").upper() if isinstance(d, dict) else ""
                metric = (d.get("quotaMetric") or d.get("quota_metric") or "") if isinstance(d, dict) else ""
                if reason == "RATE_LIMIT_EXCEEDED" or "PerDay" in metric or "free_tier" in metric:
                    return True
    except Exception:  # noqa: BLE001
        pass
    s = str(err)
    return "PerDay" in s or "free_tier_requests" in s or "GenerateRequestsPerDay" in s


def _is_transient(err: Exception) -> bool:
    s = str(err)
    if _is_daily_quota(err):
        return False
    # Include common timeout/network exception names so they retry.
    if any(name in type(err).__name__ for name in ("Timeout", "ConnectError", "ReadTimeout")):
        return True
    return any(tok in s for tok in ("RESOURCE_EXHAUSTED", "429", "503", "UNAVAILABLE", "DEADLINE_EXCEEDED"))


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def active_models() -> dict:
    return {"provider": "gemini", "easy": GEMINI_EASY, "hard": GEMINI_HARD,
            "daily_spend_usd": round(daily_spend_usd(), 4),
            "daily_budget_usd": MAX_DAILY_GEMINI_USD}


def _client_():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types as _types
        http_opts = None
        try:
            http_opts = _types.HttpOptions(timeout=GEMINI_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 — older SDKs may not have HttpOptions
            http_opts = None
        kwargs = {"api_key": os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")}
        if http_opts is not None:
            kwargs["http_options"] = http_opts
        _client = genai.Client(**kwargs)
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)
def _generate(_credits: int = 0, **kwargs):
    """Single Gemini call with smart retry on transient errors only.

    `_credits` is the per-attempt cost in our internal credit unit (1 or 8).
    We record spend BEFORE the call so retries are correctly counted toward the
    daily budget — otherwise tenacity-retries that succeed on attempt 3 would
    cost us 3x while we recorded 1x.
    """
    if _credits:
        record_spend(_credits)
    try:
        return _client_().models.generate_content(**kwargs)
    except Exception as e:
        if _is_daily_quota(e):
            raise GeminiDailyQuotaExhausted(
                "انتهت الحصة اليومية المجانية للنموذج. فعِّل الفوترة على مفتاح Gemini "
                "(Google AI Studio → Billing) لإزالة الحدّ، أو انتظر حتى تجديد الحصة غدًا."
            ) from e
        raise


def generate_from_document(file_bytes, media_type, prompt, hard):
    """Multimodal call (single image/PDF + prompt). Returns (text, truncated).
    Thin wrapper around generate_from_documents for back-compat."""
    return generate_from_documents([(file_bytes, media_type)], prompt, hard)


def generate_from_documents(files: list, prompt: str, hard: bool):
    """Multimodal call with one OR MANY images / PDFs in a single Gemini request.

    `files` is a list of (bytes, media_type) tuples. Gemini can cross-reference
    across them — useful for ID front+back of the same person, multi-page
    receipts, or a customer file with several supporting docs.

    Cost: charged per image (Gemini bills per tile internally). 2 images on
    hard = 16 credits; 4 = 32. Caller is responsible for enforcing quota before
    the call.

    Returns (text, truncated). If max_output_tokens is hit, caller should
    consider splitting into per-image calls.
    """
    from google.genai import types
    n = max(1, len(files))
    credits = (8 if hard else 1) * n
    enforce_daily_budget(credits)
    model = GEMINI_HARD if hard else GEMINI_EASY
    parts = [types.Part.from_bytes(data=b, mime_type=mt) for b, mt in files]
    # Scale output tokens with image count so a 4-image extract doesn't truncate.
    base = 16000 if hard else 8192
    max_tokens = min(base * max(1, n // 2), 32000)
    # Only send generation params the target model accepts. For the CURRENT
    # production models this is a no-op (they keep temperature/top_p/seed); for
    # newer models that deprecate sampling knobs the registry strips them so the
    # request stays valid. See app/ai/registry.effective_generation_config.
    from app.ai import registry as _registry
    _eff = _registry.effective_generation_config(
        model, {"max_output_tokens": max_tokens, "temperature": 0.0,
                "top_p": 1.0, "seed": 42})
    config = types.GenerateContentConfig(**_eff)
    try:
        resp = _generate(_credits=credits, model=model, contents=parts + [prompt], config=config)
    except Exception as exc:
        # Hard-tier model overloaded? Fall back to easy tier so the user gets
        # SOMETHING instead of a blank error. Lower accuracy on handwriting but
        # ≫ a hard failure. Only fires for transient errors AFTER tenacity's
        # 3 retries exhausted; non-transient errors (auth, daily quota) bubble.
        s = str(exc)
        is_overload = any(tok in s for tok in ("503", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
        if hard and is_overload and model != GEMINI_EASY:
            log.warning("hard-tier %s exhausted retries with %s — falling back to easy-tier %s",
                        model, type(exc).__name__, GEMINI_EASY)
            # Charge easy-tier cost (we already recorded hard-tier spend); the
            # difference is small and the user gets a result. Worth it.
            resp = _generate(_credits=0, model=GEMINI_EASY, contents=parts + [prompt], config=config)
        else:
            raise
    text = resp.text or ""
    truncated = False
    try:
        fr = resp.candidates[0].finish_reason
        truncated = str(getattr(fr, "name", fr)).upper().endswith("MAX_TOKENS")
    except Exception:  # noqa: BLE001
        pass
    return text, truncated


def generate_text(system, user, hard=True, max_tokens=1024, history=None):
    """Text-only call. Returns text."""
    from google.genai import types
    credits = 8 if hard else 1
    enforce_daily_budget(credits)
    model = GEMINI_HARD if hard else GEMINI_EASY
    contents = []
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        if role in ("user", "assistant") and turn.get("content"):
            contents.append(types.Content(
                role="model" if role == "assistant" else "user",
                parts=[types.Part.from_text(text=str(turn["content"]))]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user)]))
    from app.ai import registry as _registry
    _eff = _registry.effective_generation_config(
        model, {"max_output_tokens": max_tokens, "temperature": 0.0,
                "top_p": 1.0, "seed": 42})
    config = types.GenerateContentConfig(system_instruction=system, **_eff)
    resp = _generate(_credits=credits, model=model, contents=contents, config=config)
    return resp.text or ""
