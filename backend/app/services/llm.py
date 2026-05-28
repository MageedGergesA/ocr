"""LLM layer — Gemini.

The rest of the app talks to two functions only:
  - generate_from_document(file_bytes, media_type, prompt, hard, paid) -> (text, truncated)
  - generate_text(system, user, hard, max_tokens, history, paid)        -> text

Two-tier privacy routing:
  paid=False (default) -> GEMINI_API_KEY  (free Mostakhles plan; Google's free tier; data MAY be reviewed)
  paid=True            -> GEMINI_API_KEY_PAID  (paid plan; Google's paid tier; full privacy, no training)

If GEMINI_API_KEY_PAID is not set, paid users transparently fall back to GEMINI_API_KEY so nothing
breaks during pre-launch — but the privacy promise to paid users only becomes truthful once you
enable billing on a separate key and set GEMINI_API_KEY_PAID.

Config:
  GEMINI_API_KEY                          (required — free tier, default routing)
  GEMINI_API_KEY_PAID                     (optional — paid tier, billing enabled)
  GEMINI_MODEL_EASY / GEMINI_MODEL_HARD   (defaults below)
"""
import os

GEMINI_EASY = os.getenv("GEMINI_MODEL_EASY", "gemini-3.1-flash-lite")
GEMINI_HARD = os.getenv("GEMINI_MODEL_HARD", "gemini-3.5-flash")

_clients: dict = {}  # cache: api_key -> genai.Client


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


def has_paid_tier() -> bool:
    return bool(os.getenv("GEMINI_API_KEY_PAID"))


def active_models() -> dict:
    return {"provider": "gemini", "easy": GEMINI_EASY, "hard": GEMINI_HARD,
            "paid_tier_configured": has_paid_tier()}


def _client_(paid: bool = False):
    """Pick the Gemini client by privacy tier. Paid falls back to free if no paid key is set."""
    if paid:
        key = os.getenv("GEMINI_API_KEY_PAID") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    else:
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("Gemini API key not configured")
    if key not in _clients:
        from google import genai
        _clients[key] = genai.Client(api_key=key)
    return _clients[key]


def generate_from_document(file_bytes, media_type, prompt, hard, paid: bool = False):
    """Multimodal call (image/PDF + prompt). Returns (text, truncated)."""
    from google.genai import types
    model = GEMINI_HARD if hard else GEMINI_EASY
    part = types.Part.from_bytes(data=file_bytes, mime_type=media_type)
    config = types.GenerateContentConfig(max_output_tokens=16000 if hard else 8192)
    resp = _client_(paid).models.generate_content(model=model, contents=[part, prompt], config=config)
    text = resp.text or ""
    truncated = False
    try:
        fr = resp.candidates[0].finish_reason
        truncated = str(getattr(fr, "name", fr)).upper().endswith("MAX_TOKENS")
    except Exception:  # noqa: BLE001
        pass
    return text, truncated


def generate_text(system, user, hard=True, max_tokens=1024, history=None, paid: bool = False):
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
    resp = _client_(paid).models.generate_content(model=model, contents=contents, config=config)
    return resp.text or ""
