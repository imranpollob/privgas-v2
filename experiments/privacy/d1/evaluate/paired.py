"""Paired B3-PrivGas-v1 vs B4-CrossAccount comparison (evaluation side).

B3 and B4 runs at one (scenario, pool size, replicate) share the run seed, hence the
actors, asset senders, spender accounts, Semaphore identities and the complete
schedule (``experiments/workloads/d1/schedule.py``); they differ only in which public
account issues the credit. That makes the RUN PAIR the unit of the paired analysis.

For a metric m, each run contributes its subject mean; the B4 - B3 difference is the
subject-weighted mean over run pairs (weights = pool size, matching the pooled tables),
and its 95% CI a percentile bootstrap over run pairs. Nothing here is fitted.

Also reported: whether the R2 candidate universe is identical across every learned
feature set of a subject (a delta_bits between two models is reported only when it is),
and the account-separation evidence of every B4 run (from its private run record).
"""

from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from .labels_io import private_run

B3 = "B3-PrivGas-v1"
B4 = "B4-CrossAccount"
SCEN = {"S0-clean-shuffled": "S0", "S1-correlated-timing": "S1"}

#: (label, selector, metric). selector: ("rule", attack) or ("learned", feature_set).
#: Learned models: leave-one-replicate-out, primary registry convention.
PAIRED_METRICS: Tuple[Tuple[str, Tuple[str, str], str], ...] = (
    ("exact: Bootstrap sender == Spend sender", ("rule", "rule.r2-bootstrap-sender-eq-spend-sender"), "rule_top1"),
    ("exact: CreditSpent sender == depositor", ("rule", "rule.r2-creditspent-sender-eq-depositor"), "rule_top1"),
    ("exact: announcer == asset sender", ("rule", "rule.r2-announcer-eq-asset-sender"), "rule_top1"),
    ("exact: shared-identifier scan", ("rule", "rule.r2-shared-identifier-scan"), "rule_top1"),
    ("timing: insertion-order FIFO", ("rule", "rule.r2-insertion-order-fifo"), "rule_top1"),
    ("timing: common-delay window k=2", ("rule", "rule.r2-window-k2"), "rule_top1"),
    ("learned full trace T+AA+G: top-1", ("learned", "T+AA+G"), "top1"),
    ("learned full trace T+AA+G: CE bits", ("learned", "T+AA+G"), "ce_bits"),
    ("learned no-equality T+AA+G-minus-eq: top-1", ("learned", "T+AA+G-minus-eq"), "top1"),
    ("learned no-equality T+AA+G-minus-eq: CE bits", ("learned", "T+AA+G-minus-eq"), "ce_bits"),
    ("learned timing T+G-minus-eq: top-1", ("learned", "T+G-minus-eq"), "top1"),
    ("learned timing T+G-minus-eq: CE bits", ("learned", "T+G-minus-eq"), "ce_bits"),
    ("learned G-minus-eq (gas+proof+timing): CE bits", ("learned", "G-minus-eq"), "ce_bits"),
    ("learned gas/proof only G-minus-eq-minus-timing: top-1", ("learned", "G-minus-eq-minus-timing"), "top1"),
    ("learned gas/proof only G-minus-eq-minus-timing: CE bits", ("learned", "G-minus-eq-minus-timing"), "ce_bits"),
    ("learned all metadata T+AA+G-minus-eq-minus-timing: CE bits", ("learned", "T+AA+G-minus-eq-minus-timing"), "ce_bits"),
    ("learned no timing T+G-minus-timing: CE bits", ("learned", "T+G-minus-timing"), "ce_bits"),
)

NO_EQUALITY_SETS = ("G-minus-eq", "T+G-minus-eq", "T+AA+G-minus-eq", "G-minus-eq-minus-timing",
                    "T+AA+G-minus-eq-minus-timing")


def _select(rows: Sequence[Mapping[str, Any]], sel: Tuple[str, str], relation: str = "R2"
            ) -> List[Mapping[str, Any]]:
    kind, name = sel
    out = []
    for r in rows:
        if "_unpredicted_labelled" in r or r.get("relation") != relation:
            continue
        if kind == "rule" and r.get("kind") == "rule" and r.get("attack") == name:
            out.append(r)
        elif (kind == "learned" and r.get("kind") == "learned" and r.get("fold_kind") == "loro"
              and r.get("convention") == "primary" and r.get("feature_set") == name):
            out.append(r)
    return out


def _run_means(rows: Sequence[Mapping[str, Any]], metric: str
               ) -> Dict[Tuple[str, str, int, str], Tuple[float, int]]:
    acc: Dict[Tuple[str, str, int, str], List[float]] = defaultdict(list)
    for r in rows:
        v = r.get(metric)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        acc[(r["baseline_id"], r["scenario_id"], r["pool_size"], r["replicate"])].append(v)
    return {k: (float(np.mean(v)), len(v)) for k, v in acc.items()}


