"""Run-level train/test splits for the D1 pilot. NEUTRAL (public manifest only).

Never row-level. Every fold splits whole RUNS, and runs never share actors:
actor identities are drawn from (secret seed, pool size, slot), each replicate
has its own seed, and each pool size its own population (``experiments/
workloads/d1/actors.py``). Holding out a replicate therefore holds out every
actor, account, asset sender and wallet of that replicate; the evaluation-side
split audit re-checks this on the public addresses.

Fold kinds, per (baseline, scenario) group:

* ``loro-rK``      leave-one-replicate-out: test = replicate K (all pool sizes),
                   train = the other replicates (all pool sizes).
* ``holdout-nMAX`` configuration holdout: test = the largest pool size (all
                   replicates), train = every smaller pool size.
* ``transfer-S1-to-S0-rK`` / ``transfer-S0-to-S1-rK`` (B3, B4-CrossAccount): train on the
                   other scenario's runs of the OTHER replicates, test on
                   replicate K of this scenario (actor-held-out as well).
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any, Dict, List, Mapping

SLUG = {"S0-clean-shuffled": "S0", "S1-correlated-timing": "S1",
        "S1b-issuance-redemption-timing-only": "S1b"}


def build_splits(dataset_manifest: Mapping[str, Any]) -> Dict[str, Any]:
    runs = [r for r in dataset_manifest["runs"] if r["status"] == "recorded"]
    groups: Dict[tuple, List[Mapping[str, Any]]] = defaultdict(list)
    for r in runs:
        groups[(r["baseline_id"], r["scenario_id"])].append(r)

    def ref(r):
        return [r["experiment_id"], r["run_id"]]

    folds: List[Dict[str, Any]] = []
    for (b, s), rs in sorted(groups.items()):
        reps = sorted({r["replicate"] for r in rs})
        for rep in reps:
            folds.append({"fold_id": f"{b}.{SLUG[s]}.loro-{rep}", "baseline_id": b,
                          "scenario_id": s, "kind": "loro",
                          "train_runs": [ref(r) for r in rs if r["replicate"] != rep],
                          "test_runs": [ref(r) for r in rs if r["replicate"] == rep]})
        sizes = sorted({r["pool_size"] for r in rs})
        if len(sizes) > 1:
            big = sizes[-1]
            folds.append({"fold_id": f"{b}.{SLUG[s]}.holdout-n{big}", "baseline_id": b,
                          "scenario_id": s, "kind": "holdout",
                          "train_runs": [ref(r) for r in rs if r["pool_size"] < big],
                          "test_runs": [ref(r) for r in rs if r["pool_size"] == big]})
    for b3, src, dst in ((b, src, dst) for b in ("B3-PrivGas-v1", "B4-CrossAccount")
                         for src, dst in (("S1-correlated-timing", "S0-clean-shuffled"),
                                          ("S0-clean-shuffled", "S1-correlated-timing"))):
        if (b3, src) in groups and (b3, dst) in groups:
            for rep in sorted({r["replicate"] for r in groups[(b3, dst)]}):
                # Still actor-held-out: the source scenario's runs of the SAME replicate
                # share the test run's actors (matched design), so they are excluded.
                folds.append({
                    "fold_id": f"{b3}.{SLUG[dst]}.transfer-{SLUG[src]}-to-{SLUG[dst]}-{rep}",
                    "baseline_id": b3, "scenario_id": dst, "kind": "transfer",
                    "train_runs": [ref(r) for r in groups[(b3, src)] if r["replicate"] != rep],
                    "test_runs": [ref(r) for r in groups[(b3, dst)] if r["replicate"] == rep]})
    for f in folds:
        train = {tuple(x) for x in f["train_runs"]}
        test = {tuple(x) for x in f["test_runs"]}
        if train & test:  # pragma: no cover - construction guarantees it
            raise AssertionError(f"{f['fold_id']}: train/test runs overlap")
        if not train or not test:
            raise AssertionError(f"{f['fold_id']}: empty train or test set")
    body = {"batch": dataset_manifest["batch"], "folds": folds,
            "note": "Run-level splits; see experiments/privacy/d1/splits.py."}
    return body


def canonical_sha256(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
                          ).hexdigest()
