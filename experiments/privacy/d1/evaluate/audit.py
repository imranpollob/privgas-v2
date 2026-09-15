"""Harness and split audits (private side).

Harness audit (STOP condition "the harness encodes actor order into timing"):
for every run, (a) the order in which each on-chain phase appears in the PUBLIC
trace is mapped back to private slots and must equal the private schedule;
(b) Spearman correlation between the private generation slot and every public
phase order, and between phase orders, combined across runs as
z = sum(rho_i * sqrt(n_i - 1)) / sqrt(k) (rho ~ N(0, 1/(n-1)) under independent
uniform permutations). Flags: |z| > 3.29 for slot-vs-phase (any scenario) and
for phase-vs-phase in S0.

Split audit (STOP condition "train/test actor identities overlap"): for every
fold, the actor-specific addresses of train and test runs (asset senders,
recipient keys, recipient accounts, established wallets) must be disjoint, runs
must be disjoint, and every learned prediction's provenance must show that its
training labels came only from that fold's training runs.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

from ....recorder import paths as paths_mod
from ....workloads.d1.config import parse_experiment_id
from ....workloads.d1.schedule import spearman
from .labels_io import batch_dir, private_run

Z_STOP = 3.29


def _public_phase_orders(root: Path, exp: str, run: str, priv: Mapping[str, Any]
                         ) -> Dict[str, List[int]]:
    rp = paths_mod.run_paths(exp, run, root)
    rows = [json.loads(l) for l in rp.public_events_path.read_text().splitlines() if l.strip()]
    slot_by_account = {a["recipient_account"].lower(): a["slot"] for a in priv["actors"]}
    slot_by_sender = {a["asset_sender_address"].lower(): a["slot"] for a in priv["actors"]}
    dest = priv["roles"]["destination"].lower()
    orders: Dict[str, List[int]] = defaultdict(list)
    boot_txs = {r["transaction_hash"] for r in rows if r.get("calldata_class") == "pool_deposit"}
    for r in rows:
        et, cc = r["event_type"], r.get("calldata_class")
        if et == "asset_transfer" and cc == "erc20_transfer" and r.get("nonce") is not None:
            sub = (r.get("subject_account") or "")
            if sub in slot_by_account and r["sender"] in slot_by_sender:
                orders["deliver"].append(slot_by_account[sub])
            elif sub == dest and r["sender"] in slot_by_account:
                orders["act"].append(slot_by_account[r["sender"]])
        elif et == "native_transfer" and cc == "native_value_only" and r.get("log_index") is None:
            if r["target"] in slot_by_account and r["sender"] in slot_by_sender:
                orders["fund"].append(slot_by_account[r["target"]])
            elif r["target"] in slot_by_sender:
                orders["setup"].append(slot_by_sender[r["target"]])
        elif cc == "paymaster_policy":
            orders["fund"].append(slot_by_account[r["subject_account"]])
        elif cc == "stealth_announce_and_fund":
            orders["fund"].append(slot_by_account[r["subject_account"]])
        elif et == "user_operation_event":
            s = slot_by_account[r["sender"]]
            orders["issue" if r["transaction_hash"] in boot_txs else "act"].append(s)
    return dict(orders)


def harness_audit(root: Path, runs: List[Mapping[str, Any]]) -> Dict[str, Any]:
    per_run = []
    acc: Dict[Tuple[str, str, str], List[Tuple[float, int]]] = defaultdict(list)
    mismatches = []
    for r in runs:
        exp, run = r["experiment_id"], r["run_id"]
        priv = private_run(root, exp, run)
        sched_orders: Dict[str, List[int]] = defaultdict(list)
        sched_orders["setup"] = list(priv["schedule"]["orders"]["setup"])
        for t, phase, slot in priv["schedule"]["events"]:
            sched_orders[phase].append(slot)
        pub = _public_phase_orders(root, exp, run, priv)
        for phase, order in pub.items():
            if order != sched_orders.get(phase):
                mismatches.append({"experiment_id": exp, "run_id": run, "phase": phase})
        n = len(priv["actors"])
        slots = list(range(n))
        entry = {"experiment_id": exp, "run_id": run, "baseline_id": r["baseline_id"],
                 "scenario_id": r["scenario_id"], "pool_size": n, "rho": {}}
        phases = sorted(sched_orders)
        for p in phases:
            rho = spearman(slots, sched_orders[p])
            entry["rho"][f"slot~{p}"] = rho
            acc[(r["baseline_id"], r["scenario_id"], f"slot~{p}")].append((rho, n))
        onchain = [p for p in ("setup", "deliver", "fund", "issue", "prepare", "act")
                   if p in sched_orders]
        for i, p in enumerate(onchain):
            for q in onchain[i + 1:]:
                rho = spearman(sched_orders[p], sched_orders[q])
                entry["rho"][f"{p}~{q}"] = rho
                acc[(r["baseline_id"], r["scenario_id"], f"{p}~{q}")].append((rho, n))
        per_run.append(entry)
    combined = []
    flags = []
    for (b, s, pair), vals in sorted(acc.items()):
        vals = [(rho, n) for rho, n in vals if n > 2]
        if not vals:
            continue
        z = sum(rho * math.sqrt(n - 1) for rho, n in vals) / math.sqrt(len(vals))
        mean_rho = sum(v for v, _ in vals) / len(vals)
        row = {"baseline_id": b, "scenario_id": s, "pair": pair, "runs": len(vals),
               "mean_rho": mean_rho, "z": z}
        combined.append(row)
        is_slot = pair.startswith("slot~")
        if abs(z) > Z_STOP and (is_slot or s == "S0-clean-shuffled"):
            flags.append(row)
    return {"public_order_equals_private_schedule": not mismatches, "mismatches": mismatches,
            "combined": combined, "stop_flags": flags, "per_run": per_run,
            "method": __doc__.split("Split audit")[0].strip()}


def split_audit(root: Path, batch: str, split_body: Mapping[str, Any], split_sha: str,
                prediction_manifests: List[Mapping[str, Any]]) -> Dict[str, Any]:
    actor_addrs: Dict[Tuple[str, str], set] = {}

    def addrs(exp: str, run: str) -> set:
        key = (exp, run)
        if key not in actor_addrs:
            priv = private_run(root, exp, run)
            s = set()
            for a in priv["actors"]:
                for k in ("asset_sender_address", "recipient_key_address", "recipient_account",
                          "wallet_address"):
                    s.add(a[k].lower())
            actor_addrs[key] = s
        return actor_addrs[key]

    folds = []
    problems = []
    for fold in split_body["folds"]:
        train = [tuple(x) for x in fold["train_runs"]]
        test = [tuple(x) for x in fold["test_runs"]]
        tr = set().union(*(addrs(*k) for k in train))
        te = set().union(*(addrs(*k) for k in test))
        overlap = tr & te
        row = {"fold_id": fold["fold_id"], "train_runs": len(train), "test_runs": len(test),
               "train_actor_addresses": len(tr), "test_actor_addresses": len(te),
               "overlapping_actor_addresses": len(overlap),
               "overlapping_runs": len(set(train) & set(test))}
        folds.append(row)
        if overlap or row["overlapping_runs"]:
            problems.append(row)
    fold_by_id = {f["fold_id"]: f for f in split_body["folds"]}
    export_base = batch_dir(root, batch) / "training_labels"
    checked = 0
    for m in prediction_manifests:
        prov = m.get("attack_provenance") or {}
        if prov.get("attack_kind") != "learned":
            continue
        checked += 1
        fold = fold_by_id[prov["fold_id"]]
        me = (m["experiment_id"], m["run_id"])
        bad = []
        if prov["split_sha256"] != split_sha:
            bad.append("split digest differs")
        if list(me) not in fold["test_runs"]:
            bad.append("scored run is not a test run of the fold")
        read = prov["training_labels_read"]
        if [me[0], me[1]] in read["runs"]:
            bad.append("training labels of the scored run were read")
        if any(r not in fold["train_runs"] for r in read["runs"]):
            bad.append("labels of a non-training run were read")
        if read["file"]:
            data = (root / read["file"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != read["sha256"]:
                bad.append("training label file digest differs")
            man = json.loads((export_base / fold["fold_id"] / "manifest.json").read_text())
            if man["files"].get(m["relation"]) != read["sha256"]:
                bad.append("training label digest not in the export manifest")
        if bad:
            problems.append({"experiment_id": me[0], "run_id": me[1],
                             "attack_id": m["attack_id"], "problems": bad})
    return {"folds": folds, "learned_prediction_sets_checked": checked,
            "problems": problems, "ok": not problems}
