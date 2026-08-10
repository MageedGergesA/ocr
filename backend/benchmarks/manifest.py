"""Benchmark dataset manifest: human-reviewable, versioned case definitions."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Case:
    id: str
    country: str = ""            # EG | SA | AE | ...
    language: str = ""           # ar | en | bilingual
    doc_type: str = ""           # tax_invoice | receipt | national_id | ...
    layout: str = ""             # invoice | table | form | narrative | prescription
    source: str = ""             # synthetic | anonymized_internal | licensed_sample
    media: str = ""              # image | pdf | synthetic-json
    pages: int = 1
    difficulty: list = field(default_factory=list)   # tags (Section 12)
    pii: str = "none"            # none | synthetic_identity | anonymized
    truth: dict = field(default_factory=dict)        # ground-truth {field: value}
    field_types: dict = field(default_factory=dict)  # field -> canon type
    expected_doc_type: str = ""  # for classification metric
    ocr_truth: str = ""          # optional verbatim text for CER/WER
    input_ref: str = ""          # relative path to the input document (live mode)
    license: str = ""
    notes: str = ""


@dataclass
class Dataset:
    version: str
    provenance: str
    cases: list = field(default_factory=list)
    root: str = ""

    def slice(self, **kw) -> list:
        out = []
        for c in self.cases:
            if all(getattr(c, k, None) == v for k, v in kw.items()):
                out.append(c)
        return out


def load_dataset(manifest_path: str) -> Dataset:
    with open(manifest_path, encoding="utf-8") as fh:
        data = json.load(fh)
    cases = [Case(**{k: v for k, v in c.items() if k in Case.__dataclass_fields__})
             for c in data.get("cases", [])]
    return Dataset(version=data.get("dataset_version", "unknown"),
                   provenance=data.get("provenance", ""),
                   cases=cases,
                   root=os.path.dirname(os.path.abspath(manifest_path)))


def dataset_stats(ds: Dataset) -> dict:
    """Counts by country / doc_type / language / difficulty — for the honest
    'is the dataset statistically meaningful?' question."""
    def _count(attr):
        d: dict[str, int] = {}
        for c in ds.cases:
            d[getattr(c, attr) or "unknown"] = d.get(getattr(c, attr) or "unknown", 0) + 1
        return d

    diff: dict[str, int] = {}
    for c in ds.cases:
        for t in (c.difficulty or ["untagged"]):
            diff[t] = diff.get(t, 0) + 1
    return {
        "version": ds.version,
        "total": len(ds.cases),
        "by_country": _count("country"),
        "by_doc_type": _count("doc_type"),
        "by_language": _count("language"),
        "by_difficulty": diff,
    }
