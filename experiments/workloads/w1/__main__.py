"""CLI: run real W1 executions and record them.

    python3 -m experiments.workloads.w1 --variant all --seed 42
    python3 -m experiments.workloads.w1 --variant B2-Signature:W1-cold --seed 42

Variants: B0:W1-cold, B1:W1-cold, B1:W1-warm, B2-Allowlist:W1-cold,
B2-Signature:W1-cold.

Writes, per variant (run_id = <UTC timestamp>-<suffix>):
    data/raw/<experiment>/<run_id>/chain_dump.json, bundler_log.jsonl
    data/private/<experiment>/<run_id>/w1_private_run.json          SECRET
    data/private/<experiment>/<run_id>/w1_cost_reconciliation.json  SECRET (role-labelled)
    data/public/<experiment>/<run_id>/...                           recorder streams
    data/private/<experiment>/<run_id>/ground_truth.jsonl, run_manifest.private.json
and, for --variant all, results/w1-baselines/<timestamp>/comparison.json
(numbers and booleans only: fairness checks, cost summaries, derived components).

Exits non-zero if a run fails, accounting does not reconcile, or a fairness
check fails.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ...recorder import paths as paths_mod
from ...recorder.provenance import environment_report, repo_root
from ...recorder.writers import new_run_id
from . import compare
from .accounting import reconcile
from .config import EXPERIMENT_IDS, RUN_ID_SUFFIX
from .recording import record_run
from .runner import run_baseline, write_raw


def run_and_record(baseline_id: str, workload_id: str, seed: int, root: Path,
                   build: bool = True, env=None, now: Optional[datetime] = None) -> dict:
    result = run_baseline(baseline_id, seed, root=root, build=build, workload_id=workload_id)
    if result.failure is not None:
        raise SystemExit(f"{baseline_id} {workload_id}: canonical W1 failed: {result.failure}")
    costs = reconcile(result.chain_dump, result.private)
    run_id = new_run_id(now or datetime.now(timezone.utc),
                        suffix=RUN_ID_SUFFIX[(baseline_id, workload_id)])
    rp = paths_mod.run_paths(EXPERIMENT_IDS[(baseline_id, workload_id)], run_id, root)
    write_raw(result, rp.raw_dir, rp.private_run_dir)
    (rp.private_run_dir / "w1_cost_reconciliation.json").write_text(
        json.dumps(costs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recorded = record_run(result.chain_dump, result.bundler_log, result.private, seed,
                          run_id, root, env_report=env)
    return {"variant": (baseline_id, workload_id), "run_id": run_id, "costs": costs,
            "result": result, "rows": {k: len(v) for k, v in recorded["rows"].items()},
            "public_dir": str(rp.public_run_dir.relative_to(root))}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--variant", required=True,
                    help="'all' or <baseline>:<workload>, e.g. B1:W1-warm")
    ap.add_argument("--seed", required=True, type=int)
    ap.add_argument("--root", default=None)
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    if args.variant == "all":
        targets = list(EXPERIMENT_IDS)
    else:
        b, _, w = args.variant.partition(":")
        targets = [(b, w or "W1-cold")]
        if targets[0] not in EXPERIMENT_IDS:
            ap.error(f"unknown variant {args.variant}; known: {sorted(EXPERIMENT_IDS)}")
    env = environment_report(root)
    now = datetime.now(timezone.utc)
    outputs = {}
    for i, (b, w) in enumerate(targets):
        out = run_and_record(b, w, args.seed, root, build=not args.no_build and i == 0,
                             env=env, now=now)
        outputs[(b, w)] = out
        s = out["costs"]["summary"]
        print(f"{b} {w}: run {out['run_id']} -> {out['public_dir']}")
        print(f"    rows: {out['rows']}; checks: "
              f"{sum(c['ok'] for c in out['costs']['checks'])}/{len(out['costs']['checks'])}")
        for k in ("recipient_action_gas_used", "pre_verification_gas",
                  "bundle_transaction_gas_used", "bundler_net", "unused_recipient_eth",
                  "sender_cost", "sponsor_cost", "total_eth_consumed_by_workflow"):
            print(f"    {k}: {s[k]}")

    if args.variant == "all":
        runs = {v: {"chain_dump": o["result"].chain_dump, "private": o["result"].private}
                for v, o in outputs.items()}
        fairness = compare.fairness_checks(runs)
        comparison = {
            "seed_commitments": {f"{b} {w}": o["result"].chain_dump["seed_commitment_sha256"]
                                 for (b, w), o in outputs.items()},
            "run_ids": {f"{b} {w}": o["run_id"] for (b, w), o in outputs.items()},
            "fairness_checks": fairness,
            "unavoidable_differences": compare.unavoidable_differences(runs),
            "summaries": {f"{b} {w}": o["costs"]["summary"] for (b, w), o in outputs.items()},
            "derived": compare.derived({v: o["costs"] for v, o in outputs.items()}),
        }
        out_dir = root / "results" / "w1-baselines" / now.strftime("%Y%m%dT%H%M%SZ")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "comparison.json").write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        failed = [c for c in fairness if not c["ok"]]
        print(f"fairness: {len(fairness) - len(failed)}/{len(fairness)} checks pass -> "
              f"{out_dir.relative_to(root)}/comparison.json")
        if failed:
            print("FAILED fairness checks:", failed)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
