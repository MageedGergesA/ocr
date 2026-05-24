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

from app.services import extractor  # noqa: E402  (after load_dotenv so env is ready)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Mostakhles API", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/app", response_class=HTMLResponse)
def demo_app(request: Request):
    return templates.TemplateResponse(request, "app.html")


@app.post("/v1/extract")
async def extract_endpoint(
    file: UploadFile = File(...),
    target_schema: str = Form(""),  # optional — empty/omitted means auto-detect
    hard: bool = Form(True),
    x_api_key: str = Header(None),
):
    # TODO(#5): validate x_api_key against Postgres; TODO(#6): Redis usage + free-tier 429.
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(500, "ANTHROPIC_API_KEY not configured on server")

    schema = None
    if target_schema and target_schema.strip() not in ("", "{}"):
        try:
            schema = json.loads(target_schema)
        except json.JSONDecodeError:
            raise HTTPException(400, "target_schema must be valid JSON: {field: description}")

    image_bytes = await file.read()
    try:
        if schema:
            data = extractor.extract_schema(image_bytes, file.content_type, schema, hard=hard)
            return {"mode": "schema", "document_type": None, "data": data}
        result = extractor.extract_auto(image_bytes, file.content_type, hard=hard)
        # auto mode returns {document_type, fields}; flatten to a stable response shape
        return {
            "mode": "auto",
            "document_type": result.get("document_type"),
            "data": result.get("fields", result),
        }
    except Exception as e:  # noqa: BLE001 — surface model/parse errors to caller for now
        raise HTTPException(502, f"extraction failed: {e}")
