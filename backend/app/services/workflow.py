"""Workflow Engine v1 — evaluate per-user rules after an extraction and route
matching documents into a human approval queue.

Flow:  extract → _record_history → workflow.evaluate() → (rule matched?) →
       Approval(pending) + AuditLog('rule_matched')  →  Review Queue UI  →
       approve/reject  →  AuditLog + (on approve) ready for ERP posting.

v1 keeps rules to a single clause (<field> <op> <value>). Numeric comparisons
happen when both sides parse as numbers; otherwise it's a string compare.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from datetime import datetime
from typing import Any

from app import models

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _num(v: Any):
    """Best-effort parse of a number out of messy extracted text ('SAR 45,230.00')."""
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v))
    if v is None:
        return None
    m = _NUM_RE.search(str(v))
    if not m:
        return None
    try:
        return Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None


def _cell(node: Any) -> Any:
    """Unwrap a {value, confidence} cell to its scalar value."""
    if isinstance(node, dict):
        for k in ("value_iso", "value"):
            if node.get(k) not in (None, ""):
                return node[k]
        return None
    return node


def extract_total(data: dict) -> Decimal | None:
    """Pull the grand total from any of the shapes we emit."""
    if not isinstance(data, dict):
        return None
    d = data.get("data") if isinstance(data.get("data"), dict) else data
    totals = d.get("totals") if isinstance(d.get("totals"), dict) else {}
    for key in ("grand_total", "total", "total_amount", "amount_due", "net"):
        for src in (totals, d, d.get("header") or {}, d.get("fields") or {}):
            if isinstance(src, dict) and key in src:
                n = _num(_cell(src[key]))
                if n is not None:
                    return n
    return None


def _as_pct(c: float) -> float:
    """Normalize a confidence value to a percent (0..100), accepting 0..1 or 0..100."""
    return round(c * 100.0 if c <= 1 else c, 2)


def avg_confidence(data: dict) -> float | None:
    """Average per-field confidence in the tree, as a PERCENT (0..100)."""
    d = data.get("data") if isinstance(data.get("data"), dict) else data
    vals: list[float] = []

    def walk(node: Any):
        if isinstance(node, dict):
            c = node.get("confidence")
            if isinstance(c, (int, float)):
                vals.append(_as_pct(float(c)))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(d)
    return round(sum(vals) / len(vals), 2) if vals else None


def field_confidence(data: dict, field: str) -> float | None:
    """Confidence of a SPECIFIC extracted field, as a percent (0..100). Matches
    the field by its (leaf) key anywhere in the tree — e.g. 'total', 'vat_id'."""
    d = data.get("data") if isinstance(data.get("data"), dict) else data
    target = str(field).strip().lower()
    found: list[float | None] = [None]

    def walk(node: Any, key=None):
        if found[0] is not None:
            return
        if isinstance(node, dict):
            c = node.get("confidence")
            if (isinstance(c, (int, float)) and key is not None
                    and str(key).strip().lower() == target):
                found[0] = _as_pct(float(c))
                return
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)

    walk(d)
    return found[0]


def _field_value(data: dict, field: str) -> Any:
    """Resolve a rule's target field to a comparable value."""
    if field == "total":
        return extract_total(data)
    if field == "confidence":
        return avg_confidence(data)                 # percent (0..100)
    if field.startswith("confidence:"):             # confidence of a specific field
        return field_confidence(data, field.split(":", 1)[1])
    if field == "document_type":
        d = data.get("data") if isinstance(data.get("data"), dict) else data
        return d.get("document_type") or data.get("document_type")
    # arbitrary extracted key — search header/fields/top level
    d = data.get("data") if isinstance(data.get("data"), dict) else data
    for src in (d, d.get("header") or {}, d.get("fields") or {}):
        if isinstance(src, dict) and field in src:
            return _cell(src[field])
    return None


def _matches(actual: Any, op: str, target: str) -> bool:
    a_num, t_num = _num(actual), _num(target)
    if op in ("gt", "lt", "gte", "lte"):
        if a_num is None or t_num is None:
            return False
        return {
            "gt": a_num > t_num, "lt": a_num < t_num,
            "gte": a_num >= t_num, "lte": a_num <= t_num,
        }[op]
    a_s = "" if actual is None else str(actual).strip().lower()
    t_s = str(target).strip().lower()
    if op == "eq":
        if a_num is not None and t_num is not None:
            return a_num == t_num
        return a_s == t_s
    if op == "contains":
        return t_s in a_s
    return False


def evaluate(session, user, history) -> list["models.Approval"]:
    """Run the user's active rules against a freshly-saved History row.
    For each match, create a pending Approval + an audit entry. Best-effort:
    never raise into the extraction path.
    """
    created: list[models.Approval] = []
    try:
        rules = (session.query(models.WorkflowRule)
                 .filter_by(user_id=user.id, active=True).all())
        if not rules:
            return created
        data = history.result_json or {}
        total = extract_total(data)
        for rule in rules:
            actual = _field_value(data, rule.field)
            if actual is None:
                continue
            if not _matches(actual, rule.op, rule.value):
                continue
            # Confidence policies add a 'block' action (reject the import until a
            # human overrides); the default remains 'require_approval'.
            action = (rule.action or "require_approval")
            blocked = action == "block"
            ap = models.Approval(
                user_id=user.id, history_id=history.id, rule_id=rule.id,
                rule_name=rule.name, document_type=history.document_type,
                amount=total, status=("blocked" if blocked else "pending"),
            )
            session.add(ap)
            session.flush()  # get ap.id for the audit row
            session.add(models.AuditLog(
                user_id=user.id, approval_id=ap.id,
                event=("blocked" if blocked else "rule_matched"),
                detail=f"Rule '{rule.name}' matched ({rule.field} {rule.op} {rule.value}); "
                       + ("blocked from ERP until overridden." if blocked
                          else "held for approval."),
            ))
            created.append(ap)
        if created:
            session.commit()
    except Exception:  # noqa: BLE001 — workflow must never break extraction
        session.rollback()
    return created
