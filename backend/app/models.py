"""Data models: users, API keys, monthly usage counters."""
import secrets
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db import Base


def generate_key() -> str:
    return "mk_" + secrets.token_urlsafe(32)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    plan = Column(String, default="free", nullable=False)  # free/starter/pro/business/demo
    created_at = Column(DateTime, default=datetime.utcnow)

    api_keys = relationship("ApiKey", back_populates="user")


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
