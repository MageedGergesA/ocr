"""Shared pytest fixtures.

Hermetic: a throwaway SQLite database and stubbed Paymob credentials are wired
into the environment BEFORE the app is imported, so the suite never touches the
dev Postgres, the real `.env` Paymob keys, or the network. The app's own startup
(`init_db`) creates the schema on the temp DB.
"""
import os
import tempfile
import uuid

# --- environment MUST be set before any `app.*` import ---------------------
_TMPDIR = tempfile.mkdtemp(prefix="mostakhles-pytest-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"
os.environ["ENV"] = "local"
# TestClient talks to host "testserver"; TrustedHostMiddleware would 400 it
# otherwise (the real .env pins ALLOWED_HOSTS to the prod domain).
os.environ["ALLOWED_HOSTS"] = "testserver,localhost,127.0.0.1"
# Deterministic Paymob test config (mock — never hits Paymob).
os.environ["PAYMOB_API_KEY"] = "test_key"
os.environ["PAYMOB_HMAC"] = "test_hmac_secret"
os.environ["PAYMOB_IFRAME_ID"] = "999"
os.environ["PAYMOB_INTEGRATION_ID"] = "legacy0"
os.environ["PAYMOB_INTEGRATION_ID_USD"] = "1111"
os.environ["PAYMOB_INTEGRATION_ID_EGP"] = "2222"
os.environ["PAYMOB_CURRENCIES"] = "USD,EGP"
os.environ["EGP_PER_USD"] = "50"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

PAYMOB_HMAC = os.environ["PAYMOB_HMAC"]


@pytest.fixture(scope="session")
def client():
    """A TestClient with the app's lifespan (startup → init_db) active."""
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def user_factory():
    """Return a callable that creates a fresh user + web session and returns a
    small handle (uid, email, sid, csrf). Cleans up created users afterward."""
    from app import db, models, auth

    created: list[int] = []

    def make(plan="free"):
        s = db.SessionLocal()
        email = f"pytest_{uuid.uuid4().hex[:10]}@example.com"
        u = models.User(email=email, password_hash=auth.hash_password("x"), plan=plan)
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id
        sid = auth.create_session(s, u)
        csrf = auth.session_csrf_token(s, sid)
        s.close()
        created.append(uid)
        return type("U", (), {"uid": uid, "email": email, "sid": sid, "csrf": csrf})

    yield make

    s = db.SessionLocal()
    if created:
        s.query(models.PaymentEvent).filter(models.PaymentEvent.user_id.in_(created)).delete(synchronize_session=False)
        s.query(models.Subscription).filter(models.Subscription.user_id.in_(created)).delete(synchronize_session=False)
        s.query(models.Session).filter(models.Session.user_id.in_(created)).delete(synchronize_session=False)
        s.query(models.ApiKey).filter(models.ApiKey.user_id.in_(created)).delete(synchronize_session=False)
        s.query(models.User).filter(models.User.id.in_(created)).delete(synchronize_session=False)
        s.commit()
    s.close()
