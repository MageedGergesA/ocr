"""Phase 1 — structured-output schema builder (deterministic; no live model).

Verifies the JSON-Schema conversion and that the feature is OFF by default so the
production path is unchanged until the benchmark justifies enabling it.
"""
from app.ai import structured


def test_disabled_by_default():
    assert structured.enabled() is False


def test_to_response_schema_shape():
    caller = {"vendor": "the vendor name", "total": "the grand total"}
    rs = structured.to_response_schema(caller)
    assert rs["type"] == "object"
    assert set(rs["properties"]) == {"vendor", "total"}
    # each field is a {value, confidence} cell matching the pipeline's shape
    cell = rs["properties"]["vendor"]
    assert cell["type"] == "object"
    assert set(cell["properties"]) == {"value", "confidence"}
    assert cell["required"] == ["value"]
    # field order preserved, and fields are NOT required (absence is meaningful)
    assert rs["propertyOrdering"] == ["vendor", "total"]
    assert "required" not in rs


def test_to_response_schema_empty():
    assert structured.to_response_schema({}) == {
        "type": "object", "properties": {}, "propertyOrdering": []}


def test_validate_structured_result():
    ok, probs = structured.validate_structured_result(
        {"vendor": {"value": "Acme", "confidence": 0.9}, "total": {"value": "10"}},
        {"vendor": "", "total": ""})
    assert ok and not probs
    bad, probs2 = structured.validate_structured_result(
        {"vendor": {"confidence": 0.9}}, {"vendor": ""})   # no 'value'
    assert not bad and probs2
    notobj, _ = structured.validate_structured_result("nope", {})
    assert not notobj
