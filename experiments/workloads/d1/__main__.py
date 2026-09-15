"""CLI: run and record the D1 multi-actor pilot matrix.

    python3 -m experiments.workloads.d1 --master-seed <secret int> [--pool-size 4 ...]
        [--replicates 3] [--variant B3-PrivGas-v1:S0-clean-shuffled ...]

The master seed is SECRET (it determines every actor identity and schedule);
each run's seed is derived from (master seed, replicate, pool size) only, so all
baselines and scenarios at one (replicate, pool size) share actors (matched).

Writes, per run (run_id = <batch timestamp>-r<replicate>):
    data/raw/d1-pilot/<baseline>/<scenario>/n<N>/<run_id>/chain_dump.json, bundler_log.jsonl
    data/public/d1-pilot/.../<run_id>/{run_manifest.public.json, observer_a0a1/, observer_a2/,
                                        auxiliary/r3_wallet_directory.json}
    data/private/d1-pilot/.../<run_id>/{ground_truth.jsonl, run_manifest.private.json,
                                         d1_private_run.json}
and per batch:
    results/d1-pilot/<batch>/dataset_manifest.json               (public: runs, conditions)
    data/private/d1-pilot/<batch>/dataset_manifest.private.json  (seeds, failures, timings)

Failed runs are recorded with their reason and are NOT retried automatically.
Exit code 1 if any run failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ...recorder import paths as paths_mod
from ...recorder.provenance import environment_report, repo_root, software_revision
from ..w1 import b3
from ..w1.artifacts import forge_build
from .config import experiment_id, load_pilot_config
from .recording import record_pilot_run, write_raw
from .runner import PilotRunFailure, RunSpec, run_pilot


def run_seed(master_seed: int, replicate: int, pool_size: int) -> int:
    d = hashlib.sha256(f"privgas-v2/d1/run-seed/v1/{master_seed}/{replicate}/{pool_size}"
                       .encode()).digest()
    return int.from_bytes(d[:8], "big") >> 1  # < 2**63


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    seed_src = ap.add_mutually_exclusive_group(required=True)
    seed_src.add_argument("--master-seed", type=int)
    seed_src.add_argument("--master-seed-file",
                          help="file under data/private/ holding the secret master seed")
    ap.add_argument("--pool-size", action="append", type=int)
    ap.add_argument("--replicates", type=int)
    ap.add_argument("--variant", action="append",
                    help="<baseline>:<scenario>; default: every variant in pilot-config.json")
    ap.add_argument("--root", default=None)
    ap.add_argument("--data-root", default=None,
                    help="where data/ and results/ are written (default: --root); code, "
                         "contracts, calibration and prover artifacts always come from --root")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--batch", default=None, help="batch timestamp (default: now)")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    data_root = Path(args.data_root) if args.data_root else root
    if args.master_seed_file:
        seed_path = Path(args.master_seed_file)
        if "data/private" not in str(seed_path.resolve()):
            ap.error("--master-seed-file must lie under data/private/")
        args.master_seed = int(seed_path.read_text().strip())
    pilot = load_pilot_config(root)
    pool_sizes = args.pool_size or pilot.pool_sizes
    replicates = args.replicates or pilot.replicates
    variants = ([tuple(v.split(":", 1)) for v in args.variant] if args.variant
                else pilot.variants())
    if not args.no_build:
        forge_build(root)
        b3.forge_build_b3(root)
    batch = args.batch or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    env = environment_report(root)
    revision = software_revision(root)

    public_runs, private_runs = [], []
    failed = 0
    for n in pool_sizes:
        for rep in range(1, replicates + 1):
            seed = run_seed(args.master_seed, rep, n)
            for baseline_id, scenario_id in variants:
                exp_id = experiment_id(baseline_id, scenario_id, n)
                run_id = f"{batch}-r{rep}"
                spec = RunSpec(baseline_id, scenario_id, n, rep, seed)
                started = time.time()
                entry = {"experiment_id": exp_id, "run_id": run_id,
                         "baseline_id": baseline_id, "scenario_id": scenario_id,
                         "pool_size": n, "replicate": f"r{rep}"}
                try:
                    result = run_pilot(spec, root, pilot)
                    rp = paths_mod.run_paths(exp_id, run_id, data_root)
                    write_raw(result, rp.raw_dir)
                    rec = record_pilot_run(result, run_id, data_root, env_report=env,
                                           revision=revision)
                    entry.update({"status": "recorded", "rows": rec["rows"]})
                    private_runs.append({**entry, "seed": seed,
                                         "wall_seconds": round(time.time() - started, 2),
                                         "checks_passed": sum(c["ok"] for c in result.checks),
                                         "checks_total": len(result.checks)})
                    print(f"[ok] {exp_id} {run_id} rows={rec['rows']} "
                          f"{time.time() - started:.1f}s", flush=True)
                except (PilotRunFailure, Exception) as e:  # recorded, never hidden
                    failed += 1
                    entry.update({"status": "failed"})
                    private_runs.append({**entry, "seed": seed, "error": str(e)[:2000],
                                         "error_type": type(e).__name__,
                                         "traceback": traceback.format_exc()[-4000:]})
                    print(f"[FAILED] {exp_id} {run_id}: {type(e).__name__}: {str(e)[:300]}",
                          flush=True)
                public_runs.append(entry)

    manifest = {
        "note": "D1 pilot dataset manifest. Public: experimental conditions and run ids only. "
                "Seeds, actor tables, schedules and failure tracebacks are private.",
        "batch": batch, "pilot_config": pilot.raw, "software_revision": revision,
        "pool_sizes": pool_sizes, "replicates": replicates,
        "variants": [list(v) for v in variants], "runs": public_runs,
        "runs_recorded": sum(r["status"] == "recorded" for r in public_runs),
        "runs_failed": failed,
    }
    out = data_root / "results" / "d1-pilot" / batch
    out.mkdir(parents=True, exist_ok=True)
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True)
                                               + "\n", encoding="utf-8")
    priv = data_root / "data" / "private" / "d1-pilot" / batch
    priv.mkdir(parents=True, exist_ok=True)
    (priv / "dataset_manifest.private.json").write_text(json.dumps({
        "note": "SECRET. Master seed, run seeds, failures.", "master_seed": args.master_seed,
        "master_seed_file": args.master_seed_file,
        "runs": private_runs}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"recorded {manifest['runs_recorded']} run(s), failed {failed}; manifest -> "
          f"{out}/dataset_manifest.json")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
