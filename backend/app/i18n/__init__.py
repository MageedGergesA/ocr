"""i18n: tiny translation layer.

Two languages out of the box: ar (Arabic, default) and en (English). Add a third
by dropping `<code>.json` into this folder and registering it in SUPPORTED_LANGS.

Resolution order (from highest priority to lowest):
  1. ?lang= query parameter (used by the /set-language endpoint to redirect cleanly)
  2. 'lang' cookie (anonymous + opted-in users)
  3. User.preferred_lang (logged-in users only)
  4. Accept-Language header (browser auto-detect on first visit)
  5. Fallback 'ar'

Use:
    from app import i18n
    i18n.t("nav.dashboard", "ar")            -> "لوحة التحكم"
    i18n.t("billing.upgrade_cta", "en", plan="Pro")  -> "Upgrade to Pro"
    i18n.resolve_lang(request, user) -> "ar" | "en"
    i18n.is_rtl("ar") -> True
"""
import json
import logging
from pathlib import Path

from fastapi import Request

log = logging.getLogger("mostakhles")

SUPPORTED_LANGS = ("ar", "en")
DEFAULT_LANG = "ar"
RTL_LANGS = frozenset({"ar", "he", "fa", "ur"})

_BASE = Path(__file__).resolve().parent
_TRANSLATIONS: dict[str, dict] = {}


def _load() -> None:
    """Read all <lang>.json files into the in-memory cache. Idempotent."""
    if _TRANSLATIONS:
        return
    for lang in SUPPORTED_LANGS:
        path = _BASE / f"{lang}.json"
        if path.exists():
            try:
                _TRANSLATIONS[lang] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                log.warning("i18n: failed to load %s: %s", path, e)
                _TRANSLATIONS[lang] = {}
        else:
            _TRANSLATIONS[lang] = {}


def _lookup(d: dict, key_path: str) -> str | None:
    """Walk a dotted key path through a nested dict. 'nav.dashboard' -> d['nav']['dashboard']."""
    cur: object = d
    for part in key_path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur if isinstance(cur, str) else None


def t(key: str, lang: str = DEFAULT_LANG, **fmt) -> str:
    """Translate a dotted key. Falls back to the default lang, then the key itself.
    Supports `{name}` placeholders via str.format."""
    _load()
    val = _lookup(_TRANSLATIONS.get(lang, {}), key)
    if val is None and lang != DEFAULT_LANG:
        val = _lookup(_TRANSLATIONS.get(DEFAULT_LANG, {}), key)
    if val is None:
        return key  # last resort — visible in dev, signals a missing translation
    try:
        return val.format(**fmt) if fmt else val
    except Exception:  # noqa: BLE001 — bad placeholders shouldn't blow up the response
        return val


def is_rtl(lang: str) -> bool:
    return lang in RTL_LANGS


def detect_browser_lang(accept_language: str | None) -> str:
    """Parse Accept-Language and pick the highest-priority supported lang.
    Returns DEFAULT_LANG if no match. Tolerant of malformed headers."""
    if not accept_language:
        return DEFAULT_LANG
    candidates: list[tuple[float, str]] = []
    for part in accept_language.split(","):
        part = part.strip()
        if not part:
            continue
        if ";" in part:
            tag, q = part.split(";", 1)
            try:
                q_val = float(q.strip().lstrip("q=") or "1")
            except ValueError:
                q_val = 1.0
        else:
            tag, q_val = part, 1.0
        # 'ar-EG' -> 'ar', 'en-US' -> 'en'
        primary = tag.strip().split("-")[0].lower()
        if primary in SUPPORTED_LANGS:
            candidates.append((q_val, primary))
    if not candidates:
        return DEFAULT_LANG
    candidates.sort(reverse=True)  # highest q first
    return candidates[0][1]


def resolve_lang(request: Request, user=None) -> str:
    """Pick the language for this request. Order: query → cookie → user pref → browser → default."""
    q = (request.query_params.get("lang") or "").strip().lower()
    if q in SUPPORTED_LANGS:
        return q
    cookie = (request.cookies.get("lang") or "").strip().lower()
    if cookie in SUPPORTED_LANGS:
        return cookie
    if user is not None:
        pref = getattr(user, "preferred_lang", None)
        if pref and pref in SUPPORTED_LANGS:
            return pref
    return detect_browser_lang(request.headers.get("accept-language"))
