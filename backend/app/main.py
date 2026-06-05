"""Mostakhles API — Arabic-first document extraction.

One backend, thin clients (Odoo module, web app, public API).
This file wires routes only; real work lives in services/.
"""
import json
import logging
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

load_dotenv()

# Structured logging: timestamps + level + module + message; one line per event.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("mostakhles")

# Sentry — only initialised when SENTRY_DSN is set; harmless in local dev otherwise.
if os.getenv("SENTRY_DSN"):
    import sentry_sdk

    # Scrub any field containing extracted-document data OR auth credentials
    # from event payloads so we don't accidentally exfiltrate user content
    # or API keys via crash reports.
    _SENSITIVE_KEYS = {
        # extracted document content
        "result_json", "result", "data", "fields", "pages", "text", "payload",
        "raw_payload", "schema_json", "image_bytes", "file_bytes", "page_bytes",
        # auth secrets — must NOT reach Sentry
        "authorization", "cookie", "x-api-key", "x_api_key", "api_key",
        "password", "password_hash", "csrf_token", "webhook_secret",
        "verification_token", "password_reset_token",
        "sid", "session_token", "set-cookie",
        # provider secrets
        "gemini_api_key", "paypal_secret", "paymob_api_key", "paymob_hmac",
        "smtp_password", "cf_turnstile_secret", "sentry_dsn",
    }

    def _scrub_event(event, _hint):
        def scrub(obj):
            if isinstance(obj, dict):
                return {k: ("<scrubbed>" if k.lower() in _SENSITIVE_KEYS else scrub(v))
                        for k, v in obj.items()}
            if isinstance(obj, list):
                return [scrub(x) for x in obj]
            return obj
        try:
            if event.get("extra"):
                event["extra"] = scrub(event["extra"])
            if event.get("contexts"):
                event["contexts"] = scrub(event["contexts"])
            req = event.get("request") or {}
            if req.get("data"):
                req["data"] = scrub(req["data"])
            if req.get("headers"):
                req["headers"] = scrub(req["headers"])
            if req.get("cookies"):
                req["cookies"] = {k: "<scrubbed>" for k in req["cookies"]}
            if req.get("query_string") and isinstance(req["query_string"], str):
                # Don't try to parse — query strings rarely carry secrets, but if
                # they do (e.g., a reset token), strip the whole thing rather than risk.
                if any(s in req["query_string"].lower()
                       for s in ("token", "key", "secret", "password")):
                    req["query_string"] = "<scrubbed>"
            # Stack-frame local vars (Sentry captures these by default)
            for exc in (event.get("exception") or {}).get("values", []) or []:
                stack = exc.get("stacktrace") or {}
                for frame in stack.get("frames", []) or []:
                    if frame.get("vars"):
                        frame["vars"] = scrub(frame["vars"])
            # Breadcrumbs (Sentry auto-captures HTTP bodies here)
            for crumb in (event.get("breadcrumbs") or {}).get("values", []) or []:
                if crumb.get("data"):
                    crumb["data"] = scrub(crumb["data"])
        except Exception:  # noqa: BLE001 — never break Sentry over a scrub failure
            pass
        return event

    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_RATE", "0.05")),
        environment=os.getenv("SENTRY_ENV", "local"),
        send_default_pii=False,  # don't capture user emails by default
        before_send=_scrub_event,
    )
    log.info("Sentry enabled (env=%s)", os.getenv("SENTRY_ENV", "local"))
else:
    log.info("Sentry not configured (SENTRY_DSN unset) — errors only logged locally")

from app import auth, db, emailer, exceptions as app_exceptions, exports, i18n, jobs, models  # noqa: E402
from app.services import extractor, llm, template_filler, template_parser  # noqa: E402
from app.config import settings  # noqa: E402
from app.services_catalog import CATEGORIES, SERVICES, localized  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app):
    """Startup + graceful shutdown. In prod, Alembic owns the schema — do NOT
    run create_all there because it masks failed migrations by silently filling
    in default tables. init_db() here is only a safety net for fresh dev
    databases / unit tests."""
    _env = os.getenv("ENV", "local")
    if _env != "prod":
        db.init_db()
        log.info("startup: init_db() ran (env=%s)", _env)
    else:
        log.info("startup: skipping init_db() in prod — Alembic owns the schema")
    auth.ensure_demo_user()
    log.info("startup complete: env=%s, demo_user=ready", _env)
    yield
    # Shutdown: drain the SQLAlchemy connection pool cleanly so Postgres doesn't
    # see a flood of "connection abruptly closed" errors on SIGTERM.
    try:
        db.engine.dispose()
        log.info("shutdown: db pool disposed")
    except Exception as e:  # noqa: BLE001
        log.warning("shutdown: db dispose failed: %s", e)


# docs_url/redoc_url disabled: /docs is our own human-facing API reference page,
# and we don't expose the internal Swagger UI on a customer-facing product.
app = FastAPI(
    title="Mostakhles API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# ---- Trusted hosts (defeats Host-header injection on verify/reset email links) ----
# In prod, ALLOWED_HOSTS MUST be set explicitly — no localhost fallback. Default
# is for local dev only. The assertion below crashes boot if prod misconfigured.
_env = os.getenv("ENV", "local")
_allowed_hosts_raw = os.getenv("ALLOWED_HOSTS", "")
if _env == "prod" and not _allowed_hosts_raw.strip():
    raise RuntimeError(
        "ALLOWED_HOSTS env var is required when ENV=prod. Set it to a comma-separated "
        "list of your real public hostnames (e.g. 'mostakhles.ai,www.mostakhles.ai')."
    )
_allowed_hosts = [h.strip() for h in (_allowed_hosts_raw or
    "localhost,127.0.0.1").split(",") if h.strip()]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)


# ---- CORS — Odoo modules + browser apps on customer domains hit /v1/* directly ----
_allowed_origins = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000",
).split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---- Request-ID middleware (correlates Sentry events + structured logs) ----
import re as _re
_REQUEST_ID_PATTERN = _re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Accept a caller-supplied ID only if it matches a strict shape — defeats
        # log injection via newlines / control chars / overly-long strings. Anything
        # weird is silently replaced with a fresh server-generated UUID.
        supplied = request.headers.get("x-request-id", "")
        rid = supplied if _REQUEST_ID_PATTERN.match(supplied) else uuid.uuid4().hex
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return response


app.add_middleware(RequestIDMiddleware)
app_exceptions.register_handlers(app)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Local Paymob mock — only mounted in ENV=local so /billing/checkout works
# without real merchant credentials. Set PAYMOB_BASE_URL=http://localhost:8000/_mock/paymob
# (or similar) and the Paymob client treats it as the real API.
if _env == "local":
    from app.services.paymob_mock import router as _paymob_mock_router  # noqa: E402
    app.include_router(_paymob_mock_router)


@app.get("/healthz")
def healthz():
    """Liveness probe — process is alive. Cheap, no I/O. Use for load balancers."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness probe — DB reachable + Gemini configured. Use for deploy gates.
    Returns 503 if not ready so orchestrators don't route traffic prematurely."""
    checks = {"db": "ok", "gemini": "ok"}
    try:
        from sqlalchemy import text as _sql_text
        with db.engine.connect() as conn:
            conn.execute(_sql_text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        checks["db"] = f"fail: {type(e).__name__}"
    if not llm.is_configured():
        checks["gemini"] = "fail: GEMINI_API_KEY unset"
    ok = all(v == "ok" for v in checks.values())
    return Response(
        content=json.dumps({"status": "ok" if ok else "degraded", "checks": checks}),
        media_type="application/json",
        status_code=200 if ok else 503,
    )


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "index.html", _ctx(request, nav_links=True))


@app.get("/app", response_class=HTMLResponse)
def demo_app(request: Request):
    session = db.SessionLocal()
    try:
        if not _current_user(session, request):
            return RedirectResponse("/login", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "app.html", _ctx(request))


@app.get("/chat", response_class=HTMLResponse)
def chat_page(request: Request):
    session = db.SessionLocal()
    try:
        if not _current_user(session, request):
            return RedirectResponse("/login", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "chat.html", _ctx(request))


@app.post("/v1/chat-extract")
def chat_extract(request: Request, file: UploadFile = File(...),
                 hard: bool = Form(True), x_api_key: str = Header(None)):
    """OCR a document to text so the user can then chat with it."""
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(415, "unsupported file type")
    data_bytes = file.file.read()
    if len(data_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 20 MB)")
    pages = (_count_pdf_pages(data_bytes) if file.content_type == "application/pdf" else 1) or 1
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        cost = pages * auth.credits_for(hard)
        auth.enforce_limit(session, api_key, needed=cost)
        try:
            text = extractor.run_text(data_bytes, file.content_type,
                                      SERVICES["arabic-ocr"]["prompt"], hard)
        except Exception as e:  # noqa: BLE001
            raise _http_error_for(e, "extraction failed")
        auth.increment_usage(session, api_key, count=cost)
        used, limit, _ = auth.get_usage(session, api_key)
        return {"text": text, "usage": {"used": used, "limit": limit,
                "remaining": max(0, limit - used), "charged": cost}}
    finally:
        session.close()


