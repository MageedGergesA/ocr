"""FastAPI dependency injection.

Adoption is gradual — existing routes still open `db.SessionLocal()` manually.
New routes (and refactored ones) should use these `Depends(...)` instead.

Example:
    @app.get("/me")
    def me(user: models.User = Depends(require_user)):
        return {"email": user.email}
"""
from typing import Generator, Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session as DBSession

from app import auth, db, models


def get_db() -> Generator[DBSession, None, None]:
    """Per-request DB session. Always closed, even on exception."""
    s = db.SessionLocal()
    try:
        yield s
    finally:
        s.close()


def get_session_token(sid: Optional[str] = Cookie(None)) -> Optional[str]:
    return sid


def current_user(
    request: Request,
    s: DBSession = Depends(get_db),
    sid: Optional[str] = Depends(get_session_token),
) -> Optional[models.User]:
    """Return the logged-in user or None. Never raises — use `require_user` to enforce."""
    return auth.user_from_session(s, sid)


def require_user(
    request: Request,
    s: DBSession = Depends(get_db),
    sid: Optional[str] = Depends(get_session_token),
) -> models.User:
    """Same as current_user but raises 401 if no session.
    For HTML pages prefer the current routes' RedirectResponse-to-/login pattern;
    use this only for API routes that should return 401 JSON."""
    user = auth.user_from_session(s, sid)
    if not user:
        raise HTTPException(401, "login required")
    return user


def current_api_key(
    request: Request,
    s: DBSession = Depends(get_db),
    sid: Optional[str] = Depends(get_session_token),
    x_api_key: Optional[str] = Header(None),
) -> models.ApiKey:
    """Resolve the calling identity (API key OR session) and return the active key.
    Same gates as the old `_resolve_caller`: email verification required unless demo."""
    if x_api_key:
        key = auth.resolve_key(s, x_api_key)
    else:
        user = auth.user_from_session(s, sid)
        if not user:
            raise HTTPException(401, "login required, or provide a valid x-api-key")
        key = (s.query(models.ApiKey)
                .filter_by(user_id=user.id, active=True).first())
        if not key:
            raise HTTPException(401, "login required, or provide a valid x-api-key")
    if key.user.plan != "demo" and not getattr(key.user, "email_verified", True):
        raise HTTPException(
            403, "verify your email first — check your inbox for the activation link",
        )
    return key


# NOTE: CSRF enforcement lives in `main._require_csrf` until we mechanically
# adopt Depends() across all 40 routes. Avoid creating a parallel implementation
# here — having two CSRF code paths is a foot-gun: future contributors will
# update one and forget the other. When the router split lands, move the canonical
# implementation here and delete `main._require_csrf`.


def request_id(request: Request) -> str:
    """Pulled from RequestIDMiddleware; falls back to '-' if middleware bypassed."""
    return getattr(request.state, "request_id", "-")
