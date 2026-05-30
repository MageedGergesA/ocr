"""Centralised configuration. Pydantic Settings reads from `.env` + environment
and validates types at startup, so a missing or malformed value crashes loudly
on boot rather than silently misbehaving on the 1000th request.

Usage:
    from app.config import settings
    settings.DATABASE_URL
    settings.GEMINI_API_KEY

This file gradually replaces scattered `os.getenv(...)` calls. Existing code
still works — adoption is route-by-route.
"""
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        # Reject unknown env vars so typo'd keys (DATABSE_URL etc.) crash loudly
        # instead of silently falling back to the default. If you add a new env var,
        # declare it as a field below. Unrelated host env vars are not validated
        # because pydantic-settings only reads keys present in the .env file by default.
        extra="forbid",
    )

    # ---- Environment ----
    ENV: Literal["local", "dev", "staging", "prod"] = "local"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["plain", "json"] = "plain"

    # ---- Database ----
    DATABASE_URL: str = "sqlite:///./mostakhles.db"

    # ---- LLM (Gemini) ----
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL_EASY: str = "gemini-3.1-flash-lite"
    GEMINI_MODEL_HARD: str = "gemini-3.5-flash"
    GEMINI_TIMEOUT_MS: int = 60_000
    MAX_DAILY_GEMINI_USD: float = 50.0
    EST_COST_PER_CREDIT_USD: float = 0.0019

    # ---- Plan limits + pricing ----
    STRONG_UNITS: int = 8
    DEMO_MONTHLY_LIMIT: int = 2000
    DEMO_API_KEY: str = "mk_demo_public"

    # ---- Auth + sessions ----
    SESSION_TTL_DAYS: int = 30
    COOKIE_SECURE: bool = True

    # ---- Admin ----
    ADMIN_EMAILS: str = "mageed.gerges28@gmail.com"

    # ---- SMTP ----
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_SSL: bool = False  # True for implicit TLS on port 465

    # ---- Cloudflare Turnstile ----
    CF_TURNSTILE_SECRET: str = ""
    CF_TURNSTILE_SITEKEY: str = ""

    # ---- Sentry ----
    SENTRY_DSN: str = ""
    SENTRY_TRACES_RATE: float = 0.05
    SENTRY_ENV: str = "local"

    # ---- HTTP / proxy / CORS ----
    ALLOWED_HOSTS: str = (
        "localhost,127.0.0.1,mostakhles.ai,www.mostakhles.ai,"
        "mostakhles.app,www.mostakhles.app"
    )
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://127.0.0.1:8000"

    # ---- File limits ----
    MAX_UPLOAD_MB: int = 20
    MAX_PDF_PAGES: int = 100
    PDF_NATIVE_MAX_PAGES: int = 5
    MAX_JSON_BODY_KB: int = 2048

    # ---- Login rate-limit ----
    LOGIN_RATE_MAX: int = 5
    LOGIN_RATE_WINDOW_SEC: int = 900

    # ---- Payment providers ----
    PAYPAL_CLIENT_ID: str = ""
    PAYPAL_SECRET: str = ""
    PAYPAL_WEBHOOK_ID: str = ""
    PAYPAL_MODE: Literal["sandbox", "live"] = "sandbox"
    PAYMOB_API_KEY: str = ""
    PAYMOB_HMAC: str = ""
    PAYMOB_IFRAME_ID: str = ""

    @property
    def admin_email_set(self) -> frozenset[str]:
        return frozenset(
            e.strip().lower() for e in self.ADMIN_EMAILS.split(",") if e.strip()
        )

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"

    def assert_production_ready(self) -> None:
        """Fail-fast guard. Call from startup when ENV=prod so a half-configured
        release crashes immediately rather than silently misbehaving."""
        if not self.is_prod:
            return
        missing = []
        for required in (
            "DATABASE_URL", "GEMINI_API_KEY", "SMTP_HOST", "SMTP_FROM",
            "SENTRY_DSN", "ALLOWED_HOSTS", "ALLOWED_ORIGINS",
        ):
            if not getattr(self, required):
                missing.append(required)
        if missing:
            raise RuntimeError(
                f"Production env vars missing/empty: {', '.join(missing)}. "
                "Set them in /etc/mostakhles.env or your secret manager."
            )


settings = Settings()
