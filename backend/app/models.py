"""Data models: users, API keys, monthly usage counters."""
import secrets
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


def generate_key() -> str:
    return "mk_" + secrets.token_urlsafe(32)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=True)  # null for the seeded demo user
    plan = Column(String, default="free", nullable=False)  # free/starter/pro/business/demo
    webhook_url = Column(String, nullable=True)  # POST results here when async jobs finish
    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("ApiKey", back_populates="user")


class Session(Base):
    """Server-side web session — token lives in an httponly cookie."""
    __tablename__ = "sessions"

    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True, nullable=False, default=generate_key)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="api_keys")


class Usage(Base):
    """One row per (api_key, month). Incremented on each successful extraction."""
    __tablename__ = "usage"

    id = Column(Integer, primary_key=True)
    api_key_id = Column(Integer, ForeignKey("api_keys.id"), nullable=False)
    period = Column(String, nullable=False)  # 'YYYY-MM'
    count = Column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("api_key_id", "period", name="uq_key_period"),)


class Template(Base):
    """A reusable named field schema saved by a user."""
    __tablename__ = "templates"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    schema_json = Column(Text, nullable=False)  # {field: description}
    created_at = Column(DateTime, default=datetime.utcnow)


class History(Base):
    """A record of every successful extraction, per user."""
    __tablename__ = "history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    kind = Column(String)              # service slug or 'extract'
    document_type = Column(String, nullable=True)
    charged = Column(Integer, default=0)
    result_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
