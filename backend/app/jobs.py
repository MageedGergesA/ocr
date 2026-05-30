"""Background batch jobs for large PDFs.

A big PDF is split into single pages, each extracted in its own model call
(so nothing truncates or blows the context window). Runs in a daemon thread;
progress + partial results are kept in an in-memory store the /v1/jobs route polls.

Note: in-memory = single-process only. On a multi-worker/prod deploy, back this
with Redis or the DB. Fine for the local MVP.
"""
import json as _json
import threading
import time as _time
import uuid
from datetime import datetime

import httpx

from app import auth, models
from app.db import SessionLocal
from app.services import extractor, llm

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
    except llm.GeminiBudgetExhausted:
        # Daily $ ceiling hit mid-batch — re-raise so the WHOLE job aborts cleanly.
        # Without this re-raise the per-page exception would be swallowed and the
        # job would report "completed" with N silent failures.
        raise
    except llm.GeminiDailyQuotaExhausted:
        # Same logic: a daily Gemini quota failure should kill the batch loudly,
        # not log per-page as if it were a content issue.
        raise
    except Exception as e:  # noqa: BLE001 — content-level errors, keep going
        return {"page": index, "error": str(e)}


def _deliver_webhook(
    db, user: models.User, hook: str, job_id: str, event_kind: str,
    body_dict: dict,
) -> None:
    """Persist a WebhookDelivery row, sign + POST, then update the row with the
    outcome. We persist ONLY metadata — a short summary of the event, the URL,
    the response code — never the document content. Aligns with the privacy
    policy ("results saved in your history, deletable anytime"). The body itself
    is sent to the customer but not kept on our side beyond the request lifetime."""
    # SSRF gate first — don't even create a delivery row if the URL is unsafe.
    if not auth.is_safe_webhook_url(hook):
        return

    # Auto-provision the per-user HMAC secret on first use (session is OPEN here).
    if not user.webhook_secret:
        user.webhook_secret = models.generate_webhook_secret()
        db.commit()

    body = _json.dumps(body_dict, ensure_ascii=False).encode()
    ts = str(int(_time.time()))
    signature = auth.sign_webhook_payload(user.webhook_secret, body, ts)
    delivery_id = uuid.uuid4().hex

    # Persist BEFORE we attempt the POST so the audit trail survives a crash.
    # `payload` holds a SUMMARY only (job_id + status + page-count) — never the
    # extracted document content.
    summary = _json.dumps({
        "job_id": body_dict.get("job_id"),
        "status": body_dict.get("status"),
        "page_count": len(body_dict.get("pages") or []),
        "successful_pages": sum(
            1 for p in (body_dict.get("pages") or []) if "error" not in p
        ),
    }, ensure_ascii=False)
    delivery = models.WebhookDelivery(
        user_id=user.id,
        target_url=hook,
        event_kind=event_kind,
        payload=summary,
        status="pending",
        attempt_count=1,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    try:
        resp = httpx.post(
            hook, content=body, timeout=10, follow_redirects=False,
            headers={
                "content-type": "application/json",
                "x-mostakhles-timestamp": ts,
                "x-mostakhles-signature": signature,
                "x-mostakhles-delivery-id": delivery_id,
            },
        )
        delivery.last_status_code = resp.status_code
        if 200 <= resp.status_code < 300:
            delivery.status = "delivered"
            delivery.delivered_at = datetime.utcnow()
        else:
            delivery.status = "failed"
            delivery.last_error = f"non-2xx: {resp.status_code}"
    except Exception as e:  # noqa: BLE001 — network errors, customer's URL down, etc.
        delivery.status = "failed"
        delivery.last_error = f"{type(e).__name__}: {e}"
    db.commit()


def _persist_and_notify(
    job_id: str, results: list, success: int, hard: bool,
    api_key_id: int, terminal_status: str, error_msg: str | None,
) -> None:
    """Single persistence path used by BOTH the success and abort branches.

    Whatever pages succeeded BEFORE we hit a budget/quota wall must still be
    charged to the user, recorded in history, and delivered via webhook —
    otherwise we silently lose work the customer paid Google credits for.
    """
    db = SessionLocal()
    try:
        api_key = db.get(models.ApiKey, api_key_id)
        if not api_key:
            return
        if success:
            auth.increment_usage(db, api_key, count=success * auth.credits_for(hard))
        user = api_key.user
        # History row reflects ACTUAL completed pages, not the original total.
        db.add(models.History(
            user_id=user.id, kind="batch", document_type=None,
            charged=success * auth.credits_for(hard),
            result_json=results,
        ))
        db.commit()
        # Webhook event kind tells the customer what really happened.
        if user.webhook_url:
            event_kind = "job.completed" if terminal_status == "completed" else "job.partial_failed"
            _deliver_webhook(
                db, user, user.webhook_url, job_id, event_kind,
                {"job_id": job_id, "status": terminal_status,
                 "pages": results, "error": error_msg},
            )
    finally:
        db.close()


def _run(job_id: str, pdf_bytes: bytes, hard: bool, api_key_id: int) -> None:
    results: list = []
    success = 0
    try:
        pages = extractor.split_pdf_pages(pdf_bytes)
        for i, page_bytes in enumerate(pages, start=1):
            res = _extract_page(page_bytes, i, hard)
            results.append(res)
            if "error" not in res:
                success += 1
            _update(job_id, done_pages=i, pages=list(results))
        _persist_and_notify(
            job_id, results, success, hard, api_key_id,
            terminal_status="completed", error_msg=None,
        )
        _update(job_id, status="completed")
    except llm.GeminiBudgetExhausted as e:
        # Persist what we did finish, then fail the job loudly. Customer is only
        # charged for completed pages, not the failed ones.
        msg = f"daily budget exhausted: {e}"
        _persist_and_notify(job_id, results, success, hard, api_key_id,
                            terminal_status="partial_failed", error_msg=msg)
        _update(job_id, status="failed", error=msg, partial_success=success)
    except llm.GeminiDailyQuotaExhausted as e:
        msg = f"daily Gemini quota exhausted: {e}"
        _persist_and_notify(job_id, results, success, hard, api_key_id,
                            terminal_status="partial_failed", error_msg=msg)
        _update(job_id, status="failed", error=msg, partial_success=success)
    except Exception as e:  # noqa: BLE001
        # Last-ditch: try to persist anything we did manage to extract.
        try:
            _persist_and_notify(job_id, results, success, hard, api_key_id,
                                terminal_status="partial_failed", error_msg=str(e))
        except Exception:  # noqa: BLE001
            pass
        _update(job_id, status="failed", error=str(e), partial_success=success)


def start_batch(pdf_bytes: bytes, hard: bool, api_key_id: int, total_pages: int) -> str:
    job_id = uuid.uuid4().hex
    with _LOCK:
        _JOBS[job_id] = {"status": "processing", "total_pages": total_pages,
                         "done_pages": 0, "pages": [], "error": None}
    threading.Thread(
        target=_run, args=(job_id, pdf_bytes, hard, api_key_id), daemon=True,
    ).start()
    return job_id
