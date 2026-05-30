"""Custom exception hierarchy + FastAPI handlers.

Routes should raise these typed exceptions instead of bare `HTTPException(...)`
strings. Handlers below map them to clean JSON responses with consistent shape:
    {"error": "<code>", "message": "<human-readable>", "request_id": "..."}
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class MostakhlesError(Exception):
    """Base. Subclasses set `status_code` and `code`."""
    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str = ""):
        self.message = message or self.code
        super().__init__(self.message)


class QuotaExhausted(MostakhlesError):
    status_code = 429
    code = "quota_exhausted"


class BudgetCircuitOpen(MostakhlesError):
    status_code = 503
    code = "budget_circuit_open"


class ProviderError(MostakhlesError):
    status_code = 502
    code = "provider_error"


class ValidationError(MostakhlesError):
    status_code = 400
    code = "validation_error"


class AuthError(MostakhlesError):
    status_code = 401
    code = "auth_required"


class ForbiddenError(MostakhlesError):
    status_code = 403
    code = "forbidden"


class NotFoundError(MostakhlesError):
    status_code = 404
    code = "not_found"


def _payload(exc: MostakhlesError, request: Request) -> dict:
    return {
        "error": exc.code,
        "message": exc.message,
        "request_id": getattr(request.state, "request_id", "-"),
    }


def register_handlers(app: FastAPI) -> None:
    """Wire the handlers. Call once from main.py after `app = FastAPI(...)`."""

    @app.exception_handler(MostakhlesError)
    async def handle_typed(request: Request, exc: MostakhlesError):
        return JSONResponse(status_code=exc.status_code, content=_payload(exc, request))
