# Mostakhles Business Benchmark — `mena_v1`

A balanced, **100% synthetic** MENA document set for **model & architecture
selection**. It answers: *"Can Mostakhles correctly extract the structured fields
our customers need?"* — not *"is our accuracy X%?"* (see honesty note).

## What's here
| file | committed? | purpose |
|------|-----------|---------|
| `generate.py` | ✅ | deterministic generator (values + rendering + degradations) |
| `ids.py` | ✅ | valid/invalid MENA identifiers, consistent with `app/services/validators.py` |
| `manifest.json` | ✅ | 122 cases with **exact** ground truth |
| `_media/*.png` | ❌ (gitignored) | rendered document images — **regenerable**, byte-deterministic |

## Regenerate
```bash
# metadata only (fast):
python -m benchmarks.datasets.mena_v1.generate --out benchmarks/datasets/mena_v1/manifest.json
# + render all document images into _media/ (needed for a LIVE run):
python -m benchmarks.datasets.mena_v1.generate --out benchmarks/datasets/mena_v1/manifest.json --render
```
The committed `manifest.json` must equal what the generator emits — a test enforces
this, so ground truth can never silently drift from its source.

## Composition (122 cases)
- **Country:** EG 51 · SA 36 · AE 35
- **Language:** Arabic 68 · bilingual 28 · English 26
- **Doc types:** tax/VAT invoice, receipt, purchase order, bank statement,
  national ID (synthetic), prescription (handwriting), business form, table, contract, form
- **Difficulty slices:** clean scan, phone photo, rotated (±7°), low contrast,
  blur, noise, shadow, JPEG (q28–55), Arabic-Indic digits, bilingual, multi-page,
  stamps, handwriting — spread evenly (not "90 easy invoices + 10 rest").
- **ID fixtures:** 47 valid + 10 invalid, each genuinely valid/invalid against the
  product validators — so §22's validator-value analysis has trustworthy labels.

`python -m benchmarks stats --dataset .../manifest.json` prints the live breakdown;
`python -m benchmarks.validate --dataset .../manifest.json` checks ground-truth
consistency (dates parse, subtotal+tax=total, currency matches country, ID labels
agree with the validators).

## Two benchmarks, kept separate (Section 8)
This is the **business-field** benchmark. It is NOT an Arabic-OCR benchmark — CER/WER
and layout quality belong to a separate track (KITAB-Bench adapter; see
`benchmarks/KITAB_BENCH.md`). Do not blend them into one "global accuracy" number.

## Honesty
- Synthetic and **modest n** — enough to **choose** models/architecture and expose
  weak slices, **not** to publish a universal accuracy claim.
- No real customers, no real identities. Ground truth is exact by construction.
- A number is only real once produced by an actual `--live` run over these images
  with recorded git SHA + dataset + prompt/schema/model versions.
