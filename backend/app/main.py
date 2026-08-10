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
from app.services import envelope, extractor, llm, template_filler, template_parser  # noqa: E402
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


# ---- Security headers — every response gets these so we ship to prod safely ----
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add browser-side security headers to every response.
    - X-Content-Type-Options:nosniff stops MIME-sniffing attacks.
    - X-Frame-Options:DENY blocks clickjacking via iframe embed.
    - Referrer-Policy:strict-origin-when-cross-origin keeps full URLs off external links.
    - Permissions-Policy turns off browser APIs we don't use.
    - HSTS is sent only when ENV=prod (locally HTTP is fine).
    - CSP uses a per-request nonce: every <script> in our templates carries
      nonce="{{ csp_nonce }}" so the strict 'self' 'nonce-...' rule lets them
      run while blocking any injected inline script.
    """
    async def dispatch(self, request: Request, call_next):
        # Per-request nonce — Jinja templates read it from request.state via _ctx().
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), interest-cohort=()",
        )
        # CSP — only emit for HTML responses (skip JSON/API responses to avoid
        # accidentally blocking things in test pages, and to keep header sizes down).
        ct = resp.headers.get("content-type", "")
        if "text/html" in ct.lower():
            resp.headers.setdefault(
                "Content-Security-Policy",
                # script-src: only inline scripts carrying our nonce + same-origin
                # files run. 'strict-dynamic' lets nonce-carrying scripts load
                # further scripts (we use this for lucide / theme bootstrap).
                f"default-src 'self'; "
                # lucide + fonts are now self-hosted, so no external script/style/font
                # origins are needed — CSP is same-origin only (was unpkg / Google Fonts).
                f"script-src 'self' 'nonce-{nonce}' 'strict-dynamic'; "
                # style-src: inline style="..." is everywhere in our templates, so
                # we keep 'unsafe-inline' for now. Tightening would require a major
                # rewrite of inline styles into classes.
                f"style-src 'self' 'unsafe-inline'; "
                f"img-src 'self' data: blob: https:; "
                f"font-src 'self' data:; "
                f"connect-src 'self'; "
                f"frame-ancestors 'none'; "
                f"base-uri 'self'; "
                f"form-action 'self' https://accept.paymob.com; "
                f"object-src 'none'; "
                f"upgrade-insecure-requests",
            )
        if os.getenv("ENV") == "prod":
            resp.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return resp


app.add_middleware(SecurityHeadersMiddleware)
app_exceptions.register_handlers(app)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _asset_version() -> str:
    """Cache-buster for the main stylesheet. Returns the int mtime of style.css
    so `<link ...?v={{ asset_v }}>` changes whenever the CSS is edited, forcing
    browsers to re-fetch on a normal refresh (no hard-reload needed).
    In local/dev this is read each request so edits show immediately; in prod
    the file is stable so it's effectively a content hash."""
    try:
        return str(int(os.path.getmtime(BASE_DIR / "static" / "css" / "style.css")))
    except OSError:
        return "1"


# Expose to every template as {{ asset_v }} (read live in dev so edits bust the
# cache; cheap enough — one stat() per render).
templates.env.globals["asset_v"] = _asset_version

# Local Paymob mock — only mounted in ENV=local so /billing/checkout works
# without real merchant credentials. Set PAYMOB_BASE_URL=http://localhost:8000/_mock/paymob
# (or similar) and the Paymob client treats it as the real API.
if _env == "local":
    from app.services.paymob_mock import router as _paymob_mock_router  # noqa: E402
    from app.services.paypal_mock import router as _paypal_mock_router  # noqa: E402
    app.include_router(_paymob_mock_router)
    app.include_router(_paypal_mock_router)


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


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    """Browsers always request /favicon.ico — serve our SVG so it doesn't 404 forever.
    Also exposed at /static/favicon.svg via the StaticFiles mount."""
    return RedirectResponse(url="/static/favicon.svg", status_code=301)


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    # The hero demo posts to /v1/demo-extract which resolves the demo key
    # server-side — we don't expose any API key in the HTML source.
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
                 hard: bool = Form(True), routing: str = Form("explicit"),
                 x_api_key: str = Header(None)):
    """OCR a document to text so the user can then chat with it."""
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    if routing not in ("explicit", "auto", "fast", "hard"):
        raise HTTPException(400, "routing must be one of: explicit, auto, fast, hard")
    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(415, "unsupported file type")
    data_bytes = file.file.read()
    if len(data_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 20 MB)")
    if routing != "explicit":
        hard = extractor._resolve_hard(routing, hard, data_bytes, file.content_type)
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

