"""CLI: run the D2 pilot experiments and analysis.

    python3 -m experiments.liveness.d2 run --batch <stamp> --exp gas [--exp race ...]
    python3 -m experiments.liveness.d2 analyze --batch <stamp> [--write-doc]

Experiments (``--exp``): gas (D2-B growth + natural frozen sequence + fee envelope), control,
race, bundle, latency, stochastic, policy, segments, measured, concurrency, adversary;
``all`` runs them in that order.

Outputs:
    data/private/d2-pilot/<batch>/<exp>.attempts.jsonl   attempt records (contain
                                                        client-private fields; FIELD_TIERS)
    data/private/d2-pilot/<batch>/<exp>.arrivals.jsonl   root-changing Bootstrap records
    results/d2-pilot/<batch>/raw/<exp>.json              non-attempt measurements (D2-B rows,
                                                        deterministic experiment outcomes)
    results/d2-pilot/<batch>/manifest.json               config digest, seeds, environment,
                                                        per-experiment wall time and status
    results/d2-pilot/<batch>/tables/*, figures/d2-pilot/<batch>/*   (analyze)

Failed experiments are recorded in the manifest with their traceback and are not retried.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...recorder.provenance import repo_root

CONFIG_RELPATH = Path("experiments") / "liveness" / "d2" / "pilot-config.json"
ORDER = ("gas", "control", "race", "bundle", "latency", "stochastic", "policy", "segments",
         "measured", "concurrency", "adversary")


def load_d2_config(root: Optional[Path] = None) -> Dict[str, Any]:
    return json.loads(((Path(root) if root else repo_root()) / CONFIG_RELPATH).read_text())


def batch_dirs(batch: str, root: Optional[Path] = None) -> Dict[str, Path]:
    r = Path(root) if root else repo_root()
    return {"private": r / "data" / "private" / "d2-pilot" / batch,
            "results": r / "results" / "d2-pilot" / batch,
            "figures": r / "figures" / "d2-pilot" / batch}


def machine_info() -> Dict[str, Any]:
    def sh(cmd: List[str]) -> str:
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return ""
    return {"platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu": sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor(),
            "logical_cpus": sh(["sysctl", "-n", "hw.ncpu"]),
            "memory_bytes": sh(["sysctl", "-n", "hw.memsize"]),
            "node": sh(["node", "--version"]), "anvil": sh(["anvil", "--version"]).splitlines()[0:1]}


def _update_manifest(dirs: Dict[str, Path], key: str, value: Any, cfg: Dict[str, Any]) -> None:
    path = dirs["results"] / "manifest.json"
    man = json.loads(path.read_text()) if path.is_file() else {
        "d2_config_sha256": hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
        "d2_config": cfg, "machine": machine_info(), "experiments": {},
        "labels": ["NON-PRODUCTION", "NON-EIP-170-DEPLOYABLE-AS-BUILT", "EVALUATION-ONLY"]}
    man["experiments"][key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(man, indent=2, sort_keys=True, default=str))


def run_experiment(name: str, cfg: Dict[str, Any], dirs: Dict[str, Path], seeds: List[int]) -> None:
    from .records import ARRIVAL_FIELD_TIERS, write_jsonl
    raw = dirs["results"] / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    if name == "gas":
        from . import exp_b
        out: Dict[str, Any] = {"growth": [], "natural": [], "fee_envelope": [], "checks": []}
        for seed in cfg["d2b"]["seeds"]:
            g = exp_b.run_growth(seed, cfg)
            out["growth"] += g["rows"]
            out["checks"].append({"seed": seed, "final_root_check": g["final_root_check"],
                                  "frozen_call_gas_limit": g["frozen_call_gas_limit"]})
            out["natural"] += exp_b.run_natural(seed, cfg)["rows"]
            f = exp_b.run_fee_envelope(seed, cfg, g["rows"])
            out["fee_envelope"].append(f)
        (raw / "gas.json").write_text(json.dumps(out, default=str))
        return
    from . import exp_a
    fn = getattr(exp_a, f"run_{name}")
    result = fn(cfg, seeds, log=lambda m: print(m, flush=True))
    if "attempts" in result:
        write_jsonl(dirs["private"] / f"{name}.attempts.jsonl", result.pop("attempts"))
    if "arrivals" in result:
        write_jsonl(dirs["private"] / f"{name}.arrivals.jsonl", result.pop("arrivals"),
                    ARRIVAL_FIELD_TIERS)
    (raw / f"{name}.json").write_text(json.dumps(result, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--batch", required=True)
    r.add_argument("--exp", action="append", required=True, choices=ORDER + ("all",))
    r.add_argument("--seeds", type=int, default=None, help="use only the first K seeds")
    a = sub.add_parser("analyze")
    a.add_argument("--batch", required=True)
    a.add_argument("--write-doc", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_d2_config()
    dirs = batch_dirs(args.batch)
    if args.cmd == "analyze":
        from . import analysis
        analysis.analyze(args.batch, cfg, dirs, write_doc=args.write_doc)
        return 0
    names = list(ORDER) if "all" in args.exp else args.exp
    seeds = cfg["seeds"][: args.seeds] if args.seeds else cfg["seeds"]
    failed = False
    for name in names:
        t = time.time()
        print(f"[d2] {name} ...", flush=True)
        try:
            run_experiment(name, cfg, dirs, seeds)
            _update_manifest(dirs, name, {"status": "ok", "wall_s": time.time() - t,
                                          "seeds": seeds}, cfg)
            print(f"[d2] {name} ok ({time.time() - t:.0f}s)", flush=True)
        except Exception:
            failed = True
            tb = traceback.format_exc()
            _update_manifest(dirs, name, {"status": "failed", "wall_s": time.time() - t,
                                          "traceback": tb}, cfg)
            print(tb, file=sys.stderr, flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
