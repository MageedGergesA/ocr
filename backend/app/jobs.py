"""Background batch jobs for large PDFs.

A big PDF is split into single pages, each extracted in its own Claude call
(so nothing truncates or blows the context window). Runs in a daemon thread;
progress + partial results are kept in an in-memory store the /v1/jobs route polls.

Note: in-memory = single-process only. On a multi-worker/prod deploy, back this
with Redis or the DB. Fine for the local MVP.
"""
import threading
import uuid

from app import auth, models
from app.db import SessionLocal
from app.services import extractor

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _update(job_id: str, **fields) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


def get_job(job_id: str):
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job else None


def _extract_page(page_bytes: bytes, index: int, hard: bool) -> dict:
    try:
        r = extractor.extract_auto(page_bytes, "application/pdf", hard=hard)
        return {"page": index, "document_type": r.get("document_type"), "data": r.get("fields", r)}
    except Exception as e:  # noqa: BLE001 — record the per-page error, keep going
        return {"page": index, "error": str(e)}


def _run(job_id: str, pdf_bytes: bytes, hard: bool, api_key_id: int) -> None:
    try:
        pages = extractor.split_pdf_pages(pdf_bytes)
        results, success = [], 0
        for i, page_bytes in enumerate(pages, start=1):
            res = _extract_page(page_bytes, i, hard)
            results.append(res)
            if "error" not in res:
                success += 1
            _update(job_id, done_pages=i, pages=list(results))

        # Charge usage once, for the pages that succeeded (credits per page).
        if success:
            db = SessionLocal()
            try:
                api_key = db.get(models.ApiKey, api_key_id)
                if api_key:
                    auth.increment_usage(db, api_key, count=success * auth.credits_for(hard))
            finally:
                db.close()
        _update(job_id, status="completed")
    except Exception as e:  # noqa: BLE001
        _update(job_id, status="failed", error=str(e))


def start_batch(pdf_bytes: bytes, hard: bool, api_key_id: int, total_pages: int) -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {"status": "processing", "total_pages": total_pages,
                         "done_pages": 0, "pages": [], "error": None}
    threading.Thread(
        target=_run, args=(job_id, pdf_bytes, hard, api_key_id), daemon=True,
    ).start()
    return job_id
