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
"""
import os

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

GEMINI_EASY = os.getenv("GEMINI_MODEL_EASY", "gemini-3.1-flash-lite")
GEMINI_HARD = os.getenv("GEMINI_MODEL_HARD", "gemini-3.5-flash")

_client = None


class GeminiDailyQuotaExhausted(Exception):
    """Daily free-tier quota is gone — retrying won't help; surface a clean message."""


def _is_daily_quota(err: Exception) -> bool:
    s = str(err)
    return "PerDay" in s or "free_tier_requests" in s or "GenerateRequestsPerDay" in s


def _is_transient(err: Exception) -> bool:
    s = str(err)
    if _is_daily_quota(err):
        return False
    return any(tok in s for tok in ("RESOURCE_EXHAUSTED", "429", "503", "UNAVAILABLE", "DEADLINE_EXCEEDED"))


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def active_models() -> dict:
    return {"provider": "gemini", "easy": GEMINI_EASY, "hard": GEMINI_HARD}


def _client_():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return _client


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception(_is_transient),
    reraise=True,
)
def _generate(**kwargs):
    """Single Gemini call with smart retry on transient errors only."""
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
    """Multimodal call (image/PDF + prompt). Returns (text, truncated)."""
    from google.genai import types
    model = GEMINI_HARD if hard else GEMINI_EASY
    part = types.Part.from_bytes(data=file_bytes, mime_type=media_type)
    config = types.GenerateContentConfig(max_output_tokens=16000 if hard else 8192)
    resp = _generate(model=model, contents=[part, prompt], config=config)
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
    model = GEMINI_HARD if hard else GEMINI_EASY
    contents = []
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        if role in ("user", "assistant") and turn.get("content"):
            contents.append(types.Content(
                role="model" if role == "assistant" else "user",
                parts=[types.Part.from_text(text=str(turn["content"]))]))
    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user)]))
    config = types.GenerateContentConfig(max_output_tokens=max_tokens, system_instruction=system)
    resp = _generate(model=model, contents=contents, config=config)
    return resp.text or ""
