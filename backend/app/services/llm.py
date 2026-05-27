"""Vendor-agnostic LLM layer.

The rest of the app talks to two functions only:
  - generate_from_document(file_bytes, media_type, prompt, hard) -> (text, truncated)
  - generate_text(system, user, hard, max_tokens, history)       -> text

Which provider runs them is chosen by config, so swapping Gemini <-> Claude (or
adding another) is a settings change, never a code change:

  LLM_PROVIDER = "gemini" | "anthropic"   (if unset: auto — Gemini when GEMINI_API_KEY is present)
  GEMINI_API_KEY / ANTHROPIC_API_KEY
  GEMINI_MODEL_EASY / GEMINI_MODEL_HARD / ANTHROPIC_MODEL_EASY / ANTHROPIC_MODEL_HARD
"""
import base64
import os

ANTHROPIC_EASY = os.getenv("ANTHROPIC_MODEL_EASY", "claude-haiku-4-5-20251001")
ANTHROPIC_HARD = os.getenv("ANTHROPIC_MODEL_HARD", "claude-sonnet-4-6")
GEMINI_EASY = os.getenv("GEMINI_MODEL_EASY", "gemini-2.5-flash-lite")
GEMINI_HARD = os.getenv("GEMINI_MODEL_HARD", "gemini-2.5-flash")

_anthropic = None
_gemini = None


def provider() -> str:
    p = os.getenv("LLM_PROVIDER")
    if p:
        return p.lower()
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    return "anthropic"


def active_models() -> dict:
    """For the bake-off / debugging: which models are live right now."""
    pv = provider()
    return {"provider": pv,
            "easy": GEMINI_EASY if pv == "gemini" else ANTHROPIC_EASY,
            "hard": GEMINI_HARD if pv == "gemini" else ANTHROPIC_HARD}


# ---------------------------------------------------------------- Anthropic
def _anthropic_client():
    global _anthropic
    if _anthropic is None:
        from anthropic import Anthropic
        _anthropic = Anthropic()  # reads ANTHROPIC_API_KEY
    return _anthropic


def _anthropic_doc(file_bytes, media_type, prompt, hard):
    b64 = base64.standard_b64encode(file_bytes).decode()
    if media_type == "application/pdf":
        block = {"type": "document",
                 "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    else:
        block = {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": b64}}
    params = {
        "model": ANTHROPIC_HARD if hard else ANTHROPIC_EASY,
        "max_tokens": 16000 if hard else 8192,
        "messages": [{"role": "user", "content": [block, {"type": "text", "text": prompt}]}],
    }
    if hard:
        params["thinking"] = {"type": "enabled", "budget_tokens": 2048}
    msg = _anthropic_client().messages.create(**params)
    text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")
    return text, getattr(msg, "stop_reason", None) == "max_tokens"


def _anthropic_text(system, user, hard, max_tokens, history):
    messages = []
    for turn in (history or [])[-8:]:
        role = turn.get("role")
        if role in ("user", "assistant") and turn.get("content"):
            messages.append({"role": role, "content": str(turn["content"])})
    messages.append({"role": "user", "content": user})
    msg = _anthropic_client().messages.create(
        model=ANTHROPIC_HARD if hard else ANTHROPIC_EASY,
        max_tokens=max_tokens, system=system, messages=messages)
    return next((b.text for b in msg.content if getattr(b, "type", None) == "text"), "")


# ---------------------------------------------------------------- Gemini
def _gemini_client():
    global _gemini
    if _gemini is None:
        from google import genai
        _gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    return _gemini


def _gemini_doc(file_bytes, media_type, prompt, hard):
    from google.genai import types
    model = GEMINI_HARD if hard else GEMINI_EASY
    part = types.Part.from_bytes(data=file_bytes, mime_type=media_type)
    config = types.GenerateContentConfig(max_output_tokens=16000 if hard else 8192)
    resp = _gemini_client().models.generate_content(model=model, contents=[part, prompt], config=config)
    text = resp.text or ""
    truncated = False
    try:
        fr = resp.candidates[0].finish_reason
        truncated = str(getattr(fr, "name", fr)).upper().endswith("MAX_TOKENS")
    except Exception:  # noqa: BLE001
        pass
    return text, truncated


def _gemini_text(system, user, hard, max_tokens, history):
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
    resp = _gemini_client().models.generate_content(model=model, contents=contents, config=config)
    return resp.text or ""


# ---------------------------------------------------------------- dispatch
def generate_from_document(file_bytes, media_type, prompt, hard):
    """Multimodal call (image/PDF + prompt). Returns (text, truncated)."""
    if provider() == "gemini":
        return _gemini_doc(file_bytes, media_type, prompt, hard)
    return _anthropic_doc(file_bytes, media_type, prompt, hard)


def generate_text(system, user, hard=True, max_tokens=1024, history=None):
    """Text-only call. Returns text."""
    if provider() == "gemini":
        return _gemini_text(system, user, hard, max_tokens, history)
    return _anthropic_text(system, user, hard, max_tokens, history)
