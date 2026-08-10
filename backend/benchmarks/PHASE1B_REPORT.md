# Phase 1B — Evidence Run & Production Model Decision — FINAL REPORT

**Verdict: PARTIAL (unchanged).** The benchmark is now *evidence-ready* — harness,
dataset, cost gate, and live path are complete and green — but **zero live model
evidence could be produced in this environment because there is no `GEMINI_API_KEY`
/ `.env` here.** That is an operational blocker, not a harness deficiency. Every
number that requires calling a model is therefore **NOT AVAILABLE**, and none has
been fabricated.

No production model ID, routing rule, confidence threshold, structured-output flag,
or public claim was changed.

---

## A. Dataset
`mena_v1` — **122** synthetic cases with exact ground truth. EG 51 · SA 36 · AE 35;
Arabic 68 · bilingual 28 · English 26; 11 doc types; degradations spread evenly
(clean/phone-photo/rotated/low-contrast/blur/noise/shadow/jpeg/arabic-indic/
multi-page/handwriting); **47 valid + 10 invalid** ID fixtures, each genuinely
valid/invalid against the product validators. Deterministic + regenerable; images
gitignored. Quality: internally consistent (validator passes), balanced, but
**modest n and synthetic** — for model/architecture SELECTION, not a universal
accuracy proof.

## B. External benchmark integration
KITAB-Bench investigated (arXiv 2502.14949, MIT aggregator, CER/WER/TEDS/MARS).
Kept as a SEPARATE Arabic-OCR track; guarded optional adapter added (refuses without
local path + per-split license acknowledgement). **Not integrated/executed.** See
`KITAB_BENCH.md`.

## C. Models actually tested
**None.** No client configured → `benchmarks verify` reports availability False for
every model (honestly "could not verify", NOT "unavailable"). Availability of the
production models and gemini-3.5-flash-lite / 3.5-flash / 3.6-flash is **UNVERIFIED**.

## D–R. Baseline · matrix · structured A/B · calibration · MENA value · router · cost · latency · failures · visual grounding
**NOT AVAILABLE — require a live model.** The tooling to produce each exists and is
tested; all are blocked solely on a key. In particular:
- Confidence @60% Odoo threshold: **NOT DETERMINED** (calibration needs real preds).
- MENA validator value: fixtures + validators ready; **contribution unmeasured**.
- Router quality/cost mistakes: **unmeasured**.
- Cost/latency: only the *pre-run estimate* exists (see U).

## S. Public-claim verdict (evidence only — no copy changed)
| Claim | Status |
|---|---|
| "99% OCR accuracy" | **NOT PROVEN** — no live measurement exists |
| "Arabic-first" | **PARTIALLY PROVEN** — Arabic pipeline + Arabic-heavy dataset exist; accuracy unmeasured |
| "handwriting specialist" | **NOT PROVEN** — 6 handwriting fixtures staged, unmeasured |
| "seconds per page" | **NOT PROVEN** — latency unmeasured |
| "high confidence" | **NOT PROVEN** — calibration undetermined |
| "enterprise-grade extraction" | **NOT PROVEN** — no benchmark evidence yet |
Recommendation: leave public copy unchanged until a live run produces evidence.

## T. Production migration proposal
None executed. Section 3 made the request layer *ready* for newer models (drops
deprecated temperature/top_p for gemini-3.5-flash-lite/3.6-flash; current models
byte-identical). Any actual model switch remains a separate, reviewed commit gated
on benchmark evidence + `verify_generation_params` runtime confirmation.

## U. Tests + tooling (all green, no spend)
- Full backend suite: **145 passed**.
- New this phase: `test_model_params` (8), `test_benchmark_estimate` (11),
  `test_dataset_mena_v1` (10), `test_kitab_adapter` (3).
- Pre-run cost preview (UNVERIFIED pricing), full matrix, all 122 × 4 models × 3
  repeats = **1,464 requests ≈ $1.35** (fast models ≈ $0.12 each, strong ≈ $0.55
  each). Standard profile (50 docs × 4 × 1) is a fraction of that.

## V. Phase-1 final verdict: **PARTIAL**
Meets: harness green · meaningful dataset · cost gate · live path wired · param
regression. Missing (all key-gated): availability verified · live baseline · model
comparison · structured A/B · confidence measured · validator value · routing ·
cost · latency · failures. Standard not lowered to force a PASS.

---

## To move PARTIAL → PASS (one-time, ~$1–2, ~15 min)
```bash
cd ~/doc_ai_saas/backend
# 0. put a real key in .env:  GEMINI_API_KEY=...   (and GEMINI_MODEL_EASY/HARD)
# 1. confirm which models the account can actually use (no spend):
./venv/bin/python -m benchmarks verify
# 2. materialise the document images:
./venv/bin/python -m benchmarks.datasets.mena_v1.generate \
    --out benchmarks/datasets/mena_v1/manifest.json --render
# 3. preview cost (free), then run the live baseline + matrix:
./venv/bin/python -m benchmarks run --dataset benchmarks/datasets/mena_v1/manifest.json \
    --live --profile standard --dry-run          # cost preview
./venv/bin/python -m benchmarks run --dataset benchmarks/datasets/mena_v1/manifest.json \
    --live --allow-cost --profile standard --tier fast   --model "$GEMINI_MODEL_EASY" \
    --out benchmarks/results --run-id baseline_fast
./venv/bin/python -m benchmarks run --dataset benchmarks/datasets/mena_v1/manifest.json \
    --live --allow-cost --profile standard --tier strong --model "$GEMINI_MODEL_HARD" \
    --out benchmarks/results --run-id baseline_strong
# 4. compare, then report:
./venv/bin/python -m benchmarks compare --baseline benchmarks/results/baseline_fast.json \
    --candidate benchmarks/results/baseline_strong.json
```
Then repeat step 3 per candidate model to fill the matrix, and I'll turn the
`results/*.json` into the D–R sections above with real numbers.

## CI readiness (Section 33)
- Safe for every commit (offline, $0): the 32 new metric/estimate/dataset/param
  tests + manifest validation + a small REPLAY regression.
- **Never** put `--live` (paid) in normal CI. Schedule live evaluation manually /
  on a cadence with `--allow-cost`.