_TERMS_HTML_AR = """
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

_TERMS_HTML_EN = """
<h2>The service</h2>
<p>Mostakhles provides AI-powered tools to extract and understand document data via the web, API, and Odoo.</p>
<h2>Your account</h2>
<p>You are responsible for keeping your login credentials and API keys confidential.</p>
<h2>Acceptable use</h2>
<p>You agree not to upload illegal content or content you do not have the right to process, and not to misuse or attempt to disrupt the service.</p>
<h2>Credits and billing</h2>
<p>Each operation is charged in credits according to the mode you choose (fast / accurate), and the cost is shown to you before execution. Subscriptions are monthly and you can cancel at any time — consumed credits are non-refundable.</p>
<h2>Disclaimer</h2>
<p>Extraction is powered by AI and may not be 100% accurate, especially for handwritten documents. Please review important results before acting on them.</p>
<h2>Changes</h2>
<p>We may update these terms and will publish any changes on this page. Contact: support@mostakhles.ai</p>
"""

# ── Cookie Policy — grounded in the cookies/storage the app actually sets ─────
_COOKIES_HTML_AR = """
<h2>ما هي ملفات تعريف الارتباط؟</h2>
<p>ملفات تعريف الارتباط ملفات نصية صغيرة يخزّنها الموقع في متصفّحك. و«التخزين المحلي» ميزة مشابهة تحفظ إعدادات صغيرة على جهازك. نستخدم كليهما فقط كما هو موضّح هنا.</p>
<h2>ما نستخدمه</h2>
<p>نستخدم حاليًا فقط ملفات تعريف الارتباط والتخزين الضرورية والوظيفية. لا نستخدم ملفات إعلانية، ولا نشغّل أدوات تتبّع تسويقية أو تحليلات سلوكية من أطراف ثالثة.</p>
<ul>
<li><b>ملف الجلسة</b> (ضروري) — يبقيك مسجّلاً للدخول. حتى ~30 يومًا أو حتى تسجيل الخروج.</li>
<li><b>رمز CSRF</b> (ضروري) — يحمي من تزوير الطلبات عبر المواقع. للجلسة.</li>
<li><b>تفضيل اللغة</b> (وظيفي) — يتذكّر اختيارك بين العربية والإنجليزية. ~سنة.</li>
<li><b>تفضيل السمة</b> (وظيفي، تخزين محلي) — يتذكّر الوضع الفاتح/الداكن. حتى تمسحه.</li>
<li><b>Cloudflare Turnstile</b> (ضروري، أمان) — حماية من الروبوتات في النماذج. قصير الأمد.</li>
</ul>
<h2>طلبات الأطراف الثالثة</h2>
<p>تحمّل بعض الصفحات موارد من أطراف ثالثة، مما قد يتيح لذلك الطرف تلقّي عنوان IP وبيانات الطلب الأساسية:</p>
<ul>
<li><b>Cloudflare Turnstile</b> — حماية النماذج من الروبوتات؛ يعالج عنوان IP وإشارات المتصفّح.</li>
<li><b>خطوط Google</b> — تحمّل بعض الصفحات الخطوط من خدمة خطوط Google، فيطلب متصفّحك جلبها من Google.</li>
<li><b>Sentry</b> — خدمة مراقبة الأخطاء لدينا؛ تلتقط التشخيصات التقنية عند حدوث خلل. وهي ليست أداة إعلان أو تتبّع.</li>
</ul>
<h2>ما لا نستخدمه</h2>
<p>لا ملفات تعريف ارتباط إعلانية أو لإعادة الاستهداف. لا تتبّع سلوكي عبر المواقع. لا بيع لأي بيانات تُجمَع عبر ملفات تعريف الارتباط.</p>
<h2>إدارة ملفات تعريف الارتباط</h2>
<p>لأننا نستخدم حاليًا فقط ملفات ضرورية ووظيفية، لا يلزم شريط موافقة إلزامي — لكن يمكنك حظر أو حذف ملفات تعريف الارتباط من متصفّحك (قد يعطّل ذلك تسجيل الدخول والنماذج)، وتبديل اللغة أو السمة في أي وقت. وإذا أضفنا لاحقًا ملفات تحليلات أو تسويق، فسنضيف آلية موافقة ونحدّث هذه الصفحة قبل تشغيلها.</p>
<h2>التواصل</h2>
<p>أسئلة حول ملفات تعريف الارتباط: <a href="mailto:privacy@mostakhles.ai" class="lp-link">privacy@mostakhles.ai</a> أو <a href="/contact" class="lp-link">نموذج التواصل</a>.</p>
"""

_COOKIES_HTML_EN = """
<h2>What are cookies?</h2>
<p>Cookies are small text files a website stores in your browser. "Local storage" is a related feature that keeps small settings on your device. We use both only as described here.</p>
<h2>What we use</h2>
<p>We currently use only strictly necessary and functional cookies and storage. We do not use advertising cookies, and we do not run third-party marketing or behavioural-analytics trackers.</p>
<ul>
<li><b>Session cookie</b> (strictly necessary) — keeps you logged in. Up to ~30 days or until logout.</li>
<li><b>CSRF token</b> (strictly necessary) — protects against cross-site request forgery. Session.</li>
<li><b>Language preference</b> (functional) — remembers your Arabic/English choice. ~1 year.</li>
<li><b>Theme preference</b> (functional, browser local storage) — remembers light/dark mode. Until you clear it.</li>
<li><b>Cloudflare Turnstile</b> (strictly necessary, security) — bot and abuse protection on forms. Short-lived.</li>
</ul>
<h2>Third-party requests</h2>
<p>Some pages load resources from third parties, which may let that third party receive your IP address and basic request data:</p>
<ul>
<li><b>Cloudflare Turnstile</b> — bot protection on forms; processes IP and browser signals.</li>
<li><b>Google Fonts</b> — some pages load fonts from Google's font service, so your browser makes a request to Google to fetch fonts.</li>
<li><b>Sentry</b> — our error-monitoring service; captures technical diagnostics if something breaks. It is not an advertising or tracking tool.</li>
</ul>
<h2>What we do not use</h2>
<p>No advertising or retargeting cookies. No cross-site behavioural tracking. No selling of any data collected via cookies.</p>
<h2>Managing cookies</h2>
<p>Because we currently use only strictly-necessary and functional cookies and storage, no consent banner is strictly required — but you can still block or delete cookies in your browser (this may break login and forms), and switch language or theme back at any time. If we later add analytics or marketing cookies, we will add a consent mechanism and update this page before those cookies run.</p>
<h2>Contact</h2>
<p>Questions about cookies: <a href="mailto:privacy@mostakhles.ai" class="lp-link">privacy@mostakhles.ai</a> or the <a href="/contact" class="lp-link">contact form</a>.</p>
"""

# ── Data Processing Addendum (draft) — controller↔processor, code-grounded ────
_DPA_DRAFT_BANNER = (
    'border:1px solid #e6c073;background:rgba(240,198,116,.12);'
    'border-radius:8px;padding:12px 16px;margin-bottom:20px'
)
_DPA_HTML_AR = f"""
<div style="{_DPA_DRAFT_BANNER}"><b>مسودّة — الإصدار 1.0.</b> هذا الملحق مُقدَّم للمراجعة، ويُعتمَد ويُوقَّع عند الطلب بعد اكتمال تسجيل الشركة. للحصول على نسخة موقّعة، تواصل عبر <a href="mailto:privacy@mostakhles.ai" class="lp-link">privacy@mostakhles.ai</a>.</div>
<h2>الأطراف والأدوار</h2>
<p>يشكّل هذا الملحق جزءًا من الاتفاق بين العميل (بصفته «المتحكّم» في البيانات) ومُستخلِص (المُشغَّل بواسطة <strong>[بانتظار التأكيد: الكيان القانوني]</strong>، بصفته «المعالج»)، فيما يخصّ استخدام العميل لخدمة مُستخلِص. وعند تعارضه مع شروط الاستخدام في مسائل حماية البيانات، تكون الغلبة لهذا الملحق. العميل هو المتحكّم في البيانات الشخصية الواردة في المستندات التي يرسلها؛ ومُستخلِص هو المعالج الذي يعالجها فقط لتقديم الخدمة ووفق تعليمات العميل الموثّقة.</p>
<h2>التزاماتنا كمعالج</h2>
<ul>
<li>معالجة البيانات فقط وفق تعليمات العميل الموثّقة، ما لم يقتضِ القانون خلاف ذلك.</li>
<li>إلزام الموظفين المخوّلين بالسرّية.</li>
<li>تطبيق تدابير أمنية تقنية وتنظيمية مناسبة (الملحق II).</li>
<li>عدم استخدام البيانات لتدريب أي نموذج، وعدم بيعها أو مشاركتها إلا عبر المعالجين الفرعيين في الملحق III.</li>
<li>المساعدة في طلبات أصحاب البيانات، والإخطار بالانتهاكات، وتقييمات الأثر.</li>
<li>حذف البيانات أو إعادتها عند الإنهاء، إلا حيث يقتضي القانون الاحتفاظ بها.</li>
</ul>
<h2>المعالجون الفرعيون</h2>
<p>يمنح العميل تفويضًا عامًا لمُستخلِص للاستعانة بالمعالجين الفرعيين في الملحق III، بحماية لا تقلّ عن هذا الملحق. ونُشعِر العميل قبل إضافة أو استبدال أي معالج فرعي يعالج بياناته الشخصية، مع مهلة معقولة للاعتراض.</p>
<h2>النقل الدولي للبيانات</h2>
<p>تنقل الخدمة محتوى المستندات إلى معالجنا الفرعي للذكاء الاصطناعي (Google Gemini)، وقد تشمل مزوّدي استضافة وبريد ودفع يعالجون البيانات خارج بلد العميل. نعتمد على ضمانات هؤلاء المزوّدين ونتعامل مع النقل بما يتماشى مع مبادئ قوانين حماية البيانات المعمول بها. والعميل، بصفته المتحكّم، مسؤول عن التأكّد من ملاءمة عمليات النقل لوضعه.</p>
<h2>التصحيحات عبر موصّل أودو</h2>
<p>يتضمّن موصّل أودو ميزة (يمكن إيقافها، ومُفعَّلة افتراضيًا) ترسل التصحيحات على مستوى الحقل (اسم الحقل، القيمة الأصلية، القيمة المصحَّحة، معرّف الاستخراج) إلى مُستخلِص لتحسين الاستخراج. وحيث قد تتضمّن التصحيحات بيانات شخصية، يقرّر العميل إبقاءها مفعّلة (أودو ← الإعدادات ← مُستخلِص ← «مشاركة التصحيحات»). وعند إيقافها، لا يُرسَل شيء.</p>
<h2>طلبات أصحاب البيانات والانتهاكات</h2>
<p>نقدّم مساعدة معقولة لطلبات أصحاب البيانات ونحيل أي طلب نتلقّاه مباشرةً إلى العميل. ونُخطِر العميل دون تأخير غير مبرَّر بعد علمنا بأي انتهاك يخصّ بيانات العميل. إخطارات الانتهاك إلى: <a href="mailto:privacy@mostakhles.ai" class="lp-link">privacy@mostakhles.ai</a>.</p>
<h2>الحذف والإعادة والتدقيق</h2>
<p>عند الإنهاء، نحذف بيانات العميل الشخصية أو نعيدها (باستثناء السجلات التي يُلزم القانون بحفظها). ولأن الملفات الأصلية لا تُخزَّن افتراضيًا، تتكوّن هذه البيانات أساسًا من النتائج المُستخرَجة والقوالب المحفوظة والتصحيحات المشتركة؛ وحذف الحساب يزيلها. وندعم عمليات التدقيق بإشعار مسبق معقول، بما لا يزيد عن مرة سنويًا ما لم تقتضِ جهة رقابية خلاف ذلك.</p>
<h2>المسؤولية والقانون الحاكم</h2>
<p>تخضع مسؤولية كل طرف بموجب هذا الملحق للحدود الواردة في شروط الاستخدام. ويخضع هذا الملحق للقانون المذكور في الشروط (<strong>[بانتظار التأكيد: القانون الحاكم]</strong>).</p>
<h2>الملحق I — تفاصيل المعالجة</h2>
<p><b>الموضوع:</b> خدمات استخراج بيانات المستندات بالذكاء الاصطناعي. <b>المدة:</b> مدة استخدام العميل للخدمة. <b>الطبيعة والغرض:</b> استقبال المستندات، واستخراج البيانات المنظَّمة عبر معالج فرعي للذكاء الاصطناعي، وإرجاع النتائج، وتخزين النتائج والقوالب والتصحيحات في حساب العميل. <b>البيانات الشخصية</b> (حسب مستندات العميل) قد تشمل الأسماء وأرقام الهوية أو جواز السفر والعناوين وبيانات التواصل وبيانات البنك/الآيبان وأرقام الضرائب والسجل التجاري ومعلومات صحية مثل الوصفات الطبية. <b>أصحاب البيانات</b> حسب تحديد العميل. وقد توجد بيانات من فئات خاصة؛ والعميل مسؤول عن ضمان أساس قانوني لمعالجتها.</p>
<h2>الملحق II — التدابير الأمنية</h2>
<p>المطبَّق اليوم (موصوف بصدق، وليس شهادة): تشفير TLS 1.3 أثناء النقل؛ عدم تخزين المستندات الأصلية بعد المعالجة افتراضيًا؛ كلمات مرور مُجزَّأة ومملّحة؛ مفاتيح API محدّدة النطاق وقابلة للإلغاء؛ وصول مقصور على ما يلزم لتشغيل الخدمة ودعمها؛ مراقبة الأخطاء وسجلات تُدوَّر دوريًا؛ حماية من الروبوتات في النماذج. غير المطبَّق: شهادة SOC 2 أو ISO 27001، أو ضمانات تعاقدية لموقع البيانات، أو بنية تحتية مخصّصة، أو التزام تعاقدي بمدة التشغيل.</p>
<h2>الملحق III — المعالجون الفرعيون المعتمَدون</h2>
<ul>
<li><b>Google (Gemini API)</b> — استدلال الذكاء الاصطناعي على محتوى المستندات.</li>
<li><b>Paymob</b> — معالجة المدفوعات (مصر / الجنيه).</li>
<li><b>PayPal</b> — معالجة المدفوعات (دوليًا).</li>
<li><b>مزوّد الاستضافة لدينا</b> — تشغيل الخدمة وتخزين بيانات الحساب.</li>
<li><b>مزوّد البريد لدينا</b> — رسائل الحساب والفوترة.</li>
<li><b>Sentry</b> — مراقبة الأخطاء والتشخيصات التقنية.</li>
<li><b>Cloudflare (Turnstile)</b> — حماية النماذج من الروبوتات.</li>
</ul>
<p>يُخطَّط لإضافة PayTabs كمعالج فرعي إضافي للمدفوعات؛ وسيُحدَّث هذا الملحق قبل تفعيله.</p>
"""

_DPA_HTML_EN = f"""
<div style="{_DPA_DRAFT_BANNER}"><b>Draft — version 1.0.</b> This Data Processing Addendum is provided for review. It is finalised and signed on request once company registration completes. To execute a signed copy, contact <a href="mailto:privacy@mostakhles.ai" class="lp-link">privacy@mostakhles.ai</a>.</div>
<h2>Parties and roles</h2>
<p>This DPA forms part of the agreement between the customer (the "Customer", acting as data controller) and Mostakhles (operated by <strong>[to be confirmed: legal entity]</strong>, acting as data processor), for the Customer's use of the Mostakhles service. Where it conflicts with the Terms of Service on data-protection matters, this DPA prevails. The Customer is the controller of personal data contained in the documents it submits; Mostakhles is the processor and processes that data only to provide the service and on the Customer's documented instructions.</p>
<h2>Our obligations as processor</h2>
<ul>
<li>Process personal data only on the Customer's documented instructions, unless required by law.</li>
<li>Bind authorised staff to confidentiality.</li>
<li>Apply appropriate technical and organisational security measures (Annex II).</li>
<li>Never use the data to train any AI model, and not sell or share it except via the sub-processors in Annex III.</li>
<li>Assist with data-subject requests, breach notification, and impact assessments.</li>
<li>Delete or return the data on termination, except where retention is required by law.</li>
</ul>
<h2>Sub-processors</h2>
<p>The Customer gives general authorisation for Mostakhles to engage the sub-processors in Annex III, under protections no less strict than this DPA. We give notice before adding or replacing any sub-processor that processes Customer personal data, allowing a reasonable period to object.</p>
<h2>International transfers</h2>
<p>The service transmits document content to our AI sub-processor (Google Gemini) and may involve hosting, email, and payment providers that process data outside the Customer's country. We rely on those providers' safeguards and handle transfers in line with the principles of the applicable data-protection laws. The Customer, as controller, is responsible for confirming these transfers suit its own compliance posture.</p>
<h2>Corrections via the Odoo connector</h2>
<p>The Odoo connector includes an opt-out feature (on by default) that sends field-level corrections (field name, original value, corrected value, extraction id) back to Mostakhles to improve extraction. Where corrections may contain personal data, the Customer decides whether to leave it on (Odoo → Settings → Mostakhles → "Share corrections"). When disabled, nothing is sent.</p>
<h2>Data-subject requests and breaches</h2>
<p>We provide reasonable assistance for data-subject requests and forward any we receive directly to the Customer. We notify the Customer without undue delay after becoming aware of a personal data breach affecting Customer personal data. Breach notices to: <a href="mailto:privacy@mostakhles.ai" class="lp-link">privacy@mostakhles.ai</a>.</p>
<h2>Deletion, return and audit</h2>
<p>On termination, we delete or return Customer personal data (except records legally required to be kept). Because source files are not stored by default, this data is mainly extraction results, saved templates, and shared corrections; deleting the account removes these. We support audits on reasonable prior notice, no more than once a year unless a supervisory authority requires otherwise.</p>
<h2>Liability and governing law</h2>
<p>Each party's liability under this DPA is subject to the limitations in the Terms of Service. This DPA is governed by the law stated in the Terms (<strong>[to be confirmed: governing law]</strong>).</p>
<h2>Annex I — Details of processing</h2>
<p><b>Subject matter:</b> AI document-extraction services. <b>Duration:</b> the term of the Customer's use. <b>Nature and purpose:</b> receiving documents, extracting structured data via an AI sub-processor, returning results, and storing results, templates, and corrections in the Customer's account. <b>Personal data</b> (as determined by the Customer's documents) may include names, national ID or passport numbers, addresses, contact details, bank/IBAN details, tax and commercial-registration numbers, and health information such as prescriptions. <b>Data subjects</b> are as determined by the Customer — its customers, employees, patients, suppliers, and counterparties. Special-category data may be present; the Customer is responsible for ensuring a lawful basis.</p>
<h2>Annex II — Security measures</h2>
<p>In place today (described honestly, not a certification): TLS 1.3 in transit; source documents not stored after processing by default; salted-hash passwords; scoped, revocable API keys; access limited to what is needed to run and support the service; error monitoring and rotated logs; bot and abuse protection on forms. Not in place: SOC 2 or ISO 27001 certification, contractual data-residency guarantees, dedicated single-tenant infrastructure, or a formal uptime SLA.</p>
<h2>Annex III — Approved sub-processors</h2>
<ul>
<li><b>Google (Gemini API)</b> — AI inference on document content.</li>
<li><b>Paymob</b> — payment processing (Egypt / EGP).</li>
<li><b>PayPal</b> — payment processing (international).</li>
<li><b>Our hosting provider</b> — running the service and storing account data.</li>
<li><b>Our email provider</b> — account and billing emails.</li>
<li><b>Sentry</b> — error monitoring and technical diagnostics.</li>
<li><b>Cloudflare (Turnstile)</b> — bot protection on forms.</li>
</ul>
<p>PayTabs is planned as an additional payment sub-processor; this annex will be updated before it goes live.</p>
"""


@app.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse(request, "privacy.html", _ctx(request))


@app.get("/terms", response_class=HTMLResponse)
def terms_page(request: Request):
    lang = i18n.resolve_lang(request, None)
    title = "Terms of service" if lang == "en" else "شروط الاستخدام"
    body = _TERMS_HTML_EN if lang == "en" else _TERMS_HTML_AR
    return templates.TemplateResponse(request, "legal.html",
                                      _ctx(request, title=title, body=body))


@app.get("/cookies", response_class=HTMLResponse)
def cookies_page(request: Request):
    lang = i18n.resolve_lang(request, None)
    title = "Cookie Policy" if lang == "en" else "سياسة ملفات تعريف الارتباط"
    body = _COOKIES_HTML_EN if lang == "en" else _COOKIES_HTML_AR
    updated = "July 2026" if lang == "en" else "يوليو 2026"
    return templates.TemplateResponse(request, "legal.html",
                                      _ctx(request, title=title, body=body, updated=updated))


@app.get("/dpa", response_class=HTMLResponse)
def dpa_page(request: Request):
    lang = i18n.resolve_lang(request, None)
    title = "Data Processing Addendum" if lang == "en" else "ملحق معالجة البيانات"
    body = _DPA_HTML_EN if lang == "en" else _DPA_HTML_AR
    updated = "Draft v1.0" if lang == "en" else "مسودّة 1.0"
    return templates.TemplateResponse(request, "legal.html",
                                      _ctx(request, title=title, body=body, updated=updated))


@app.get("/about", response_class=HTMLResponse)
def about_page(request: Request):
    return templates.TemplateResponse(request, "about.html", _ctx(request))


@app.get("/pricing", response_class=HTMLResponse)
def pricing_page(request: Request):
    return templates.TemplateResponse(request, "pricing.html", _ctx(request))


# ── SEO sub-landing pages — one Jinja template driven by app/seo_pages.py ─────
# Routes are registered explicitly (not via /{slug}) so they don't shadow other
# top-level paths like /contact, /login, /dashboard. SEO needs short URLs and
# we'd rather list the 6 we serve than catch-all the world.
from app import seo_pages as _seo_pages  # noqa: E402


def _seo_response(slug: str, request: Request):
    page = _seo_pages.get(slug)
    if not page:
        raise HTTPException(404, "not found")
    return templates.TemplateResponse(request, "seo_landing.html", _ctx(request, page=page))


@app.get("/arabic-prescription-ocr", response_class=HTMLResponse)
def seo_prescription(request: Request): return _seo_response("arabic-prescription-ocr", request)

@app.get("/arabic-invoice-extraction", response_class=HTMLResponse)
def seo_invoice(request: Request): return _seo_response("arabic-invoice-extraction", request)

@app.get("/arabic-id-card-ocr", response_class=HTMLResponse)
def seo_id_card(request: Request): return _seo_response("arabic-id-card-ocr", request)

@app.get("/arabic-handwriting-ocr", response_class=HTMLResponse)
def seo_handwriting(request: Request): return _seo_response("arabic-handwriting-ocr", request)

@app.get("/arabic-contract-extraction", response_class=HTMLResponse)
def seo_contract(request: Request): return _seo_response("arabic-contract-extraction", request)

@app.get("/arabic-bank-statement-ocr", response_class=HTMLResponse)
def seo_bank_statement(request: Request): return _seo_response("arabic-bank-statement-ocr", request)


@app.get("/sitemap.xml")
def sitemap_xml(request: Request):
    """Sitemap of every indexable public URL — landing + SEO sub-landings."""
    base = f"{request.url.scheme}://{request.url.netloc}"
    urls = ["/", "/pricing", "/about", "/contact", "/privacy", "/terms", "/cookies", "/dpa", "/docs", "/tools"]
    urls += [f"/{p.slug}" for p in _seo_pages.all_pages()]
    items = "".join(
        f"<url><loc>{base}{u}</loc>"
        f"<xhtml:link rel='alternate' hreflang='ar' href='{base}{u}?lang=ar'/>"
        f"<xhtml:link rel='alternate' hreflang='en' href='{base}{u}?lang=en'/>"
        f"<changefreq>weekly</changefreq></url>"
        for u in urls
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
        f"{items}</urlset>"
    )
    return Response(content=body, media_type="application/xml")


@app.get("/robots.txt")
def robots_txt(request: Request):
    base = f"{request.url.scheme}://{request.url.netloc}"
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /dashboard\n"
        "Disallow: /account\n"
        "Disallow: /v1/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(content=body, media_type="text/plain")


@app.get("/contact", response_class=HTMLResponse)
def contact_page(request: Request):
    return templates.TemplateResponse(request, "contact.html", _ctx(request))


@app.post("/contact")
def contact_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    company: str = Form(""),
    topic: str = Form("other"),
    message: str = Form(...),
):
    """Receive the contact-form submission, email it to admins, and re-render
    the form with a friendly thanks message. Spam guard: cap body lengths,
    reject obvious empty/bot submissions (zero-length message, no @ in email).
    No DB write — keep it lightweight; if you want history, log it."""
    lang = i18n.resolve_lang(request, None)
    en = lang == "en"

    # Cheap validation — let the heavy lifting happen at the email step
    name = (name or "").strip()[:200]
    email = (email or "").strip()[:200]
    company = (company or "").strip()[:200]
    topic = (topic or "other").strip()[:50]
    message = (message or "").strip()[:5000]
    if not name or "@" not in email or len(message) < 3:
        err = "Please fill in all required fields." if en else "يرجى تعبئة الحقول المطلوبة."
        return templates.TemplateResponse(request, "contact.html", _ctx(request, err=err))

    # Forward to admin inbox — failures degrade gracefully (we still show success
    # to the user) so a temporary SMTP outage doesn't break the funnel. Real
    # error visibility comes from Sentry.
    admins = list(auth.ADMIN_EMAILS) or ["support@mostakhles.ai"]
    body_text = (
        f"Topic: {topic}\nName: {name}\nEmail: {email}\nCompany: {company}\n\n"
        f"---\n{message}\n"
    )
    for admin in admins:
        try:
            emailer.send_email(
                to=admin,
                subject=f"[Mostakhles contact · {topic}] {name}",
                body_text=body_text,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("contact form email to %s failed: %s", admin, e)

    msg = (
        "Thanks — we got your message and will reply within one business day."
        if en else
        "شكرًا — وصلتنا رسالتك وسنردّ خلال يوم عمل واحد."
    )
    return templates.TemplateResponse(request, "contact.html", _ctx(request, msg=msg))


@app.post("/v1/contact")
def contact_submit_json(request: Request, payload: dict = Body(...)):
    """JSON contact endpoint for the React marketing SPA (served same-origin
    behind nginx; /v1/* is proxied here). Mirrors the HTML /contact handler —
    same validation and admin email fan-out — but returns JSON so the SPA can
    show its own success state without a page reload. Public, no auth. Failures
    to email degrade gracefully; the caller still sees success so a transient
    SMTP outage doesn't break the funnel."""
    req_lang = str(payload.get("lang") or "").strip().lower()
    # Honor the SPA's active language when it sends one; otherwise fall back to
    # the usual query/cookie/browser resolution.
    lang = req_lang if req_lang in ("en", "ar") else i18n.resolve_lang(request, None)
    en = lang == "en"

    name = str(payload.get("name") or "").strip()[:200]
    email = str(payload.get("email") or "").strip()[:200]
    company = str(payload.get("company") or "").strip()[:200]
    topic = str(payload.get("topic") or "web").strip()[:50]
    message = str(payload.get("message") or "").strip()[:5000]
    # Honeypot: real users never fill a hidden field; bots do.
    if str(payload.get("website") or payload.get("hp") or "").strip():
        return {"ok": True}
    if not name or "@" not in email or len(message) < 3:
        return {
            "ok": False,
            "error": "Please fill in all required fields." if en
            else "يرجى تعبئة الحقول المطلوبة.",
        }

    admins = list(auth.ADMIN_EMAILS) or ["support@mostakhles.ai"]
    body_text = (
        f"Topic: {topic}\nName: {name}\nEmail: {email}\nCompany: {company}\n\n"
        f"---\n{message}\n"
    )
    for admin in admins:
        try:
            emailer.send_email(
                to=admin,
                subject=f"[Mostakhles contact · {topic}] {name}",
                body_text=body_text,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("contact form (json) email to %s failed: %s", admin, e)

    return {"ok": True}


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


def _summarize_result(data):
    """Derive (field_count, avg_confidence 0-100) from an extraction result so the
    metrics dashboard can aggregate without re-scanning result_json on every read.
    Robust to the varied shapes we return (fields / expert / prescription)."""
    confs, leaves = [], 0

    def walk(o):
        nonlocal leaves
        if isinstance(o, dict):
            c = o.get("confidence")
            if isinstance(c, (int, float)):
                confs.append(c * 100 if c <= 1 else c)
            for k, v in o.items():
                if k == "confidence":
                    continue
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, (str, int, float)) and str(o).strip():
            leaves += 1

    walk(data)
    field_count = len(confs) if confs else leaves
    avg_conf = int(round(sum(confs) / len(confs))) if confs else None
    return field_count, avg_conf


def _log_ops(session, user_id, kind, status, latency_ms=None, tier=None,
             http_status=None, error_type=None):
    """Best-effort observability event (one row per extraction attempt, ok OR
    error). Never break the request path on a logging failure."""
    try:
        session.add(models.OpsEvent(
            user_id=user_id, kind=kind, status=status, latency_ms=latency_ms,
            tier=tier, http_status=http_status, error_type=error_type))
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _log_doc_event(user_id, history_id, stage, detail=None):
    """Best-effort delivery-side lifecycle stamp (exported / erp), keyed to a
    History row. Opens its own short session so it can be called after the request
    session is closed; verifies the history belongs to the caller before writing.
    Never breaks the request path (export must still succeed if logging fails)."""
    if not history_id or not user_id:
        return
    session = db.SessionLocal()
    try:
        h = session.get(models.History, int(history_id))
        if not h or h.user_id != user_id:
            return
        session.add(models.DocumentEvent(
            history_id=int(history_id), user_id=user_id, stage=stage, detail=detail))
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()
    finally:
        session.close()


def _orig_value(data, field):
    """Best-effort: what the model originally produced for `field` (for the
    before/after learning signal). Recurses the result shape."""
    target = str(field).strip().lower()
    hit = [None]

    def walk(o):
        if hit[0] is not None:
            return
        if isinstance(o, dict):
            for k, v in o.items():
                if str(k).strip().lower() == target:
                    hit[0] = v.get("value") if isinstance(v, dict) and "value" in v else (
                        v if not isinstance(v, (dict, list)) else None)
                    if hit[0] is not None:
                        return
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return hit[0]


# ── Learning loop v1.1 — corrections are applied POST-extraction, gated ──────
# v1 injected learned values into the prompt and told the model to always apply
# them — which could override a document's TRUE value. v1.1 extracts clean, then
# applies a learned value ONLY when every guard passes: the field isn't volatile
# (never amounts/dates/numbers), the correction came from the SAME vendor (or is
# global), the model was NOT confident in what it read, and the correction is
# recent (or well-reinforced). Safer by construction: guards can only REDUCE
# applications, never cause a wrong override.
LEARN_LOW_CONF = 0.75       # only fill a field the model was unsure about
LEARN_DECAY_DAYS = 180      # ignore stale corrections …
LEARN_MIN_COUNT_KEEP = 3    # … unless a reviewer reinforced them ≥3 times

# Field kinds that vary per document — never safe to reuse a learned literal for.
_VOLATILE_TOKENS = (
    "amount", "total", "subtotal", "balance", "due", "price", "cost", "qty",
    "quantity", "date", "time", "number", "invoice_no", "invoice_number",
    "bill_no", "ref", "reference", "serial", "iban", "account_no",
    "account_number", "tax", "vat_amount", "discount", "net", "gross", "paid",
    "unit_price", "line_total",
)
# Stable identity fields that merely CONTAIN a volatile token — keep learnable.
_STABLE_IDENTITY = (
    "vat_id", "tax_id", "vat_number", "tax_number", "tax_registration",
    "vat_registration", "registration_number", "commercial_register",
)


def _lc_norm(s):
    """Loose normalization for comparing keys/values (lower, collapse spaces)."""
    import re as _re
    return _re.sub(r"\s+", " ", str(s or "").strip().lower())


# Fields that identify the document's source (used to scope learned corrections).
_SCOPE_FIELDS = ("seller", "vendor", "supplier", "merchant", "issuer", "company",
                 "company_name", "partner", "partner_name", "name")
# Legal-form suffixes stripped when comparing vendor identities, so the same
# vendor matches across formatting ("ACME Trading" == "ACME Trading Co.").
_LEGAL_SUFFIX = ("co", "ltd", "llc", "inc", "company", "corp", "corporation",
                 "group", "est", "plc", "gmbh", "sa", "srl", "wll")


def _scope_norm(s):
    """Normalize a vendor/party name into a stable scope key (drop punctuation and
    common legal-form suffixes) so one supplier's documents share a scope."""
    import re as _re
    s = _re.sub(r"[^\w\s]", " ", _lc_norm(s))
    toks = [t for t in s.split() if t and t not in _LEGAL_SUFFIX]
    return " ".join(toks)


def _is_volatile_field(key):
    k = _lc_norm(key)
    if any(t in k for t in _STABLE_IDENTITY):
        return False
    return any(t in k for t in _VOLATILE_TOKENS)


def _iter_field_nodes(obj):
    """Walk an extraction result and yield (key, wrapped_node, flat_parent) for
    each field — covering flat ``{k: {value,confidence}}`` / ``{k: scalar}`` and
    nested ``header``/``totals``/``line_items`` shapes. For a wrapped field the
    node dict is returned (value at node['value']); for a scalar field the parent
    dict is returned so the caller can set parent[key]."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("_layout_html", "value", "confidence", "learned"):
                continue
            if isinstance(v, dict):
                if "value" in v:
                    yield (k, v, None)
                else:
                    yield from _iter_field_nodes(v)
            elif isinstance(v, list):
                for item in v:
                    yield from _iter_field_nodes(item)
            elif isinstance(v, (str, int, float)):
                yield (k, None, obj)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_field_nodes(item)


def _doc_scope(data):
    """Best-effort vendor/party identity for scoping learned corrections."""
    for key, node, parent in _iter_field_nodes(data):
        if _lc_norm(key) in _SCOPE_FIELDS:
            val = node.get("value") if node is not None else parent.get(key)
            if val and str(val).strip():
                return _scope_norm(str(val))
    return ""


def _apply_learned_corrections(session, user_id, document_type, data):
    """Apply this account's learned corrections to a fresh extraction, gated by
    vendor scope + low-confidence + non-volatile + recency. Mutates ``data`` in
    place and returns a list of the changes made — each
    ``{field, model_value, model_confidence, learned_value}`` — so the caller can
    persist provenance. ``len(result)`` is the honest 'learned corrections applied'
    count.

    Provenance contract (P0.3): a learned correction NEVER silently erases the
    model's read. On each applied field we keep the model's original value and
    confidence on the node (``model_value`` / ``model_confidence``), mark it
    ``learned`` with its ``learned_source``, and — crucially — we do NOT fabricate
    a high (0.9) confidence; the model's own confidence is preserved. The original
    extraction therefore stays fully reconstructable from the stored result, and
    the returned change list is recorded as auditable version rows.
    """
    if not isinstance(data, (dict, list)):
        return []
    C = models.CorrectionMemory
    try:
        from datetime import timedelta as _td
        cutoff = datetime.utcnow() - _td(days=LEARN_DECAY_DAYS)
        q = session.query(C).filter(C.user_id == user_id)
        if document_type:
            q = q.filter((C.document_type == document_type) | (C.document_type.is_(None)))
        q = q.filter((C.updated_at >= cutoff) | (C.count >= LEARN_MIN_COUNT_KEEP))
        rows = q.order_by(C.count.desc(), C.updated_at.desc()).limit(50).all()
    except Exception:  # noqa: BLE001
        return []
    if not rows:
        return []

    scope = _doc_scope(data)
    nodes = {}
    for key, node, parent in _iter_field_nodes(data):
        nodes.setdefault(_lc_norm(key), (key, node, parent))

    changes: list[dict] = []
    for r in rows:
        cv = (r.corrected_value or "").strip()
        if not cv or _is_volatile_field(r.field_key):
            continue
        # Vendor scope: a source-specific correction only applies to that source.
        if r.scope_key and scope and r.scope_key != scope:
            continue
        hit = nodes.get(_lc_norm(r.field_key))
        if not hit:
            continue
        key, node, parent = hit
        if node is not None:
            conf, cur = node.get("confidence"), node.get("value")
            if isinstance(conf, (int, float)):
                conf01 = conf / 100.0 if conf > 1 else conf
                if conf01 >= LEARN_LOW_CONF:
                    continue  # model was confident — trust the document
            # Nothing to override if the model already produced this value.
            if _lc_norm(str(cur)) == _lc_norm(cv):
                continue
            # Apply the learned value while PRESERVING the model's read + confidence.
            # (No blind 0.9 — confidence stays whatever the model reported.)
            node["model_value"] = cur
            node["model_confidence"] = conf
            node["value"] = cv
            node["learned"] = True
            node["learned_source"] = "correction_memory"
            changes.append({"field": key, "model_value": cur,
                            "model_confidence": conf, "learned_value": cv})
        else:
            cur = parent.get(key)
            if _lc_norm(str(cur)) == _lc_norm(cv):
                continue
            parent[key] = cv
            changes.append({"field": key, "model_value": cur,
                            "model_confidence": None, "learned_value": cv})
    return changes


def _record_learned_versions(session, hid, user_id, changes):
    """Append one auditable ExtractionVersion (source='learned') per learned
    override, capturing the model's original value (old_value) and the value
    CorrectionMemory applied (new_value) with a timestamp. Best-effort — the
    learning loop must never break the extraction path."""
    if not (hid and changes):
        return
    try:
        from sqlalchemy import func as _lfunc
        base_v = (session.query(_lfunc.max(models.ExtractionVersion.version))
                  .filter_by(history_id=hid).scalar()) or 1
        for i, ch in enumerate(changes, start=1):
            session.add(models.ExtractionVersion(
                history_id=hid, user_id=user_id, version=base_v + i,
                source="learned", field=ch["field"],
                old_value=(str(ch["model_value"]) if ch["model_value"] is not None else None),
                new_value=(str(ch["learned_value"]) if ch["learned_value"] is not None else None)))
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _record_history(session, user, kind, document_type, data, charged,
                    duration_ms=None, layout=None, output_lang=None):
    """Best-effort log of a successful extraction for the dashboard.
    `data` is stored as JSONB (Postgres) — pass a dict/list, not a JSON string.
    Returns the new History row id (or None on failure) so callers can hand the
    `hid` back to the client — needed for the correction/feedback loop."""
    try:
        field_count, avg_confidence = _summarize_result(data)
        h = models.History(
            user_id=user.id, kind=kind, document_type=document_type,
            charged=charged, duration_ms=duration_ms,
            layout=layout, output_lang=output_lang,
            result_json=data,
            field_count=field_count, avg_confidence=avg_confidence,
        )
        session.add(h)
        session.commit()
        # Workflow Engine: route the document to approval if any rule matches.
        try:
            from app.services import workflow as _workflow
            _workflow.evaluate(session, user, h)
        except Exception:  # noqa: BLE001 — never break the extraction path
            session.rollback()
        # Version 1 — the initial extraction (append-only version log).
        try:
            session.add(models.ExtractionVersion(
                history_id=h.id, user_id=user.id, version=1, source="extracted"))
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()
        return h.id
    except Exception:  # noqa: BLE001
        session.rollback()
        return None


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
        "csp_nonce": getattr(request.state, "csp_nonce", ""),
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
        first_key, first_raw = models.new_api_key(user.id)  # give them a first key
        session.add(first_key)
        session.commit()

        # Send verification email (console fallback if SMTP not configured locally)
        verify_url = str(request.base_url).rstrip("/") + f"/verify/{user.verification_token}"
        try:
            emailer.send_verification_email(user.email, verify_url)
        except Exception:  # noqa: BLE001 — don't block signup on email failure; user can resend
            pass
        # Keys are stored hashed and never shown again — reveal the first key ONCE
        # here so the user can copy it. (It works for API calls immediately; the
        # email-verification gate only blocks extraction until they confirm.)
        return templates.TemplateResponse(request, "verify_sent.html",
            _ctx(request, email=user.email, new_api_key=first_raw))
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
        limit = auth.PLAN_LIMITS.get(user.plan, 30)

        keys = []
        for k in user.api_keys:
            used, _, _ = auth.get_usage(session, k)
            # Only the non-secret prefix is ever rendered — the full key is shown
            # once at creation and is not recoverable (stored hashed).
            keys.append({"id": k.id, "prefix": k.key_prefix, "active": k.active, "used": used})

        # One-time reveal: a freshly-created key is passed via a short-lived,
        # httponly cookie set by POST /dashboard/keys; show it once, then clear it.
        new_api_key = request.cookies.get("mk_new_key")

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

        resp = templates.TemplateResponse(request, "dashboard.html", _ctx(request,
            plan=user.plan, limit=limit, keys=keys,
            new_api_key=new_api_key,  # one-time reveal of a just-created key
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
        # Clear the one-time reveal cookie so the key is shown only on this load.
        if new_api_key:
            resp.delete_cookie("mk_new_key")
        return resp
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


@app.post("/admin/run-utilization-check")
def admin_run_utilization_check(request: Request):
    """Trigger the high-utilization warning sweep. Wired to a daily cron
    via a curl POST from systemd-timer / supervisor / external scheduler."""
    from app.services import cost_alerts
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user or not auth.is_admin(user):
            raise HTTPException(404, "not found")
        result = cost_alerts.run_high_utilization_check(session)
        return result
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
        key_obj, raw = models.new_api_key(user.id)
        session.add(key_obj)
        session.commit()
        # Keys are stored hashed, so the raw value can never be recovered. Hand it
        # to the /dashboard render exactly once via a short-lived, httponly cookie
        # (not a URL param — secrets must not land in query strings/history).
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("mk_new_key", raw, max_age=120, httponly=True,
                        samesite="lax", secure=settings.COOKIE_SECURE, path="/dashboard")
        return resp
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
def job_status(request: Request, job_id: str, x_api_key: str = Header(None)):
    """Poll a batch job's progress and (partial) results.

    Authorization: the caller (API key or CSRF-checked session) must OWN the job.
    A non-owner — or an unauthenticated request that clears the caller gate but
    targets someone else's job — gets the same 404 as a missing job, so job
    existence is not observable across tenants. The `owner_user_id` field is
    internal and stripped from the response to keep the poll shape unchanged.
    """
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        caller_uid = api_key.user_id
    finally:
        session.close()
    job = jobs.get_job(job_id)
    if not job or job.get("owner_user_id") != caller_uid:
        raise HTTPException(404, "job not found")
    return {"job_id": job_id,
            **{k: v for k, v in job.items() if k != "owner_user_id"}}


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


@app.get("/v1/metrics")
def metrics(request: Request, x_api_key: str = Header(None)):
    """Real customer-outcome KPIs for the current month — all measured from the
    History/Approval tables, no assumptions except the labelled time-saved estimate."""
    from sqlalchemy import func
    session = db.SessionLocal()
    try:
        caller = _resolve_caller(session, x_api_key, request)
        uid = caller.user_id
        H, A = models.History, models.Approval
        month0 = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        base = session.query(H).filter(H.user_id == uid, H.created_at >= month0)

        docs = base.count()
        fields = session.query(func.coalesce(func.sum(H.field_count), 0)).filter(
            H.user_id == uid, H.created_at >= month0).scalar() or 0
        credits = session.query(func.coalesce(func.sum(H.charged), 0)).filter(
            H.user_id == uid, H.created_at >= month0).scalar() or 0
        avg_ms = session.query(func.avg(H.duration_ms)).filter(
            H.user_id == uid, H.created_at >= month0, H.duration_ms.isnot(None)).scalar()
        avg_conf = session.query(func.avg(H.avg_confidence)).filter(
            H.user_id == uid, H.created_at >= month0, H.avg_confidence.isnot(None)).scalar()
        avg_ms = float(avg_ms) if avg_ms is not None else None       # Postgres avg() → Decimal
        avg_conf = float(avg_conf) if avg_conf is not None else None

        corrected = base.filter(H.corrected_json.isnot(None)).count()
        routed = session.query(A).filter(A.user_id == uid, A.created_at >= month0).count()
        reviews_needed = min(docs, corrected + routed)           # proxy: corrected OR routed to approval
        stp = round((docs - reviews_needed) / docs, 4) if docs else None

        MANUAL_MIN = 4                                            # assumed manual-entry minutes / doc
        actual_min = ((avg_ms or 0) / 60000.0) * docs
        est_saved = max(0, round(docs * MANUAL_MIN - actual_min))

        return {
            "period": "month",
            "documents_processed": docs,
            "fields_extracted": int(fields),
            "avg_confidence": round(float(avg_conf), 1) if avg_conf is not None else None,
            "avg_seconds": round(float(avg_ms) / 1000, 1) if avg_ms is not None else None,
            "credits_spent": int(credits),
            "reviews_needed": reviews_needed,
            "straight_through_rate": stp,
            "estimated_minutes_saved": est_saved,
            "estimate_basis": f"time saved assumes ~{MANUAL_MIN} min manual entry per document",
        }
    finally:
        session.close()


@app.get("/v1/observability")
def observability(request: Request, x_api_key: str = Header(None)):
    """Real reliability metrics from the ops-event log — request volume, error
    rate, and latency percentiles over 24h and 30d. All measured, no estimates."""
    from datetime import timedelta
    session = db.SessionLocal()
    try:
        caller = _resolve_caller(session, x_api_key, request)
        uid = caller.user_id
        O = models.OpsEvent
        now = datetime.utcnow()

        def window(since):
            q = session.query(O).filter(O.user_id == uid, O.created_at >= since)
            total = q.count()
            errors = q.filter(O.status == "error").count()
            lat = sorted(r[0] for r in session.query(O.latency_ms).filter(
                O.user_id == uid, O.created_at >= since, O.status == "ok",
                O.latency_ms.isnot(None)).all())

            def pct(p):
                if not lat:
                    return None
                i = max(0, min(len(lat) - 1, int(round(p / 100.0 * len(lat)) - 1)))
                return lat[i]

            return {
                "requests": total,
                "errors": errors,
                "error_rate": round(errors / total, 4) if total else None,
                "success_rate": round((total - errors) / total, 4) if total else None,
                "p50_ms": pct(50),
                "p95_ms": pct(95),
            }

        return {"last_24h": window(now - timedelta(hours=24)),
                "last_30d": window(now - timedelta(days=30))}
    finally:
        session.close()


@app.get("/v1/status")
def public_status(request: Request):
    """PUBLIC system status — aggregate reliability across ALL traffic. No auth,
    no per-user data. Every figure is measured from the ops-event log; nothing
    here is hand-set. Powers the public /status trust page."""
    from datetime import timedelta
    from sqlalchemy import func
    session = db.SessionLocal()
    try:
        O, H = models.OpsEvent, models.History
        now = datetime.utcnow()

        def win(since):
            q = session.query(O).filter(O.created_at >= since)
            total = q.count()
            errors = q.filter(O.status == "error").count()
            lat = sorted(r[0] for r in session.query(O.latency_ms).filter(
                O.created_at >= since, O.status == "ok", O.latency_ms.isnot(None)).all())

            def pct(p):
                if not lat:
                    return None
                i = max(0, min(len(lat) - 1, int(round(p / 100.0 * len(lat)) - 1)))
                return lat[i]

            return {"requests": total, "errors": errors,
                    "success_rate": round((total - errors) / total, 4) if total else None,
                    "p50_ms": pct(50), "p95_ms": pct(95)}

        last1h = win(now - timedelta(hours=1))
        er = (last1h["errors"] / last1h["requests"]) if last1h["requests"] else 0.0
        state = "operational" if er < 0.05 else "degraded"
        fields_30d = session.query(func.coalesce(func.sum(H.field_count), 0)).filter(
            H.created_at >= now - timedelta(days=30)).scalar() or 0

        return {
            "status": state,
            "last_24h": win(now - timedelta(hours=24)),
            "last_30d": win(now - timedelta(days=30)),
            "fields_processed_30d": int(fields_30d),
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    finally:
        session.close()


@app.get("/v1/documents")
def documents(request: Request, x_api_key: str = Header(None), limit: int = 12):
    """The caller's recent extractions, newest first — powers the SPA's Recent list."""
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        rows = (session.query(models.History)
                .filter_by(user_id=api_key.user_id)
                .order_by(models.History.id.desc())
                .limit(min(max(limit, 1), 50)).all())
        return {"documents": [{
            "id": h.id,
            "document_type": h.document_type or "document",
            "kind": h.kind,
            "created_at": h.created_at.isoformat() if h.created_at else None,
        } for h in rows]}
    finally:
        session.close()


# ---------- Workflow Engine v1: rules → approvals → audit ----------

_ALLOWED_OPS = {"gt", "lt", "gte", "lte", "eq", "contains"}


def _approval_dict(a) -> dict:
    return {
        "id": a.id,
        "history_id": a.history_id,
        "rule_id": a.rule_id,
        "rule_name": a.rule_name,
        "document_type": a.document_type or "document",
        "amount": float(a.amount) if a.amount is not None else None,
        "status": a.status,
        "note": a.note,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "decided_at": a.decided_at.isoformat() if a.decided_at else None,
    }


@app.get("/v1/workflow/rules")
def list_workflow_rules(request: Request, x_api_key: str = Header(None)):
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        rules = (session.query(models.WorkflowRule)
                 .filter_by(user_id=api_key.user_id)
                 .order_by(models.WorkflowRule.id.desc()).all())
        return {"rules": [{
            "id": r.id, "name": r.name, "field": r.field, "op": r.op,
            "value": r.value, "action": r.action, "active": r.active,
        } for r in rules]}
    finally:
        session.close()


@app.post("/v1/workflow/rules")
def create_workflow_rule(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        name = (payload.get("name") or "").strip()
        field = (payload.get("field") or "").strip()
        op = (payload.get("op") or "").strip().lower()
        value = str(payload.get("value") if payload.get("value") is not None else "").strip()
        if not name or not field or op not in _ALLOWED_OPS or value == "":
            raise HTTPException(400, f"name, field, value, and op ∈ {sorted(_ALLOWED_OPS)} are required")
        rule = models.WorkflowRule(
            user_id=api_key.user_id, name=name, field=field, op=op,
            value=value, action="require_approval", active=True)
        session.add(rule)
        session.commit()
        return {"id": rule.id, "name": rule.name, "field": rule.field,
                "op": rule.op, "value": rule.value, "active": rule.active}
    finally:
        session.close()


@app.delete("/v1/workflow/rules/{rid}")
def delete_workflow_rule(rid: int, request: Request, x_api_key: str = Header(None)):
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        rule = session.query(models.WorkflowRule).filter_by(id=rid, user_id=api_key.user_id).first()
        if not rule:
            raise HTTPException(404, "rule not found")
        session.delete(rule)
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.get("/v1/approvals")
def list_approvals(request: Request, x_api_key: str = Header(None), status: str = "pending", limit: int = 50):
    """The review queue. `status` ∈ pending|approved|rejected|all."""
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        q = session.query(models.Approval).filter_by(user_id=api_key.user_id)
        if status and status != "all":
            q = q.filter(models.Approval.status == status)
        rows = q.order_by(models.Approval.id.desc()).limit(min(max(limit, 1), 100)).all()
        pending_n = (session.query(models.Approval)
                     .filter_by(user_id=api_key.user_id, status="pending").count())
        blocked_n = (session.query(models.Approval)
                     .filter_by(user_id=api_key.user_id, status="blocked").count())
        return {"approvals": [_approval_dict(a) for a in rows],
                "pending_count": pending_n, "blocked_count": blocked_n}
    finally:
        session.close()


def _decide_approval(request, x_api_key, aid: int, new_status: str, payload: dict | None):
    from datetime import datetime
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        ap = session.query(models.Approval).filter_by(id=aid, user_id=api_key.user_id).first()
        if not ap:
            raise HTTPException(404, "approval not found")
        # 'pending' (require_approval) and 'blocked' (block policy) are both open
        # states a reviewer can decide; already-decided ones can't be re-decided.
        if ap.status not in ("pending", "blocked"):
            raise HTTPException(409, f"already {ap.status}")
        note = (payload or {}).get("note") if isinstance(payload, dict) else None
        ap.status = new_status
        ap.decided_by = api_key.user_id
        ap.decided_at = datetime.utcnow()
        ap.note = note
        session.add(models.AuditLog(
            user_id=api_key.user_id, approval_id=ap.id, event=new_status,
            detail=f"{new_status.capitalize()} by user{(' — ' + note) if note else ''}."))
        if new_status == "approved":
            session.add(models.AuditLog(
                user_id=api_key.user_id, approval_id=ap.id, event="erp_export",
                detail="Marked ready for Odoo/ERP posting (fields-as-columns export)."))
        session.commit()
        return {"ok": True, "approval": _approval_dict(ap)}
    finally:
        session.close()


@app.post("/v1/approvals/{aid}/approve")
def approve_approval(aid: int, request: Request, payload: dict = Body(None), x_api_key: str = Header(None)):
    return _decide_approval(request, x_api_key, aid, "approved", payload)


@app.post("/v1/approvals/{aid}/reject")
def reject_approval(aid: int, request: Request, payload: dict = Body(None), x_api_key: str = Header(None)):
    return _decide_approval(request, x_api_key, aid, "rejected", payload)


@app.get("/v1/audit")
def list_audit(request: Request, x_api_key: str = Header(None), limit: int = 30):
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        rows = (session.query(models.AuditLog).filter_by(user_id=api_key.user_id)
                .order_by(models.AuditLog.id.desc()).limit(min(max(limit, 1), 100)).all())
        return {"audit": [{
            "id": r.id, "approval_id": r.approval_id, "event": r.event,
            "detail": r.detail,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]}
    finally:
        session.close()


@app.get("/v1/workflow/stats")
def workflow_stats(request: Request, x_api_key: str = Header(None)):
    """Process-monitoring metrics for the operations dashboard — all real counts."""
    from datetime import datetime
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)
        uid = api_key.user_id
        H, A = models.History, models.Approval
        docs_total = session.query(H).filter_by(user_id=uid).count()
        today0 = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        docs_today = session.query(H).filter(H.user_id == uid, H.created_at >= today0).count()
        def acount(st): return session.query(A).filter_by(user_id=uid, status=st).count()
        pending, approved, rejected = acount("pending"), acount("approved"), acount("rejected")
        decided = approved + rejected
        return {
            "documents_total": docs_total,
            "documents_today": docs_today,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            # docs that never tripped a rule → straight-through, no human needed
            "auto_cleared": max(docs_total - (pending + approved + rejected), 0),
            "approval_rate": round(approved / decided * 100, 1) if decided else None,
        }
    finally:
        session.close()


@app.get("/v1/session")
def session_info(request: Request):
    """Bootstrap for the SPA app: whether the visitor is logged in, minimal user
    fields, and the CSRF token needed for cookie-authed /v1/* calls. No secrets
    are exposed. This endpoint itself needs no CSRF (it's how the SPA gets it)."""
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return {"authenticated": False}
        csrf = auth.session_csrf_token(session, request.cookies.get("sid")) or ""
        return {
            "authenticated": True,
            "user": {"email": user.email, "plan": user.plan},
            "csrf_token": csrf,
        }
    finally:
        session.close()


@app.post("/v1/tool/{slug}")
def run_tool(slug: str, request: Request, file: UploadFile = File(...),
             hard: bool = Form(True), routing: str = Form("explicit"),
             output_lang: str = Form("preserve"),
             x_api_key: str = Header(None)):
    """Run a catalog OCR service (text / fields / table / searchable PDF).
    output_lang: 'preserve' | 'ar' | 'en' — controls language of extracted values.
    routing: 'explicit' (default, back-compat — honour `hard`); 'auto' picks fast vs
    hard via a cheap heuristic; 'fast'/'hard' force one tier."""
    svc = SERVICES.get(slug)
    if not svc:
        raise HTTPException(404, "unknown service")
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    if output_lang not in ("preserve", "ar", "en"):
        raise HTTPException(400, "output_lang must be one of: preserve, ar, en")
    if routing not in ("explicit", "auto", "fast", "hard"):
        raise HTTPException(400, "routing must be one of: explicit, auto, fast, hard")
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

    if routing != "explicit":
        hard = extractor._resolve_hard(routing, hard, data_bytes, file.content_type,
                                       doctype_hint=slug)
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
        hid = _record_history(session, api_key.user, slug, out.get("document_type"),
                              out.get("data") or out.get("text") or out, cost, duration_ms=_dur_ms)
        used, limit, _ = auth.get_usage(session, api_key)
        out["usage"] = {"used": used, "limit": limit, "remaining": max(0, limit - used), "charged": cost}
        # `hid` lets a client (e.g. the Odoo connector) POST field corrections
        # back to /v1/extract/correct/{hid} — the human-in-the-loop feedback loop.
        out["hid"] = hid
        return out
    finally:
        session.close()


@app.post("/v1/export-table")
def export_table(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    session = db.SessionLocal()
    try:
        _uid = _resolve_caller(session, x_api_key, request).user.id
    finally:
        session.close()
    fmt, columns, rows = payload.get("format", "xlsx"), payload.get("columns", []), payload.get("rows", [])
    if fmt == "xlsx":
        data, media, fname = exports.table_to_xlsx(columns, rows)
    elif fmt == "csv":
        data, media, fname = exports.table_to_csv(columns, rows)
    else:
        raise HTTPException(400, "format must be xlsx or csv")
    _log_doc_event(_uid, payload.get("history_id"), "exported", f"table:{fmt}")
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


@app.post("/v1/reproduce")
def reproduce_endpoint(request: Request, payload: dict = Body(...),
                       x_api_key: str = Header(None)):
    """Render an extracted result as a polished HTML/PDF/DOCX (Path A).

    Payload:
      {document_type, data, format: 'html'|'pdf'|'docx', lang: 'ar'|'en',
       extracted_at?}
    """
    session = db.SessionLocal()
    try:
        _uid = _resolve_caller(session, x_api_key, request).user.id
    finally:
        session.close()
    from app.services import repro as _repro
    doctype = (payload.get("document_type") or "").strip()
    data = payload.get("data") or {}
    fmt = (payload.get("format") or "html").lower()
    lang = payload.get("lang") or "ar"
    extracted_at = payload.get("extracted_at") or ""
    # No doctype gate — the renderer falls back to the generic template for
    # any unknown type, so this endpoint accepts everything.
    if not doctype:
        doctype = "document"
    try:
        if fmt == "html":
            body, mt, fn = _repro.render_html(doctype, data, lang=lang, extracted_at=extracted_at)
        elif fmt == "pdf":
            body, mt, fn = _repro.render_pdf(doctype, data, lang=lang, extracted_at=extracted_at)
        elif fmt == "docx":
            body, mt, fn = _repro.render_docx(doctype, data, lang=lang, extracted_at=extracted_at)
        else:
            raise HTTPException(400, "format must be one of: html, pdf, docx")
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    _log_doc_event(_uid, payload.get("history_id"), "exported", f"repro:{fmt}")
    return Response(content=body, media_type=mt,
                    headers={"Content-Disposition": f'attachment; filename="{fn}"'})


@app.post("/v1/export")
def export_data(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    """Turn extracted rows into a downloadable file (csv/xlsx/docx/pdf/xml).

    Two payload shapes are accepted:
      1. {format, rows: [...]} — generic flat export (legacy, all formats).
      2. {format: 'xlsx', result: {layout, document_type, ...}} — layout-aware
         Excel that renders prescription / invoice / table shapes natively.
         Falls back to the flat row exporter if the layout is unrecognised.
    """
    session = db.SessionLocal()
    try:
        _uid = _resolve_caller(session, x_api_key, request).user.id  # auth gate
    finally:
        session.close()
    fmt = payload.get("format", "csv")
    rows = payload.get("rows", [])
    result = payload.get("result")
    # Odoo-importable (fields-as-columns) exports advance the ERP stage; every
    # other format is a plain "exported" delivery event.
    _stage = "erp" if str(fmt).startswith("xlsx_columns") else "exported"
    # Export language is independent of the session/output locale: the caller
    # picks it per-export ("en" → English LTR headers, else Arabic RTL).
    lang = "en" if str(payload.get("lang", "ar")).lower().startswith("en") else "ar"
    if fmt not in exports.EXPORTERS:
        raise HTTPException(400, f"unsupported format '{fmt}'. Use: {', '.join(exports.EXPORTERS)}")

    # Layout-aware path: only xlsx for now; other formats stay flat.
    if isinstance(result, dict) and fmt == "xlsx":
        data, media_type, filename = exports.to_xlsx_layout_aware(result)
        _log_doc_event(_uid, payload.get("history_id"), _stage, fmt)
        return Response(content=data, media_type=media_type,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    if not rows:
        raise HTTPException(400, "no rows to export (pass `rows` or a rich `result` for xlsx)")
    data, media_type, filename = exports.EXPORTERS[fmt](rows, lang=lang)
    _log_doc_event(_uid, payload.get("history_id"), _stage, fmt)
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
        # Active subscription (if any) drives the Manage Subscription card.
        # We show ONE row — the most recent active or cancelled-pending sub.
        # Past expired ones live in the PaymentEvent log; the UI cares only
        # about what's billing the user right now.
        sub = (session.query(models.Subscription)
               .filter_by(user_id=user.id)
               .filter(models.Subscription.status.in_(("active", "past_due", "cancelled")))
               .order_by(models.Subscription.created_at.desc())
               .first())
        return templates.TemplateResponse(request, "account.html",
            _ctx(request, msg=None, err=None, active_subscription=sub))
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
def save_correction(hid: int, request: Request, payload: dict = Body(...),
                    x_api_key: str = Header(None)):
    """Persist a user's inline correction to History.corrected_json.
    Accepts {field, value}. Authenticated by session cookie (web inline-edit) OR
    x-api-key (programmatic clients, e.g. the Odoo connector's correction loop).
    Builds up a per-row dict of user overrides — the before/after signal is
    recoverable by diffing corrected_json against result_json for prompt-tuning."""
    field = (payload.get("field") or "").strip()
    value = payload.get("value")
    if not field:
        raise HTTPException(400, "field is required")
    session = db.SessionLocal()
    try:
        # _resolve_caller handles both api-key and (CSRF-checked) session auth.
        user = _resolve_caller(session, x_api_key, request).user
        h = session.get(models.History, hid)
        if not h or h.user_id != user.id:
            raise HTTPException(404, "not found")
        corrections = dict(h.corrected_json or {})
        _old_val = corrections.get(field) if field in corrections else _orig_value(h.result_json, field)
        corrections[field] = value
        h.corrected_json = corrections
        session.commit()

        # Version log: append a version for this correction (field / from / to).
        try:
            from sqlalchemy import func as _func
            maxv = session.query(_func.max(models.ExtractionVersion.version)).filter_by(history_id=hid).scalar() or 1
            session.add(models.ExtractionVersion(
                history_id=hid, user_id=user.id, version=maxv + 1, source="corrected", field=field,
                old_value=str(_old_val) if _old_val is not None else None,
                new_value=str(value) if value is not None else None))
            session.commit()
        except Exception:  # noqa: BLE001
            session.rollback()

        # Learning: remember this fix so future extractions can apply it — but
        # ONLY for stable fields (never volatile amounts/dates/numbers, which vary
        # per document), and SCOPED to this document's vendor so a fix learned for
        # one supplier won't bleed onto another. Volatile edits still live in
        # corrected_json + the version log above for audit; they're just not
        # turned into a reusable literal. [[project_mostakhles_prove_the_platform]]
        if not _is_volatile_field(field):
            try:
                orig = _orig_value(h.result_json, field)
                scope = _doc_scope(h.result_json) or None
                C = models.CorrectionMemory
                existing = session.query(C).filter_by(
                    user_id=user.id, document_type=h.document_type,
                    field_key=field, scope_key=scope).first()
                if existing:
                    if orig is not None:
                        existing.original_value = str(orig)
                    if value is not None:
                        existing.corrected_value = str(value)
                    existing.count = (existing.count or 1) + 1
                    existing.updated_at = datetime.utcnow()
                else:
                    session.add(C(user_id=user.id, document_type=h.document_type,
                                  field_key=field, scope_key=scope,
                                  original_value=str(orig) if orig is not None else None,
                                  corrected_value=str(value) if value is not None else None,
                                  count=1))
                session.commit()
            except Exception:  # noqa: BLE001 — learning is best-effort, never break the save
                session.rollback()

        return {"ok": True, "corrected_count": len(corrections)}
    finally:
        session.close()


# ---------- History ----------
@app.get("/v1/history/{hid}/versions")
def history_versions(hid: int, request: Request, x_api_key: str = Header(None)):
    """The append-only version timeline for one extraction — v1 (extracted) plus a
    version per correction (field / from / to). Auditable and reproducible-by-replay."""
    session = db.SessionLocal()
    try:
        user = _resolve_caller(session, x_api_key, request).user
        h = session.get(models.History, hid)
        if not h or h.user_id != user.id:
            raise HTTPException(404, "not found")
        V = models.ExtractionVersion
        rows = session.query(V).filter_by(history_id=hid).order_by(V.version.asc()).all()
        return {
            "history_id": hid,
            "current_version": rows[-1].version if rows else 1,
            "versions": [{
                "version": r.version, "source": r.source, "field": r.field,
                "old_value": r.old_value, "new_value": r.new_value,
                "at": r.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if r.created_at else None,
            } for r in rows],
        }
    finally:
        session.close()


@app.get("/v1/history/{hid}/timeline")
def history_timeline(hid: int, request: Request, x_api_key: str = Header(None)):
    """The per-document lifecycle timeline — Uploaded → Extracted → Validated →
    Reviewed → Approved → Exported → Sent to ERP, each with a real timestamp.
    Delivery stages (exported/erp) come from DocumentEvent; the earlier stages are
    DERIVED from History / ExtractionVersion / Approval, so the audit view is
    always consistent with the source-of-truth tables and can't drift."""
    from sqlalchemy import func as _func
    from datetime import timedelta as _td

    def _iso(dt):
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None

    session = db.SessionLocal()
    try:
        user = _resolve_caller(session, x_api_key, request).user
        h = session.get(models.History, hid)
        if not h or h.user_id != user.id:
            raise HTTPException(404, "not found")

        created = h.created_at
        # Uploaded ≈ extraction start = completion − processing wall-clock.
        uploaded_at = created
        if created and h.duration_ms:
            try:
                uploaded_at = created - _td(milliseconds=int(h.duration_ms))
            except Exception:  # noqa: BLE001
                uploaded_at = created

        # Reviewed — first human correction (from the append-only version log).
        V = models.ExtractionVersion
        rev = (session.query(_func.min(V.created_at), _func.count(V.id))
               .filter(V.history_id == hid, V.source == "corrected").first())
        reviewed_at, reviewed_n = (rev or (None, 0))

        # Approved / rejected / in-review — from the review queue.
        A = models.Approval
        routed_at = session.query(_func.min(A.created_at)).filter(A.history_id == hid).scalar()
        approved_row = (session.query(A).filter(A.history_id == hid, A.status == "approved")
                        .order_by(A.decided_at.asc()).first())
        rejected_row = (session.query(A).filter(A.history_id == hid, A.status == "rejected")
                        .order_by(A.decided_at.asc()).first())
        if approved_row:
            appr_state, appr_at = "approved", approved_row.decided_at
        elif rejected_row:
            appr_state, appr_at = "rejected", rejected_row.decided_at
        elif routed_at is not None:
            appr_state, appr_at = "pending", routed_at
        else:
            appr_state, appr_at = None, None

        # Delivery stages — from DocumentEvent.
        D = models.DocumentEvent

        def _dev(stage):
            r = (session.query(_func.min(D.created_at), _func.count(D.id))
                 .filter(D.history_id == hid, D.stage == stage).first())
            return (r or (None, 0))
        exported_at, exported_n = _dev("exported")
        erp_at, erp_n = _dev("erp")
        imported_at, imported_n = _dev("imported")
        imported_detail = None
        if imported_at:
            imported_detail = (session.query(D.detail)
                               .filter(D.history_id == hid, D.stage == "imported")
                               .order_by(D.created_at.asc()).limit(1).scalar()) or "confirmed in ERP"

        conf = h.avg_confidence
        stages = [
            {"key": "uploaded", "label": "Uploaded", "reached": bool(created),
             "at": _iso(uploaded_at), "detail": None},
            {"key": "extracted", "label": "Extracted", "reached": bool(created),
             "at": _iso(created), "detail": (f"{h.field_count} fields" if h.field_count else None)},
            {"key": "validated", "label": "Validated", "reached": conf is not None,
             "at": (_iso(created) if conf is not None else None),
             "detail": (f"{conf}% avg confidence" if conf is not None else None)},
            {"key": "reviewed", "label": "Reviewed", "reached": reviewed_at is not None,
             "at": _iso(reviewed_at),
             "detail": (f"{reviewed_n} correction{'s' if reviewed_n != 1 else ''}" if reviewed_at else None)},
            {"key": "approved", "label": ("Rejected" if appr_state == "rejected" else "Approved"),
             "reached": appr_state in ("approved", "rejected"), "at": _iso(appr_at),
             "state": appr_state, "detail": ("in review" if appr_state == "pending" else appr_state)},
            {"key": "exported", "label": "Exported", "reached": exported_at is not None,
             "at": _iso(exported_at),
             "detail": (f"{exported_n} export{'s' if exported_n != 1 else ''}" if exported_at else None)},
            {"key": "erp", "label": "Sent to ERP", "reached": erp_at is not None,
             "at": _iso(erp_at), "detail": ("Odoo-ready export" if erp_at else None)},
            {"key": "imported", "label": "Imported to ERP", "reached": imported_at is not None,
             "at": _iso(imported_at), "detail": imported_detail},
        ]
        return {"history_id": hid, "document_type": h.document_type,
                "pending_review": appr_state == "pending", "stages": stages}
    finally:
        session.close()


@app.post("/v1/erp/confirm")
def erp_confirm(request: Request, payload: dict = Body(...), x_api_key: str = Header(None)):
    """Confirm that an extraction's data was imported into the caller's ERP — the
    inbound callback the Mostakhles Odoo connector fires after it writes the mapped
    fields onto an Odoo record. Stamps the 'imported' lifecycle stage so the
    document timeline shows a real 'Imported to ERP' event (closing the loop that
    'Sent to ERP' — the Odoo-ready export — only opened).

    Body: {history_id, model?, record_id?, record_ref?}. Auth: x-api-key (the
    connector) or a CSRF-checked session. Best-effort; never the connector's
    problem if this fails — the Odoo write is already committed on their side."""
    hid = payload.get("history_id") or payload.get("hid")
    if not hid:
        raise HTTPException(400, "history_id is required")
    session = db.SessionLocal()
    try:
        user = _resolve_caller(session, x_api_key, request).user
        h = session.get(models.History, int(hid))
        if not h or h.user_id != user.id:
            raise HTTPException(404, "not found")
        model = str(payload.get("model") or "").strip()
        ref = str(payload.get("record_ref") or payload.get("ref") or "").strip()
        rid = payload.get("record_id")
        loc = f"{model}#{rid}" if (model and rid) else (model or None)
        detail = " · ".join([b for b in (ref, loc) if b])[:250] or None
        _uid = user.id
    finally:
        session.close()
    _log_doc_event(_uid, hid, "imported", detail)
    return {"ok": True, "history_id": int(hid), "stage": "imported"}


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


DEMO_PER_IP_LIMIT = int(os.getenv("DEMO_PER_IP_LIMIT", "10"))
DEMO_PER_IP_WINDOW_SEC = int(os.getenv("DEMO_PER_IP_WINDOW_SEC", str(30 * 86400)))


@app.post("/v1/demo-extract")
def demo_extract_endpoint(request: Request, file: UploadFile = File(...)):
    """Anonymous landing-page hero demo.

    Hardened for public exposure:
      - Server-side resolves the demo API key (it is NEVER sent from the client,
        so visitors can't scrape it and burn the shared quota from a script).
      - Forces routing='fast' → 1 credit/page so a single visitor can't drain
        the demo pool with a 100-page PDF on Hard tier.
      - Per-IP monthly cap (DEMO_PER_IP_LIMIT, default 10) on top of the
        existing 30-req/min/IP burst limit and the demo user's monthly quota.
      - Returns 429 with a clear message when a visitor hits the cap, so the
        landing JS can prompt them to sign up for their own 30 free credits.
    """
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")

    client_ip = request.client.host if request.client else None
    if not auth.rate_limit_check(f"demo:burst:{client_ip}", max_attempts=10, window_sec=60):
        raise HTTPException(429, "too many demo requests from this IP — wait a minute")
    if not auth.rate_limit_check(f"demo:month:{client_ip}",
                                 max_attempts=DEMO_PER_IP_LIMIT,
                                 window_sec=DEMO_PER_IP_WINDOW_SEC):
        raise HTTPException(
            429,
            f"You've used the public demo {DEMO_PER_IP_LIMIT} times this month. "
            "Sign up — you get 30 free credits on your own account.",
        )

    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(415, "unsupported file type — use PNG, JPG, WEBP, GIF, or PDF.")
    data_bytes = file.file.read()
    # Demo path: tighter file-size ceiling than the paid API (5 MB vs 20 MB).
    if len(data_bytes) > 5 * 1024 * 1024:
        raise HTTPException(413, "demo file too large (max 5 MB). Sign up to upload larger files.")

    session = db.SessionLocal()
    try:
        demo_key = session.query(models.ApiKey).filter_by(key=auth.DEMO_API_KEY, active=True).first()
        if not demo_key:
            raise HTTPException(503, "demo not available — please sign up to try it")

        # Force fast tier (cost = 1 credit / page) — caps Gemini spend per demo.
        n_pages = _count_pdf_pages(data_bytes) if file.content_type == "application/pdf" else 1
        n_pages = n_pages or 1
        if n_pages > 5:
            raise HTTPException(413, "demo PDF too long (max 5 pages). Sign up for full extractions.")
        cost = auth.credits_for(False) * n_pages  # False → fast tier
        auth.enforce_limit(session, demo_key, needed=cost)

        try:
            result = extractor.extract_auto(data_bytes, file.content_type, hard=False,
                                            output_lang="preserve")
        except Exception as e:  # noqa: BLE001
            raise _http_error_for(e, "extraction failed")

        auth.increment_usage(session, demo_key, count=cost)
        auth.rate_limit_record(f"demo:burst:{client_ip}")
        auth.rate_limit_record(f"demo:month:{client_ip}")

        # Strip the cognitive envelope to keep the response small for the hero.
        data = result if any(k in result for k in ("patient", "medications", "header",
                                                    "line_items", "clauses", "totals", "table"))\
                     else result.get("fields", result)
        from datetime import datetime as _dt
        return envelope.wrap_extraction(
            raw_data=data,
            document_type=result.get("document_type"),
            layout=result.get("layout"),
            output_lang="preserve",
            files_count=1,
            usage={"charged": cost},
            duration_ms=0,
            model="gemini", tier="fast",
            request_id=getattr(request.state, "request_id", None),
            extracted_at_iso=_dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
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
    # Smart routing: 'explicit' (default, back-compat — honour `hard`); 'auto'
    # picks fast vs hard via a cheap heuristic; 'fast'/'hard' force one tier.
    routing: str = Form("explicit"),
    # Path B — visual reproduction. When True, ask Gemini to ALSO emit a
    # `_layout_html` field containing a self-contained HTML that visually
    # mirrors the source. Forces hard tier and charges 3 extra credits.
    visual: bool = Form(False),
    output_lang: str = Form("preserve"),   # 'preserve' | 'ar' | 'en'
    x_api_key: str = Header(None),
    idempotency_key: str = Header(None, alias="Idempotency-Key"),
):
    if not llm.is_configured():
        raise HTTPException(500, "GEMINI_API_KEY not configured on server")
    if output_lang not in ("preserve", "ar", "en"):
        raise HTTPException(400, "output_lang must be one of: preserve, ar, en")
    if routing not in ("explicit", "auto", "fast", "hard"):
        raise HTTPException(400, "routing must be one of: explicit, auto, fast, hard")
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

    # Smart routing: resolve to a concrete `hard` bool BEFORE billing so we
    # don't charge for the wrong tier. Pure heuristic — no LLM call.
    if routing != "explicit":
        hard = extractor._resolve_hard(routing, hard, image_bytes, image_ct)

    n_pages = _count_pdf_pages(image_bytes) if image_ct == "application/pdf" else None
    native_max = int(os.getenv("PDF_NATIVE_MAX_PAGES", "5"))  # ≤ this → one merged call
    hard_max = int(os.getenv("MAX_PDF_PAGES", "100"))         # > this → rejected

    # Auth + free-tier enforcement. No key => the public demo account.
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)

        # Idempotency: a repeated request with the same Idempotency-Key replays
        # the stored response — no re-run, no double charge.
        if idempotency_key:
            prior = (session.query(models.IdempotencyKey)
                     .filter_by(user_id=api_key.user_id, key=idempotency_key)
                     .order_by(models.IdempotencyKey.id.desc()).first())
            if prior and prior.response_json:
                return prior.response_json

        # Large PDF → background batch job (one call per page; never truncates).
        # Only the single-file path goes through batching today; multi-image
        # uploads are always under the size threshold (1-10 images).
        if n_files == 1 and n_pages and n_pages > native_max:
            if n_pages > hard_max:
                raise HTTPException(413, f"this PDF has {n_pages} pages; the limit is {hard_max}. "
                                         "Split it into smaller files.")
            auth.enforce_limit(session, api_key, needed=n_pages * auth.credits_for(hard))
            job_id = jobs.start_batch(image_bytes, hard, api_key.id, n_pages,
                                      owner_user_id=api_key.user_id)
            return {"mode": "batch", "job_id": job_id, "total_pages": n_pages, "status": "processing"}

        # Single image OR multi-image batch → one synchronous call (Gemini handles
        # multiple images in a single request and bills per image).
        # Path B (visual=True) requires hard tier (needs the strong model to
        # produce coherent HTML) and adds 3 credits to cover ~2-3k extra tokens.
        if visual:
            hard = True
        cost = auth.credits_for(hard) * n_files + (3 if visual else 0)
        auth.enforce_limit(session, api_key, needed=cost)
        import time as _time
        _t0 = _time.time()
        layout = None
        mode = "auto"   # pre-init so ops-logging on an early failure has a label
        _learned_n = 0  # set after extraction — learned corrections are applied post-hoc
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
                                                output_lang=output_lang,
                                                with_layout=visual)
                document_type = result.get("document_type")
                layout = result.get("layout")
                # If Path B emitted `_layout_html`, hoist it onto the result
                # envelope so the polished export can use it directly.
                _layout_html = result.pop("_layout_html", None)
                if any(k in result for k in ("patient", "medications", "header",
                                              "line_items", "clauses", "totals", "table")):
                    data = result
                else:
                    data = result.get("fields", result)
                if _layout_html and isinstance(data, dict):
                    data["_layout_html"] = _layout_html
                mode = "auto"
        except Exception as e:  # noqa: BLE001 — surface model/parse errors; don't bill failures
            _he = _http_error_for(e, "extraction failed")
            _log_ops(session, api_key.user_id, mode, "error",
                     latency_ms=int((_time.time() - _t0) * 1000),
                     tier=("hard" if hard else "fast"),
                     http_status=_he.status_code, error_type=type(e).__name__)
            raise _he
        _dur_ms = int((_time.time() - _t0) * 1000)

        # Learning loop (post-hoc, gated): fill low-confidence, same-vendor,
        # non-volatile fields with values this account has reliably corrected
        # before. Applied to `data` before it's stored/returned.
        try:
            _learned_changes = _apply_learned_corrections(
                session, api_key.user_id, document_type, data)
        except Exception:  # noqa: BLE001 — learning must never break extraction
            _learned_changes = []
        _learned_n = len(_learned_changes)

        # Only meter successful extractions.
        auth.increment_usage(session, api_key, count=cost)
        hid = _record_history(session, api_key.user, mode, document_type, data, cost,
                              duration_ms=_dur_ms, layout=layout,
                              output_lang=output_lang if output_lang != "preserve" else None)
        # Provenance for the learning loop: record each learned override as an
        # auditable version (source='learned') so we can reconstruct BOTH what the
        # model produced and what CorrectionMemory changed it to. Never breaks
        # extraction.
        _record_learned_versions(session, hid, api_key.user_id, _learned_changes)
        used, limit, _ = auth.get_usage(session, api_key)
        usage = {"used": used, "limit": limit, "remaining": max(0, limit - used), "charged": cost}
        from datetime import datetime as _dt
        body = envelope.wrap_extraction(
            raw_data=data,
            document_type=document_type,
            layout=layout,
            output_lang=output_lang,
            files_count=n_files,
            usage=usage,
            duration_ms=_dur_ms,
            model="gemini",
            tier=("hard" if hard else "fast"),
            request_id=getattr(request.state, "request_id", None),
            extracted_at_iso=_dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        body["mode"] = mode  # back-compat: extraction strategy ("auto"/"schema"/"auto_multi")
        # `hid` lets a client (e.g. the Odoo connector) POST field corrections
        # back to /v1/extract/correct/{hid} — the human-in-the-loop feedback loop.
        body["hid"] = hid
        body["learned_applied"] = _learned_n   # # of learned corrections actually applied (gated)
        # Confidence/workflow policies: evaluate() (inside _record_history) may have
        # held or blocked this document. Surface the verdict so a client — the Odoo
        # connector especially — can enforce "block before import".
        try:
            from sqlalchemy import func as _pfunc  # noqa: F401  (kept local, consistent w/ file)
            _aps = (session.query(models.Approval)
                    .filter_by(history_id=hid).all()) if hid else []
            _holds = [{"rule": a.rule_name, "status": a.status,
                       "action": "block" if a.status == "blocked" else "require_approval",
                       "id": a.id} for a in _aps]
            body["policy"] = {"holds": _holds,
                              "blocked": any(a.status == "blocked" for a in _aps),
                              "held": any(a.status == "pending" for a in _aps)}
        except Exception:  # noqa: BLE001 — policy surfacing is best-effort
            body["policy"] = {"holds": [], "blocked": False, "held": False}
        # Observability: one 'ok' row per successful extraction.
        _log_ops(session, api_key.user_id, mode, "ok", latency_ms=_dur_ms,
                 tier=("hard" if hard else "fast"))
        # Idempotency: remember this response so a retried key replays it.
        if idempotency_key:
            try:
                session.add(models.IdempotencyKey(
                    user_id=api_key.user_id, key=idempotency_key, response_json=body))
                session.commit()
            except Exception:  # noqa: BLE001
                session.rollback()
        return body
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
from app.services import paytabs as _paytabs  # noqa: E402
from app.services.plans import PAID_PLANS, get_plan  # noqa: E402


def _apply_subscription(session, user, plan_slug: str, provider: str,
                        external_id: str, amount_usd: float | None) -> int:
    """Provider-agnostic grant: cancel any active subscription, open a fresh
    30-day one, and flip user.plan. Returns the new subscription id. (Paymob and
    PayPal predate this and inline the same logic; new providers use this.)"""
    now = datetime.utcnow()
    (session.query(models.Subscription)
        .filter_by(user_id=user.id, status="active")
        .update({"status": "cancelled", "cancelled_at": now, "updated_at": now},
                synchronize_session=False))
    sub = models.Subscription(
        user_id=user.id, provider=provider, external_id=external_id,
        plan=plan_slug, status="active",
        current_period_end=now + timedelta(days=30), amount_usd=amount_usd)
    session.add(sub)
    session.flush()
    user.plan = plan_slug
    return sub.id


def _usd_to_paytabs(usd: float) -> tuple[float, str]:
    """USD plan price → PayTabs settlement currency (SAR enables mada, AED for
    UAE). SAR/AED are USD-pegged. Returns (amount, currency)."""
    cur = (settings.PAYTABS_CURRENCY or "SAR").upper()
    rate = {"SAR": settings.SAR_PER_USD, "AED": settings.AED_PER_USD}.get(cur, 1.0)
    return round(usd * rate, 2), cur


def _paytabs_provider() -> str:
    """Region-tagged provider slug so KSA (mada) and UAE records stay distinct
    if both regions are ever run — paytabs_sa / paytabs_ae / paytabs."""
    return {"SAR": "paytabs_sa", "AED": "paytabs_ae"}.get(
        (settings.PAYTABS_CURRENCY or "").upper(), "paytabs")


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


# Currencies we're willing to charge through Paymob, in the merchant's preferred
# order (first = default selection on the picker). Filtered to the ones we know
# how to price. Anything else in the config string is ignored.
_PAYMOB_KNOWN_CURRENCIES = ("USD", "EGP")


def _paymob_currencies() -> list[str]:
    """Parsed, validated, de-duplicated list from settings.PAYMOB_CURRENCIES."""
    seen: list[str] = []
    for raw in (settings.PAYMOB_CURRENCIES or "").split(","):
        cur = raw.strip().upper()
        if cur in _PAYMOB_KNOWN_CURRENCIES and cur not in seen:
            seen.append(cur)
    return seen or ["USD"]


def _paymob_amount(plan_cfg, currency: str) -> float:
    """Charge amount for `plan_cfg` in `currency`, in that currency's major unit.
    USD is the native plan price; EGP is derived at the configured rate."""
    if currency.upper() == "EGP":
        return round(plan_cfg.usd * settings.EGP_PER_USD, 2)
    return round(plan_cfg.usd, 2)


def _paymob_currency_available(currency: str) -> bool:
    """True if a Paymob integration (MID) is configured for `currency`."""
    return bool(_paymob.integration_id_for(currency))


@app.get("/billing/checkout", response_class=HTMLResponse)
def billing_checkout_picker(request: Request, plan: str = Query(...)):
    """Render the payment-method picker for `plan`. User picks Paymob (EGP)
    or PayPal (USD), then the form on the picker page POSTs to the right
    provider endpoint. This is the page the "Subscribe" button on /pricing
    redirects to so we keep the pricing page itself uncluttered."""
    plan_cfg = get_plan(plan)
    if not plan_cfg:
        raise HTTPException(status_code=400, detail=f"unknown plan: {plan}")

    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse(
                f"/login?next=/billing/checkout%3Fplan%3D{plan}",
                status_code=303,
            )
        # Probe per-provider availability so the UI can grey out unconfigured
        # methods instead of letting the user click and get a 502.
        paypal_available = bool(plans.paypal_plan_id(plan)
                                and settings.PAYPAL_CLIENT_ID
                                and settings.PAYPAL_SECRET)
        # Per-currency Paymob options: each currency the merchant offers AND has
        # an integration (MID) configured for. The template renders one radio per
        # option so the customer picks USD or EGP.
        paymob_options = [
            {"currency": cur,
             "amount": _paymob_amount(plan_cfg, cur),
             "available": _paymob_currency_available(cur)}
            for cur in _paymob_currencies()
        ]
        paymob_available = bool(settings.PAYMOB_API_KEY) and any(
            o["available"] for o in paymob_options)
        # Back-compat for any template still reading a single EGP figure.
        amount_egp = round(plan_cfg.usd * settings.EGP_PER_USD, 2)
        paytabs_available = bool(settings.PAYTABS_PROFILE_ID and settings.PAYTABS_SERVER_KEY)
        paytabs_amount, paytabs_currency = _usd_to_paytabs(plan_cfg.usd)
        ctx = _ctx(request,
                   plan=plan_cfg,
                   amount_egp=amount_egp,
                   paymob_options=paymob_options,
                   paypal_available=paypal_available,
                   paymob_available=paymob_available,
                   paytabs_available=paytabs_available,
                   paytabs_amount=paytabs_amount,
                   paytabs_currency=paytabs_currency)
        return templates.TemplateResponse(request, "checkout.html", ctx)
    finally:
        session.close()


@app.post("/billing/paymob/checkout")
def billing_paymob_checkout(request: Request, plan: str = Form(...),
                            currency: str = Form(""), csrf_token: str = Form("")):
    """Mint a Paymob iframe for the requested plan, charging in the chosen
    currency (USD or EGP). Auth'd users only. Posted to from the Paymob tile on
    /billing/checkout."""
    _require_csrf(request, csrf_token)
    plan_cfg = get_plan(plan)
    if not plan_cfg:
        raise HTTPException(status_code=400, detail=f"unknown plan: {plan}")
    # Validate the requested currency against what we offer; default to the first.
    offered = _paymob_currencies()
    currency = (currency or "").strip().upper()
    if currency not in offered:
        currency = offered[0]
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login?next=/pricing", status_code=303)
        amount = _paymob_amount(plan_cfg, currency)
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
            iframe, _order_id = _paymob.begin_checkout(amount, mid, billing,
                                                       currency=currency)
        except _paymob.PaymobError as exc:
            log.error("paymob checkout failed (currency=%s): %s", currency, exc)
            # Friendly redirect rather than raw 502 JSON dump.
            return RedirectResponse(
                f"/billing/checkout?plan={plan}&error=paymob_unavailable",
                status_code=303,
            )
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
        # We may charge in USD or EGP. Normalise to USD for reporting using the
        # currency Paymob echoes back (it's part of the signed HMAC payload, so
        # it's trustworthy). A USD charge is 1:1; EGP is divided by the rate.
        charge_currency = (obj.get("currency") or "EGP").upper()
        if not amount_cents:
            amount_usd = None
        elif charge_currency == "USD":
            amount_usd = round(amount_cents / 100, 2)
        else:
            amount_usd = round(amount_cents / 100 / settings.EGP_PER_USD, 2)

        user = None
        plan_slug = None
        subscription_id = None

        # Resolve the user from the merchant_order_id whether the payment
        # succeeded or failed, so a FAILED PaymentEvent is still attributable to
        # the user (support, fraud review, dunning). The plan grant below stays
        # strictly gated on `success`.
        if decoded:
            user_id, plan_slug = decoded
            user = session.query(models.User).filter_by(id=user_id).first()

        if user and success:
            plan_cfg = plans.get_plan(plan_slug)
            if plan_cfg:
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
                log.warning("paymob upgrade skipped: user=%s plan=%s not a known plan",
                            user.id, plan_slug)
        elif success and not user:
            # Paid, but we couldn't map the payment to a user (deleted user or
            # unrecognised merchant_order_id). Event is still recorded below.
            log.warning("paymob success but unresolved user: mid=%s decoded=%s", mid, decoded)

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


# ============================================================================
#   PayTabs billing (Gulf: KSA mada + UAE / GCC cards)
# ============================================================================
#
# Same shape as Paymob: mint mst_v1_… cart_id → hosted PayPage redirect →
# server-to-server IPN. The IPN does NOT trust its posted body; it queries
# PayTabs (with our Server Key) for the authoritative status before granting.

@app.post("/billing/paytabs/checkout")
def billing_paytabs_checkout(request: Request, plan: str = Form(...),
                             csrf_token: str = Form("")):
    """Create a PayTabs hosted PayPage for `plan` (mada / GCC cards). Auth'd
    users only. Posted to from the PayTabs tile on /billing/checkout."""
    _require_csrf(request, csrf_token)
    plan_cfg = get_plan(plan)
    if not plan_cfg:
        raise HTTPException(status_code=400, detail=f"unknown plan: {plan}")
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login?next=/pricing", status_code=303)
        amount, currency = _usd_to_paytabs(plan_cfg.usd)
        mid = _mint_merchant_order_id(user.id, plan_cfg.slug)
        base = str(request.base_url).rstrip("/")
        customer = {
            "name": (user.email.split("@")[0] or "Customer")[:60],
            "email": user.email,
            "phone": "0500000000",  # PayTabs requires a non-empty phone
            "street1": "NA", "city": "NA",
            "country": {"SAR": "SA", "AED": "AE"}.get(currency, "SA"),
        }
        try:
            redirect, _ref = _paytabs.begin_checkout(
                amount, currency, mid,
                f"Mostakhles {plan_cfg.name} plan",
                customer,
                callback_url=f"{base}/billing/paytabs/callback",
                return_url=f"{base}/billing/paytabs/return")
        except _paytabs.PayTabsError as exc:
            log.error("paytabs checkout failed: %s", exc)
            return RedirectResponse(
                f"/billing/checkout?plan={plan}&error=paytabs_unavailable",
                status_code=303)
        return RedirectResponse(redirect, status_code=303)
    finally:
        session.close()


@app.api_route("/billing/paytabs/return", methods=["GET", "POST"])
async def paytabs_return(request: Request):
    """Browser lands here after the PayPage. The plan grant happens on the
    server-to-server IPN below — this page just confirms to the user."""
    return RedirectResponse("/billing/success", status_code=303)


@app.post("/billing/paytabs/callback")
async def paytabs_callback(request: Request):
    """PayTabs → Mostakhles IPN. Does NOT trust the posted body: takes tran_ref,
    queries PayTabs (authenticated with our Server Key) for the real status,
    then idempotently records the PaymentEvent + Subscription and flips
    user.plan. Returns 200 so PayTabs stops retrying."""
    ctype = request.headers.get("content-type", "")
    raw = await request.body()
    if "application/json" in ctype:
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = dict(await request.form())

    tran_ref = str(payload.get("tran_ref") or payload.get("tranRef") or "")
    sig = str(payload.get("signature") or "")
    if sig and not _paytabs.verify_signature(payload, sig):
        log.warning("paytabs IPN signature mismatch (tran_ref=%s) — relying on query", tran_ref)
    if not tran_ref:
        return {"received": True, "ignored": "missing tran_ref"}

    try:
        q = _paytabs.query_transaction(tran_ref)
    except _paytabs.PayTabsError as exc:
        log.error("paytabs query failed for tran_ref=%s: %s", tran_ref, exc)
        return {"received": True, "error": "query_failed"}

    success = _paytabs.is_approved(q)
    mid = str(q.get("cart_id") or payload.get("cart_id") or "")
    decoded = _parse_merchant_order_id(mid)
    provider = _paytabs_provider()
    log.info("paytabs IPN: tran_ref=%s approved=%s cart_id=%s decoded=%s",
             tran_ref, success, mid, decoded)

    session = db.SessionLocal()
    try:
        existing = (session.query(models.PaymentEvent)
                    .filter_by(provider=provider, external_id=tran_ref).first())
        if existing:
            return {"received": True, "duplicate": True}

        try:
            cart_amount = float(q.get("cart_amount") or 0)
        except (TypeError, ValueError):
            cart_amount = 0.0
        cur = str(q.get("cart_currency") or settings.PAYTABS_CURRENCY or "SAR").upper()
        rate = {"SAR": settings.SAR_PER_USD, "AED": settings.AED_PER_USD}.get(cur, 1.0)
        amount_usd = round(cart_amount / rate, 2) if (cart_amount and rate) else None

        user = None
        plan_slug = None
        subscription_id = None
        if decoded and success:
            user_id, plan_slug = decoded
            user = session.query(models.User).filter_by(id=user_id).first()
            plan_cfg = plans.get_plan(plan_slug)
            if user and plan_cfg:
                subscription_id = _apply_subscription(
                    session, user, plan_slug, provider, tran_ref, amount_usd)
                log.info("paytabs upgrade: user=%s plan=%s sub=%s amount_usd=%s",
                         user.id, plan_slug, subscription_id, amount_usd)
            else:
                log.warning("paytabs upgrade skipped: user=%s plan=%s (user=%s, plan=%s)",
                            user_id, plan_slug, bool(user), bool(plan_cfg))

        evt = models.PaymentEvent(
            provider=provider, external_id=tran_ref,
            event_type=("paytabs.payment.success" if success else "paytabs.payment.failed"),
            subscription_id=subscription_id, user_id=user.id if user else None,
            amount_usd=amount_usd,
            raw_payload=((raw.decode("utf-8", errors="replace")) or json.dumps(q))[:65535],
            processed_at=datetime.utcnow())
        session.add(evt)
        session.commit()
        return {"received": True, "tran_ref": tran_ref, "upgraded": bool(subscription_id)}
    except Exception:
        session.rollback()
        log.exception("paytabs callback failed: tran_ref=%s", tran_ref)
        raise
    finally:
        session.close()


# ============================================================================
#   PayPal billing (Sitting PP-A)
# ============================================================================
#
# Flow (mirrors the Paymob shape so the dashboard / renewal email / cancel UI
# can stay provider-agnostic):
#
#   1. User on /pricing clicks "Subscribe Pro · PayPal"
#      → POST /billing/paypal/checkout?plan=pro
#   2. We mint a `custom_id` = mst_v1_{user_id}_{plan}_{nonce} (same format
#      the Paymob flow uses) and call PayPal's Subscriptions API with it.
#      PayPal returns a subscription_id + approval URL.
#   3. We redirect the user to PayPal's approval URL. They consent on PayPal.
#   4. PayPal sends them back to /billing/paypal/return?subscription_id=I-xxx.
#      We GET the subscription, confirm status=ACTIVE, then flip user.plan and
#      record the Subscription + PaymentEvent rows idempotently.
#   5. PayPal also POSTs webhooks (BILLING.SUBSCRIPTION.ACTIVATED / CANCELLED /
#      PAYMENT.SALE.COMPLETED) — handled in Sitting PP-B.
#
# The custom_id IS the channel for user→subscription mapping — same trick
# Paymob uses with merchant_order_id, same decoder.

from app.services import paypal as _paypal  # noqa: E402


@app.post("/billing/paypal/checkout")
def billing_paypal_checkout(request: Request, plan: str = Form(...),
                            csrf_token: str = Form("")):
    """Mint a PayPal subscription for the requested plan, redirect the user
    to PayPal's approval URL. Auth'd users only."""
    _require_csrf(request, csrf_token)
    plan_cfg = plans.get_plan(plan)
    if not plan_cfg:
        raise HTTPException(status_code=400, detail=f"unknown plan: {plan}")
    paypal_plan = plans.paypal_plan_id(plan)
    if not paypal_plan:
        # No PayPal plan ID configured for this tier — friendly redirect
        # to the picker with an error flag instead of raw JSON.
        log.warning("paypal checkout blocked: PAYPAL_PLAN_ID_%s not set", plan.upper())
        return RedirectResponse(
            f"/billing/checkout?plan={plan}&error=paypal_unavailable",
            status_code=303,
        )

    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login?next=/pricing", status_code=303)

        custom_id = _mint_merchant_order_id(user.id, plan_cfg.slug)
        base = str(request.base_url).rstrip("/")
        return_url = f"{base}/billing/paypal/return"
        cancel_url = f"{base}/pricing?paypal=cancelled"

        try:
            approve, sub_id = _paypal.begin_checkout(
                paypal_plan, custom_id,
                return_url=return_url, cancel_url=cancel_url,
                subscriber_email=user.email,
            )
        except _paypal.PayPalError as exc:
            log.error("paypal checkout failed: %s", exc)
            raise HTTPException(status_code=502,
                                detail=f"payment provider error: {exc}")

        log.info("paypal checkout: user=%s plan=%s sub_id=%s custom_id=%s",
                 user.id, plan, sub_id, custom_id)
        return RedirectResponse(approve, status_code=303)
    finally:
        session.close()


@app.get("/billing/paypal/return")
def billing_paypal_return(request: Request,
                          subscription_id: str = Query("", alias="subscription_id")):
    """User came back from PayPal's approval flow. Confirm the subscription is
    ACTIVE, write the Subscription + PaymentEvent rows, flip user.plan, then
    drop them on /billing/success.

    Idempotent: if PayPal's webhook beat us to the punch (Sitting PP-B), the
    PaymentEvent UNIQUE(provider, external_id) short-circuits the second
    upgrade attempt."""
    if not subscription_id:
        return RedirectResponse("/pricing?paypal=missing_sub", status_code=303)

    try:
        sub_data = _paypal.get_subscription(subscription_id)
    except _paypal.PayPalError as exc:
        log.error("paypal return: get_subscription failed: %s", exc)
        return RedirectResponse("/pricing?paypal=lookup_failed", status_code=303)

    status = (sub_data.get("status") or "").upper()
    custom_id = sub_data.get("custom_id") or ""
    plan_id_external = sub_data.get("plan_id") or ""
    decoded = _parse_merchant_order_id(custom_id)
    log.info("paypal return: sub=%s status=%s custom_id=%s decoded=%s",
             subscription_id, status, custom_id, decoded)

    if status != "ACTIVE":
        # APPROVAL_PENDING / SUSPENDED / CANCELLED / EXPIRED — let the webhook
        # handle the eventual transition. We don't upgrade here.
        return RedirectResponse(f"/pricing?paypal=status_{status.lower()}",
                                status_code=303)

    if not decoded:
        log.warning("paypal return: custom_id not parseable: %s", custom_id)
        return RedirectResponse("/pricing?paypal=bad_custom_id", status_code=303)

    user_id, plan_slug = decoded
    session = db.SessionLocal()
    try:
        # Idempotency: PayPal webhook may have already processed this.
        existing = (session.query(models.PaymentEvent)
                    .filter_by(provider="paypal", external_id=subscription_id)
                    .first())
        if existing:
            log.info("paypal return: sub=%s already processed (event id=%s)",
                     subscription_id, existing.id)
            return RedirectResponse("/billing/success?already=1", status_code=303)

        user = session.query(models.User).filter_by(id=user_id).first()
        plan_cfg = plans.get_plan(plan_slug)
        if not (user and plan_cfg):
            log.warning("paypal return: unknown user or plan: user=%s plan=%s",
                        user_id, plan_slug)
            return RedirectResponse("/pricing?paypal=unknown_user_or_plan",
                                    status_code=303)

        now = datetime.utcnow()
        # Close any active sub on this user — single-active-sub invariant.
        (session.query(models.Subscription)
                .filter_by(user_id=user.id, status="active")
                .update({"status": "cancelled", "cancelled_at": now,
                         "updated_at": now}, synchronize_session=False))

        sub = models.Subscription(
            user_id=user.id,
            provider="paypal",
            external_id=subscription_id,
            plan=plan_slug,
            status="active",
            current_period_end=now + timedelta(days=30),
            amount_usd=plan_cfg.usd,
        )
        session.add(sub)
        session.flush()  # for sub.id

        evt = models.PaymentEvent(
            provider="paypal",
            external_id=subscription_id,
            event_type="paypal.subscription.activated",
            subscription_id=sub.id,
            user_id=user.id,
            amount_usd=plan_cfg.usd,
            raw_payload=json.dumps(sub_data)[:65535],
            processed_at=now,
        )
        session.add(evt)
        user.plan = plan_slug
        session.commit()

        log.info("paypal upgrade: user=%s plan=%s sub=%s external_id=%s",
                 user.id, plan_slug, sub.id, subscription_id)
        return RedirectResponse("/billing/success", status_code=303)
    except Exception:
        session.rollback()
        log.exception("paypal return failed: sub=%s", subscription_id)
        raise
    finally:
        session.close()


# ----------------------------------------------------------------------------
# PayPal webhook — Sitting PP-B.
#
# Events we handle:
#   BILLING.SUBSCRIPTION.ACTIVATED     → write Subscription+Event, flip user.plan
#   BILLING.SUBSCRIPTION.CANCELLED     → mark cancelled, keep access until period_end
#   BILLING.SUBSCRIPTION.SUSPENDED     → mark past_due (billing failed at PayPal)
#   BILLING.SUBSCRIPTION.EXPIRED       → mark cancelled, downgrade user.plan='free'
#   PAYMENT.SALE.COMPLETED             → extend current_period_end +30d (renewal)
#   BILLING.SUBSCRIPTION.PAYMENT.FAILED → mark past_due, log
#
# Idempotency: each PayPal event has a unique `id` (WH-xxx-xxx). We key
# PaymentEvent on (provider='paypal', external_id=event_id) so retries
# short-circuit. Subscription rows are keyed on (provider, external_id) where
# external_id = the PayPal subscription_id (I-xxx) so the ACTIVATED handler
# also short-circuits if /billing/paypal/return already wrote the row.
#
# We return 200 on every legitimate event (success OR no-op) so PayPal stops
# retrying — we've already audited what happened. Signature failures return 403.
# ----------------------------------------------------------------------------

# Subscription event types we know how to handle. Anything else is logged
# and 200'd without state changes (PayPal still considers it delivered).
_PP_SUB_ACTIVATED = "BILLING.SUBSCRIPTION.ACTIVATED"
_PP_SUB_CANCELLED = "BILLING.SUBSCRIPTION.CANCELLED"
_PP_SUB_SUSPENDED = "BILLING.SUBSCRIPTION.SUSPENDED"
_PP_SUB_EXPIRED   = "BILLING.SUBSCRIPTION.EXPIRED"
_PP_PAY_COMPLETED = "PAYMENT.SALE.COMPLETED"
_PP_PAY_FAILED    = "BILLING.SUBSCRIPTION.PAYMENT.FAILED"

_PP_KNOWN_EVENTS = frozenset({
    _PP_SUB_ACTIVATED, _PP_SUB_CANCELLED, _PP_SUB_SUSPENDED,
    _PP_SUB_EXPIRED, _PP_PAY_COMPLETED, _PP_PAY_FAILED,
})


def _pp_find_active_sub(session, *, paypal_sub_id: str):
    """Look up our Subscription row by PayPal subscription_id. None if missing."""
    return (session.query(models.Subscription)
            .filter_by(provider="paypal", external_id=paypal_sub_id).first())


@app.post("/billing/paypal/webhook")
async def paypal_webhook(request: Request):
    """PayPal → Mostakhles webhook. Verifies signature, dispatches by event_type,
    writes an idempotent PaymentEvent + applies state changes to Subscription /
    user.plan as appropriate."""
    raw = await request.body()
    try:
        event = json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")

    # Verify signature — bypassed in local mode where the mock points the
    # verify endpoint at itself and returns SUCCESS. In prod this hits PayPal's
    # /v1/notifications/verify-webhook-signature using PAYPAL_WEBHOOK_ID.
    if not _paypal.verify_webhook_signature(dict(request.headers), event):
        log.warning("paypal webhook rejected: signature invalid (event_id=%s)",
                    event.get("id"))
        raise HTTPException(status_code=403, detail="invalid signature")

    event_id   = str(event.get("id") or "")
    event_type = str(event.get("event_type") or "")
    resource   = event.get("resource") or {}
    log.info("paypal webhook: event=%s type=%s", event_id, event_type)

    if not event_id:
        return {"received": True, "ignored": "missing event id"}
    if event_type not in _PP_KNOWN_EVENTS:
        log.info("paypal webhook: type=%s not handled, ignoring", event_type)
        return {"received": True, "ignored": f"unknown type {event_type}"}

    session = db.SessionLocal()
    try:
        # Idempotency short-circuit on the event ID. PayPal retries up to ~25h.
        existing = (session.query(models.PaymentEvent)
                    .filter_by(provider="paypal", external_id=event_id).first())
        if existing:
            log.info("paypal webhook: event=%s already processed (id=%s), skipping",
                     event_id, existing.id)
            return {"received": True, "duplicate": True}

        now = datetime.utcnow()
        sub_row = None
        user = None
        amount_usd: float | None = None

        # Find the affected subscription. For SALE events the sub_id is in
        # `resource.billing_agreement_id`; for billing events it's `resource.id`.
        paypal_sub_id = (resource.get("billing_agreement_id")
                         or resource.get("id") or "")

        if paypal_sub_id and paypal_sub_id.startswith("I-"):
            sub_row = _pp_find_active_sub(session, paypal_sub_id=paypal_sub_id)
            if sub_row:
                user = session.query(models.User).filter_by(id=sub_row.user_id).first()

        # ---- Per-event dispatch ----

        if event_type == _PP_SUB_ACTIVATED:
            # /billing/paypal/return may have already written this — if so,
            # sub_row exists and we just record the PaymentEvent for audit.
            if not sub_row:
                # Webhook beat the return URL (rare but possible). Mirror what
                # billing_paypal_return does: decode custom_id, write Sub.
                custom_id = resource.get("custom_id") or ""
                decoded = _parse_merchant_order_id(custom_id)
                if decoded:
                    user_id, plan_slug = decoded
                    user = session.query(models.User).filter_by(id=user_id).first()
                    plan_cfg = plans.get_plan(plan_slug)
                    if user and plan_cfg and paypal_sub_id:
                        # Close any other active sub before inserting the new one.
                        (session.query(models.Subscription)
                                .filter_by(user_id=user.id, status="active")
                                .update({"status": "cancelled", "cancelled_at": now,
                                         "updated_at": now}, synchronize_session=False))
                        sub_row = models.Subscription(
                            user_id=user.id, provider="paypal",
                            external_id=paypal_sub_id, plan=plan_slug,
                            status="active",
                            current_period_end=now + timedelta(days=30),
                            amount_usd=plan_cfg.usd,
                        )
                        session.add(sub_row)
                        session.flush()
                        user.plan = plan_slug
                        amount_usd = float(plan_cfg.usd)
                        log.info("paypal webhook ACTIVATED upgrade: user=%s plan=%s sub=%s",
                                 user.id, plan_slug, sub_row.id)
            # If sub_row already exists, no state change needed — return URL handled it.

        elif event_type == _PP_SUB_CANCELLED:
            if sub_row and sub_row.status != "cancelled":
                sub_row.status = "cancelled"
                sub_row.cancelled_at = now
                sub_row.updated_at = now
                log.info("paypal webhook CANCELLED: user=%s sub=%s (access until %s)",
                         sub_row.user_id, sub_row.id, sub_row.current_period_end)
                # NOTE: we DON'T flip user.plan here. They keep access until
                # current_period_end. The renewal cron (PP-C) downgrades when
                # the period elapses.

        elif event_type == _PP_SUB_SUSPENDED:
            if sub_row and sub_row.status != "past_due":
                sub_row.status = "past_due"
                sub_row.updated_at = now
                log.warning("paypal webhook SUSPENDED: user=%s sub=%s — billing failed at PayPal",
                            sub_row.user_id, sub_row.id)

        elif event_type == _PP_SUB_EXPIRED:
            if sub_row:
                sub_row.status = "cancelled"
                sub_row.cancelled_at = sub_row.cancelled_at or now
                sub_row.updated_at = now
                if user:
                    user.plan = "free"
                    log.info("paypal webhook EXPIRED: user=%s downgraded to free",
                             user.id)

        elif event_type == _PP_PAY_COMPLETED:
            # Recurring renewal payment succeeded. Extend the period.
            try:
                amount_usd = float(((resource.get("amount") or {}).get("total"))
                                   or resource.get("amount", {}).get("value")
                                   or 0)
            except (TypeError, ValueError):
                amount_usd = None
            if sub_row:
                sub_row.current_period_end = (sub_row.current_period_end or now) + timedelta(days=30)
                if sub_row.status in ("past_due", "trialing"):
                    sub_row.status = "active"
                sub_row.updated_at = now
                log.info("paypal webhook PAYMENT.SALE.COMPLETED: user=%s sub=%s "
                         "amount=%s extended to %s",
                         sub_row.user_id, sub_row.id, amount_usd,
                         sub_row.current_period_end)

        elif event_type == _PP_PAY_FAILED:
            if sub_row and sub_row.status == "active":
                sub_row.status = "past_due"
                sub_row.updated_at = now
                log.warning("paypal webhook PAYMENT.FAILED: user=%s sub=%s -> past_due",
                            sub_row.user_id, sub_row.id)

        # ---- Always write the PaymentEvent for the audit trail ----
        evt = models.PaymentEvent(
            provider="paypal",
            external_id=event_id,
            event_type=event_type.lower().replace(".", "_"),
            subscription_id=sub_row.id if sub_row else None,
            user_id=user.id if user else None,
            amount_usd=amount_usd,
            raw_payload=json.dumps(event)[:65535],
            processed_at=now,
        )
        session.add(evt)
        session.commit()
        return {"received": True, "event_id": event_id, "type": event_type}
    except Exception:
        session.rollback()
        log.exception("paypal webhook failed: event=%s type=%s",
                      event_id, event_type)
        raise
    finally:
        session.close()


# ============================================================================
#   Cancel / downgrade (Sitting D)
# ============================================================================
#
# One endpoint serves both providers — we look at sub.provider and route the
# external cancellation accordingly:
#   - PayPal: call cancel_subscription() to STOP recurring billing at PayPal.
#   - Paymob: no external call (our model bills via one-time charges + cron
#             extends current_period_end on PAYMENT.SALE.COMPLETED).
#
# In both cases the DB row goes to status='cancelled' with cancelled_at=now.
# We DO NOT downgrade user.plan immediately — they keep access until
# current_period_end (then cron_renewals.expire_cancelled() flips them to free).

@app.post("/billing/cancel")
def billing_cancel(request: Request, csrf_token: str = Form("")):
    """Cancel the user's currently-active (or past-due) subscription. Keeps
    access until the end of the current billing period.

    Idempotent: re-running on an already-cancelled sub is a no-op."""
    _require_csrf(request, csrf_token)
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login?next=/account%23subscription",
                                    status_code=303)

        sub = (session.query(models.Subscription)
               .filter_by(user_id=user.id)
               .filter(models.Subscription.status.in_(("active", "past_due")))
               .order_by(models.Subscription.created_at.desc())
               .first())

        if not sub:
            log.info("billing/cancel: user=%s has no active subscription", user.id)
            return RedirectResponse("/account?cancel=no_active_sub#subscription",
                                    status_code=303)

        # External provider cancellation FIRST — if it fails we don't change
        # local state, so the user can retry. (Reverse order would risk us
        # showing "cancelled" while PayPal keeps billing them.)
        if sub.provider == "paypal":
            try:
                _paypal.cancel_subscription(
                    sub.external_id,
                    reason=f"User cancelled via /account · {datetime.utcnow().isoformat()}",
                )
                log.info("paypal cancel: user=%s sub=%s external=%s",
                         user.id, sub.id, sub.external_id)
            except _paypal.PayPalError as exc:
                # Already-cancelled at PayPal is fine — surface as success.
                if "SUBSCRIPTION_STATUS_INVALID" in str(exc):
                    log.info("paypal cancel: sub=%s already cancelled at PayPal",
                             sub.id)
                else:
                    log.error("paypal cancel failed: %s", exc)
                    return RedirectResponse(
                        "/account?cancel=provider_error#subscription",
                        status_code=303)

        # Local state change + audit trail.
        now = datetime.utcnow()
        sub.status = "cancelled"
        sub.cancelled_at = now
        sub.updated_at = now

        evt = models.PaymentEvent(
            provider=sub.provider,
            external_id=f"cancel-{sub.id}-{int(now.timestamp())}",
            event_type=f"{sub.provider}.subscription.cancelled_by_user",
            subscription_id=sub.id,
            user_id=user.id,
            amount_usd=sub.amount_usd,
            raw_payload=(f'{{"cancelled_by": "user", '
                         f'"at": "{now.isoformat()}", '
                         f'"period_end": "{sub.current_period_end.isoformat() if sub.current_period_end else None}"}}'),
            processed_at=now,
        )
        session.add(evt)
        session.commit()
        log.info("billing/cancel: user=%s sub=%s provider=%s -> cancelled",
                 user.id, sub.id, sub.provider)
        return RedirectResponse("/account?cancel=ok#subscription",
                                status_code=303)
    except Exception:
        session.rollback()
        log.exception("billing/cancel failed for user request")
        raise
    finally:
        session.close()


