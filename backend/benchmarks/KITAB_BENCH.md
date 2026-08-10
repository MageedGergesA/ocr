# KITAB-Bench integration — investigation (Section 7C)

**Verdict: worth adding as an OPTIONAL, separate Arabic-OCR track — never bundled
into the repo, never blended into the business-field accuracy number.**

## What it is (verified 2026-08)
- **KITAB-Bench** — "A Comprehensive Multi-Domain Benchmark for Arabic OCR and
  Document Understanding", MBZUAI Oryx, ACL 2025. arXiv **2502.14949**.
- **~8,809 samples, 36 sub-domains, 9 domains:** layout detection, line
  recognition, image-to-text (OCR), VQA, diagram-to-code, table recognition,
  charts-to-JSON, PDF-to-Markdown, Arabic numerals.
- **Metrics:** CER, WER (OCR); MARS (PDF→Markdown); TEDS (tables); SCRM (charts);
  CODM (diagrams).
- **Distribution:** HuggingFace collection `ahmedheakl/kitab-bench…` (per-task
  datasets, e.g. `arocrbench_*`); evaluation code on GitHub
  `mbzuai-oryx/KITAB-Bench`.

## License
- The **GitHub repo (code + benchmark) is MIT** — permissive, commercial use OK
  with attribution.
- ⚠️ **Caveat that MUST be checked before use:** individual HuggingFace sub-dataset
  cards (e.g. `arocrbench_adab`) do **not** all restate a license, and several
  KITAB-Bench tasks are **re-packaged from upstream datasets** that may carry their
  own terms. MIT on the aggregator does not automatically re-license third-party
  source data. **Action:** for each sub-task we actually use, confirm the specific
  card's license + the upstream source's terms before any commercial evaluation.

## Why it does NOT replace `mena_v1`
Section 8 — two different questions:
| | `mena_v1` (ours) | KITAB-Bench |
|---|---|---|
| Question | Can we extract the **business fields** customers need? | How well does the system **read Arabic**? |
| Output | structured `{field: value}` | text / markdown / table structure |
| Metrics | field P/R/F1, exact/normalized accuracy, classification | CER/WER/TEDS/MARS |
| Ground truth | our exact synthetic truth | KITAB's transcriptions |

KITAB-Bench measures the **OCR/layout floor** (a capability signal). It cannot tell
us whether we pulled the right `total` / `vat_number` off an invoice. Keep them on
separate tracks; do not average them into one "accuracy".

## Proposed integration (optional, guarded)
`benchmarks/kitab_adapter.py` (added): converts a **locally-downloaded** KITAB OCR
split into `manifest.Case` objects on the **Arabic-OCR track** (populates
`ocr_truth`, so `metrics.cer`/`metrics.wer` score it), tagged
`source="licensed_external"`. It **refuses** to run unless BOTH:
1. a local dataset path is supplied (we never auto-download or vendor the blobs), and
2. an explicit `acknowledge_license=True` is passed (forces a human to confirm the
   per-split license first).

This keeps external execution optional and off CI, and keeps third-party data out
of our Git history.

## Runbook (when we choose to use it)
```bash
# 1. Manually download the split you want + READ ITS LICENSE:
#    huggingface-cli download ahmedheakl/arocrbench_<task> --repo-type dataset --local-dir /data/kitab/<task>
# 2. Convert to our Case format (only after confirming the license):
python -m benchmarks.kitab_adapter --path /data/kitab/<task> --acknowledge-license --out /tmp/kitab_<task>.json
# 3. Score OCR (CER/WER) — separate from the business benchmark.
```

## Recommendation
- **Do NOT copy KITAB-Bench into the repo.**
- Add the guarded adapter (done) so a *future* Arabic-OCR measurement is one command.
- Before publishing any Arabic-OCR number, confirm each split's license and cite
  KITAB-Bench (arXiv 2502.14949) + sample size + our adapter/metric versions.

Sources: [project site](https://mbzuai-oryx.github.io/KITAB-Bench/) ·
[arXiv 2502.14949](https://arxiv.org/abs/2502.14949) ·
[GitHub (MIT)](https://github.com/mbzuai-oryx/KITAB-Bench) ·
[HF collection](https://huggingface.co/collections/ahmedheakl/kitab-bench).
