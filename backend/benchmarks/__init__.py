"""Mostakhles evaluation framework.

Deterministic, offline-testable benchmark harness for measuring extraction quality
BEFORE optimizing anything. Kept separate from production request handling.

Design principles:
- Ground truth is authoritative for deterministic business fields. No LLM judge.
- Benchmark-only canonicalization is conservative and explicit, and is kept
  independent of the production normalizers so we never "grade with the same code
  that produced the answer."
- HARNESS READY, DATASET MATURE, and PUBLIC-BENCHMARK READY are separate states;
  the harness can be production-grade while the dataset is still tiny.
"""
