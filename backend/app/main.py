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
from app.services_catalog import CATEGORIES, SERVICES  # noqa: E402

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
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server")
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
            raise HTTPException(502, f"extraction failed: {e}")
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
            raise HTTPException(502, f"chat failed: {e}")
        auth.increment_usage(session, api_key, count=1)
        used, limit, _ = auth.get_usage(session, api_key)
        return {"answer": answer, "usage": {"used": used, "limit": limit,
                "remaining": max(0, limit - used), "charged": 1}}
    finally:
        session.close()


@app.get("/tools", response_class=HTMLResponse)
def tools_hub(request: Request):
    return templates.TemplateResponse(request, "tools.html",
                                      _ctx(request, services=SERVICES, categories=CATEGORIES))


@app.get("/tools/{slug}", response_class=HTMLResponse)
def tool_page(request: Request, slug: str):
    svc = SERVICES.get(slug)
    if not svc:
        return RedirectResponse("/tools", status_code=303)
    session = db.SessionLocal()
    try:
        if not _current_user(session, request):
            return RedirectResponse("/login", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "tool.html", _ctx(request, slug=slug, svc=svc))


# ---------- Web auth + dashboard ----------

COOKIE_KW = dict(httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)


def _current_user(session, request: Request):
    return auth.user_from_session(session, request.cookies.get("sid"))


def _ctx(request: Request, **extra):
    """Template context with the logged-in user (for the shared nav)."""
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
    finally:
        session.close()
    return {"user": user, **extra}


def _record_history(session, user, kind, document_type, data, charged):
    """Best-effort log of a successful extraction for the dashboard."""
    try:
        session.add(models.History(user_id=user.id, kind=kind, document_type=document_type,
                                   charged=charged, result_json=json.dumps(data, ensure_ascii=False)))
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


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
    session = db.SessionLocal()
    try:
        if _current_user(session, request):
            return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "signup.html", {"error": None, "user": None})


@app.post("/signup")
def signup(request: Request, email: str = Form(...), password: str = Form(...)):
    session = db.SessionLocal()
    try:
        email = email.strip().lower()
        if len(password) < 8:
            return templates.TemplateResponse(request, "signup.html",
                {"error": "كلمة المرور يجب أن تكون 8 أحرف على الأقل", "user": None}, status_code=400)
        if session.query(models.User).filter_by(email=email).first():
            return templates.TemplateResponse(request, "signup.html",
                {"error": "هذا البريد مسجّل بالفعل", "user": None}, status_code=400)
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
    session = db.SessionLocal()
    try:
        if _current_user(session, request):
            return RedirectResponse("/dashboard", status_code=303)
    finally:
        session.close()
    return templates.TemplateResponse(request, "login.html", {"error": None, "user": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    session = db.SessionLocal()
    try:
        user = session.query(models.User).filter_by(email=email.strip().lower()).first()
        if not user or not user.password_hash or not auth.verify_password(password, user.password_hash):
            return templates.TemplateResponse(request, "login.html",
                {"error": "بريد إلكتروني أو كلمة مرور غير صحيحة", "user": None}, status_code=401)
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
        tpls = (session.query(models.Template).filter_by(user_id=user.id)
                .order_by(models.Template.id.desc()).all())
        templates_list = [{"id": t.id, "name": t.name,
                          "fields": list(json.loads(t.schema_json).keys())} for t in tpls]
        hist = (session.query(models.History).filter_by(user_id=user.id)
                .order_by(models.History.id.desc()).limit(20).all())
        history_list = [{"id": h.id, "kind": h.kind, "document_type": h.document_type,
                        "charged": h.charged, "created_at": str(h.created_at)[:16]} for h in hist]
        return templates.TemplateResponse(request, "dashboard.html",
            {"user": user, "plan": user.plan, "limit": limit, "keys": keys,
             "templates": templates_list, "history": history_list,
             "webhook_url": user.webhook_url or ""})
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
             hard: bool = Form(True), x_api_key: str = Header(None)):
    """Run a catalog OCR service (text / fields / table / searchable PDF)."""
    svc = SERVICES.get(slug)
    if not svc:
        raise HTTPException(404, "unknown service")
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server")

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
        ct = file.content_type  # `hard` (Sonnet + thinking) comes from the request, default True
        try:
            if kind == "text":
                out = {"kind": "text", "text": extractor.run_text(data_bytes, ct, svc["prompt"], hard)}
            elif kind == "fields":
                out = {"kind": "fields", "data": extractor.extract_schema(data_bytes, ct, svc["schema"], hard)}
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
            raise HTTPException(502, f"service failed: {e}")

        auth.increment_usage(session, api_key, count=cost)
        _record_history(session, api_key.user, slug, out.get("document_type"),
                        out.get("data") or out.get("text") or out, cost)
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
        return [{"id": t.id, "name": t.name, "schema": json.loads(t.schema_json)} for t in tpls]
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
                                    schema_json=json.dumps(schema, ensure_ascii=False)))
        session.commit()
        return {"ok": True}
    finally:
        session.close()


@app.post("/dashboard/templates/{tid}/delete")
def delete_template(tid: int, request: Request):
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
@app.post("/dashboard/webhook")
def set_webhook(request: Request, webhook_url: str = Form("")):
    session = db.SessionLocal()
    try:
        user = _current_user(session, request)
        if not user:
            return RedirectResponse("/login", status_code=303)
        user.webhook_url = webhook_url.strip() or None
        session.commit()
        return RedirectResponse("/dashboard", status_code=303)
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
                "created_at": str(h.created_at), "result": json.loads(h.result_json) if h.result_json else None}
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
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server")
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
            raise HTTPException(502, f"compare failed: {e}")
        auth.increment_usage(session, api_key, count=cost)
        used, limit, _ = auth.get_usage(session, api_key)
        return {"report": report, "usage": {"used": used, "limit": limit,
                "remaining": max(0, limit - used), "charged": cost}}
    finally:
        session.close()


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
            auth.enforce_limit(session, api_key, needed=n_pages * auth.credits_for(hard))
            job_id = jobs.start_batch(image_bytes, hard, api_key.id, n_pages)
            return {"mode": "batch", "job_id": job_id, "total_pages": n_pages, "status": "processing"}

        # Single image or small PDF → one synchronous call.
        cost = auth.credits_for(hard)
        auth.enforce_limit(session, api_key, needed=cost)
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
        auth.increment_usage(session, api_key, count=cost)
        _record_history(session, api_key.user, mode, document_type, data, cost)
        used, limit, _ = auth.get_usage(session, api_key)
        return {
            "mode": mode,
            "document_type": document_type,
            "data": data,
            "usage": {"used": used, "limit": limit, "remaining": max(0, limit - used), "charged": cost},
        }
    finally:
        session.close()
