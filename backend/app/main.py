"""Mostakhles API — Arabic-first document extraction.

One backend, thin clients (Odoo module, web app, public API).
This file wires routes only; real work lives in services/.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

from app import auth, db, exports, jobs, models  # noqa: E402
from app.services import extractor  # noqa: E402  (after load_dotenv so env is ready)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Mostakhles API", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Create tables and seed the public demo key on startup.
db.init_db()
auth.ensure_demo_user()


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/app", response_class=HTMLResponse)
def demo_app(request: Request):
    session = db.SessionLocal()
    try:
        if not _current_user(session, request):
            return RedirectResponse("/login", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "app.html")


# ---------- Web auth + dashboard ----------

COOKIE_KW = dict(httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)


def _current_user(session, request: Request):
    return auth.user_from_session(session, request.cookies.get("sid"))


def _resolve_caller(session, x_api_key, request: Request):
    """Identify the caller: API key (programmatic) or logged-in session (web).
    No anonymous access — extraction always requires authentication."""
    if x_api_key:
        return auth.resolve_key(session, x_api_key)
    user = _current_user(session, request)
    if user:
        key = session.query(models.ApiKey).filter_by(user_id=user.id, active=True).first()
        if key:
            return key
    raise HTTPException(401, "login required, or provide a valid x-api-key")


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse(request, "signup.html", {"error": None})


@app.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...)):
    session = db.SessionLocal()
    try:
        email = email.strip().lower()
        if len(password) < 8:
            return templates.TemplateResponse(request, "signup.html",
                {"error": "كلمة المرور يجب أن تكون 8 أحرف على الأقل"}, status_code=400)
        if session.query(models.User).filter_by(email=email).first():
            return templates.TemplateResponse(request, "signup.html",
                {"error": "هذا البريد مسجّل بالفعل"}, status_code=400)
        user = models.User(email=email, password_hash=auth.hash_password(password), plan="free")
        session.add(user)
        session.commit()
        session.refresh(user)
        session.add(models.ApiKey(user_id=user.id))  # give them a first key
        session.commit()
        token = auth.create_session(session, user)
        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("sid", token, **COOKIE_KW)
        return resp
    finally:
        session.close()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    session = db.SessionLocal()
    try:
        user = session.query(models.User).filter_by(email=email.strip().lower()).first()
        if not user or not user.password_hash or not auth.verify_password(password, user.password_hash):
            return templates.TemplateResponse(request, "login.html",
                {"error": "بريد إلكتروني أو كلمة مرور غير صحيحة"}, status_code=401)
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


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
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
        return templates.TemplateResponse(request, "dashboard.html",
            {"user": user, "plan": user.plan, "limit": limit, "keys": keys})
    finally:
        session.close()


@app.post("/dashboard/keys")
def create_key(request: Request):
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
def revoke_key(key_id: int, request: Request):
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


@app.post("/v1/extract")
def extract_endpoint(  # sync def => FastAPI runs it in a threadpool, so the slow
                       # (synchronous) Claude call never blocks the event loop.
    request: Request,
    file: UploadFile = File(...),
    target_schema: str = Form(""),  # optional — empty/omitted means auto-detect
    hard: bool = Form(True),
    x_api_key: str = Header(None),
):
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server")

    schema = None
    if target_schema and target_schema.strip() not in ("", "{}"):
        try:
            schema = json.loads(target_schema)
        except json.JSONDecodeError:
            raise HTTPException(400, "target_schema must be valid JSON: {field: description}")

    allowed = {"image/png", "image/jpeg", "image/webp", "image/gif", "application/pdf"}
    if file.content_type not in allowed:
        raise HTTPException(415, f"unsupported file type: {file.content_type}. "
                                 "Use PNG, JPG, WEBP, GIF, or PDF.")

    image_bytes = file.file.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 20 MB)")

    n_pages = _count_pdf_pages(image_bytes) if file.content_type == "application/pdf" else None
    native_max = int(os.getenv("PDF_NATIVE_MAX_PAGES", "5"))  # ≤ this → one merged call
    hard_max = int(os.getenv("MAX_PDF_PAGES", "100"))         # > this → rejected

    # Auth + free-tier enforcement. No key => the public demo account.
    session = db.SessionLocal()
    try:
        api_key = _resolve_caller(session, x_api_key, request)

        # Large PDF → background batch job (one call per page; never truncates).
        if n_pages and n_pages > native_max:
            if n_pages > hard_max:
                raise HTTPException(413, f"this PDF has {n_pages} pages; the limit is {hard_max}. "
                                         "Split it into smaller files.")
            auth.enforce_limit(session, api_key, needed=n_pages)  # one unit per page
            job_id = jobs.start_batch(image_bytes, hard, api_key.id, n_pages)
            return {"mode": "batch", "job_id": job_id, "total_pages": n_pages, "status": "processing"}

        # Single image or small PDF → one synchronous call.
        auth.enforce_limit(session, api_key)
        try:
            if schema:
                data = extractor.extract_schema(image_bytes, file.content_type, schema, hard=hard)
                document_type, mode = None, "schema"
            else:
                result = extractor.extract_auto(image_bytes, file.content_type, hard=hard)
                data, document_type, mode = result.get("fields", result), result.get("document_type"), "auto"
        except Exception as e:  # noqa: BLE001 — surface model/parse errors; don't bill failures
            raise HTTPException(502, f"extraction failed: {e}")

        # Only meter successful extractions.
        auth.increment_usage(session, api_key)
        used, limit, _ = auth.get_usage(session, api_key)
        return {
            "mode": mode,
            "document_type": document_type,
            "data": data,
            "usage": {"used": used, "limit": limit, "remaining": max(0, limit - used)},
        }
    finally:
        session.close()
