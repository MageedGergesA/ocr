"""Benchmark CLI.

    python -m benchmarks run    --dataset PATH [--predictions PATH] [--model ID]
                                [--profile smoke|standard|full] [--max-docs N]
                                [--dry-run] [--live --allow-cost] [--out DIR]
    python -m benchmarks report --run RESULT.json [--format md|csv]
    python -m benchmarks compare --baseline A.json --candidate B.json
    python -m benchmarks stats  --dataset PATH

Safety: replay is the default. A LIVE run (real model, real cost) requires BOTH
--live and --allow-cost, and is still bounded by the profile's max-docs.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

from benchmarks import manifest, report, runner


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _cmd_stats(args):
    ds = manifest.load_dataset(args.dataset)
    print(json.dumps(manifest.dataset_stats(ds), ensure_ascii=False, indent=2))


def _cmd_run(args):
    ds = manifest.load_dataset(args.dataset)
    prof_max, _repeats = runner.PROFILES.get(args.profile, (args.max_docs or 3, 1))
    max_docs = args.max_docs or prof_max

    predictions = None
    live_provider = None
    if args.live:
        if not args.allow_cost:
            print("REFUSING live run without --allow-cost (real provider spend). "
                  "Add --allow-cost to proceed.", file=sys.stderr)
            return 2
        from benchmarks.live import build_live_provider
        live_provider = build_live_provider(ds.root, hard=(args.tier != "fast"))
    else:
        if not args.predictions:
            print("replay mode needs --predictions PATH (or use --live --allow-cost)",
                  file=sys.stderr)
            return 2
        with open(args.predictions, encoding="utf-8") as fh:
            predictions = json.load(fh)

    if args.dry_run:
        plan = runner.run(ds, run_id="dryrun", model_id=args.model,
                          predictions=predictions, live_provider=live_provider,
                          max_docs=max_docs, dry_run=True)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    rr = runner.run(ds, run_id=args.run_id or f"run_{_git_sha()}_{args.profile}",
                    model_id=args.model, predictions=predictions,
                    live_provider=live_provider, git_sha=_git_sha(),
                    prompt_version=args.prompt_version, schema_version=args.schema_version,
                    max_docs=max_docs)
    if args.out:
        path = runner.save_run(rr, args.out)
        print(f"saved {path}", file=sys.stderr)
    from dataclasses import asdict
    print(report.render_markdown(asdict(rr)))
    return 0


def _cmd_report(args):
    with open(args.run, encoding="utf-8") as fh:
        rr = json.load(fh)
    if args.format == "csv":
        print(report.render_cases_csv(rr))
    else:
        print(report.render_markdown(rr))


def _cmd_compare(args):
    with open(args.baseline, encoding="utf-8") as fh:
        base = json.load(fh)
    with open(args.candidate, encoding="utf-8") as fh:
        cand = json.load(fh)
    ba, ca = base.get("aggregate", {}), cand.get("aggregate", {})
    def d(k):
        b, c = ba.get(k), ca.get(k)
        if b is None or c is None:
            return "n/a"
        return f"{(c - b) * 100:+.1f} pts"
    print(f"# Compare {base.get('model_id')} -> {cand.get('model_id')}")
    for k in ("normalized_accuracy", "exact_accuracy", "precision", "recall", "f1",
              "missing_rate", "hallucinated_rate", "doc_error_rate"):
        print(f"- {k}: {d(k)}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="benchmarks")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run")
    r.add_argument("--dataset", required=True)
    r.add_argument("--predictions")
    r.add_argument("--model", default="unknown")
    r.add_argument("--profile", default="smoke", choices=list(runner.PROFILES))
    r.add_argument("--max-docs", type=int, default=None)
    r.add_argument("--tier", default="strong", choices=["fast", "strong"])
    r.add_argument("--prompt-version", default="")
    r.add_argument("--schema-version", default="")
    r.add_argument("--run-id", default="")
    r.add_argument("--out", default="")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--live", action="store_true")
    r.add_argument("--allow-cost", action="store_true")
    r.set_defaults(func=_cmd_run)

    rp = sub.add_parser("report")
    rp.add_argument("--run", required=True)
    rp.add_argument("--format", default="md", choices=["md", "csv"])
    rp.set_defaults(func=_cmd_report)

    cp = sub.add_parser("compare")
    cp.add_argument("--baseline", required=True)
    cp.add_argument("--candidate", required=True)
    cp.set_defaults(func=_cmd_compare)

    st = sub.add_parser("stats")
    st.add_argument("--dataset", required=True)
    st.set_defaults(func=_cmd_stats)

    args = p.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