@app.post("/v1/chat")
def chat_answer(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    """Answer a question against the extracted document text. Charges 1 credit."""
    text, question = payload.get("text", ""), payload.get("question", "")
    history = payload.get("history", [])
    if not text or not question:
        raise HTTPException(400, "text and question are required")
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        auth.enforce_limit(session, api_key, needed=1)
        try:
            answer = extractor.chat(text, question, history)
        except Exception as e:  # noqa: BLE001
            raise _http_error_for(e, "chat failed")
        auth.increment_usage(session, api_key, count=1)
        used, limit, _ = auth.get_usage(session, api_key)
        return {"answer": answer, "usage": {"used": used, "limit": limit,
                "remaining": max(0, limit - used), "charged": 1}}
    finally:
        session.close()


_PRIVACY_HTML = """
<h2>ما المعلومات التي نجمعها</h2>
<p>بريدك الإلكتروني عند إنشاء الحساب، وبيانات الاستخدام (عدد عمليات الاستخراج) لإدارة رصيدك.</p>
<h2>صور المستندات لا تُخزَّن</h2>
<p>تُعالَج صور وملفات PDF التي ترفعها في الذاكرة وتُحذَف فور انتهاء الاستخراج. لا نحتفظ بنسخ من ملفاتك ولا نؤرشفها.</p>
<h2>نتائج الاستخراج تُحفَظ في سجلّك</h2>
<p>تُحفَظ نتائج الاستخراج (النصوص والحقول المستخرَجة فقط، لا الصور) في صفحة «السجل» الخاصة بحسابك حتى يسهل عليك الرجوع إليها وتصديرها. يمكنك حذف أي سجل في أي وقت أو حذف الحساب بالكامل لمسح كل البيانات.</p>
<h2>معالجة المحتوى بالذكاء الاصطناعي</h2>
<p>نستخدم نماذج رؤية متقدمة لمعالجة مستنداتك. لا يُستخدم محتوى مستنداتك لتدريب نماذج الذكاء الاصطناعي.</p>
<h2>المدفوعات</h2>
<p>تُعالَج المدفوعات عبر مزوّدَين معتمدَين: Paymob (للبطاقات والمحافظ المحلية في الشرق الأوسط) و PayPal (للدفع الدولي والاشتراكات). لا نرى ولا نخزّن بيانات بطاقتك البنكية.</p>
<h2>ملفات تعريف الارتباط</h2>
<p>نستخدم ملف تعريف ارتباط واحدًا للجلسة من أجل إبقائك مسجّلاً للدخول فقط — لا تتبّع إعلاني.</p>
<h2>حقوقك</h2>
<p>يمكنك إلغاء مفاتيح الـ API أو حذف حسابك في أي وقت. للتواصل بخصوص بياناتك: support@mostakhles.ai</p>
"""

_TERMS_HTML = """
<h2>الخدمة</h2>
<p>يوفّر «مُستخلِص» أدوات ذكاء اصطناعي لاستخراج وفهم بيانات المستندات عبر الويب والـ API وأودو.</p>
<h2>الحساب</h2>
<p>أنت مسؤول عن الحفاظ على سرية بيانات دخولك ومفاتيح الـ API الخاصة بك.</p>
<h2>الاستخدام المقبول</h2>
<p>تتعهّد بعدم رفع محتوى غير قانوني أو لا تملك حقّ معالجته، وبعدم إساءة استخدام الخدمة أو محاولة تعطيلها.</p>
<h2>النقاط والفوترة</h2>
<p>تُحتسب كل عملية بالنقاط حسب الوضع المختار (سريع/دقيق)، ويظهر لك ذلك قبل التنفيذ. الاشتراكات شهرية، ويمكنك الإلغاء في أي وقت — النقاط المستهلَكة غير قابلة للاسترداد.</p>
<h2>إخلاء المسؤولية</h2>
<p>الاستخراج مدعوم بالذكاء الاصطناعي وقد لا يكون دقيقًا بنسبة 100٪، خاصةً في المستندات المكتوبة بخط اليد. يرجى مراجعة النتائج المهمّة قبل الاعتماد عليها.</p>
<h2>التعديلات</h2>
<p>قد نحدّث هذه الشروط، وسننشر أي تغييرات على هذه الصفحة. للتواصل: support@mostakhles.ai</p>
"""


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse(request, "legal.html",
                                      _ctx(request, title="سياسة الخصوصية", body=_PRIVACY_HTML))


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    return templates.TemplateResponse(request, "legal.html",
                                      _ctx(request, title="شروط الاستخدام", body=_TERMS_HTML))


@app.get("/docs", response_class=HTMLResponse)
def api_docs(request: Request):
    return templates.TemplateResponse(request, "docs.html", _ctx(request))


@app.get("/tools", response_class=HTMLResponse)
def tools_hub(request: Request):
    lang = i18n.resolve_lang(request, None)
    svc, cats = localized(lang)
    return templates.TemplateResponse(request, "tools.html",
                                      _ctx(request, services=svc, categories=cats))


@app.get("/tools/{slug}", response_class=HTMLResponse)
def tool_page(request: Request, slug: str):
    """Deep link into the main /app extractor with the picked tool pre-selected.
    Consolidates the formerly-separate tool.html into one upgraded UI surface so
    every tool gets the visual gallery, multi-image upload, layout-aware renderer,
    confidence dots, inline edit, and template-upload features for free."""
    if slug not in SERVICES:
        return RedirectResponse("/tools", status_code=303)
    return RedirectResponse(f"/app?tool={slug}", status_code=303)


# ---------- Web auth + dashboard ----------

COOKIE_KW = dict(
    httponly=True,
    samesite="lax",
    max_age=60 * 60 * 24 * 30,
    # Default ON in prod; opt-out for local-http dev with COOKIE_SECURE=0.
    secure=os.getenv("COOKIE_SECURE", "1") == "1",
)


def _current_user(session, request: Request):
    return auth.user_from_session(session, request.cookies.get("sid"))


def _record_history(session, user, kind, document_type, data, charged,
                    duration_ms=None, layout=None, output_lang=None):
    """Best-effort log of a successful extraction for the dashboard.
    `data` is stored as JSONB (Postgres) — pass a dict/list, not a JSON string."""
    try:
        session.add(models.History(
            user_id=user.id, kind=kind, document_type=document_type,
            charged=charged, duration_ms=duration_ms,
            layout=layout, output_lang=output_lang,
            result_json=data,
        ))
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _http_error_for(e: Exception, prefix: str) -> HTTPException:
    """Surface a clean 429 for known quota errors, 503 for our budget circuit breaker,
    generic 502 for the rest."""
    if isinstance(e, llm.GeminiDailyQuotaExhausted):
        return HTTPException(429, str(e))
    if isinstance(e, llm.GeminiBudgetExhausted):
        return HTTPException(503, str(e))
    return HTTPException(502, f"{prefix}: {e}")


def _require_csrf(request: Request, submitted: str) -> None:
    """Raise 403 if the submitted CSRF token doesn't match the session's."""
    session = db.SessionLocal()
    try:
        sid = request.cookies.get("sid")
        if not auth.verify_csrf(session, sid, submitted):
            raise HTTPException(403, "CSRF token mismatch — refresh the page and try again.")
    finally:
        session.close()


def _ctx(request: Request, **extra):
    """Template context with the logged-in user (for the shared nav), plus i18n
    helpers (`lang`, `dir`, `t`) that every template can use directly."""
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        csrf = auth.session_csrf_token(session, request.cookies.get("sid")) or ""
    finally:
        session.close()
    lang = i18n.resolve_lang(request, user)
    return {
        "user": user,
        "csrf_token": csrf,
        "lang": lang,
        "dir": "rtl" if i18n.is_rtl(lang) else "ltr",
        # Bind lang into the translator so templates can write `{{ t('nav.dashboard') }}`
        # without repeating the lang each time.
        "t": lambda key, **fmt: i18n.t(key, lang, **fmt),
        "supported_langs": i18n.SUPPORTED_LANGS,
        **extra,
    }


@app.get("/set-language")
def set_language(request: Request, lang: str, next: str = "/"):
    """Switch site language. Saves to cookie + (if logged in) user.preferred_lang.
    Redirects back to `next` so the user keeps their place."""
    if lang not in i18n.SUPPORTED_LANGS:
        raise HTTPException(400, f"unsupported language: {lang}")
    # Sanity-check `next` so we don't get used as an open redirect.
    if not next.startswith("/") or next.startswith("//"):
        next = "/"
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if user:
            user.preferred_lang = lang
            session.commit()
    finally:
        session.close()
    resp = RedirectResponse(next, status_code=303)
    # 1-year cookie so the choice persists. Not httponly — JS reads it for the dir attr.
    resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
    return resp


def _resolve_caller(session, x_api_key, request: Request):
    """Identify the caller: API key (programmatic) or logged-in session (web).
    Also gates:
      - Account must have a verified email before any extraction is allowed
        (kills bot signups since bots won't open the verification email).
      - When falling back to session-cookie auth, require an X-CSRF-Token header
        matching the session's CSRF token. Without this, credentialed-CORS would
        let any allowed-origin XHR drive the logged-in user's /v1/* quota.
        Programmatic API-key callers don't need it (the key itself authenticates).
    """
    if x_api_key:
        key = auth.resolve_key(session, x_api_key)
    else:
        user = _current_user(session, request)
        if not user:
            raise HTTPException(401, "login required, or provide a valid x-api-key")
        # Cookie auth on /v1/* requires CSRF — the web app's nav inlines a fetch
        # wrapper that auto-adds this header on every /v1/* call.
        submitted = request.headers.get("x-csrf-token") or request.headers.get("X-CSRF-Token")
        if not auth.verify_csrf(session, request.cookies.get("sid"), submitted):
            raise HTTPException(
                403,
                "missing or invalid X-CSRF-Token header on cookie-authed /v1/* call. "
                "Refresh the page or use an x-api-key header for programmatic calls.",
            )
        key = session.query(models.ApiKey).filter_by(user_id=user.id, active=True).first()
        if not key:
            raise HTTPException(401, "login required, or provide a valid x-api-key")
    # Email-verification gate (skipped for the seeded demo account)
    if key.user.plan != "demo" and not getattr(key.user, "email_verified", True):
        raise HTTPException(403, "verify your email first — check your inbox for the activation link")
    return key


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    session = db.SessionLocal()
    try:
        if _current_user(session, request):
            return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "signup.html",
        _ctx(request, error=None, turnstile_sitekey=auth.turnstile_sitekey()))


