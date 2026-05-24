"""Mostakhles API — Arabic-first document extraction.

One backend, thin clients (Odoo module, web app, public API).
This file wires routes only; real work lives in services/.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()

from app import auth, db  # noqa: E402
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
    return templates.TemplateResponse(request, "app.html")


@app.get("/v1/usage")
def usage(x_api_key: str = Header(None)):
    """Report the caller's current-month usage and quota."""
    session = db.SessionLocal()
    try:
        api_key = auth.resolve_key(session, x_api_key or auth.DEMO_API_KEY)
        used, limit, _ = auth.get_usage(session, api_key)
        return {"plan": api_key.user.plan, "used": used, "limit": limit,
                "remaining": max(0, limit - used)}
    finally:
        session.close()


@app.post("/v1/extract")
async def extract_endpoint(
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

    image_bytes = await file.read()
    if len(image_bytes) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large (max 20 MB)")

    # Auth + free-tier enforcement. No key => the public demo account.
    session = db.SessionLocal()
    try:
        api_key = auth.resolve_key(session, x_api_key or auth.DEMO_API_KEY)
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
