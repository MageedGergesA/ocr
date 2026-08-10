"""P0.2 — API keys are stored hashed, never plaintext.

Regression for the discovery finding: api_keys.key held the raw credential, so a
DB dump exposed usable keys for every tenant. These tests prove keys authenticate
by hash, the raw is never persisted, lookup/revocation still work, and a
"legacy" key (migrated by hashing its known raw) keeps working.
"""
import hashlib

from app import db, models


def _row_for(raw: str):
    s = db.SessionLocal()
    try:
        return s.query(models.ApiKey).filter_by(
            key_hash=models.hash_api_key(raw)).first()
    finally:
        s.close()


def test_new_key_authenticates_and_is_stored_hashed(client, user_factory, api_key_factory):
    u = user_factory()
    raw = api_key_factory(u.uid)
    # It works as a credential.
    r = client.get("/v1/usage", headers={"x-api-key": raw})
    assert r.status_code == 200, r.text
    # It is stored as sha256(raw), NOT as the raw value.
    row = _row_for(raw)
    assert row is not None
    assert row.key_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert row.key_hash != raw
    # The display prefix is the non-secret fragment only.
    assert row.key_prefix == raw[:12]
    assert len(row.key_prefix) < len(raw)


def test_apikey_model_has_no_plaintext_column():
    """A DB dump must not reveal usable credentials: there is no `key` column."""
    cols = {c.name for c in models.ApiKey.__table__.columns}
    assert "key" not in cols
    assert "key_hash" in cols and "key_prefix" in cols


def test_wrong_key_rejected(client):
    r = client.get("/v1/usage", headers={"x-api-key": "mk_definitely_not_valid"})
    assert r.status_code == 401


def test_revoked_key_rejected(client, user_factory, api_key_factory):
    u = user_factory()
    raw = api_key_factory(u.uid)
    assert client.get("/v1/usage", headers={"x-api-key": raw}).status_code == 200
    # Revoke by flipping active (mirrors /dashboard/keys/{id}/revoke).
    s = db.SessionLocal()
    try:
        row = s.query(models.ApiKey).filter_by(key_hash=models.hash_api_key(raw)).first()
        row.active = False
        s.commit()
    finally:
        s.close()
    assert client.get("/v1/usage", headers={"x-api-key": raw}).status_code == 401


def test_legacy_key_still_works_after_migration(client, user_factory):
    """Simulate the migration backfill: a pre-existing raw key whose HASH we store
    (exactly what upgrade() does) must keep authenticating with the same raw the
    customer already holds — no key invalidation."""
    u = user_factory()
    legacy_raw = "mk_legacy_customer_key_value_kept"
    s = db.SessionLocal()
    try:
        usr = s.get(models.User, u.uid)
        usr.email_verified = True
        s.add(models.ApiKey(user_id=u.uid,
                            key_hash=models.hash_api_key(legacy_raw),
                            key_prefix=models.api_key_prefix(legacy_raw)))
        s.commit()
    finally:
        s.close()
    r = client.get("/v1/usage", headers={"x-api-key": legacy_raw})
    assert r.status_code == 200, r.text


def test_create_key_endpoint_reveals_once_then_masks(client, user_factory):
    """POST /dashboard/keys must reveal the raw key exactly once (via the one-time
    cookie) and the dashboard must never render a full stored key afterwards."""
    u = user_factory()
    # An API key implies a real account; verify the email so the extraction gate
    # doesn't mask the auth we're actually testing.
    s = db.SessionLocal()
    try:
        usr = s.get(models.User, u.uid); usr.email_verified = True; s.commit()
    finally:
        s.close()
    client.cookies.set("sid", u.sid)
    try:
        # Create a key (CSRF-protected form post); don't follow the redirect so we
        # can inspect the one-time cookie.
        r = client.post("/dashboard/keys", data={"csrf_token": u.csrf},
                        follow_redirects=False)
        assert r.status_code == 303
        revealed = r.cookies.get("mk_new_key")
        assert revealed and revealed.startswith("mk_")
        # The revealed key authenticates.
        assert client.get("/v1/usage", headers={"x-api-key": revealed}).status_code == 200
        # A later dashboard load without the cookie must NOT contain the full key.
        client.cookies.delete("mk_new_key")
        page = client.get("/dashboard")
        assert page.status_code == 200
        assert revealed not in page.text          # full secret never rendered
        assert revealed[:12] in page.text          # only the prefix is shown
    finally:
        client.cookies.clear()
