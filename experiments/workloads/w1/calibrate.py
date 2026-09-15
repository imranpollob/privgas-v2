"""CALIBRATION PHASE: measure the EntryPoint unmeasured overhead O and write
the reproducible artifact experiment runs price preVerificationGas with.

    python3 -m experiments.workloads.w1.calibrate --seed 910001 --seed 910002

For every AA variant and every seed, run the exact-bundle snapshot dry run
(``pvg_mode="dry_run"``, method ``break_even_calibration_v1``), collect O per
operation shape, and require one value per shape across every variant and
seed; also require the environment fingerprint to be identical and the
resulting runs to reconcile with no bundler subsidy. Writes
``baselines/w1_b0_b2/calibration/pvg-overhead.json`` (committable: no seed,
no role, no address).

Calibration seeds are calibration-only; the artifact records only their
commitments. Do not reuse them for experiment runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...recorder.digest import commit_to_value
from ...recorder.provenance import repo_root
from . import calibration
from .accounting import reconcile
from .artifacts import forge_build
from .config import EXPERIMENT_IDS, load_config
from .runner import run_baseline

AA_VARIANTS = [v for v in EXPERIMENT_IDS if v[0] != "B0"]


class CalibrationInconsistent(RuntimeError):
    pass


def run_calibration(seeds: List[int], root: Path, build: bool = True) -> Dict[str, Any]:
    if build:
        forge_build(root)
    cfg = load_config(root)
    samples: List[Dict[str, Any]] = []
    fingerprints = []
    for seed in seeds:
        for b, w in AA_VARIANTS:
            r = run_baseline(b, seed, root, build=False, workload_id=w, pvg_mode="dry_run")
            if r.failure is not None:
                raise CalibrationInconsistent(f"{b} {w} failed during calibration: {r.failure}")
            reconcile(r.chain_dump, r.private)  # includes the no-subsidy assertion
            fingerprints.append(r.chain_dump["bundler"]["environment_fingerprint"])
            for label, rec in r.chain_dump["pvg_records"].items():
                samples.append({"variant": f"{b} {w}", "label": label,
                                "op_shape": rec["op_shape"],
                                "entrypoint_unmeasured_overhead":
                                    rec["entrypoint_unmeasured_overhead"],
                                "dry_run_bundle_gas_used": rec["dry_run_bundle_gas_used"],
                                "dry_run_calldata_bytes": rec["dry_run_calldata_bytes"],
                                "seed_commitment_sha256": commit_to_value(
                                    "w1-pvg-calibration", seed)})
    if any(fp != fingerprints[0] for fp in fingerprints):
        raise CalibrationInconsistent("environment fingerprint differed between runs")
    by_shape: Dict[str, set] = {}
    for s in samples:
        by_shape.setdefault(s["op_shape"], set()).add(s["entrypoint_unmeasured_overhead"])
    spread = {k: sorted(v) for k, v in by_shape.items() if len(v) != 1}
    if spread:
        raise CalibrationInconsistent(f"overhead is not constant within a shape: {spread}")
    return {
        "artifact_version": calibration.ARTIFACT_VERSION,
        "method": "break_even_calibration_v1 (exact-bundle evm_snapshot dry run)",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "regenerate_with": "python3 -m experiments.workloads.w1.calibrate --seed <s> ...",
        "environment_fingerprint": fingerprints[0],
        "bundle_size": calibration.BUNDLE_SIZE,
        "provisional_pre_verification_gas": cfg.provisional_pre_verification_gas,
        "matched_config_sha256": calibration.digest(cfg.raw),
        "entrypoint_unmeasured_overhead_by_shape": {k: next(iter(v))
                                                    for k, v in sorted(by_shape.items())},
        "seed_count": len(seeds),
        "samples": samples,
        "notes": ("O = bundle receipt gasUsed - (UserOperationEvent.actualGasUsed - PVG) "
                  "- 21,000 - EIP-2028 calldata gas of the exact bundle. Valid only for "
                  "the fingerprinted environment; experiment runs refuse to use it "
                  "otherwise."),
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, action="append", required=True)
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    artifact = run_calibration(args.seed, root)
    path = calibration.artifact_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(root)}")
    print("overhead by shape:", artifact["entrypoint_unmeasured_overhead_by_shape"])
    print(f"samples: {len(artifact['samples'])} across {len(args.seed)} seed(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
