"""Batch accuracy test bench.

Drop real documents (images or PDFs) into ../test_docs/, then run:
    ../venv/bin/python test_bench.py            # uses ../test_docs
    ../venv/bin/python test_bench.py /path/dir  # any folder

It extracts each document (auto mode) via the local API, prints a summary,
and writes results.csv with a blank 'correct?' column. Mark each row y/n,
then your accuracy = (# y) / (total rows).
"""
import csv
import glob
import os
import sys
import time

import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000/v1/extract")
DOCS_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "test_docs")
HARD = os.getenv("HARD", "true")  # true=Sonnet+thinking (handwriting), false=Haiku (printed)

CONTENT_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".pdf": "application/pdf",
}


def main():
    files = [f for f in sorted(glob.glob(os.path.join(DOCS_DIR, "*")))
             if os.path.splitext(f)[1].lower() in CONTENT_TYPES]
    if not files:
        print(f"No documents found in {os.path.abspath(DOCS_DIR)}")
        print("Drop some images/PDFs there and re-run.")
        return

    print(f"Testing {len(files)} document(s) against {API_URL}  (hard={HARD})\n")
    rows = []
    for path in files:
        ext = os.path.splitext(path)[1].lower()
        name = os.path.basename(path)
        with open(path, "rb") as fh:
            t0 = time.time()
            try:
                resp = httpx.post(
                    API_URL,
                    files={"file": (name, fh, CONTENT_TYPES[ext])},
                    data={"target_schema": "", "hard": HARD},
                    timeout=180,
                )
            except Exception as e:  # noqa: BLE001
                print(f"=== {name} ===\n  REQUEST FAILED: {e}\n")
                continue
        dt = time.time() - t0

        print(f"=== {name}  ({dt:.1f}s) ===")
        if resp.status_code != 200:
            print(f"  ERROR {resp.status_code}: {resp.text[:200]}\n")
            continue
        body = resp.json()
        print(f"  document_type: {body.get('document_type')}")
        data = body.get("data", {})
        for field, info in data.items():
            value = info.get("value") if isinstance(info, dict) else info
            conf = info.get("confidence") if isinstance(info, dict) else ""
            conf_str = f"{conf:.0%}" if isinstance(conf, (int, float)) else ""
            print(f"   - {field}: {value}   [{conf_str}]")
            rows.append({
                "file": name, "document_type": body.get("document_type"),
                "field": field, "value": value, "confidence": conf,
                "correct? (y/n)": "",
            })
        print()

    if not rows:
        print("No successful extractions.")
        return

    out = os.path.join(DOCS_DIR, "results.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "file", "document_type", "field", "value", "confidence", "correct? (y/n)"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Saved {len(rows)} extracted fields → {os.path.abspath(out)}")
    print("Open it, mark the 'correct?' column y/n; accuracy = (# y) / total.")


if __name__ == "__main__":
    main()