def paired_differences(rows: Sequence[Mapping[str, Any]], reps: int = 4000,
                       seed: int = 20260915) -> List[Dict[str, Any]]:
    out = []
    rng = np.random.default_rng(seed)
    for label, sel, metric in PAIRED_METRICS:
        means = _run_means(_select(rows, sel), metric)
        for scen in SCEN:
            pairs = []
            for (b, s, n, rep), (v3, k3) in sorted(means.items()):
                if b != B3 or s != scen:
                    continue
                other = means.get((B4, s, n, rep))
                if other is None:
                    continue
                pairs.append((n, v3, other[0]))
            if not pairs:
                continue
            w = np.array([p[0] for p in pairs], dtype=float)
            v3 = np.array([p[1] for p in pairs])
            v4 = np.array([p[2] for p in pairs])
            chance = None
            if metric in ("top1", "rule_top1"):
                chance = float((w * (1.0 / w)).sum() / w.sum())
            elif metric == "ce_bits":
                chance = float((w * np.log2(w)).sum() / w.sum())
            boots = np.empty(reps)
            for i in range(reps):
                pick = rng.integers(0, len(pairs), size=len(pairs))
                boots[i] = ((w[pick] * (v4[pick] - v3[pick])).sum() / w[pick].sum())
            lo, hi = np.quantile(boots, [0.025, 0.975])
            out.append({"comparison": label, "metric": metric, "scenario_id": scen,
                        "run_pairs": len(pairs), "b3": float((w * v3).sum() / w.sum()),
                        "b4": float((w * v4).sum() / w.sum()), "chance": chance,
                        "b4_minus_b3": float((w * (v4 - v3)).sum() / w.sum()),
                        "ci_lo": float(lo), "ci_hi": float(hi)})
    return out


