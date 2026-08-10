"""P0.4 — atomic credit accounting (reserve-then-settle) + idempotency uniqueness.

Regression for the discovery findings:
  - enforce_limit (check) and increment_usage (charge) were non-atomic, so two
    concurrent requests could both pass the check and spend the same remaining
    credits (overspend past the plan limit + lost updates);
  - IdempotencyKey had no unique constraint, so a replay guarantee rested on app
    logic a race could defeat.

These tests prove the reservation is atomic (no overspend even under real thread
contention), refunds floor at 0 (no negative balance), a failed extraction is not
billed (reserve+refund nets zero), and the DB now enforces idempotency uniqueness.
"""
import threading

import pytest
import sqlalchemy as sa

from app import auth, db, models


def _usage(uid):
    s = db.SessionLocal()
    try:
        k = s.query(models.ApiKey).filter_by(user_id=uid).first()
        row = s.query(models.Usage).filter_by(api_key_id=k.id,
                                              period=auth.current_period()).first()
        return row.count if row else 0
    finally:
        s.close()


def _api_key_obj(uid):
    s = db.SessionLocal()
    try:
        return s.query(models.ApiKey).filter_by(user_id=uid).first(), s
    finally:
        pass  # caller closes


def test_reserve_charges_and_refund_releases(user_factory, api_key_factory):
    u = user_factory("free")          # free plan = 30 credits
    api_key_factory(u.uid)
    s = db.SessionLocal()
    try:
        k = s.query(models.ApiKey).filter_by(user_id=u.uid).first()
        auth.reserve_credits(s, k, needed=5)
    finally:
        s.close()
    assert _usage(u.uid) == 5
    # A failed extraction refunds — net zero, nothing billed.
    s = db.SessionLocal()
    try:
        k = s.query(models.ApiKey).filter_by(user_id=u.uid).first()
        auth.refund_credits(s, k, 5)
    finally:
        s.close()
    assert _usage(u.uid) == 0


def test_reserve_rejects_over_limit_and_does_not_charge(user_factory, api_key_factory):
    u = user_factory("free")          # 30 credits
    api_key_factory(u.uid)
    s = db.SessionLocal()
    try:
        k = s.query(models.ApiKey).filter_by(user_id=u.uid).first()
        auth.reserve_credits(s, k, needed=28)      # ok -> 28
        with pytest.raises(Exception) as ei:       # 5 more would exceed 30
            auth.reserve_credits(s, k, needed=5)
        assert getattr(ei.value, "status_code", None) == 429
    finally:
        s.close()
    # The rejected reservation must NOT have charged anything.
    assert _usage(u.uid) == 28


def test_refund_floors_at_zero(user_factory, api_key_factory):
    u = user_factory("free")
    api_key_factory(u.uid)
    s = db.SessionLocal()
    try:
        k = s.query(models.ApiKey).filter_by(user_id=u.uid).first()
        auth.reserve_credits(s, k, needed=3)
        auth.refund_credits(s, k, 100)             # over-refund
    finally:
        s.close()
    assert _usage(u.uid) == 0                      # never negative


def test_no_overspend_under_concurrency(user_factory, api_key_factory):
    """20 threads each try to reserve 1 credit against a 5-credit budget. At most 5
    may succeed and the final counter must never exceed 5 — proving the reserve is
    atomic (the old check-then-charge would let >5 through)."""
    u = user_factory("free")
    api_key_factory(u.uid)
    # Pin the plan limit low for a crisp assertion, independent of PLAN_LIMITS.
    orig = auth.PLAN_LIMITS.get("free")
    auth.PLAN_LIMITS["free"] = 5
    successes = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()                              # maximize contention
        s = db.SessionLocal()
        try:
            k = s.query(models.ApiKey).filter_by(user_id=u.uid).first()
            auth.reserve_credits(s, k, needed=1)
            with lock:
                successes.append(1)
        except Exception:                           # 429 or transient lock -> no charge
            pass
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(20)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        final = _usage(u.uid)
        assert final <= 5, f"overspend: final usage {final} > limit 5"
        assert len(successes) == final, "successes must equal the charged count"
        assert final == 5, "all 5 available credits should be reservable"
    finally:
        if orig is not None:
            auth.PLAN_LIMITS["free"] = orig


def test_idempotency_key_unique_constraint_enforced(user_factory):
    u = user_factory()
    s = db.SessionLocal()
    try:
        s.add(models.IdempotencyKey(user_id=u.uid, key="dup-key", response_json={"a": 1}))
        s.commit()
    finally:
        s.close()
    # A second row with the same (user_id, key) must violate the DB constraint.
    s = db.SessionLocal()
    try:
        s.add(models.IdempotencyKey(user_id=u.uid, key="dup-key", response_json={"a": 2}))
        with pytest.raises(sa.exc.IntegrityError):
            s.commit()
    finally:
        s.rollback()
        s.close()