@app.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...),
           cf_turnstile_response: str = Form("", alias="cf-turnstile-response")):
    def render_error(msg, code=400):
        return templates.TemplateResponse(request, "signup.html",
            _ctx(request, error=msg, turnstile_sitekey=auth.turnstile_sitekey()),
            status_code=code)

    # Rate-limit by IP: 10 signups / hour. Stops mass-signup attacks burning Turnstile
    # budget + SMTP reputation. Cloudflare edge limit is the second layer in prod.
    client_ip = request.client.host if request.client else None
    if not auth.rate_limit_check(f"signup:{client_ip}", max_attempts=10, window_sec=3600):
        return render_error("محاولات تسجيل كثيرة من هذا الجهاز. حاول لاحقًا.", code=429)
    auth.rate_limit_record(f"signup:{client_ip}")

    session = db.SessionLocal()
    try:
        email = email.strip().lower()
        if len(password) < 8:
            return render_error("كلمة المرور يجب أن تكون 8 أحرف على الأقل")
        if "@" not in email or "." not in email.split("@")[-1]:
            return render_error("صيغة البريد غير صحيحة")
        if auth.is_disposable_email(email):
            return render_error("لا نقبل عناوين البريد المؤقّتة. الرجاء استخدام بريد دائم.")
        client_ip = request.client.host if request.client else None
        if not auth.verify_turnstile(cf_turnstile_response, client_ip):
            return render_error("فشل التحقق من أنك لست روبوتًا. حاول مرة أخرى.")
        if session.query(models.User).filter_by(email=email).first():
            return render_error("هذا البريد مسجّل بالفعل")

        user = models.User(email=email, password_hash=auth.hash_password(password), plan="free",
                           email_verified=False, verification_token=secrets.token_urlsafe(32))
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(models.ApiKey(user_id=user.id))  # give them a first key
        session.commit()

        # Send verification email (console fallback if SMTP not configured locally)
        verify_url = str(request.base_url).rstrip("/") + f"/verify/{user.verification_token}"
        try:
            emailer.send_verification_email(user.email, verify_url)
        except Exception:  # noqa: BLE001 — don't block signup on email failure; user can resend
            pass
        return templates.TemplateResponse(request, "verify_sent.html",
            _ctx(request, email=user.email))
    finally:
        session.close()


@app.get("/verify/{token}", response_class=HTMLResponse)
def verify_email(request: Request, token: str):
    session = db.SessionLocal()
    try:
        user = session.query(models.User).filter_by(verification_token=token).first()
        if not user:
            return templates.TemplateResponse(request, "verify_sent.html",
                _ctx(request, email=None,
                     error="رابط التأكيد غير صالح أو منتهٍ."),
                status_code=400)
        user.email_verified = True
        user.verification_token = None
        session.commit()
        # Don't auto-create a session — verification links travel through SMTP relays,
        # browser history, mail-scanner prefetch (Outlook Safe Links, etc.). One leaked
        # link must NOT grant a persistent session. User logs in normally.
        return RedirectResponse("/login?verified=1", status_code=303)
    finally:
        session.close()


@app.post("/verify/resend")
def verify_resend(request: Request, email: str = Form(...)):
    # Rate-limit by IP: 5/hour. Stops mass email spamming.
    client_ip = request.client.host if request.client else None
    if not auth.rate_limit_check(f"resend:{client_ip}", max_attempts=5, window_sec=3600):
        return templates.TemplateResponse(request, "verify_sent.html",
            _ctx(request, email=email))
    auth.rate_limit_record(f"resend:{client_ip}")
    session = db.SessionLocal()
    try:
        user = session.query(models.User).filter_by(email=email.strip().lower()).first()
        if user and not user.email_verified:
            if not user.verification_token:
                user.verification_token = secrets.token_urlsafe(32)
                session.commit()
            verify_url = str(request.base_url).rstrip("/") + f"/verify/{user.verification_token}"
            try:
                emailer.send_verification_email(user.email, verify_url)
            except Exception:  # noqa: BLE001
                pass
        return templates.TemplateResponse(request, "verify_sent.html",
            _ctx(request, email=email))
    finally:
        session.close()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, verified: int = 0):
    session = db.SessionLocal()
    try:
        if _current_user(session, request):
            return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()
    lang = i18n.resolve_lang(request, None)
    if verified:
        notice = ("Your email has been verified. You can now log in."
                  if lang == "en"
                  else "تم تأكيد بريدك بنجاح. يمكنك الآن تسجيل الدخول.")
    else:
        notice = None
    return templates.TemplateResponse(request, "login.html",
        _ctx(request, error=None, notice=notice))


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    ip = request.client.host if request.client else None
    lang = i18n.resolve_lang(request, None)
    if not auth.login_rate_limit_check(ip):
        msg = ("Too many attempts. Try again in 15 minutes."
               if lang == "en" else "محاولات كثيرة. حاول مجددًا بعد 15 دقيقة.")
        return templates.TemplateResponse(request, "login.html",
            _ctx(request, error=msg), status_code=429)
    session = db.SessionLocal()
    try:
        user = session.query(models.User).filter_by(email=email.strip().lower()).first()
        if not user or not user.password_hash or not auth.verify_password(password, user.password_hash):
            auth.login_rate_limit_record(ip)
            msg = ("Incorrect email or password" if lang == "en"
                   else "بريد إلكتروني أو كلمة مرور غير صحيحة")
            return templates.TemplateResponse(request, "login.html",
                _ctx(request, error=msg), status_code=401)
        token = auth.create_session(session, user)
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("sid", token, **COOKIE_KW)
        return resp
    finally:
        session.close()


@app.get("/logout")
def logout(request: Request):
    session = db.SessionLocal()
    try:
        auth.delete_session(session, request.cookies.get("sid"))
    finally:
        session.close()
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("sid")
    return resp


# ---- Forgot / reset password ----
@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return templates.TemplateResponse(request, "forgot_password.html",
        _ctx(request, sent=False, error=None))


@app.post("/forgot-password")
def forgot_password(request: Request, email: str = Form(...)):
    # Rate-limit by IP: 5/hour. Stops attackers using reset emails to spam users
    # and probe which accounts exist via timing differences.
    client_ip = request.client.host if request.client else None
    if not auth.rate_limit_check(f"forgot:{client_ip}", max_attempts=5, window_sec=3600):
        return templates.TemplateResponse(request, "forgot_password.html",
            _ctx(request, sent=True, error=None))  # silent so we don't leak the rate-limit
    auth.rate_limit_record(f"forgot:{client_ip}")

    session = db.SessionLocal()
    try:
        user = session.query(models.User).filter_by(email=email.strip().lower()).first()
        # Always show the same confirmation — never reveal whether the email exists.
        if user and user.password_hash:
            token = auth.make_password_reset(session, user)
            reset_url = str(request.base_url).rstrip("/") + f"/reset-password/{token}"
            try:
                emailer.send_password_reset_email(user.email, reset_url)
            except Exception:  # noqa: BLE001
                pass
        return templates.TemplateResponse(request, "forgot_password.html",
            _ctx(request, sent=True, error=None))
    finally:
        session.close()


@app.get("/reset-password/{token}", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str):
    session = db.SessionLocal()
    try:
        user = auth.consume_password_reset(session, token)
        ok = user is not None
        return templates.TemplateResponse(request, "reset_password.html",
            _ctx(request, token=token, ok=ok, error=None, done=False))
    finally:
        session.close()


