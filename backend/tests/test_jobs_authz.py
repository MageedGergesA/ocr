"""P0.1 — ownership authorization on GET /v1/jobs/{job_id}.

Regression for the discovery finding: possession of a batch-job UUID was enough
to read another tenant's extracted document (no auth, no ownership check). These
tests inject a job straight into the in-memory store (no Gemini call) and prove:

  - the owner can read it (and legitimate polling shape is preserved)
  - a DIFFERENT authenticated user gets 404 (the old attack), not the document
  - an unauthenticated caller cannot read it
  - a missing id is indistinguishable from a not-owned id (no existence oracle)
  - the internal `owner_user_id` never leaks into the response
"""
from app import jobs


def _seed_job(owner_user_id: int, job_id: str = "job_test_fixedid") -> str:
    """Insert a completed-looking job owned by `owner_user_id`. Mirrors the shape
    start_batch/_run produce, including document data a leak would expose."""
    jobs._JOBS[job_id] = {
        "status": "completed",
        "total_pages": 1,
        "done_pages": 1,
        "pages": [{"page": 1, "document_type": "invoice",
                   "data": {"total": {"value": "SAR 9,999", "confidence": 0.98}}}],
        "error": None,
        "owner_user_id": owner_user_id,
    }
    return job_id


def _cleanup(job_id: str) -> None:
    jobs._JOBS.pop(job_id, None)


def test_owner_can_read_job_and_shape_preserved(client, user_factory, api_key_factory):
    owner = user_factory()
    key = api_key_factory(owner.uid)
    job_id = _seed_job(owner.uid)
    try:
        r = client.get(f"/v1/jobs/{job_id}", headers={"x-api-key": key})
        assert r.status_code == 200, r.text
        body = r.json()
        # Poll response shape is unchanged: the documented fields are all present.
        assert body["job_id"] == job_id
        assert body["status"] == "completed"
        assert body["total_pages"] == 1 and body["done_pages"] == 1
        assert body["pages"][0]["document_type"] == "invoice"
        assert body["error"] is None
        # The internal ownership marker must NOT be exposed.
        assert "owner_user_id" not in body
    finally:
        _cleanup(job_id)


def test_other_user_cannot_read_job(client, user_factory, api_key_factory):
    """THE attack: a second, fully-authenticated tenant must not read the job."""
    owner = user_factory()
    attacker = user_factory()
    attacker_key = api_key_factory(attacker.uid)
    job_id = _seed_job(owner.uid)
    try:
        r = client.get(f"/v1/jobs/{job_id}", headers={"x-api-key": attacker_key})
        assert r.status_code == 404, r.text
        # No document content leaks in the error body.
        assert "SAR 9,999" not in r.text
        assert "invoice" not in r.text
    finally:
        _cleanup(job_id)


def test_unauthenticated_cannot_read_job(client, user_factory):
    owner = user_factory()
    job_id = _seed_job(owner.uid)
    try:
        r = client.get(f"/v1/jobs/{job_id}")
        assert r.status_code == 401, r.text
        assert "SAR 9,999" not in r.text
    finally:
        _cleanup(job_id)


def test_missing_and_not_owned_are_indistinguishable(client, user_factory, api_key_factory):
    """A not-owned job and a nonexistent job return the SAME 404 — no oracle that
    reveals whether another tenant's job exists."""
    owner = user_factory()
    other = user_factory()
    other_key = api_key_factory(other.uid)
    job_id = _seed_job(owner.uid)
    try:
        not_owned = client.get(f"/v1/jobs/{job_id}", headers={"x-api-key": other_key})
        missing = client.get("/v1/jobs/does_not_exist_at_all", headers={"x-api-key": other_key})
        assert not_owned.status_code == missing.status_code == 404
        assert not_owned.json() == missing.json()
    finally:
        _cleanup(job_id)


def test_invalid_key_is_rejected(client, user_factory):
    owner = user_factory()
    job_id = _seed_job(owner.uid)
    try:
        r = client.get(f"/v1/jobs/{job_id}", headers={"x-api-key": "mk_not_a_real_key"})
        assert r.status_code == 401, r.text
    finally:
        _cleanup(job_id)
