"""AI model architecture: a central model registry + prompt/schema versioning.

These are the single source of truth for *which* model and *which* prompt/schema
produced an extraction — shared by the production extraction path (for provenance)
and the benchmark framework (for fair, reproducible comparison). Runtime model
selection still honors the same GEMINI_MODEL_* env vars llm.py already uses, so
production behavior is unchanged until benchmark evidence justifies a change.
"""
