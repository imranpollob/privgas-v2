"""CLI: run one real W1 execution for a baseline and record it.

    python3 -m experiments.workloads.w1 --baseline B0 --seed 42
    python3 -m experiments.workloads.w1 --baseline all --seed 42

Writes, per baseline (run_id = <UTC timestamp>-<baseline>):
    data/raw/<experiment>/<run_id>/chain_dump.json, bundler_log.jsonl
    data/private/<experiment>/<run_id>/w1_private_run.json          SECRET
    data/private/<experiment>/<run_id>/w1_cost_reconciliation.json  SECRET (role-labelled)
    data/public/<experiment>/<run_id>/...                           recorder streams
    data/private/<experiment>/<run_id>/ground_truth.jsonl, run_manifest.private.json

Exits non-zero if the run fails or the accounting does not reconcile.
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
from .accounting import reconcile
from .config import BASELINE_EXPERIMENT_IDS
from .recording import record_run
from .runner import BASELINES, run_baseline, write_raw


def run_and_record(baseline_id: str, seed: int, root: Path, build: bool = True,
                   env=None) -> dict:
    result = run_baseline(baseline_id, seed, root=root, build=build)
    if result.failure is not None:
        raise SystemExit(f"{baseline_id}: canonical W1 failed: {result.failure}")
    costs = reconcile(result.chain_dump, result.private)
    run_id = new_run_id(datetime.now(timezone.utc), suffix=baseline_id.lower())
    rp = paths_mod.run_paths(BASELINE_EXPERIMENT_IDS[baseline_id], run_id, root)
    write_raw(result, rp.raw_dir, rp.private_run_dir)
    (rp.private_run_dir / "w1_cost_reconciliation.json").write_text(
        json.dumps(costs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    recorded = record_run(result.chain_dump, result.bundler_log, result.private, seed,
                          run_id, root, env_report=env)
    return {"baseline_id": baseline_id, "run_id": run_id, "costs": costs,
            "rows": {k: len(v) for k, v in recorded["rows"].items()},
            "public_dir": str(rp.public_run_dir.relative_to(root))}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", required=True, choices=list(BASELINES) + ["all"])
    ap.add_argument("--seed", required=True, type=int)
    ap.add_argument("--root", default=None)
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    env = environment_report(root)
    targets = BASELINES if args.baseline == "all" else (args.baseline,)
    for i, b in enumerate(targets):
        out = run_and_record(b, args.seed, root, build=not args.no_build and i == 0, env=env)
        s = out["costs"]["summary"]
        print(f"{b}: run {out['run_id']} -> {out['public_dir']}")
        print(f"    rows: {out['rows']}")
        print(f"    checks: {sum(c['ok'] for c in out['costs']['checks'])}/"
              f"{len(out['costs']['checks'])} reconcile")
        for k in ("recipient_action_gas_used", "recipient_action_gas_charge",
                  "unused_recipient_eth", "sender_cost", "sponsor_cost",
                  "total_workflow_eth_expenditure"):
            print(f"    {k}: {s[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
