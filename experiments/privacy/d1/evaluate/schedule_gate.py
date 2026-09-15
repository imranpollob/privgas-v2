"""S1b scheduler leakage gate (evaluation side; runs BEFORE splits, labels and attacks).

For every S1b run the public order of each on-chain phase is mapped back to private slots
(``audit._public_phase_orders``; it must equal the private schedule), and the off-chain
proof-preparation order is taken from the schedule. For every pair of orders EXCEPT the
one intended correlation (issuance ~ redemption) two statistics are pooled per
(baseline, pair) over runs:

* rank-match recovery: actors at the same rank in both orders. Under independent uniform
  permutations the count per run has mean 1 and variance 1, so
  z = (hits - runs) / sqrt(runs);
* Spearman rank correlation, combined as z = sum(rho_i sqrt(n_i - 1)) / sqrt(k).

The gate REJECTS the batch (exit 1, ``schedule_gate.json`` ok = false) if any unintended pair
has |z| > 3.29 on either statistic, or if any run has an unintended pair with identical
orders (deterministic exposure). The intended pair is reported, not gated.

Pairs named by the experiment specification (delivery / funding / setup vs issuance /
redemption) are marked ``required``; every other unintended pair is gated as well.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping

from ....workloads.d1.schedule import S1B, spearman
from .audit import Z_STOP, _public_phase_orders
from .labels_io import batch_dir, private_run

INTENDED = ("issue", "act")
REQUIRED = {("deliver", "issue"), ("deliver", "act"), ("fund", "issue"), ("fund", "act"),
            ("setup", "issue"), ("setup", "act"), ("setup_issuer", "issue"),
            ("setup_issuer", "act")}
NAMES = ("setup", "setup_issuer", "deliver", "fund", "issue", "prepare", "act")


def run_gate(root: Path, runs: List[Mapping[str, Any]], scenario: str = S1B) -> Dict[str, Any]:
    acc: Dict[tuple, Dict[str, Any]] = defaultdict(lambda: {"hits": 0, "runs": 0, "subjects": 0,
                                                            "rho_z": [], "identical": 0})
    mismatches = []
    for r in runs:
        if r["scenario_id"] != scenario:
            continue
        priv = private_run(root, r["experiment_id"], r["run_id"])
        n = len(priv["actors"])
        sched: Dict[str, List[int]] = defaultdict(list)
        for _t, phase, slot in priv["schedule"]["events"]:
            sched[phase].append(slot)
        for k in ("setup", "setup_issuer"):
            if k in priv["schedule"]["orders"]:
                sched[k] = list(priv["schedule"]["orders"][k])
        public = _public_phase_orders(root, r["experiment_id"], r["run_id"], priv)
        for phase, order in public.items():
            if order != sched.get(phase):
                mismatches.append({"experiment_id": r["experiment_id"], "run_id": r["run_id"],
                                   "phase": phase})
        orders = {p: (public.get(p) or sched.get(p)) for p in NAMES if sched.get(p)}
        present = [p for p in NAMES if p in orders]
        for i, p in enumerate(present):
            for q in present[i + 1:]:
                a = acc[(r["baseline_id"], p, q)]
                hits = sum(x == y for x, y in zip(orders[p], orders[q]))
                a["hits"] += hits
                a["runs"] += 1
                a["subjects"] += n
                a["rho_z"].append(spearman(orders[p], orders[q]) * math.sqrt(n - 1))
                a["identical"] += int(orders[p] == orders[q])
    rows, rejects = [], []
    for (b, p, q), a in sorted(acc.items()):
        z_hits = (a["hits"] - a["runs"]) / math.sqrt(a["runs"])
        z_rho = sum(a["rho_z"]) / math.sqrt(len(a["rho_z"]))
        intended = (p, q) == INTENDED
        row = {"baseline_id": b, "pair": f"{p}~{q}", "intended": intended,
               "required_by_spec": (p, q) in REQUIRED, "runs": a["runs"],
               "rank_match_rate": a["hits"] / a["subjects"],
               "chance_rank_match_rate": a["runs"] / a["subjects"],
               "rank_match_z": z_hits, "spearman_z": z_rho, "runs_with_identical_orders": a["identical"]}
        rows.append(row)
        if not intended and (abs(z_hits) > Z_STOP or abs(z_rho) > Z_STOP or a["identical"]):
            rejects.append(row)
    ok = bool(rows) and not rejects and not mismatches
    return {"ok": ok, "scenario_id": scenario, "pairs": rows, "rejected_pairs": rejects,
            "public_order_mismatches": mismatches, "z_threshold": Z_STOP,
            "method": __doc__.strip()}


def write_gate(root: Path, batch: str, runs: List[Mapping[str, Any]],
               scenario: str = S1B) -> Dict[str, Any]:
    res = run_gate(root, runs, scenario)
    name = "schedule_gate.json" if scenario == S1B else f"schedule_gate.{scenario}.json"
    (batch_dir(root, batch) / name).write_text(
        json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return res
