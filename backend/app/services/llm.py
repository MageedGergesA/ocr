"""LLM layer — Gemini.

The rest of the app talks to two functions only:
  - generate_from_document(file_bytes, media_type, prompt, hard) -> (text, truncated)
  - generate_text(system, user, hard, max_tokens, history)       -> text

Config:
  GEMINI_API_KEY              (required)
  GEMINI_MODEL_EASY / GEMINI_MODEL_HARD   (defaults below)

Kept as a thin seam so a different provider could be slotted in later without
touching the rest of the app — but only Gemini is wired today.
"""
import os

GEMINI_EASY = os.getenv("GEMINI_MODEL_EASY", "gemini-2.5-flash-lite")
GEMINI_HARD = os.getenv("GEMINI_MODEL_HARD", "gemini-2.5-flash")

_client = None


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


def generate_from_document(file_bytes, media_type, prompt, hard):
    """Multimodal call (image/PDF + prompt). Returns (text, truncated)."""
    from google.genai import types
    model = GEMINI_HARD if hard else GEMINI_EASY
    part = types.Part.from_bytes(data=file_bytes, mime_type=media_type)
    config = types.GenerateContentConfig(max_output_tokens=16000 if hard else 8192)
    resp = _client_().models.generate_content(model=model, contents=[part, prompt], config=config)
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
    resp = _client_().models.generate_content(model=model, contents=contents, config=config)
    return resp.text or ""
