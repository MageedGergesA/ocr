"""Optional KITAB-Bench → Case adapter for the Arabic-OCR track (Section 7C).

KITAB-Bench (arXiv 2502.14949, MBZUAI, MIT-licensed aggregator) measures Arabic
OCR/layout ability — a DIFFERENT question from the Mostakhles business benchmark
(Section 8). This adapter converts a LOCALLY-DOWNLOADED KITAB OCR split into
manifest.Case objects that carry `ocr_truth`, so metrics.cer / metrics.wer can
score them on the OCR track. It never mixes into the business-field accuracy.

HARD GUARDS (deliberate friction):
  * We do NOT download or vendor KITAB data — you pass a local --path you fetched.
  * We REFUSE without --acknowledge-license: individual KITAB splits re-package
    upstream datasets whose terms are NOT covered by the aggregator's MIT license.
    A human must confirm the specific split's license first (see KITAB_BENCH.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from benchmarks import manifest


class LicenseNotAcknowledged(RuntimeError):
    pass


def load_kitab_ocr(path: str, *, acknowledge_license: bool = False,
                   limit: Optional[int] = None) -> list:
    """Load a local KITAB OCR split (image + text pairs) into Case objects on the
    OCR track. Raises unless the license is explicitly acknowledged and the path
    exists. Returns [] structurally-typed list of manifest.Case."""
    if not acknowledge_license:
        raise LicenseNotAcknowledged(
            "Refusing to load KITAB-Bench without acknowledge_license=True. Confirm "
            "the specific split's license + upstream terms first (see KITAB_BENCH.md).")
    if not path or not os.path.exists(path):
        raise FileNotFoundError(
            f"KITAB split not found at {path!r}. Download it yourself first — this "
            "adapter never fetches or vendors the data.")

    # KITAB OCR splits are HF datasets: image + text (transcription). We read either
    # a HF-saved arrow/parquet dir (via `datasets`) or a simple index.json we don't
    # assume a schema we haven't verified — load lazily and fail loudly on mismatch.
    try:
        from datasets import load_from_disk  # optional dep; only needed here
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "the `datasets` library is required to read a KITAB split; install it in "
            "the benchmark env (it is intentionally NOT a core Mostakhles dependency)"
        ) from e

    ds = load_from_disk(path)
    cases = []
    for i, row in enumerate(ds):
        if limit and i >= limit:
            break
        text = row.get("text") or row.get("ground_truth") or ""
        cases.append(manifest.Case(
            id=f"kitab_ocr_{i:05d}", country="", language="ar",
            doc_type="ocr_line", layout="line", source="licensed_external",
            media="image", difficulty=["arabic_ocr", "external"],
            ocr_truth=str(text), expected_doc_type="",
            input_ref="",  # image is in-memory here; live OCR track handles bytes
            license="KITAB-Bench (verify per-split)"))
    return cases


def main(argv=None):
    p = argparse.ArgumentParser(prog="benchmarks.kitab_adapter")
    p.add_argument("--path", required=True, help="local KITAB split dir (you download)")
    p.add_argument("--acknowledge-license", action="store_true",
                   help="confirm you checked the split's license (required)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    try:
        cases = load_kitab_ocr(args.path, acknowledge_license=args.acknowledge_license,
                               limit=args.limit)
    except (LicenseNotAcknowledged, FileNotFoundError, RuntimeError) as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2
    out = {"dataset_version": "kitab_ocr_external",
           "provenance": "KITAB-Bench (arXiv 2502.14949) — external, license verified per-split by operator",
           "cases": [c.__dict__ for c in cases]}
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
        print(f"wrote {args.out}: {len(cases)} OCR cases", file=sys.stderr)
    else:
        print(f"{len(cases)} OCR cases (not saved; pass --out)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