def paired_by_n(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for label, sel, metric in PAIRED_METRICS:
        means = _run_means(_select(rows, sel), metric)
        cells: Dict[Tuple[str, int], Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
        for (b, s, n, _rep), (v, _k) in means.items():
            cells[(s, n)][b].append(v)
        for (s, n), by_b in sorted(cells.items()):
            if B3 in by_b and B4 in by_b:
                out.append({"comparison": label, "metric": metric, "scenario_id": s,
                            "pool_size": n, "b3": float(np.mean(by_b[B3])),
                            "b4": float(np.mean(by_b[B4])),
                            "chance": (1.0 / n if metric.endswith("top1")
                                       else math.log2(n) if metric == "ce_bits" else None)})
    return out


def candidate_universe_check(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """For every R2 subject: identical candidate-set size across every learned feature set
    and every rule, and the truth always inside it."""
    sizes: Dict[Tuple[str, str, str], set] = defaultdict(set)
    truth_missing = 0
    for r in rows:
        if "_unpredicted_labelled" in r or r.get("relation") != "R2":
            continue
        sizes[(r["experiment_id"], r["run_id"], r["subject_ref"])].add(r["candidate_set_size"])
        if r.get("truth_in_candidate_set") != 1.0:
            truth_missing += 1
    bad = [k for k, v in sizes.items() if len(v) != 1]
    per_b: Dict[str, int] = defaultdict(int)
    for (exp, _run, _ref) in sizes:
        per_b[exp.split("/")[1]] += 1
    return {"subjects": len(sizes), "subjects_by_baseline_slug": dict(per_b),
            "subjects_with_differing_universe": len(bad), "truth_outside_universe": truth_missing,
            "ok": not bad and truth_missing == 0}


def b4_separation_audit(root: Path, runs: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = []
    for r in runs:
        if r["baseline_id"] != B4:
            continue
        priv = private_run(root, r["experiment_id"], r["run_id"])
        sep = (priv.get("b4") or {}).get("account_separation") or {}
        b4_checks = [c for c in priv["checks"] if c["name"].startswith("b4_")]
        actors = priv["actors"]
        rows.append({
            "experiment_id": r["experiment_id"], "run_id": r["run_id"],
            "scenario_id": r["scenario_id"], "pool_size": r["pool_size"],
            "b4_checks": len(b4_checks), "b4_checks_passed": sum(c["ok"] for c in b4_checks),
            "issuer_ne_spender_accounts": sum(a["issuer_account"].lower()
                                              != a["recipient_account"].lower() for a in actors),
            "issuer_ne_spender_keys": sum(a["issuer_key_address"].lower()
                                          != a["recipient_key_address"].lower() for a in actors),
            "distinct_bootstrap_senders": len(sep.get("bootstrap_senders", [])),
            "distinct_spend_senders": len(sep.get("spend_senders", [])),
            "bootstrap_and_spend_sender_overlap": len(set(sep.get("bootstrap_senders", []))
                                                      & set(sep.get("spend_senders", []))),
            "cross_side_transactions": sep.get("cross_side_transactions"),
            "issuer_token_receipts": sep.get("issuer_token_receipts")})
    ok = bool(rows) and all(
        x["b4_checks"] > 0 and x["b4_checks"] == x["b4_checks_passed"]
        and x["issuer_ne_spender_accounts"] == x["pool_size"]
        and x["issuer_ne_spender_keys"] == x["pool_size"]
        and x["distinct_bootstrap_senders"] == x["pool_size"]
        and x["distinct_spend_senders"] == x["pool_size"]
        and x["bootstrap_and_spend_sender_overlap"] == 0
        and x["cross_side_transactions"] == 0 and x["issuer_token_receipts"] == 0 for x in rows)
    return {"runs": rows, "ok": ok}


def _f(v: Any, nd: int = 3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    return f"{v:.{nd}f}" if isinstance(v, float) else str(v)


def markdown(ctx: Mapping[str, Any], md_table) -> str:
    s = []
    s.append("\n#### Paired B3-PrivGas-v1 vs B4-CrossAccount (run pairs matched on scenario, N, "
             "replicate; subject-weighted; 95% bootstrap CI over run pairs)\n")
    s.append(md_table(["scen.", "comparison", "run pairs", "B3", "B4", "chance", "B4 − B3 [CI]"],
                      [[SCEN[d["scenario_id"]], d["comparison"], str(d["run_pairs"]),
                        _f(d["b3"]), _f(d["b4"]), _f(d["chance"]),
                        f"{_f(d['b4_minus_b3'])} [{_f(d['ci_lo'])}, {_f(d['ci_hi'])}]"]
                       for d in sorted(ctx["paired"], key=lambda d: (d["scenario_id"],))]))
    s.append("\n#### Paired comparison by pool size (mean over replicates)\n")
    s.append(md_table(["scen.", "N", "comparison", "B3", "B4", "chance"],
                      [[SCEN[d["scenario_id"]], str(d["pool_size"]), d["comparison"], _f(d["b3"]),
                        _f(d["b4"]), _f(d["chance"])]
                       for d in sorted(ctx["paired_by_n"],
                                       key=lambda d: (d["scenario_id"], d["pool_size"]))]))
    u = ctx["universe"]
    s.append("\n#### R2 candidate universe\n")
    s.append(md_table(["check", "result"], [[k, str(v)] for k, v in u.items()]))
    nd = [d for d in ctx["deltas"] if d["relation"] == "R2" and d["fold_kind"] == "loro"
          and d["convention"] == "primary" and d["from"] == "none"
          and d["to"] in NO_EQUALITY_SETS + ("T+AA+G",)]
    s.append("\n#### R2 predictive delta_bits against the uniform model over the SAME N issuances "
             "(leave-one-replicate-out, primary convention)\n")
    s.append(md_table(["baseline", "scen.", "to", "subjects", "CE uniform", "CE model",
                       "delta_bits [CI]"],
                      [[d["baseline_id"], SCEN[d["scenario_id"]], d["to"], str(d["subjects"]),
                        _f(d["ce_from_bits"]), _f(d["ce_to_bits"]),
                        f"{_f(d['delta_bits'])} [{_f(d['delta_ci_lo'])}, {_f(d['delta_ci_hi'])}]"]
                       for d in sorted(nd, key=lambda d: (d["baseline_id"], d["scenario_id"],
                                                          d["to"]))]))
    sep = ctx["separation"]
    s.append("\n#### B4 account-separation audit (every B4 run; from its private run record)\n")
    s.append(md_table(["scen.", "N", "run", "b4 checks passed", "issuer≠spender accounts",
                       "issuer≠spender keys", "Bootstrap senders", "Spend senders",
                       "sender overlap", "issuer↔spender txs", "W1T to issuer"],
                      [[SCEN[x["scenario_id"]], str(x["pool_size"]), x["run_id"],
                        f"{x['b4_checks_passed']}/{x['b4_checks']}",
                        str(x["issuer_ne_spender_accounts"]), str(x["issuer_ne_spender_keys"]),
                        str(x["distinct_bootstrap_senders"]), str(x["distinct_spend_senders"]),
                        str(x["bootstrap_and_spend_sender_overlap"]),
                        str(x["cross_side_transactions"]), str(x["issuer_token_receipts"])]
                       for x in sorted(sep["runs"], key=lambda x: (x["scenario_id"],
                                                                   x["pool_size"], x["run_id"]))]))
    s.append(f"\nAll B4 runs pass the separation audit: **{sep['ok']}**.")
    return "\n".join(s) + "\n"