@app.post("/reset-password/{token}")
def reset_password(request: Request, token: str,
                   new_password: str = Form(...),
                   confirm_password: str = Form(...)):
    session = db.SessionLocal()
    try:
        user = auth.consume_password_reset(session, token)
        lang = i18n.resolve_lang(request, None)
        ctx_extra = {"token": token, "ok": user is not None, "done": False, "error": None}
        if not user:
            ctx_extra["error"] = ("Link is invalid or expired. Request a new one."
                                  if lang == "en"
                                  else "الرابط غير صالح أو انتهت صلاحيته. اطلب رابطًا جديدًا.")
            return templates.TemplateResponse(request, "reset_password.html",
                _ctx(request, **ctx_extra), status_code=400)
        if len(new_password) < 8:
            ctx_extra["error"] = ("Password must be at least 8 characters."
                                  if lang == "en"
                                  else "كلمة المرور يجب أن تكون 8 أحرف على الأقل.")
            return templates.TemplateResponse(request, "reset_password.html",
                _ctx(request, **ctx_extra), status_code=400)
        if new_password != confirm_password:
            ctx_extra["error"] = ("Passwords do not match." if lang == "en"
                                  else "كلمتا المرور غير متطابقتين.")
            return templates.TemplateResponse(request, "reset_password.html",
                _ctx(request, **ctx_extra), status_code=400)
        user.password_hash = auth.hash_password(new_password)
        user.password_reset_token = None
        user.password_reset_expires = None
        # Invalidate all existing sessions so a thief loses their cookie when the owner resets.
        session.query(models.Session).filter_by(user_id=user.id).delete()
        session.commit()
        ctx_extra["done"] = True
        return templates.TemplateResponse(request, "reset_password.html",
            _ctx(request, **ctx_extra))
    finally:
        session.close()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, q: str = "", paid: str = ""):
    from collections import Counter
    from datetime import date, datetime as dt, timedelta
    from calendar import monthrange

    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        limit = auth.PLAN_LIMITS.get(user.plan, 50)

        keys = []
        for k in user.api_keys:
            used, _, _ = auth.get_usage(session, k)
            keys.append({"id": k.id, "key": k.key, "active": k.active, "used": used})

        tpls = (session.query(models.Template).filter_by(user_id=user.id)
                .order_by(models.Template.id.desc()).all())
        templates_list = [{"id": t.id, "name": t.name,
                          "fields": list((t.schema_json or {}).keys())} for t in tpls]

        # ---- analytics from History ----
        now = dt.utcnow()
        today = now.date()
        month_start = today.replace(day=1)
        thirty_days_ago = now - timedelta(days=30)

        all_hist = (session.query(models.History)
                    .filter(models.History.user_id == user.id)
                    .order_by(models.History.id.desc()).all())

        total_extractions = len(all_hist)
        total_credits_ever = sum(h.charged or 0 for h in all_hist)
        month_extractions = sum(1 for h in all_hist if h.created_at and h.created_at.date() >= month_start)
        month_credits = sum(h.charged or 0 for h in all_hist if h.created_at and h.created_at.date() >= month_start)
        today_extractions = sum(1 for h in all_hist if h.created_at and h.created_at.date() == today)
        today_credits = sum(h.charged or 0 for h in all_hist if h.created_at and h.created_at.date() == today)
        last_activity = all_hist[0].created_at if all_hist else None

        # Days until quota renewal (1st of next month)
        last_day = monthrange(today.year, today.month)[1]
        days_to_renewal = (last_day - today.day) + 1

        # Cost projection: if you keep this month's pace
        days_elapsed = max(1, today.day)
        projected_month = round(month_credits / days_elapsed * last_day)
        will_exceed = projected_month > limit

        # 30-day daily series
        daily = {(thirty_days_ago + timedelta(days=i)).date(): 0 for i in range(31)}
        for h in all_hist:
            if h.created_at and h.created_at >= thirty_days_ago:
                d = h.created_at.date()
                if d in daily:
                    daily[d] += (h.charged or 0)
        chart_days = [{"d": d.strftime("%m-%d"), "v": v} for d, v in sorted(daily.items())]
        chart_max = max((d["v"] for d in chart_days), default=1) or 1

        # Tool / document-type breakdown (this month)
        tool_counts: Counter = Counter()
        doctype_counts: Counter = Counter()
        for h in all_hist:
            if h.created_at and h.created_at.date() >= month_start:
                tool_counts[(h.kind or "other")] += (h.charged or 0)
                if h.document_type:
                    doctype_counts[h.document_type] += 1

        top_tools = tool_counts.most_common(8)
        top_tools_max = max((c for _, c in top_tools), default=1) or 1
        top_doctypes = doctype_counts.most_common(6)

        # Mode breakdown (this month): 1 credit = fast, 8 = hard, anything else = "other"
        mode_fast = sum(1 for h in all_hist if h.created_at and h.created_at.date() >= month_start and h.charged == 1)
        mode_hard = sum(1 for h in all_hist if h.created_at and h.created_at.date() >= month_start and h.charged == 8)
        mode_other = max(0, month_extractions - mode_fast - mode_hard)

        # Recent history table (last 20, kept for the activity feed) — filtered by q if present
        if q:
            ql = q.lower()
            filtered = [h for h in all_hist
                        if ql in (h.kind or "").lower() or ql in (h.document_type or "").lower()]
        else:
            filtered = all_hist
        history_list = [{"id": h.id, "kind": h.kind, "document_type": h.document_type,
                        "charged": h.charged, "created_at": str(h.created_at)[:16]}
                        for h in filtered[:20]]

        return templates.TemplateResponse(request, "dashboard.html", _ctx(request,
            plan=user.plan, limit=limit, keys=keys,
            templates=templates_list, history=history_list,
            webhook_url=user.webhook_url or "",
            paid_flash=paid,  # "1" right after a Paymob success → render green banner
            # analytics
            month_credits=month_credits, month_extractions=month_extractions,
            today_credits=today_credits, today_extractions=today_extractions,
            total_extractions=total_extractions, total_credits_ever=total_credits_ever,
            last_activity=str(last_activity)[:16] if last_activity else None,
            days_to_renewal=days_to_renewal,
            projected_month=projected_month, will_exceed=will_exceed,
            remaining=max(0, limit - month_credits),
            usage_pct=min(100, round(month_credits / limit * 100)) if limit else 0,
            chart_days=chart_days, chart_max=chart_max,
            top_tools=[{"name": n, "credits": c, "pct": round(c / top_tools_max * 100)} for n, c in top_tools],
            top_doctypes=[{"name": n, "count": c} for n, c in top_doctypes],
            mode_fast=mode_fast, mode_hard=mode_hard, mode_other=mode_other,
            q=q,
        ))
    finally:
        session.close()


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    """Owner/admin overview — cross-account metrics. Gated by ADMIN_EMAILS env var.
    Returns 404 (not 401/403) to BOTH unauth and non-admin so the URL doesn't leak
    AND so admin email enumeration isn't possible by comparing response codes."""
    from collections import Counter
    from datetime import datetime as dt, timedelta

    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user or not auth.is_admin(user):
            raise HTTPException(404, "not found")

        now = dt.utcnow()
        today = now.date()
        month_start = today.replace(day=1)
        thirty_days_ago = now - timedelta(days=30)

        # ----- Users -----
        users = session.query(models.User).all()
        total_users = len(users)
        verified = sum(1 for u in users if u.email_verified)
        unverified = total_users - verified
        active_keys = session.query(models.ApiKey).filter_by(active=True).count()
        plan_counts: Counter = Counter(u.plan for u in users)
        signups_today = sum(1 for u in users if u.created_at and u.created_at.date() == today)
        signups_7d = sum(1 for u in users if u.created_at and (now - u.created_at) <= timedelta(days=7))
        signups_30d = sum(1 for u in users if u.created_at and u.created_at >= thirty_days_ago)

        # 30-day signups chart
        signup_daily = {(thirty_days_ago + timedelta(days=i)).date(): 0 for i in range(31)}
        for u in users:
            if u.created_at and u.created_at >= thirty_days_ago:
                d = u.created_at.date()
                if d in signup_daily:
                    signup_daily[d] += 1
        signups_chart = [{"d": d.strftime("%m-%d"), "v": v} for d, v in sorted(signup_daily.items())]
        signups_chart_max = max((d["v"] for d in signups_chart), default=1) or 1

        # ----- Extractions / credits across all users -----
        all_hist = session.query(models.History).all()
        total_extractions = len(all_hist)
        total_credits = sum(h.charged or 0 for h in all_hist)
        month_credits = sum(h.charged or 0 for h in all_hist if h.created_at and h.created_at.date() >= month_start)
        month_extractions = sum(1 for h in all_hist if h.created_at and h.created_at.date() >= month_start)
        today_extractions = sum(1 for h in all_hist if h.created_at and h.created_at.date() == today)

        # Estimated Gemini spend this month (hard=8cr/$0.015, fast=1cr/$0.0025)
        # We log charged credits, not raw mode — back into approximate cost per credit.
        hard_ops = sum(1 for h in all_hist if h.created_at and h.created_at.date() >= month_start and h.charged == 8)
        fast_ops = sum(1 for h in all_hist if h.created_at and h.created_at.date() >= month_start and h.charged == 1)
        est_cost_month = round(hard_ops * 0.015 + fast_ops * 0.0025, 2)

        # 30-day usage chart (sum credits per day across all users)
        usage_daily = {(thirty_days_ago + timedelta(days=i)).date(): 0 for i in range(31)}
        for h in all_hist:
            if h.created_at and h.created_at >= thirty_days_ago:
                d = h.created_at.date()
                if d in usage_daily:
                    usage_daily[d] += (h.charged or 0)
        usage_chart = [{"d": d.strftime("%m-%d"), "v": v} for d, v in sorted(usage_daily.items())]
        usage_chart_max = max((d["v"] for d in usage_chart), default=1) or 1

        # ----- Top users this month (by credits) -----
        user_credit: Counter = Counter()
        user_ops: Counter = Counter()
        for h in all_hist:
            if h.created_at and h.created_at.date() >= month_start:
                user_credit[h.user_id] += (h.charged or 0)
                user_ops[h.user_id] += 1
        user_by_id = {u.id: u for u in users}
        top_users = []
        for uid, credits in user_credit.most_common(10):
            u = user_by_id.get(uid)
            if u:
                top_users.append({"email": u.email, "plan": u.plan, "credits": credits,
                                  "ops": user_ops[uid]})

        # ----- Top tools / document types this month -----
        tool_counts: Counter = Counter()
        doctype_counts: Counter = Counter()
        for h in all_hist:
            if h.created_at and h.created_at.date() >= month_start:
                tool_counts[h.kind or "other"] += (h.charged or 0)
                if h.document_type:
                    doctype_counts[h.document_type] += 1
        top_tools = [{"name": n, "credits": c} for n, c in tool_counts.most_common(10)]
        top_doctypes = [{"name": n, "count": c} for n, c in doctype_counts.most_common(8)]

        # ----- Recent signups -----
        recent_signups = sorted(users, key=lambda u: u.created_at or dt.min, reverse=True)[:10]
        recent_signups_list = [{"email": u.email, "plan": u.plan, "verified": u.email_verified,
                                "created_at": str(u.created_at)[:16]} for u in recent_signups]

        # ----- Recent activity (last 15 across all users) -----
        recent = (session.query(models.History).order_by(models.History.id.desc()).limit(15).all())
        recent_activity = []
        for h in recent:
            u = user_by_id.get(h.user_id)
            recent_activity.append({
                "email": u.email if u else "?", "kind": h.kind,
                "document_type": h.document_type, "charged": h.charged,
                "created_at": str(h.created_at)[:16],
            })

        # ----- Active sessions (rough proxy for current users) -----
        active_sessions = session.query(models.Session).count()

        # ===== Deeper statistics =====
        # Conversion funnel
        active_user_ids = {h.user_id for h in all_hist}
        active_users = len(active_user_ids)
        paid_users = sum(1 for u in users if u.plan and u.plan not in ("free", "demo"))
        verify_rate = round(verified / total_users * 100) if total_users else 0
        activation_rate = round(active_users / total_users * 100) if total_users else 0
        paid_conversion = round(paid_users / total_users * 100, 1) if total_users else 0

        # Per-user averages
        avg_credits_per_user = round(month_credits / max(1, active_users), 1)
        avg_ops_per_user = round(month_extractions / max(1, active_users), 1)

        # Day-over-day & week-over-week
        yesterday = today - timedelta(days=1)
        seven_days_ago = today - timedelta(days=7)
        fourteen_days_ago = today - timedelta(days=14)
        yest_extractions = sum(1 for h in all_hist if h.created_at and h.created_at.date() == yesterday)
        last_7d_ext = sum(1 for h in all_hist if h.created_at and seven_days_ago <= h.created_at.date() <= today)
        prev_7d_ext = sum(1 for h in all_hist if h.created_at and fourteen_days_ago <= h.created_at.date() < seven_days_ago)
        dod_growth = round((today_extractions - yest_extractions) / max(1, yest_extractions) * 100)
        wow_growth = round((last_7d_ext - prev_7d_ext) / max(1, prev_7d_ext) * 100)

        # Churn proxy: signed up >7 days ago, no activity in last 7 days
        churn_candidates = sum(
            1 for u in users
            if u.created_at and (now - u.created_at) > timedelta(days=7)
            and u.id not in {h.user_id for h in all_hist if h.created_at and h.created_at >= (now - timedelta(days=7))}
        )

        # ===== Performance KPIs (from duration_ms; null for historical rows) =====
        durations = sorted([h.duration_ms for h in all_hist if h.duration_ms])
        if durations:
            avg_ms = round(sum(durations) / len(durations))
            p50_ms = durations[len(durations) // 2]
            p95_ms = durations[int(len(durations) * 0.95)] if len(durations) >= 20 else durations[-1]
            slowest_ms = durations[-1]
            timed_ops = len(durations)
        else:
            avg_ms = p50_ms = p95_ms = slowest_ms = None
            timed_ops = 0

        # Throughput: ops/day in last 7 days (where activity exists)
        recent_7d_days = set(h.created_at.date() for h in all_hist
                             if h.created_at and h.created_at.date() >= seven_days_ago)
        throughput_per_day = round(last_7d_ext / max(1, len(recent_7d_days)), 1) if recent_7d_days else 0

        # Peak hour of activity (last 7 days)
        hour_counts: Counter = Counter()
        for h in all_hist:
            if h.created_at and h.created_at.date() >= seven_days_ago:
                hour_counts[h.created_at.hour] += 1
        peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

        # ===== Forecasting (simple linear from 30-day pace) =====
        from calendar import monthrange as _mr
        last_day = _mr(today.year, today.month)[1]
        days_elapsed = max(1, today.day)
        days_left = last_day - today.day

        # End-of-month projections (linear from this month's pace)
        proj_signups_month = round((signups_30d / 30) * last_day)
        proj_extractions_month = round((month_extractions / days_elapsed) * last_day)
        proj_credits_month = round((month_credits / days_elapsed) * last_day)
        proj_cost_month = round(proj_credits_month * 0.0019, 2)  # weighted avg cost/credit

        # 30-day forward forecast on signups + usage (linear extrapolation)
        signup_rate_per_day = signups_30d / 30
        usage_rate_per_day = sum(d["v"] for d in usage_chart) / 30
        forecast_30d = []
        for i in range(1, 31):
            d = today + timedelta(days=i)
            forecast_30d.append({
                "d": d.strftime("%m-%d"),
                "signups": round(signup_rate_per_day * i),
                "credits": round(usage_rate_per_day * i),
            })
        forecast_signup_max = max((f["signups"] for f in forecast_30d), default=1) or 1
        forecast_usage_max = max((f["credits"] for f in forecast_30d), default=1) or 1

        # Days until milestone
        def days_to(target, current, rate):
            if current >= target:
                return 0
            return round((target - current) / rate) if rate > 0 else None
        ms_users_100 = days_to(100, total_users, signup_rate_per_day)
        ms_users_1000 = days_to(1000, total_users, signup_rate_per_day)
        ms_ext_1000 = days_to(1000, total_extractions, (total_extractions / 30) if total_extractions else 0)

        # ----- DB size (sqlite only) -----
        db_size_mb = None
        try:
            db_path = db.DATABASE_URL.replace("sqlite:///", "")
            db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        except Exception:  # noqa: BLE001
            pass

        return templates.TemplateResponse(request, "admin.html", {
            "user": user, "csrf_token": "",
            # users
            "total_users": total_users, "verified": verified, "unverified": unverified,
            "active_keys": active_keys, "plan_counts": dict(plan_counts),
            "signups_today": signups_today, "signups_7d": signups_7d, "signups_30d": signups_30d,
            "signups_chart": signups_chart, "signups_chart_max": signups_chart_max,
            # usage
            "total_extractions": total_extractions, "total_credits": total_credits,
            "month_credits": month_credits, "month_extractions": month_extractions,
            "today_extractions": today_extractions,
            "hard_ops": hard_ops, "fast_ops": fast_ops, "est_cost_month": est_cost_month,
            "usage_chart": usage_chart, "usage_chart_max": usage_chart_max,
            # leaderboards
            "top_users": top_users, "top_tools": top_tools, "top_doctypes": top_doctypes,
            # recent
            "recent_signups": recent_signups_list, "recent_activity": recent_activity,
            # system
            "active_sessions": active_sessions, "db_size_mb": db_size_mb,
            "llm_models": llm.active_models(),
            # deeper stats
            "active_users": active_users, "paid_users": paid_users,
            "verify_rate": verify_rate, "activation_rate": activation_rate,
            "paid_conversion": paid_conversion,
            "avg_credits_per_user": avg_credits_per_user, "avg_ops_per_user": avg_ops_per_user,
            "dod_growth": dod_growth, "wow_growth": wow_growth,
            "churn_candidates": churn_candidates,
            # performance
            "avg_ms": avg_ms, "p50_ms": p50_ms, "p95_ms": p95_ms,
            "slowest_ms": slowest_ms, "timed_ops": timed_ops,
            "throughput_per_day": throughput_per_day, "peak_hour": peak_hour,
            # forecasting
            "proj_signups_month": proj_signups_month,
            "proj_extractions_month": proj_extractions_month,
            "proj_credits_month": proj_credits_month, "proj_cost_month": proj_cost_month,
            "forecast_30d": forecast_30d,
            "forecast_signup_max": forecast_signup_max, "forecast_usage_max": forecast_usage_max,
            "ms_users_100": ms_users_100, "ms_users_1000": ms_users_1000,
            "ms_ext_1000": ms_ext_1000, "days_left": days_left,
        })
    finally:
        session.close()


@app.get("/dashboard/history.csv")
def history_csv(request: Request):
    import csv
    import io as _io
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        rows = (session.query(models.History).filter_by(user_id=user.id)
                .order_by(models.History.id.desc()).all())
        buf = _io.StringIO()
        w = csv.writer(buf)
        w.writerow(["id", "created_at", "kind", "document_type", "charged"])
        for h in rows:
            w.writerow([h.id, h.created_at.isoformat() if h.created_at else "",
                        h.kind or "", h.document_type or "", h.charged or 0])
        csv_bytes = ("﻿" + buf.getvalue()).encode("utf-8")  # BOM so Excel shows Arabic
        return Response(content=csv_bytes, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="history.csv"'})
    finally:
        session.close()


@app.post("/dashboard/keys")
def create_key(request: Request, csrf_token: str = Form("")):
    _require_csrf(request, csrf_token)
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        session.add(models.ApiKey(user_id=user.id))
        session.commit()
        return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()


@app.post("/dashboard/keys/{key_id}/revoke")
def revoke_key(key_id: int, request: Request, csrf_token: str = Form("")):
    _require_csrf(request, csrf_token)
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        key = session.get(models.ApiKey, key_id)
        if key and key.user_id == user.id:
            key.active = False
            session.commit()
        return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()


def _count_pdf_pages(data: bytes):
    try:
        import io
        from pypdf import PdfReader
        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:  # noqa: BLE001
        return None


@app.get("/v1/jobs/{job_id}")
def job_status(job_id: str):
    """Poll a batch job's progress and (partial) results."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return {"job_id": job_id, **job}


@app.post("/v1/estimate")
def estimate(request: Request, file: UploadFile = File(...), x_api_key: str = Header(None)):
    """Pre-run cost estimate: pages + credits (strong vs fast) + current balance.
    No AI call — just counts pages."""
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        used, limit, _ = auth.get_usage(session, api_key)
    finally:
        session.close()
    data = file.file.read()
    pages = (_count_pdf_pages(data) if file.content_type == "application/pdf" else 1) or 1
    return {
        "pages": pages,
        "cost_strong": pages * auth.credits_for(True),
        "cost_fast": pages * auth.credits_for(False),
        "used": used, "limit": limit, "remaining": max(0, limit - used),
    }


@app.get("/v1/usage")
def usage(request: Request, x_api_key: str = Header(None)):
    """Report the caller's current-month usage and quota."""
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        used, limit, _ = auth.get_usage(session, api_key)
        return {"plan": api_key.user.plan, "used": used, "limit": limit,
                "remaining": max(0, limit - used)}
    finally:
        session.close()


@app.post("/v1/tool/{slug}")
def run_tool(slug: str, request: Request, file: UploadFile = File(...),
             hard: bool = Form(True), output_lang: str = Form("preserve"),
             x_api_key: str = Header(None)):
    """Run a catalog OCR service (text / fields / table / searchable PDF).
    output_lang: 'preserve' | 'ar' | 'en' — controls language of extracted values."""
    svc = SERVICES.get(slug)
    if not svc:
        raise HTTPException(404, "unknown service")
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    if output_lang not in ("preserve", "ar", "en"):
        raise HTTPException(400, "output_lang must be one of: preserve, ar, en")
    # Per-IP burst limit — defence-in-depth in front of the credit quota.
    # 30 calls / minute / IP catches both runaway clients and the shared demo key.
    client_ip = request.client.host if request.client else None
    if not auth.rate_limit_check(f"tool:{client_ip}", max_attempts=30, window_sec=60):
        raise HTTPException(429, "too many requests from this IP, slow down")
    auth.rate_limit_record(f"tool:{client_ip}")

    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(415, "unsupported file type. Use PNG, JPG, WEBP, GIF, or PDF.")
    data_bytes = file.file.read()
    if len(data_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 20 MB)")

    kind = svc["kind"]
    if kind == "searchable_pdf" and file.content_type == "application/pdf":
        raise HTTPException(400, "هذه الخدمة تعمل على الصور الممسوحة، وليس على ملفات PDF")

    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        cost = auth.credits_for(hard)
        auth.enforce_limit(session, api_key, needed=cost)
        ct = file.content_type  # `hard` comes from the request, default True
        import time as _time
        _t0 = _time.time()
        try:
            if kind == "text":
                out = {"kind": "text", "text": extractor.run_text(data_bytes, ct, svc["prompt"], hard)}
            elif kind == "fields":
                # Tools with `expert_role` + `cognitive_brief` go through the rich
                # extractor that emits {document_type, fields, line_items?, totals?,
                # clauses?, validations, derived, summary}. Tools without those
                # fields fall back to the thin schema-only extractor so existing
                # 22+ services keep working unchanged.
                if svc.get("expert_role") and svc.get("cognitive_brief"):
                    rich = extractor.extract_expert(
                        data_bytes, ct,
                        expert_role=svc["expert_role"],
                        cognitive_brief=svc["cognitive_brief"],
                        schema=svc["schema"],
                        hard=hard, output_lang=output_lang,
                        document_type_hint=slug,
                    )
                    out = {"kind": "expert", "data": rich}
                else:
                    out = {"kind": "fields", "data": extractor.extract_schema(
                        data_bytes, ct, svc["schema"], hard, hint=svc.get("hint", ""),
                        output_lang=output_lang)}
            elif kind == "prescription":
                # Pass the rich rx structure straight through. The frontend's
                # prescriptionHtml() expects {patient, medications, as_needed?,
                # phone_numbers?, notes?} and won't render the medications table
                # if it can't find `medications`. The earlier flatten-to-rows
                # transform broke that — meds went into a generic table that
                # prescriptionHtml never reads.
                rx = extractor.extract_prescription(data_bytes, ct, hard)
                out = {"kind": "prescription", **rx}
            elif kind == "table":
                t = extractor.run_table(data_bytes, ct, hard)
                out = {"kind": "table", "columns": t["columns"], "rows": t["rows"]}
            elif kind == "searchable_pdf":
                text = extractor.run_text(data_bytes, ct, SERVICES["arabic-ocr"]["prompt"], hard)
                pdf, media, fname = exports.image_to_searchable_pdf(data_bytes, text)
                auth.increment_usage(session, api_key, count=cost)
                return Response(content=pdf, media_type=media,
                                headers={"Content-Disposition": f'attachment; filename="{fname}"'})
            else:
                raise HTTPException(400, "unsupported service kind")
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            raise _http_error_for(e, "service failed")

        _dur_ms = int((_time.time() - _t0) * 1000)
        auth.increment_usage(session, api_key, count=cost)
        _record_history(session, api_key.user, slug, out.get("document_type"),
                        out.get("data") or out.get("text") or out, cost, duration_ms=_dur_ms)
        used, limit, _ = auth.get_usage(session, api_key)
        out["usage"] = {"used": used, "limit": limit, "remaining": max(0, limit - used), "charged": cost}
        return out
    finally:
        session.close()


@app.post("/v1/export-table")
def export_table(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    session = db.SessionLocal()
    try:
        _resolve_caller(session, x_api_key, request)
    finally:
        session.close()
    fmt, columns, rows = payload.get("format", "xlsx"), payload.get("columns", []), payload.get("rows", [])
    if fmt == "xlsx":
        data, media, fname = exports.table_to_xlsx(columns, rows)
    elif fmt == "csv":
        data, media, fname = exports.table_to_csv(columns, rows)
    else:
        raise HTTPException(400, "format must be xlsx or csv")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/v1/export-text")
def export_text(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    session = db.SessionLocal()
    try:
        _resolve_caller(session, x_api_key, request)
    finally:
        session.close()
    fmt, text = payload.get("format", "docx"), payload.get("text", "")
    if fmt == "docx":
        data, media, fname = exports.text_to_docx(text)
    elif fmt == "pdf":
        data, media, fname = exports.text_to_pdf(text)
    else:
        raise HTTPException(400, "format must be docx or pdf")
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@app.post("/v1/export")
def export_data(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    """Turn extracted rows into a downloadable file (csv/xlsx/docx/pdf)."""
    session = db.SessionLocal()
    try:
        _resolve_caller(session, x_api_key, request)  # auth gate
    finally:
        session.close()
    fmt = payload.get("format", "csv")
    rows = payload.get("rows", [])
    if fmt not in exports.EXPORTERS:
        raise HTTPException(400, f"unsupported format '{fmt}'. Use: {', '.join(exports.EXPORTERS)}")
    if not rows:
        raise HTTPException(400, "no rows to export")
    data, media_type, filename = exports.EXPORTERS[fmt](rows)
    return Response(content=data, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---------- Saved templates ----------
@app.get("/v1/templates")
def list_templates(request: Request, x_api_key: str = Header(None)):
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        tpls = (session.query(models.Template).filter_by(user_id=api_key.user.id)
                .order_by(models.Template.id.desc()).all())
        return [{"id": t.id, "name": t.name, "schema": t.schema_json} for t in tpls]
    finally:
        session.close()


@app.post("/v1/templates")
def create_template(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    name = (payload.get("name") or "").strip()
    schema = payload.get("schema")
    if not name or not isinstance(schema, dict) or not schema:
        raise HTTPException(400, "name and a non-empty schema are required")
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        session.add(models.Template(user_id=api_key.user.id, name=name,
                                    schema_json=schema))
        session.commit()
        return {"ok": True}
    finally:
        session.close()


# ---------- Upload-your-template ----------
_TEMPLATE_KINDS = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/pdf",
    "text/html",
    "application/xhtml+xml",
}


@app.post("/v1/templates/upload")
def upload_template(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(""),
    save: bool = Form(True),
    x_api_key: str = Header(None),
):
    """Introspect an uploaded template (Excel/Word/PDF form/HTML) and return its
    discovered fields as a schema. When `save=True` (default), persist as a
    user Template with the original file bytes so it can be filled back later."""
    if file.content_type not in _TEMPLATE_KINDS:
        raise HTTPException(
            415,
            "unsupported template type. Use .xlsx, .docx, .pdf, or .html",
        )
    raw = file.file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "template too large (max 10 MB)")
    info = template_parser.introspect(raw, file.filename, file.content_type)
    if not info.get("kind"):
        raise HTTPException(400, info.get("warning") or "unsupported template")
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        tpl_id = None
        if save and info["fields"]:
            tpl_name = name.strip() or (file.filename or "Template").rsplit(".", 1)[0]
            tpl = models.Template(
                user_id=api_key.user.id,
                name=tpl_name[:100],
                schema_json=info["fields"],
                source_kind=info["kind"],
                source_bytes=raw,
                source_name=file.filename or f"template.{info['kind']}",
            )
            session.add(tpl); session.commit(); session.refresh(tpl)
            tpl_id = tpl.id
        return {
            "kind": info["kind"],
            "fields": info["fields"],
            "field_count": info["field_count"],
            "warning": info["warning"],
            "template_id": tpl_id,
        }
    finally:
        session.close()


@app.post("/v1/templates/{tid}/fill")
def fill_template_endpoint(
    tid: int, request: Request, payload: dict = Body(...),
    x_api_key: str = Header(None),
):
    """Take an extracted-data dict (from /v1/extract) and stream back the user's
    template with values filled in. Body: {"data": {...}, "rows": optional list
    for tables}. Output: the filled file in the original format."""
    data = payload.get("data") or {}
    rows = payload.get("rows")
    if not isinstance(data, dict):
        raise HTTPException(400, "data must be an object")
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        tpl = session.get(models.Template, tid)
        if not tpl or tpl.user_id != api_key.user.id:
            raise HTTPException(404, "template not found")
        if not tpl.source_bytes or not tpl.source_kind:
            raise HTTPException(400, "this template has no source file — re-upload to enable filling")
        try:
            content, media, _suggested = template_filler.fill_template(
                tpl.source_bytes, tpl.source_kind, data, rows=rows,
            )
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:  # noqa: BLE001
            raise HTTPException(500, f"fill failed: {e}")
        fname = tpl.source_name or f"filled.{tpl.source_kind}"
        # Inject "filled-" prefix so user can distinguish original vs filled
        if "." in fname:
            stem, ext = fname.rsplit(".", 1)
            fname = f"filled-{stem}.{ext}"
        return Response(content=content, media_type=media,
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})
    finally:
        session.close()


@app.post("/dashboard/templates/{tid}/delete")
def delete_template(tid: int, request: Request, csrf_token: str = Form("")):
    _require_csrf(request, csrf_token)
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        t = session.get(models.Template, tid)
        if t and t.user_id == user.id:
            session.delete(t)
            session.commit()
        return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()


# ---------- Webhook ----------
@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request):
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(request, "account.html",
            _ctx(request, msg=None, err=None))
    finally:
        session.close()


@app.post("/account/password")
def account_change_password(request: Request,
                            current_password: str = Form(...),
                            new_password: str = Form(...),
                            confirm_password: str = Form(...),
                            csrf_token: str = Form("")):
    _require_csrf(request, csrf_token)
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        lang = i18n.resolve_lang(request, user)
        EN = lang == "en"
        ctx = _ctx(request, msg=None, err=None)
        if not user.password_hash or not auth.verify_password(current_password, user.password_hash):
            ctx["err"] = ("Current password is incorrect." if EN
                          else "كلمة المرور الحالية غير صحيحة.")
        elif len(new_password) < 8:
            ctx["err"] = ("New password must be at least 8 characters." if EN
                          else "كلمة المرور الجديدة يجب أن تكون 8 أحرف على الأقل.")
        elif new_password != confirm_password:
            ctx["err"] = ("New passwords do not match." if EN
                          else "كلمتا المرور الجديدتان غير متطابقتين.")
        else:
            user.password_hash = auth.hash_password(new_password)
            # Invalidate all OTHER sessions so a stolen cookie loses access on rotation.
            # Keep the current session so the user stays logged in.
            current_sid = request.cookies.get("sid")
            (session.query(models.Session)
                    .filter(models.Session.user_id == user.id,
                            models.Session.token != current_sid)
                    .delete(synchronize_session=False))
            session.commit()
            ctx["msg"] = ("Password updated. All other sessions have been signed out." if EN
                          else "تم تغيير كلمة المرور بنجاح. تم تسجيل خروج كل الجلسات الأخرى.")
        return templates.TemplateResponse(request, "account.html", ctx)
    finally:
        session.close()


@app.post("/account/email")
def account_change_email(request: Request,
                         new_email: str = Form(...),
                         current_password: str = Form(...),
                         csrf_token: str = Form("")):
    _require_csrf(request, csrf_token)
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        lang = i18n.resolve_lang(request, user)
        EN = lang == "en"
        ctx = _ctx(request, msg=None, err=None)
        new_email = new_email.strip().lower()
        if not user.password_hash or not auth.verify_password(current_password, user.password_hash):
            ctx["err"] = "Password is incorrect." if EN else "كلمة المرور غير صحيحة."
        elif "@" not in new_email or "." not in new_email.split("@")[-1]:
            ctx["err"] = "Invalid email format." if EN else "صيغة البريد غير صحيحة."
        elif auth.is_disposable_email(new_email):
            ctx["err"] = ("Disposable email addresses are not allowed." if EN
                          else "لا نقبل عناوين البريد المؤقّتة.")
        elif new_email == user.email:
            ctx["err"] = ("That's already your current email." if EN
                          else "هذا هو بريدك الحالي بالفعل.")
        elif session.query(models.User).filter_by(email=new_email).first():
            ctx["err"] = ("This email is used by another account." if EN
                          else "هذا البريد مستخدم في حساب آخر.")
        else:
            # Update email + require re-verification. Send link to the NEW address.
            user.email = new_email
            user.email_verified = False
            user.verification_token = secrets.token_urlsafe(32)
            session.commit()
            verify_url = str(request.base_url).rstrip("/") + f"/verify/{user.verification_token}"
            try:
                emailer.send_verification_email(new_email, verify_url)
            except Exception:  # noqa: BLE001
                pass
            ctx["msg"] = ((f"Email changed to {new_email}. "
                           "We've sent a verification link to the new address — "
                           "click it to reactivate your account.") if EN else
                          (f"تم تغيير البريد إلى {new_email}. "
                           "أرسلنا رابط تأكيد إلى البريد الجديد — اضغطه لإعادة تفعيل حسابك."))
        return templates.TemplateResponse(request, "account.html", ctx)
    finally:
        session.close()


@app.post("/account/delete")
def account_delete(request: Request, current_password: str = Form(...),
                   confirm: str = Form(""), csrf_token: str = Form("")):
    _require_csrf(request, csrf_token)
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        lang = i18n.resolve_lang(request, user)
        EN = lang == "en"
        if not user.password_hash or not auth.verify_password(current_password, user.password_hash):
            return templates.TemplateResponse(request, "account.html",
                _ctx(request, msg=None,
                     err=("Password is incorrect — your account was not deleted." if EN
                          else "كلمة المرور غير صحيحة — لم نحذف حسابك.")))
        if confirm.strip().upper() != "DELETE":
            return templates.TemplateResponse(request, "account.html",
                _ctx(request, msg=None,
                     err=("Type DELETE (uppercase) in the confirmation box to proceed." if EN
                          else "للتأكيد اكتب الكلمة DELETE (بالأحرف الإنجليزية الكبيرة) في خانة التأكيد.")))
        # Cascade-clean the user's data. WebhookDelivery + Subscription +
        # PaymentEvent get the explicit sweep here so a customer's "delete my
        # account" leaves nothing behind (matches the privacy policy claim).
        user_id = user.id
        # Usage refs api_keys.id, so delete Usage BEFORE api_keys.
        session.query(models.Usage).filter(
            models.Usage.api_key_id.in_(
                session.query(models.ApiKey.id).filter_by(user_id=user_id))).delete(synchronize_session=False)
        session.query(models.ApiKey).filter_by(user_id=user_id).delete()
        session.query(models.Session).filter_by(user_id=user_id).delete()
        session.query(models.Template).filter_by(user_id=user_id).delete()
        session.query(models.History).filter_by(user_id=user_id).delete()
        # New tables added in Wave 5 — must also be swept for GDPR/PDPL.
        session.query(models.WebhookDelivery).filter_by(user_id=user_id).delete()
        session.query(models.PaymentEvent).filter_by(user_id=user_id).delete()
        session.query(models.Subscription).filter_by(user_id=user_id).delete()
        session.delete(user)
        session.commit()
        resp = RedirectResponse("/", status_code=303)
        resp.delete_cookie("sid")
        return resp
    finally:
        session.close()


@app.post("/dashboard/webhook")
def set_webhook(request: Request, webhook_url: str = Form(""), csrf_token: str = Form("")):
    _require_csrf(request, csrf_token)
    url = webhook_url.strip() or None
    # SSRF gate: reject http://, loopback, private CIDRs, instance metadata, etc.
    if url and not auth.is_safe_webhook_url(url):
        raise HTTPException(
            400,
            "رابط الـ Webhook يجب أن يكون HTTPS عاماً (https://...) — العناوين الخاصة أو "
            "localhost أو عناوين IP الداخلية مرفوضة لأسباب أمنية.",
        )
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        user.webhook_url = url
        session.commit()
        return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()


# ---------- Corrections (inline edit from the web app) ----------
@app.post("/v1/extract/correct/{hid}")
def save_correction(hid: int, request: Request, payload: dict = Body(...)):
    """Persist a user's inline correction to History.corrected_json.
    Accepts {field, value}. Web-only (session-authed). Builds up a per-row dict of
    user overrides that can be used for prompt-tuning + future history exports."""
    field = (payload.get("field") or "").strip()
    value = payload.get("value")
    if not field:
        raise HTTPException(400, "field is required")
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            raise HTTPException(401, "login required")
        h = session.get(models.History, hid)
        if not h or h.user_id != user.id:
            raise HTTPException(404, "not found")
        corrections = dict(h.corrected_json or {})
        corrections[field] = value
        h.corrected_json = corrections
        session.commit()
        return {"ok": True, "corrected_count": len(corrections)}
    finally:
        session.close()


# ---------- History ----------
@app.get("/v1/history/{hid}")
def history_item(hid: int, request: Request):
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            raise HTTPException(401, "login required")
        h = session.get(models.History, hid)
        if not h or h.user_id != user.id:
            raise HTTPException(404, "not found")
        return {"kind": h.kind, "document_type": h.document_type, "charged": h.charged,
                "created_at": str(h.created_at), "result": h.result_json,
                "corrected": h.corrected_json, "layout": h.layout,
                "output_lang": h.output_lang}
    finally:
        session.close()


# ---------- Document comparison ----------
@app.get("/compare", response_class=HTMLResponse)
def compare_page(request: Request):
    session = db.SessionLocal()
    try:
        if not _current_user(session, request):
            return RedirectResponse("/login", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "compare.html", _ctx(request))


@app.post("/v1/compare")
def compare_docs(request: Request, file_a: UploadFile = File(...), file_b: UploadFile = File(...),
                 hard: bool = Form(True), x_api_key: str = Header(None)):
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
    if file_a.content_type not in allowed or file_b.content_type not in allowed:
        raise HTTPException(415, "unsupported file type")
    a, b = file_a.file.read(), file_b.file.read()
    if len(a) > 20 * 1024 * 1024 or len(b) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 20 MB)")
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        cost = 2 * auth.credits_for(hard)
        auth.enforce_limit(session, api_key, needed=cost)
        try:
            ta = extractor.run_text(a, file_a.content_type, SERVICES["arabic-ocr"]["prompt"], hard)
            tb = extractor.run_text(b, file_b.content_type, SERVICES["arabic-ocr"]["prompt"], hard)
            report = extractor.compare(ta, tb)
        except Exception as e:  # noqa: BLE001
            raise _http_error_for(e, "compare failed")
        auth.increment_usage(session, api_key, count=cost)
        used, limit, _ = auth.get_usage(session, api_key)
        return {"report": report, "usage": {"used": used, "limit": limit,
                "remaining": max(0, limit - used), "charged": cost}}
    finally:
        session.close()


@app.post("/v1/extract")
def extract_endpoint(  # sync def => FastAPI runs it in a threadpool, so the slow
                       # (synchronous) model call never blocks the event loop.
    request: Request,
    file: UploadFile = File(None),         # backward-compat single-file param
    files: list[UploadFile] = File([]),    # NEW: multi-file. Send the form field as `files` repeated.
    target_schema: str = Form(""),         # optional — empty/omitted means auto-detect
    hard: bool = Form(True),
    output_lang: str = Form("preserve"),   # 'preserve' | 'ar' | 'en'
    x_api_key: str = Header(None),
):
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    if output_lang not in ("preserve", "ar", "en"):
        raise HTTPException(400, "output_lang must be one of: preserve, ar, en")
    # Per-IP burst limit (see /v1/tool note). Defence-in-depth on top of credit quota.
    client_ip = request.client.host if request.client else None
    if not auth.rate_limit_check(f"extract:{client_ip}", max_attempts=30, window_sec=60):
        raise HTTPException(429, "too many requests from this IP, slow down")
    auth.rate_limit_record(f"extract:{client_ip}")

    schema = None
    if target_schema and target_schema.strip() not in ("", "{}"):
        try:
            schema = json.loads(target_schema)
        except json.JSONDecodeError:
            raise HTTPException(400, "target_schema must be valid JSON: {field: description}")

    # Unify the two upload paths. Backward-compat: `file=` single is also accepted.
    upload_list = [u for u in ([file] + list(files or [])) if u is not None and u.filename]
    if not upload_list:
        raise HTTPException(400, "at least one file is required (field 'file' or 'files')")
    if len(upload_list) > 10:
        raise HTTPException(413, "too many files in one batch (max 10)")

    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
    for u in upload_list:
        if u.content_type not in allowed:
            raise HTTPException(415, f"unsupported file type: {u.content_type}. "
                                     "Use PNG, JPG, WEBP, GIF, or PDF.")

    # Read all files into memory + enforce 20MB per file.
    multi_files: list[tuple[bytes, str]] = []
    for u in upload_list:
        b = u.file.read()
        if len(b) > 20 * 1024 * 1024:
            raise HTTPException(413, f"file '{u.filename}' too large (max 20 MB)")
        multi_files.append((b, u.content_type))
    # Primary file for the single-image path (also used for PDF page count).
    image_bytes, image_ct = multi_files[0]
    n_files = len(multi_files)

    n_pages = _count_pdf_pages(image_bytes) if image_ct == "application/pdf" else None
    native_max = int(os.getenv("PDF_NATIVE_MAX_PAGES", "5"))  # ≤ this → one merged call
    hard_max = int(os.getenv("MAX_PDF_PAGES", "100"))         # > this → rejected

    # Auth + free-tier enforcement. No key => the public demo account.
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)

        # Large PDF → background batch job (one call per page; never truncates).
        # Only the single-file path goes through batching today; multi-image
        # uploads are always under the size threshold (1-10 images).
        if n_files == 1 and n_pages and n_pages > native_max:
            if n_pages > hard_max:
                raise HTTPException(413, f"this PDF has {n_pages} pages; the limit is {hard_max}. "
                                         "Split it into smaller files.")
            auth.enforce_limit(session, api_key, needed=n_pages * auth.credits_for(hard))
            job_id = jobs.start_batch(image_bytes, hard, api_key.id, n_pages)
            return {"mode": "batch", "job_id": job_id, "total_pages": n_pages, "status": "processing"}

        # Single image OR multi-image batch → one synchronous call (Gemini handles
        # multiple images in a single request and bills per image).
        cost = auth.credits_for(hard) * n_files
        auth.enforce_limit(session, api_key, needed=cost)
        import time as _time
        _t0 = _time.time()
        layout = None
        try:
            if schema:
                # Schema mode: single image only for now (rare to combine images
                # with a fixed schema). Use the first file.
                data = extractor.extract_schema(image_bytes, image_ct, schema,
                                                hard=hard, output_lang=output_lang)
                document_type, mode = None, "schema"
            elif n_files > 1:
                # Multi-image auto: send all to Gemini at once so it can
                # cross-reference (ID front+back, multi-page receipt, etc.).
                result = extractor.extract_auto_multi(multi_files, hard=hard,
                                                       output_lang=output_lang)
                document_type = result.get("document_type")
                layout = result.get("layout")
                if any(k in result for k in ("patient", "medications", "header",
                                              "line_items", "clauses", "totals", "table")):
                    data = result
                else:
                    data = result.get("fields", result)
                mode = "auto_multi"
            else:
                result = extractor.extract_auto(image_bytes, image_ct, hard=hard,
                                                output_lang=output_lang)
                document_type = result.get("document_type")
                layout = result.get("layout")
                if any(k in result for k in ("patient", "medications", "header",
                                              "line_items", "clauses", "totals", "table")):
                    data = result
                else:
                    data = result.get("fields", result)
                mode = "auto"
        except Exception as e:  # noqa: BLE001 — surface model/parse errors; don't bill failures
            raise _http_error_for(e, "extraction failed")
        _dur_ms = int((_time.time() - _t0) * 1000)

        # Only meter successful extractions.
        auth.increment_usage(session, api_key, count=cost)
        _record_history(session, api_key.user, mode, document_type, data, cost,
                        duration_ms=_dur_ms, layout=layout,
                        output_lang=output_lang if output_lang != "preserve" else None)
        used, limit, _ = auth.get_usage(session, api_key)
        return {
            "mode": mode,
            "document_type": document_type,
            "layout": layout,
            "output_lang": output_lang,
            "files_count": n_files,
            "data": data,
            "usage": {"used": used, "limit": limit, "remaining": max(0, limit - used), "charged": cost},
        }
    finally:
        session.close()


# ============================================================================
# Billing (Paymob)
# ============================================================================
#
# Flow:
#   1. User on /#pricing clicks "Subscribe Pro" → POST /billing/checkout?plan=pro
#   2. We mint a `merchant_order_id` encoding (user_id, plan, nonce),
#      call Paymob's 3-step API and redirect the user to the iframe.
#   3. Paymob HMAC-signs the callback to /billing/paymob/callback (Sitting 2).
#   4. After webhook confirms, user lands on /billing/success.
#
# The merchant_order_id IS the channel for user→payment mapping — Paymob echoes
# it back on the webhook and we decode it to know which user to upgrade.

from datetime import datetime, timedelta  # noqa: E402

from app.services import paymob as _paymob, plans  # noqa: E402
from app.services.plans import PAID_PLANS, get_plan  # noqa: E402


def _mint_merchant_order_id(user_id: int, plan_slug: str) -> str:
    """Format: mst_v1_{user_id}_{plan}_{nonce}. Self-contained so the webhook
    can map a Paymob callback back to a user without a pre-checkout DB write."""
    return f"mst_v1_{user_id}_{plan_slug}_{secrets.token_hex(6)}"


def _parse_merchant_order_id(mid: str) -> tuple[int, str] | None:
    """Reverse _mint_merchant_order_id. Returns (user_id, plan_slug) or None
    if the format doesn't match (e.g. Paymob-test traffic)."""
    parts = (mid or "").split("_")
    if len(parts) < 5 or parts[0] != "mst" or parts[1] != "v1":
        return None
    try:
        return int(parts[2]), parts[3]
    except (ValueError, IndexError):
        return None


@app.post("/billing/checkout")
def billing_checkout(request: Request, plan: str = Form(...), csrf_token: str = Form("")):
    """Mint a Paymob checkout for the requested plan. Auth'd users only."""
    _require_csrf(request, csrf_token)
    plan_cfg = get_plan(plan)
    if not plan_cfg:
        raise HTTPException(status_code=400, detail=f"unknown plan: {plan}")
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login?next=/%23pricing", status_code=303)
        amount_egp = round(plan_cfg.usd * settings.EGP_PER_USD, 2)
        mid = _mint_merchant_order_id(user.id, plan_cfg.slug)
        billing = {
            "first_name": (user.email.split("@")[0] or "Customer")[:50],
            "last_name": "Mostakhles",
            "email": user.email,
            "phone_number": "+201000000000",  # Paymob requires non-empty
            "country": "EG", "city": "Cairo", "street": "NA",
            "building": "NA", "floor": "NA", "apartment": "NA",
        }
        try:
            iframe, _order_id = _paymob.begin_checkout(amount_egp, mid, billing)
        except _paymob.PaymobError as exc:
            log.error("paymob checkout failed: %s", exc)
            raise HTTPException(status_code=502, detail=f"payment provider error: {exc}")
        return RedirectResponse(iframe, status_code=303)
    finally:
        session.close()


@app.get("/billing/success", response_class=HTMLResponse)
def billing_success(request: Request):
    """Generic landing after Paymob redirect. The plan upgrade itself happens
    in the webhook (Sitting 2) — this page just confirms to the user."""
    return templates.TemplateResponse(request, "billing_success.html", _ctx(request))


@app.post("/billing/paymob/callback")
async def paymob_callback(request: Request, hmac_sig: str = Query("", alias="hmac")):
    """Paymob → Mostakhles webhook. Verifies HMAC, decodes merchant_order_id
    back to (user, plan), idempotently writes the PaymentEvent + Subscription,
    and flips user.plan so the next request sees the new quota.

    Returns 200 on every legitimate Paymob hit (success OR failure) so the
    provider doesn't retry — we already recorded what happened. Only HMAC
    mismatches return 403."""
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")
    obj = body.get("obj") or {}
    if not _paymob.verify_hmac(obj, hmac_sig):
        log.warning("paymob callback rejected: HMAC mismatch (txn=%s)", obj.get("id"))
        raise HTTPException(status_code=403, detail="invalid signature")

    txn_id = str(obj.get("id") or "")
    success = bool(obj.get("success"))
    mid = (obj.get("order") or {}).get("merchant_order_id", "")
    decoded = _parse_merchant_order_id(mid)
    log.info("paymob callback OK: txn=%s success=%s mid=%s decoded=%s",
             txn_id, success, mid, decoded)

    if not txn_id:
        return {"received": True, "ignored": "missing txn id"}

    session = db.SessionLocal()
    try:
        # Idempotency: short-circuit if we've already processed this Paymob txn.
        # The UNIQUE(provider, external_id) on PaymentEvent is the durable
        # backstop — this check just avoids the extra work + an IntegrityError.
        existing = (session.query(models.PaymentEvent)
                    .filter_by(provider="paymob", external_id=txn_id).first())
        if existing:
            log.info("paymob callback: txn=%s already processed (event id=%s), skipping",
                     txn_id, existing.id)
            return {"received": True, "duplicate": True}

        amount_cents = int(obj.get("amount_cents") or 0)
        amount_usd = round(amount_cents / 100 / settings.EGP_PER_USD, 2) if amount_cents else None

        user = None
        plan_slug = None
        subscription_id = None

        if decoded and success:
            user_id, plan_slug = decoded
            user = session.query(models.User).filter_by(id=user_id).first()
            plan_cfg = plans.get_plan(plan_slug)
            if user and plan_cfg:
                # Close any active subscription on this user before opening a new one.
                # Two active subs would let the dashboard / quota logic disagree on
                # which plan is current.
                now = datetime.utcnow()
                (session.query(models.Subscription)
                        .filter_by(user_id=user.id, status="active")
                        .update({"status": "cancelled", "cancelled_at": now,
                                 "updated_at": now}, synchronize_session=False))
                sub = models.Subscription(
                    user_id=user.id,
                    provider="paymob",
                    external_id=txn_id,
                    plan=plan_slug,
                    status="active",
                    current_period_end=now + timedelta(days=30),
                    amount_usd=amount_usd,
                )
                session.add(sub)
                session.flush()  # need sub.id for the PaymentEvent FK
                subscription_id = sub.id
                user.plan = plan_slug
                log.info("paymob upgrade: user=%s plan=%s sub=%s amount_usd=%s",
                         user.id, plan_slug, sub.id, amount_usd)
            else:
                log.warning("paymob upgrade skipped: user=%s plan=%s (user_exists=%s, plan_known=%s)",
                            user_id, plan_slug, bool(user), bool(plan_cfg))

        event_type = "paymob.transaction.success" if success else "paymob.transaction.failed"
        evt = models.PaymentEvent(
            provider="paymob",
            external_id=txn_id,
            event_type=event_type,
            subscription_id=subscription_id,
            user_id=user.id if user else None,
            amount_usd=amount_usd,
            raw_payload=raw.decode("utf-8", errors="replace")[:65535],
            processed_at=datetime.utcnow(),
        )
        session.add(evt)
        session.commit()
        return {"received": True, "txn": txn_id, "upgraded": bool(subscription_id)}
    except Exception:
        session.rollback()
        log.exception("paymob callback failed: txn=%s", txn_id)
        raise
    finally:
        session.close()
