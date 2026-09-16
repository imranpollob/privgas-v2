"""D2 kill-condition analysis: tables, statistics and figures, from recorded data only.

Nothing here types an experimental number: every cell and every plotted point is read from
``results/d2-killcondition/<batch>/raw/*.json`` and
``data/private/d2-killcondition/<batch>/*.jsonl``. ``--write-doc`` replaces the GENERATED
block of ``docs/d2-killcondition-results.md``.

Formatting, Wilson intervals, CSV/JSON writing and the figure style are imported from the
frozen D2 pilot's analysis module so the two documents are formatted identically.

Analytical baseline (Section 8 of the phase brief). Under Poisson root updates with
mu = lambda * T, a proof whose root is retained for K updates is still valid iff fewer than
K updates occur after it::

    P(valid | K) = sum_{j=0}^{K-1} exp(-mu) mu^j / j!
    P(stale | K) = 1 - P(valid | K)

For K = 1 this is 1 - exp(-mu), the frozen baseline the pilot measured.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import stats

from ...recorder.provenance import repo_root
from ..d2.analysis import (C1, C2, C3, INK, INK2, NEUTRAL, _plt, ci, fmt, md_table, wilson,
                           write_csv)
from ..d2.engine import STALE_CLASSES, VALID_PROOF_INCLUDED
from .records import read_jsonl

GWEI = 1e9
DOC = Path("docs") / "d2-killcondition-results.md"
BEGIN = "<!-- BEGIN GENERATED: d2k tables -->"
END = "<!-- END GENERATED: d2k tables -->"
K_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#a259d9", "#d6a52a", "#d62a6e", "#2ab5d6"]


def p_stale(mu: float, k: int) -> float:
    """1 - P(N < K) for N ~ Poisson(mu)."""
    if mu <= 0:
        return 0.0
    return float(1.0 - stats.poisson.cdf(k - 1, mu))


def variant_k(v: str) -> int:
    return 1 if v == "frozen" else int(v[1:])


def order_variants(vs: Sequence[str]) -> List[str]:
    return ([v for v in vs if v == "frozen"]
            + sorted([v for v in vs if v != "frozen"], key=variant_k))


class Data:
    def __init__(self, dirs: Dict[str, Path]) -> None:
        self.dirs = dirs
        self.raw: Dict[str, Any] = {}
        for p in sorted((dirs["results"] / "raw").glob("*.json")):
            self.raw[p.stem] = json.loads(p.read_text())
        self.attempts: Dict[str, List[Dict[str, Any]]] = {}
        for p in sorted(dirs["private"].glob("*.attempts.jsonl")):
            self.attempts[p.name.split(".")[0]] = read_jsonl(p)
        self.arrivals: Dict[str, List[Dict[str, Any]]] = {}
        for p in sorted(dirs["private"].glob("*.arrivals.jsonl")):
            self.arrivals[p.name.split(".")[0]] = read_jsonl(p)
        man = dirs["results"] / "manifest.json"
        self.manifest = json.loads(man.read_text()) if man.is_file() else {}


# --- Question A tables --------------------------------------------------------------------


def boundary_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("boundary") or {}).get("rows", [])
    agg: Dict[Tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        agg[(r["variant"], r["intervening_root_updates"])].append(r)
    out = []
    for (v, dd), rs in sorted(agg.items(), key=lambda kv: (variant_k(kv[0][0]),
                                                           kv[0][0] != "frozen", kv[0][1])):
        inc = sum(1 for r in rs if r["included"])
        out.append({
            "variant": v, "history_capacity": rs[0]["history_capacity"],
            "intervening_root_updates": dd, "runs": len(rs), "included": inc,
            "predicted_valid": rs[0]["predicted_valid"],
            "prediction_matches": sum(1 for r in rs if r["prediction_matches_outcome"]),
            "simulation_accepted": sum(1 for r in rs if r["simulation_accepted"]),
            "view_accepts_proof_root": sum(1 for r in rs if r["view_accepts_proof_root"]),
            "root_age_at_inclusion": sorted({r["root_age_at_inclusion"] for r in rs}),
            "onchain_error": sorted({r["onchain_revert_inner_error"] for r in rs}),
            "nullifier_spent": sum(1 for r in rs if r["nullifier_spent"]),
            "nonce_advanced": sum(1 for r in rs if r["nonce_advanced"]),
            "bundler_net_gwei_mean": float(np.mean([r["bundler_net_wei"] for r in rs])) / GWEI,
            "sponsor_charge_gwei_mean": float(np.mean([r["sponsor_charge_wei"] for r in rs])) / GWEI,
        })
    md = md_table(["variant", "K", "intervening root updates", "runs", "included",
                   "model says valid", "model = outcome", "sim accepted", "view accepts",
                   "root age", "on-chain error", "nullifier spent", "nonce advanced",
                   "bundler net (gwei)", "sponsor charge (gwei)"],
                  [[r["variant"], r["history_capacity"], r["intervening_root_updates"],
                    r["runs"], r["included"], str(r["predicted_valid"]), r["prediction_matches"],
                    r["simulation_accepted"], r["view_accepts_proof_root"],
                    ", ".join(str(x) for x in r["root_age_at_inclusion"]),
                    ", ".join(str(x) for x in r["onchain_error"]), r["nullifier_spent"],
                    r["nonce_advanced"], r["bundler_net_gwei_mean"],
                    r["sponsor_charge_gwei_mean"]] for r in out])
    return md, out


def security_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("security") or {}).get("rows", [])
    agg: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        agg[r["case"]].append(r)
    order = ["current_root_accepted", "retained_historical_root_accepted",
             "root_older_than_window_rejected", "fabricated_root_rejected",
             "future_unknown_root_rejected", "wrong_message_rejected", "wrong_scope_rejected",
             "invalid_groth16_rejected", "nullifier_reuse_rejected",
             "same_credit_twice_rejected", "k1_matches_frozen"]
    out = []
    for case in [c for c in order if c in agg] + [c for c in agg if c not in order]:
        rs = agg[case]
        out.append({"case": case, "K": rs[0]["history_capacity"], "runs": len(rs),
                    "expectation_met": sum(1 for r in rs if r["expectation_met"]),
                    "expected_included": rs[0].get("expected_included"),
                    "included": sum(1 for r in rs if r.get("included")),
                    "expected_error": rs[0].get("expected_error"),
                    "observed_errors": sorted({r.get("observed_error") for r in rs
                                               if r.get("observed_error")}),
                    "rejected_at_simulation": sum(1 for r in rs
                                                  if r.get("simulation_accepted") is False),
                    "detail": ("same acceptance and same current root as the frozen contract "
                               "at every root state" if case == "k1_matches_frozen" else "")})
    md = md_table(["invariant", "K", "runs", "held", "expected included", "included",
                   "expected error", "observed error", "rejected at simulation"],
                  [[r["case"], r["K"], r["runs"], r["expectation_met"],
                    str(r["expected_included"]), r["included"], str(r["expected_error"]),
                    ", ".join(str(x) for x in r["observed_errors"]) or "–",
                    r["rejected_at_simulation"]] for r in out])
    return md, out


def stochastic_tables(d: Data) -> Tuple[str, str, Dict[str, Any], List[Dict[str, Any]]]:
    recs = d.attempts.get("stochastic", [])
    cells: Dict[Tuple[str, float, float], List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        cells[(r["variant"], float(r["lambda"]), float(r["window"]))].append(r)
    cell_rows = []
    for (v, lam, T), rs in sorted(cells.items(), key=lambda kv: (variant_k(kv[0][0]),
                                                                 kv[0][1], kv[0][2])):
        stale = sum(1 for r in rs if r["outcome_class"] in STALE_CLASSES)
        mu = lam * T
        k = rs[0]["history_capacity"]
        lo, hi = wilson(stale, len(rs))
        analytic = p_stale(mu, k)
        cell_rows.append({
            "variant": v, "history_capacity": k, "lambda": lam, "T": T, "lambda_T": mu,
            "trials": len(rs), "stale": stale, "p_hat": stale / len(rs),
            "ci_low": lo, "ci_high": hi, "analytic_p_stale": analytic,
            "in_ci": (lo is not None and lo <= analytic <= hi),
            "binom_p": float(stats.binomtest(stale, len(rs), min(max(analytic, 1e-12),
                                                                 1 - 1e-12)).pvalue),
            "included": sum(1 for r in rs if r["outcome_class"] == VALID_PROOF_INCLUDED),
            "sim_accepted": sum(1 for r in rs if r.get("simulation_result") == "accepted"),
            "valid_at_sim_stale_before_inclusion": sum(
                1 for r in rs if r["outcome_class"] == "VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION"),
            "other_failures": sum(1 for r in rs if r["outcome_class"] not in
                                  STALE_CLASSES + (VALID_PROOF_INCLUDED,)),
            "inconsistent": sum(1 for r in rs if r.get("consistent") is False),
            "model_mismatch": sum(1 for r in rs if r.get("prediction_matches_outcome") is False),
            "root_updates_survived_mean": float(np.mean(
                [r["root_updates_survived"] for r in rs
                 if r.get("root_updates_survived") is not None] or [np.nan])),
            "root_age_at_inclusion_max": max(
                [r["root_updates_survived"] for r in rs
                 if r.get("root_updates_survived") is not None] or [0]),
            "bundler_loss_gwei_total": sum(r.get("bundler_loss_wei") or 0 for r in rs) / GWEI,
            "sponsor_charge_gwei_total": sum(r.get("sponsor_credit_charge_wei") or 0
                                             for r in rs) / GWEI,
        })
    # pooled by variant
    by_v: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        by_v[r["variant"]].append(r)
    pooled = []
    for v in order_variants(by_v):
        rs = by_v[v]
        pos = [r for r in rs if float(r["lambda"]) > 0]
        stale = sum(1 for r in pos if r["outcome_class"] in STALE_CLASSES)
        lo, hi = wilson(stale, len(pos))
        sim_stale = sum(1 for r in pos if r["outcome_class"]
                        == "VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION")
        pooled.append({
            "variant": v, "history_capacity": rs[0]["history_capacity"],
            "trials_all": len(rs), "trials_lambda_pos": len(pos), "stale": stale,
            "p_hat": stale / len(pos) if pos else None, "ci_low": lo, "ci_high": hi,
            "valid_at_sim_stale_before_inclusion": sim_stale,
            "included": sum(1 for r in rs if r["outcome_class"] == VALID_PROOF_INCLUDED),
            "other_failures": sum(1 for r in rs if r["outcome_class"] not in
                                  STALE_CLASSES + (VALID_PROOF_INCLUDED,)),
            "inconsistent": sum(1 for r in rs if r.get("consistent") is False),
            "model_mismatch": sum(1 for r in rs if r.get("prediction_matches_outcome") is False),
            "bundler_loss_gwei_total": sum(r.get("bundler_loss_wei") or 0 for r in rs) / GWEI,
            "max_root_updates_survived": max(
                [r["root_updates_survived"] for r in rs
                 if r.get("root_updates_survived") is not None] or [0]),
        })
    md_pooled = md_table(
        ["variant", "K", "trials (λ>0)", "stale", "P̂(stale)", "95% CI",
         "valid at sim → stale at inclusion", "included (all cells)", "other failures",
         "inconsistent", "model mismatch", "bundler loss (gwei)", "max root updates survived"],
        [[r["variant"], r["history_capacity"], r["trials_lambda_pos"], r["stale"],
          r["p_hat"], ci(r["ci_low"], r["ci_high"]), r["valid_at_sim_stale_before_inclusion"],
          r["included"], r["other_failures"], r["inconsistent"], r["model_mismatch"],
          r["bundler_loss_gwei_total"], r["max_root_updates_survived"]] for r in pooled])
    # analytic-vs-measured, grouped by lambda*T
    by_mu: Dict[Tuple[int, float], List[Dict[str, Any]]] = defaultdict(list)
    for r in cell_rows:
        if r["lambda"] > 0:
            by_mu[(r["history_capacity"], round(r["lambda_T"], 6))].append(r)
    fit_rows = []
    for (k, mu), rs in sorted(by_mu.items()):
        trials = sum(r["trials"] for r in rs)
        stale = sum(r["stale"] for r in rs)
        lo, hi = wilson(stale, trials)
        a = p_stale(mu, k)
        fit_rows.append({"history_capacity": k, "lambda_T": mu, "trials": trials,
                         "stale": stale, "p_hat": stale / trials, "ci_low": lo, "ci_high": hi,
                         "analytic_p_stale": a, "in_ci": lo <= a <= hi,
                         "abs_error": abs(stale / trials - a)})
    md_fit = md_table(["K", "λT", "trials", "stale", "P̂(stale)", "95% CI",
                       "analytic P(stale|K)", "in CI", "|error|"],
                      [[r["history_capacity"], r["lambda_T"], r["trials"], r["stale"],
                        r["p_hat"], ci(r["ci_low"], r["ci_high"]), r["analytic_p_stale"],
                        str(r["in_ci"]), r["abs_error"]] for r in fit_rows])
    summary = {"pooled": pooled, "fit": fit_rows,
               "cells": len(cell_rows),
               "cells_outside_ci": sum(1 for r in cell_rows if r["lambda"] > 0
                                       and not r["in_ci"]),
               "cells_lambda_pos": sum(1 for r in cell_rows if r["lambda"] > 0),
               "total_attempts": len(recs),
               "total_inconsistent": sum(1 for r in recs if r.get("consistent") is False),
               "total_model_mismatch": sum(1 for r in recs
                                           if r.get("prediction_matches_outcome") is False),
               "outcome_classes": dict(Counter(r["outcome_class"] for r in recs))}
    return md_pooled, md_fit, summary, cell_rows


def retry_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    recs = d.attempts.get("retry", [])
    trials = (d.raw.get("retry") or {}).get("trials", [])
    by_v: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in recs:
        by_v[r["variant"]].append(r)
    tr_by_v: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in trials:
        tr_by_v[t["variant"]].append(t)
    out = []
    for v in order_variants(by_v):
        rs = by_v[v]
        ts = [t for t in tr_by_v[v] if float(t["lambda"]) > 0]
        succ = [t for t in ts if t["successes"] > 0]
        attempts = sum(t["attempts"] for t in ts)
        sims = sum(t["simulations"] for t in ts)
        times = [r["time_to_success"] for r in rs if r.get("time_to_success") is not None
                 and float(r["lambda"]) > 0]
        out.append({
            "variant": v, "history_capacity": rs[0]["history_capacity"],
            "trials_lambda_pos": len(ts), "successes": len(succ),
            "success_rate": len(succ) / len(ts) if ts else None,
            "attempts_per_success": attempts / len(succ) if succ else None,
            "proofs_per_success": attempts / len(succ) if succ else None,
            "simulations_per_success": sims / len(succ) if succ else None,
            "failures_at_simulation": sum(1 for r in rs if r.get("failure_stage") == "simulation"),
            "failures_onchain": sum(1 for r in rs if r.get("failure_stage") == "onchain"),
            "bundler_loss_gwei": sum(r.get("bundler_loss_wei") or 0 for r in rs) / GWEI,
            "time_to_success_p50": float(np.percentile(times, 50)) if times else None,
            "time_to_success_p95": float(np.percentile(times, 95)) if times else None,
            "proof_ms_total": sum(r.get("proof_generation_ms") or 0 for r in rs),
        })
    md = md_table(["variant", "K", "trials (λ>0)", "successes", "success rate",
                   "attempts (= proofs) / success", "simulations / success",
                   "failures at simulation", "failures on chain", "bundler loss (gwei)",
                   "time to success p50 (s)", "p95 (s)", "proving ms (total)"],
                  [[r["variant"], r["history_capacity"], r["trials_lambda_pos"],
                    r["successes"], r["success_rate"], r["attempts_per_success"],
                    r["simulations_per_success"], r["failures_at_simulation"],
                    r["failures_onchain"], r["bundler_loss_gwei"],
                    r["time_to_success_p50"], r["time_to_success_p95"],
                    r["proof_ms_total"]] for r in out])
    return md, out


def bundle_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("bundle") or {}).get("rows", [])
    agg: Dict[Tuple[str, str, int, int], List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        agg[(r["mode"], r["variant"], r["bundle_size"], r["intervening_root_updates"])].append(r)
    out = []
    for (mode, v, bs, dd), rs in sorted(
            agg.items(), key=lambda kv: (kv[0][0], variant_k(kv[0][1]), kv[0][1] != "frozen",
                                         kv[0][2], kv[0][3])):
        out.append({"mode": mode, "variant": v, "history_capacity": rs[0]["history_capacity"],
                    "bundle_size": bs, "intervening_root_updates": dd, "runs": len(rs),
                    "all_included": sum(1 for r in rs if r["all_included"]),
                    "included_ops_total": sum(r["included_ops"] for r in rs),
                    "ops_total": sum(r["ops"] for r in rs),
                    "predicted_all_included": rs[0]["predicted_all_included"],
                    "onchain_error": sorted({r["onchain_revert_inner_error"] for r in rs}),
                    "failing_op_index": sorted({r["onchain_revert_op_index"] for r in rs}),
                    "bundler_net_gwei_mean": float(np.mean(
                        [r["bundler_net_wei"] for r in rs])) / GWEI})
    md = md_table(["mode", "variant", "K", "bundle size", "intervening root updates", "runs",
                   "whole bundle included", "ops included / ops", "model says all included",
                   "on-chain error", "failing op index", "bundler net (gwei)"],
                  [[r["mode"], r["variant"], r["history_capacity"], r["bundle_size"],
                    r["intervening_root_updates"], r["runs"], r["all_included"],
                    f'{r["included_ops_total"]}/{r["ops_total"]}',
                    str(r["predicted_all_included"]),
                    ", ".join(str(x) for x in r["onchain_error"]),
                    ", ".join(str(x) for x in r["failing_op_index"]),
                    r["bundler_net_gwei_mean"]] for r in out])
    return md, out


def overhead_tables(d: Data) -> Tuple[str, str, str, Dict[str, List[Dict[str, Any]]]]:
    raw = d.raw.get("overhead") or {}
    upd, val, dep = raw.get("root_update", []), raw.get("spend_validation", []), \
        raw.get("deployment", [])

    def base(rows: List[Dict[str, Any]], key) -> Dict[Any, float]:
        return {key(r): r for r in rows if r["variant"] == "frozen"}

    # validation overhead
    fro_v = [r for r in val if r["variant"] == "frozen"]
    fro_validate = float(np.mean([r["validate_frame_gas_used"] for r in fro_v])) if fro_v else None
    fro_actual = float(np.mean([r["actual_gas_used"] for r in fro_v])) if fro_v else None
    by_v: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in val:
        by_v[r["variant"]].append(r)
    val_rows = []
    for v in order_variants(by_v):
        rs = by_v[v]
        g = float(np.mean([r["validate_frame_gas_used"] for r in rs]))
        a = float(np.mean([r["actual_gas_used"] for r in rs]))
        val_rows.append({
            "variant": v, "history_capacity": rs[0]["history_capacity"], "samples": len(rs),
            "validate_frame_gas": g, "delta_vs_frozen_gas": g - fro_validate,
            "delta_vs_frozen_fraction": (g - fro_validate) / fro_validate,
            "verify_proof_frame_gas": float(np.mean([r["verify_proof_frame_gas_used"]
                                                     for r in rs])),
            "userop_actual_gas_used": a, "actual_delta_vs_frozen_gas": a - fro_actual,
            "actual_delta_fraction": (a - fro_actual) / fro_actual,
            "paymaster_charge_wei": float(np.mean([r["paymaster_charge_wei"] for r in rs])),
            "paymaster_slots_written": sorted({r["paymaster_slots_written"] for r in rs}),
            "proof_depth": sorted({r["proof_depth"] for r in rs}),
            "pool_size": sorted({r["pool_size"] for r in rs})})
    md_val = md_table(
        ["variant", "K", "samples", "validatePaymasterUserOp frame gas", "Δ vs frozen (gas)",
         "Δ vs frozen", "verifyProof frame gas", "UserOp actualGasUsed", "Δ actual (gas)",
         "Δ actual", "Paymaster charge (wei)", "Paymaster slots written"],
        [[r["variant"], r["history_capacity"], r["samples"], r["validate_frame_gas"],
          r["delta_vs_frozen_gas"], f'{r["delta_vs_frozen_fraction"] * 100:.3f}%',
          r["verify_proof_frame_gas"], r["userop_actual_gas_used"],
          r["actual_delta_vs_frozen_gas"], f'{r["actual_delta_fraction"] * 100:.3f}%',
          r["paymaster_charge_wei"],
          ", ".join(str(x) for x in r["paymaster_slots_written"])] for r in val_rows])

    # root-update overhead
    fro_u = {r["tree_size_before"]: r for r in upd if r["variant"] == "frozen"}
    by_vu: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in upd:
        by_vu[r["variant"]].append(r)
    upd_rows = []
    for v in order_variants(by_vu):
        for r in sorted(by_vu[v], key=lambda x: x["tree_size_before"]):
            f = fro_u.get(r["tree_size_before"])
            if not f:
                continue
            dep_d = r["deposit_frame_gas_used"] - f["deposit_frame_gas_used"]
            boot_d = ((r["bootstrap_actual_gas_used"] or 0)
                      - (f["bootstrap_actual_gas_used"] or 0))
            upd_rows.append({
                "variant": v, "history_capacity": r["history_capacity"],
                "tree_size_before": r["tree_size_before"],
                "mirror_frame_gas": r["mirror_root_frame_gas_used"],
                "mirror_delta_gas": (r["mirror_root_frame_gas_used"] or 0)
                - (f["mirror_root_frame_gas_used"] or 0),
                "deposit_frame_gas": r["deposit_frame_gas_used"],
                "deposit_delta_gas": dep_d,
                "deposit_delta_fraction": dep_d / f["deposit_frame_gas_used"],
                "bootstrap_actual_gas_used": r["bootstrap_actual_gas_used"],
                "bootstrap_delta_gas": boot_d,
                "bootstrap_delta_fraction": (boot_d / f["bootstrap_actual_gas_used"]
                                             if f["bootstrap_actual_gas_used"] else None),
                "paymaster_slots_written": r["paymaster_slots_written"],
                "paymaster_slots_new_nonzero": r["paymaster_slots_new_nonzero"],
                "history_length": r["history_length"],
                "sponsor_charge_wei": r["bootstrap_sponsor_charge_wei"]})
    md_upd = md_table(
        ["variant", "K", "tree size", "mirrorRoot frame gas", "Δ mirror (gas)",
         "deposit frame gas", "Δ deposit (gas)", "Δ deposit", "Bootstrap actualGasUsed",
         "Δ Bootstrap (gas)", "Δ Bootstrap", "Paymaster slots written", "new non-zero",
         "history length"],
        [[r["variant"], r["history_capacity"], r["tree_size_before"], r["mirror_frame_gas"],
          r["mirror_delta_gas"], r["deposit_frame_gas"], r["deposit_delta_gas"],
          f'{r["deposit_delta_fraction"] * 100:.2f}%', r["bootstrap_actual_gas_used"],
          r["bootstrap_delta_gas"],
          (f'{r["bootstrap_delta_fraction"] * 100:.2f}%'
           if r["bootstrap_delta_fraction"] is not None else "–"),
          r["paymaster_slots_written"], r["paymaster_slots_new_nonzero"],
          r["history_length"]] for r in upd_rows])

    # deployment / code size
    by_vd: Dict[str, Dict[str, Any]] = {}
    for r in dep:
        if "CreditPaymaster" in r["name"] and r["variant"] not in by_vd:
            by_vd[r["variant"]] = r
    fro_d = by_vd.get("frozen")
    dep_rows = []
    for v in order_variants(by_vd):
        r = by_vd[v]
        dep_rows.append({
            "variant": v, "history_capacity": r["history_capacity"], "contract": r["name"],
            "deployment_gas": r["deployment_gas"],
            "deployment_delta_gas": r["deployment_gas"] - fro_d["deployment_gas"],
            "runtime_code_bytes": r["runtime_code_bytes"],
            "runtime_code_delta_bytes": r["runtime_code_bytes"] - fro_d["runtime_code_bytes"],
            "steady_state_storage_slots": 1 if v == "frozen" else 2 * variant_k(v) + 1,
            "eip170_headroom_bytes": 24576 - r["runtime_code_bytes"]})
    md_dep = md_table(["variant", "K", "contract", "deployment gas", "Δ gas",
                       "runtime code (bytes)", "Δ bytes", "steady-state storage slots",
                       "EIP-170 headroom (bytes)"],
                      [[r["variant"], r["history_capacity"], r["contract"],
                        r["deployment_gas"], r["deployment_delta_gas"],
                        r["runtime_code_bytes"], r["runtime_code_delta_bytes"],
                        r["steady_state_storage_slots"], r["eip170_headroom_bytes"]]
                       for r in dep_rows])
    return md_val, md_upd, md_dep, {"validation": val_rows, "root_update": upd_rows,
                                    "deployment": dep_rows}


# --- kill-condition evaluation -------------------------------------------------------------


def kill_condition(cfg: Dict[str, Any], stoch: Dict[str, Any], cells: List[Dict[str, Any]],
                   over: Dict[str, List[Dict[str, Any]]]) -> Tuple[str, List[Dict[str, Any]]]:
    th = cfg["d2k"]["preregistered_thresholds"]
    max_mu = float(th.get("stale_failure_region_max_lambda_T", 1.0))
    rows = []
    val = {r["variant"]: r for r in over.get("validation", [])}
    dep = {r["variant"]: r for r in over.get("deployment", [])}
    upd_by_v: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in over.get("root_update", []):
        upd_by_v[r["variant"]].append(r)
    for v in order_variants({r["variant"] for r in cells}):
        region = [r for r in cells if r["variant"] == v and 0 < r["lambda_T"] <= max_mu]
        trials = sum(r["trials"] for r in region)
        stale = sum(r["stale"] for r in region)
        lo, hi = wilson(stale, trials)
        vr = val.get(v)
        ur = upd_by_v.get(v, [])
        worst_upd = max((r["bootstrap_delta_fraction"] or 0) for r in ur) if ur else None
        dr = dep.get(v)
        ok_stale = hi is not None and hi <= float(th["stale_failure_rate_max"])
        ok_val = vr is not None and vr["actual_delta_fraction"] <= float(
            th["validation_overhead_max_fraction"])
        ok_upd = worst_upd is not None and worst_upd <= float(
            th["root_update_overhead_max_fraction"])
        slots = dr["steady_state_storage_slots"] if dr else None
        ok_store = slots is not None and slots <= int(th["bounded_storage_max_total_slots"])
        rows.append({
            "variant": v, "history_capacity": variant_k(v),
            "region": f"0 < λT ≤ {max_mu:g}", "trials": trials, "stale": stale,
            "stale_rate": stale / trials if trials else None, "ci_high": hi,
            "threshold_stale": float(th["stale_failure_rate_max"]), "meets_stale": ok_stale,
            "validation_overhead_fraction": vr["actual_delta_fraction"] if vr else None,
            "threshold_validation": float(th["validation_overhead_max_fraction"]),
            "meets_validation": ok_val,
            "root_update_overhead_fraction_worst": worst_upd,
            "threshold_root_update": float(th["root_update_overhead_max_fraction"]),
            "meets_root_update": ok_upd,
            "steady_state_storage_slots": slots, "meets_storage": ok_store,
            "meets_all": bool(ok_stale and ok_val and ok_upd and ok_store)})
    smallest = next((r["history_capacity"] for r in rows
                     if r["meets_all"] and r["variant"] != "frozen"), None)
    md = md_table(["variant", "K", "region", "trials", "stale", "stale rate", "95% CI upper",
                   f'< {th["stale_failure_rate_max"]}', "validation overhead",
                   f'< {th["validation_overhead_max_fraction"]}',
                   "root-update overhead (worst size)",
                   f'< {th["root_update_overhead_max_fraction"]}', "storage slots",
                   f'<= {th["bounded_storage_max_total_slots"]}', "meets all"],
                  [[r["variant"], r["history_capacity"], r["region"], r["trials"], r["stale"],
                    r["stale_rate"], r["ci_high"], str(r["meets_stale"]),
                    (f'{r["validation_overhead_fraction"] * 100:.3f}%'
                     if r["validation_overhead_fraction"] is not None else "–"),
                    str(r["meets_validation"]),
                    (f'{r["root_update_overhead_fraction_worst"] * 100:.2f}%'
                     if r["root_update_overhead_fraction_worst"] is not None else "–"),
                    str(r["meets_root_update"]), r["steady_state_storage_slots"],
                    str(r["meets_storage"]), str(r["meets_all"])] for r in rows])
    md += (f"\n\nSmallest K meeting every pre-registered threshold: "
           f"**{smallest if smallest else 'none'}**.")
    return md, rows


# --- Question B tables ---------------------------------------------------------------------


def decomp_tables(d: Data) -> Tuple[str, str, Dict[str, Any], List[Dict[str, Any]]]:
    raw = d.raw.get("decomp") or {}
    rows = raw.get("rows", [])
    floor = raw.get("floor", {})
    seeds = sorted({r["seed"] for r in rows})
    base = [r for r in rows if r["seed"] == seeds[0]] if seeds else []
    poseidon_gas = (float(np.median(floor.get("g5_poseidon_hash_gas_warm") or [np.nan]))
                    if floor else float("nan"))
    g3a = float(np.median([r["g3a_frame_gas"] for r in base
                           if r.get("g3a_frame_gas") and r["tree_size_before"] > 0] or [np.nan]))
    g3b = float(np.median([r["g3b_frame_gas"] for r in base
                           if r.get("g3b_frame_gas") and r["tree_size_before"] > 0] or [np.nan]))
    g2f = float(np.median([r["g2_frozen_mirror_frame_gas"] for r in base
                           if r.get("g2_frozen_mirror_frame_gas")
                           and r["tree_size_before"] > 0] or [np.nan]))
    g4 = float(np.median(floor.get("g4_noop_frame_gas") or [np.nan]))
    curve = []
    for r in base:
        s = r["tree_size_before"]
        resid = (r["g0_deposit_frame_gas"] - r["g1_insert_frame_gas"] - g3a) if s > 0 else None
        curve.append({
            "tree_size_before": s, "tree_size_after": r["tree_size_after"],
            "leanimt_depth_after": r["leanimt_depth_after"],
            "index_set_bits": r["insertion_index_bits"],
            "g0_deposit_frame_gas": r["g0_deposit_frame_gas"],
            "g1_insert_frame_gas": r["g1_insert_frame_gas"],
            "g0_minus_g1": r["g0_deposit_frame_gas"] - r["g1_insert_frame_gas"],
            "g2_frozen_mirror_frame_gas": r.get("g2_frozen_mirror_frame_gas"),
            "g3a_frame_gas": r.get("g3a_frame_gas"), "g3b_frame_gas": r.get("g3b_frame_gas"),
            "g0_poseidon_calls": r["g0_poseidon_calls"],
            "g1_poseidon_calls": r["g1_poseidon_calls"],
            "g0_pool_slots_written": r["g0_pool_slots_written"],
            "g0_pool_slots_new_nonzero": r["g0_pool_slots_new_nonzero"],
            "g1_slots_written": r["g1_slots_written"],
            "g1_slots_new_nonzero": r["g1_slots_new_nonzero"],
            "g0_mirror_frame_gas": r["g0_mirror_frame_gas"],
            "g0_bootstrap_actual_gas_used": r["g0_bootstrap_actual_gas_used"],
            "g0_bootstrap_sponsor_charge_wei": r["g0_bootstrap_sponsor_charge_wei"],
            "predicted_g0_from_parts": (r["g1_insert_frame_gas"] + g3a) if s > 0 else None,
            "residual_gas": resid,
            "residual_fraction": (resid / r["g0_deposit_frame_gas"]) if resid is not None else None,
        })
    show = [r for r in curve if r["tree_size_before"] in
            (0, 1, 2, 3, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255)]
    md_curve = md_table(
        ["tree size before", "after", "depth", "index set bits", "G0 deposit", "G1 insert",
         "G0 − G1", "G2 mirror", "G3a", "Poseidon calls (G0/G1)", "pool slots (written/new)",
         "G1 slots (written/new)", "Bootstrap actualGasUsed", "predicted G0 = G1 + G3a",
         "residual"],
        [[r["tree_size_before"], r["tree_size_after"], r["leanimt_depth_after"],
          r["index_set_bits"], r["g0_deposit_frame_gas"], r["g1_insert_frame_gas"],
          r["g0_minus_g1"], r["g2_frozen_mirror_frame_gas"], r["g3a_frame_gas"],
          f'{r["g0_poseidon_calls"]}/{r["g1_poseidon_calls"]}',
          f'{r["g0_pool_slots_written"]}/{r["g0_pool_slots_new_nonzero"]}',
          f'{r["g1_slots_written"]}/{r["g1_slots_new_nonzero"]}',
          r["g0_bootstrap_actual_gas_used"], r["predicted_g0_from_parts"],
          r["residual_gas"]] for r in show])

    # per-level explanation: worst case at sizes 2^d - 1
    worst = [r for r in curve if r["tree_size_before"] > 0
             and (r["tree_size_before"] + 1) & r["tree_size_before"] == 0]
    level_rows = []
    prev = None
    for r in sorted(worst, key=lambda x: x["tree_size_before"]):
        level_rows.append({
            "tree_size_before": r["tree_size_before"],
            "poseidon_calls": r["g0_poseidon_calls"],
            "g0_deposit_frame_gas": r["g0_deposit_frame_gas"],
            "g1_insert_frame_gas": r["g1_insert_frame_gas"],
            "delta_g0_vs_previous_level": (r["g0_deposit_frame_gas"]
                                           - prev["g0_deposit_frame_gas"]) if prev else None,
            "delta_g1_vs_previous_level": (r["g1_insert_frame_gas"]
                                           - prev["g1_insert_frame_gas"]) if prev else None,
            "delta_poseidon_calls": (r["g0_poseidon_calls"]
                                     - prev["poseidon_calls"]) if prev else None,
            "measured_poseidon_call_gas": poseidon_gas,
            "unexplained_per_level": ((r["g0_deposit_frame_gas"] - prev["g0_deposit_frame_gas"])
                                      - (r["g0_poseidon_calls"] - prev["poseidon_calls"])
                                      * poseidon_gas) if prev else None})
        prev = {"g0_deposit_frame_gas": r["g0_deposit_frame_gas"],
                "g1_insert_frame_gas": r["g1_insert_frame_gas"],
                "poseidon_calls": r["g0_poseidon_calls"]}
    md_level = md_table(
        ["tree size (2^d − 1)", "Poseidon calls", "G0 deposit", "G1 insert",
         "Δ G0 / level", "Δ G1 / level", "Δ Poseidon calls",
         "measured PoseidonT3.hash gas", "unexplained per level"],
        [[r["tree_size_before"], r["poseidon_calls"], r["g0_deposit_frame_gas"],
          r["g1_insert_frame_gas"], r["delta_g0_vs_previous_level"],
          r["delta_g1_vs_previous_level"], r["delta_poseidon_calls"],
          r["measured_poseidon_call_gas"], r["unexplained_per_level"]] for r in level_rows])
    summary = {
        "poseidon_hash_gas_warm_median": poseidon_gas,
        "poseidon_hash_gas_first": floor.get("g5_poseidon_hash_gas_first"),
        "g4_call_floor_gas": g4, "g2_frozen_mirror_steady_gas": g2f,
        "g3a_surround_gas": g3a, "g3b_surround_plus_bookkeeping_gas": g3b,
        "g3b_minus_g3a": g3b - g3a,
        "residual_median_gas": float(np.median([r["residual_gas"] for r in curve
                                                if r["residual_gas"] is not None] or [np.nan])),
        "residual_max_abs_gas": float(np.max(np.abs([r["residual_gas"] for r in curve
                                                     if r["residual_gas"] is not None]
                                                    or [np.nan]))),
        "residual_max_fraction": float(np.max([abs(r["residual_fraction"]) for r in curve
                                               if r["residual_fraction"] is not None]
                                              or [np.nan])),
        "checks": raw.get("checks", {}),
        "seeds": seeds,
        "g0_at_size_0": next((r["g0_deposit_frame_gas"] for r in curve
                              if r["tree_size_before"] == 0), None),
        "g0_at_max": curve[-1]["g0_deposit_frame_gas"] if curve else None,
        "max_tree_size": curve[-1]["tree_size_before"] if curve else None,
        "seed_agreement": _seed_agreement(rows, seeds),
    }
    return md_curve, md_level, summary, curve


def _seed_agreement(rows: List[Dict[str, Any]], seeds: List[int]) -> Optional[bool]:
    if len(seeds) < 2:
        return None
    by = defaultdict(dict)
    for r in rows:
        by[r["tree_size_before"]][r["seed"]] = r["g0_deposit_frame_gas"]
    return all(len(set(v.values())) == 1 for v in by.values() if len(v) == len(seeds))


def envelope_tables(d: Data) -> Tuple[str, str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    raw = d.raw.get("envelope") or {}
    limits = raw.get("limits", [])
    fees = raw.get("fees", [])
    md_lim = md_table(
        ["tree size", "frozen callGasLimit", "frozen: included", "execution success",
         "commitment inserted", "failure class", "grant consumed",
         "sponsor charged (wei)", "minimal sufficient callGasLimit", "frozen margin (gas)",
         "actualGasUsed at minimal limit"],
        [[r["tree_size_before"], r["frozen_call_gas_limit"], str(r["frozen_included"]),
          str(r["frozen_execution_success"]), str(r["frozen_root_changed"]),
          str(r["frozen_failure_class"]), str(r["frozen_grant_consumed"]),
          r["frozen_paymaster_charge_wei"], r["min_required_call_gas_limit"],
          r["frozen_limit_margin_gas"], r["minreq_actual_gas_used"]] for r in limits])
    agg: Dict[Tuple[int, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in fees:
        agg[(r["tree_size_before"], r["limit_kind"])].append(r)
    fee_rows = []
    for (s, kind), rs in sorted(agg.items()):
        ok = [r["max_fee_gwei"] for r in rs if r["sim_accepted"]]
        gas_sum = rs[0]["gas_limits_sum"]
        fee_rows.append({
            "tree_size_before": s, "limit_kind": kind,
            "call_gas_limit": rs[0]["call_gas_limit"], "gas_limits_sum": gas_sum,
            "max_feasible_gwei_measured": max(ok) if ok else None,
            "analytic_p_max_gwei": 0.005e18 / gas_sum / 1e9 if gas_sum else None,
            "nominal_cap_gwei": 10.0,
            "nominal_cap_reachable": bool(ok and max(ok) >= 10.0),
            "refusals": sorted({r["sim_inner_error"] for r in rs if not r["sim_accepted"]})})
    md_fee = md_table(
        ["tree size", "limit kind", "callGasLimit", "Σ gas limits",
         "max feasible gas price (gwei)", "analytic p_max = 0.005 ETH / Σ (gwei)",
         "nominal cap (gwei)", "nominal cap reachable", "refusal"],
        [[r["tree_size_before"], r["limit_kind"], r["call_gas_limit"], r["gas_limits_sum"],
          r["max_feasible_gwei_measured"], r["analytic_p_max_gwei"], r["nominal_cap_gwei"],
          str(r["nominal_cap_reachable"]),
          ", ".join(str(x) for x in r["refusals"]) or "–"] for r in fee_rows])
    return md_lim, md_fee, limits, fee_rows


def grant_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("grant") or {}).get("rows", [])
    out = []
    for r in rows:
        b, a, ar = r["state_before"], r["state_after_failure"], r["state_after_retry"]
        sf = r["self_funded_deposit"]
        out.append({
            "seed": r["seed"], "starved_call_gas_limit": r["starved_call_gas_limit"],
            "failure_class": r["failed_attempt"].get("failure_class"),
            "validation_passed": r["failed_attempt"].get("sim_accepted"),
            "bundle_included": r["failed_attempt"].get("included"),
            "execution_success": r["failed_attempt"].get("execution_success"),
            "grant_before": b["bootstrap_paymaster_is_used"],
            "grant_after": a["bootstrap_paymaster_is_used"],
            "pool_eligible_after": a["credit_pool_is_eligible"],
            "pool_has_deposited_after": a["credit_pool_has_deposited"],
            "paymaster_deposit_before_wei": b["bootstrap_paymaster_deposit_wei"],
            "paymaster_deposit_after_wei": a["bootstrap_paymaster_deposit_wei"],
            "sponsor_loss_wei": r["sponsor_loss_on_failure_wei"],
            "nonce_before": b["account_entrypoint_nonce"],
            "nonce_after": a["account_entrypoint_nonce"],
            "account_code_before": b["account_code_size"],
            "account_code_after": a["account_code_size"],
            "tree_size_before": b["credit_pool_tree_size"],
            "tree_size_after": a["credit_pool_tree_size"],
            "root_before": b["credit_pool_root"], "root_after": a["credit_pool_root"],
            "sponsored_retry_result": (r["retry_attempt"].get("sim_reason")
                                       or ("included" if r["retry_attempt"].get("root_changed")
                                           else "failed")),
            "grant_permanently_consumed": r["grant_permanently_consumed"],
            "self_funded_userop_included": sf.get("userop_included"),
            "self_funded_userop_cost_wei": sf.get("userop_actual_gas_cost_wei"),
            "account_eth_before_wei": sf.get("account_eth_wei"),
            "credit_recoverable_without_external_funding": sf.get(
                "credit_recoverable_without_external_funding"),
            "tree_size_after_self_funded": sf.get("tree_size_after"),
        })
    md = md_table(
        ["starved callGasLimit", "failure class", "validation passed", "bundle included",
         "execution success", "grant before → after", "pool eligible after",
         "hasDeposited after", "Paymaster deposit before → after (wei)", "sponsor loss (wei)",
         "nonce before → after", "account code before → after (bytes)",
         "tree size before → after", "root changed", "sponsored retry",
         "grant permanently consumed", "self-funded UserOp included",
         "self-funded cost (wei)", "credit recoverable without external funding"],
        [[r["starved_call_gas_limit"], r["failure_class"], str(r["validation_passed"]),
          str(r["bundle_included"]), str(r["execution_success"]),
          f'{r["grant_before"]} → {r["grant_after"]}', str(r["pool_eligible_after"]),
          str(r["pool_has_deposited_after"]),
          f'{r["paymaster_deposit_before_wei"]:,} → {r["paymaster_deposit_after_wei"]:,}',
          r["sponsor_loss_wei"], f'{r["nonce_before"]} → {r["nonce_after"]}',
          f'{r["account_code_before"]} → {r["account_code_after"]}',
          f'{r["tree_size_before"]} → {r["tree_size_after"]}',
          str(r["root_before"] != r["root_after"]), r["sponsored_retry_result"],
          str(r["grant_permanently_consumed"]), str(r["self_funded_userop_included"]),
          r["self_funded_userop_cost_wei"],
          str(r["credit_recoverable_without_external_funding"])] for r in out])
    return md, out


def detect_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("detect") or {}).get("rows", [])
    md = md_table(
        ["seed", "callGasLimit", "is frozen value", "validation-only eth_call handleOps",
         "debug_traceCall sees OOG", "eth_estimateGas(deposit)", "estimate > callGasLimit",
         "on-chain UserOp success", "actualGasUsed", "grant consumed"],
        [[r["seed"], r["call_gas_limit"], str(r["is_frozen_limit"]),
          "accepted" if r["handleops_eth_call_accepted"] else str(r["handleops_eth_call_reason"]),
          str(r["trace_call_execution_out_of_gas"]), r["estimate_gas_pool_deposit"],
          str((r.get("estimate_gas_pool_deposit") or 0) > r["call_gas_limit"]),
          str(r["onchain_userop_success"]), r["onchain_actual_gas_used"],
          str(r.get("grant_consumed"))] for r in rows])
    return md, rows


# --- figures --------------------------------------------------------------------------------


def figures(d: Data, cells: List[Dict[str, Any]], over: Dict[str, List[Dict[str, Any]]],
            curve: List[Dict[str, Any]], decomp: Dict[str, Any],
            env_limits: List[Dict[str, Any]], grant_rows: List[Dict[str, Any]],
            out_dir: Path) -> List[str]:
    plt = _plt()
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []

    def save(fig, name: str) -> None:
        fig.tight_layout()
        fig.savefig(out_dir / f"{name}.png", dpi=180)
        fig.savefig(out_dir / f"{name}.svg")
        plt.close(fig)
        made.append(name)

    variants = order_variants({r["variant"] for r in cells}) if cells else []

    # 1 + 2: stale probability vs lambda*T per K, measured points + analytical curves
    if cells:
        fig, ax = plt.subplots(figsize=(6.4, 4.2))
        mus = np.linspace(0.02, 10, 400)
        for i, v in enumerate(variants):
            k = variant_k(v)
            col = K_COLORS[i % len(K_COLORS)]
            pts = defaultdict(lambda: [0, 0])
            for r in cells:
                if r["variant"] == v and r["lambda_T"] > 0:
                    pts[round(r["lambda_T"], 6)][0] += r["stale"]
                    pts[round(r["lambda_T"], 6)][1] += r["trials"]
            xs = sorted(pts)
            ys = [pts[x][0] / pts[x][1] for x in xs]
            ax.plot(mus, [p_stale(m, k) for m in mus], color=col, lw=1.2, alpha=0.55)
            if v == "frozen":
                # drawn as a large open ring so the K=1 points, which coincide with it
                # exactly, remain visible inside it
                ax.plot(xs, ys, "o", mfc="none", mec=INK, ms=9, mew=1.2,
                        label="frozen (latest root)")
            else:
                ax.plot(xs, ys, "o", color=col, ms=4, label=f"K = {k}")
        ax.set_xscale("log")
        ax.set_xlabel("λ·T (expected root updates in the vulnerability window)")
        ax.set_ylabel("P(stale root)")
        ax.set_title("Stale-root probability vs λ·T: measured points, analytical curves")
        ax.set_ylim(-0.03, 1.03)
        ax.legend(fontsize=7, ncol=2)
        save(fig, "stale_probability_vs_lambdaT_by_K")

        fig, ax = plt.subplots(figsize=(5.4, 4.2))
        for i, v in enumerate(variants):
            k = variant_k(v)
            rs = [r for r in cells if r["variant"] == v and r["lambda_T"] > 0]
            ax.plot([r["analytic_p_stale"] for r in rs], [r["p_hat"] for r in rs], "o",
                    ms=4, color=K_COLORS[i % len(K_COLORS)], label=f"K={k}")
        ax.plot([0, 1], [0, 1], "--", color=NEUTRAL, lw=1)
        ax.set_xlabel("analytical P(stale | K)")
        ax.set_ylabel("measured P̂(stale)")
        ax.set_title("Analytical vs measured, per cell")
        ax.legend(fontsize=7, ncol=2)
        save(fig, "analytic_vs_measured_by_K")

        # 3: failure rate vs history size, per lambda*T band
        fig, ax = plt.subplots(figsize=(6.0, 4.2))
        bands = [(0, 0.5), (0.5, 1.0), (1.0, 2.5), (2.5, 11)]
        for j, (lo, hi) in enumerate(bands):
            ks, ys = [], []
            for v in variants:
                rs = [r for r in cells if r["variant"] == v and lo < r["lambda_T"] <= hi]
                if not rs:
                    continue
                ks.append(variant_k(v))
                ys.append(sum(r["stale"] for r in rs) / sum(r["trials"] for r in rs))
            if ks:
                ax.plot(ks, ys, "o-", color=K_COLORS[j % len(K_COLORS)], ms=4,
                        label=f"{lo:g} < λT ≤ {hi:g}")
        ax.set_xscale("log", base=2)
        ax.set_yscale("symlog", linthresh=1e-3)
        ax.set_xlabel("history size K")
        ax.set_ylabel("measured stale-root failure rate")
        ax.set_title("Failure rate vs bounded history size")
        ax.legend(fontsize=7)
        save(fig, "failure_rate_vs_history_size")

    # 4 + 5: validation and root-update overhead vs K
    val = over.get("validation", [])
    if val:
        fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.6))
        ks = [variant_k(r["variant"]) for r in val if r["variant"] != "frozen"]
        axes[0].plot(ks, [r["delta_vs_frozen_gas"] for r in val if r["variant"] != "frozen"],
                     "o-", color=C1, ms=4)
        axes[0].set_xscale("log", base=2)
        axes[0].set_xlabel("history size K")
        axes[0].set_ylim(0, 160)
        axes[0].set_ylabel("Δ validatePaymasterUserOp gas vs frozen")
        axes[0].set_title("Spend validation overhead (constant in K)")
        upd = over.get("root_update", [])
        byv = defaultdict(list)
        for r in upd:
            if r["variant"] != "frozen":
                byv[variant_k(r["variant"])].append(r)
        xs = sorted(byv)
        # The first K updates write cold zero->non-zero ring slots, so each K has a
        # transient maximum and a steady-state minimum; plotting the median would land on
        # whichever of the two the tested tree sizes happen to favour.
        lo = [min(r["mirror_delta_gas"] for r in byv[k]) for k in xs]
        hi = [max(r["mirror_delta_gas"] for r in byv[k]) for k in xs]
        axes[1].fill_between(xs, lo, hi, color=C2, alpha=0.15)
        axes[1].plot(xs, lo, "o-", color=C2, ms=4, label="steady state (ring full)")
        axes[1].plot(xs, hi, "s--", color=C3, ms=4, label="while the ring is still filling")
        axes[1].set_xscale("log", base=2)
        axes[1].set_ylim(0, max(hi) * 1.15)
        axes[1].set_xlabel("history size K")
        axes[1].set_ylabel("Δ gas per root update vs frozen")
        axes[1].set_title("Root-update overhead")
        axes[1].legend(fontsize=7, loc="lower right")
        save(fig, "overhead_vs_history_size")

    # 6: gas decomposition vs tree size / depth
    if curve:
        fig, ax = plt.subplots(figsize=(6.6, 4.2))
        xs = [r["tree_size_before"] for r in curve]
        ax.plot(xs, [r["g0_deposit_frame_gas"] for r in curve], color=C1, lw=0.8, alpha=0.35,
                label="G0 frozen CreditPool.deposit (every insertion)")
        ax.plot(xs, [r["g1_insert_frame_gas"] for r in curve], color=C2, lw=0.8, alpha=0.35,
                label="G1 LeanIMT insertion only (every insertion)")
        worst = [r for r in curve if r["tree_size_before"] > 0
                 and (r["tree_size_before"] + 1) & r["tree_size_before"] == 0]
        ax.plot([r["tree_size_before"] for r in worst],
                [r["g0_deposit_frame_gas"] for r in worst], "o-", color=C1, ms=4, lw=1.6,
                label="G0 worst case (sizes 2^d − 1)")
        ax.plot([r["tree_size_before"] for r in worst],
                [r["g1_insert_frame_gas"] for r in worst], "s-", color=C2, ms=4, lw=1.6,
                label="G1 worst case")
        g3a = decomp.get("g3a_surround_gas")
        if g3a and not math.isnan(g3a):
            ax.axhline(g3a, color=C3, lw=1.2, ls="--",
                       label=f"G3a B3 surrounding logic ({g3a:,.0f})")
        g2 = decomp.get("g2_frozen_mirror_steady_gas")
        if g2 and not math.isnan(g2):
            ax.axhline(g2, color=NEUTRAL, lw=1.2, ls=":",
                       label=f"G2 root mirror only ({g2:,.0f})")
        ax.set_xscale("log", base=2)
        ax.set_xlabel("tree size before insertion")
        ax.set_ylabel("frame gas")
        ax.set_title("Deposit gas decomposition")
        ax.legend(fontsize=7)
        save(fig, "gas_decomposition_vs_tree_size")

        fig, ax = plt.subplots(figsize=(6.0, 4.0))
        pos = [r for r in curve if r["g0_poseidon_calls"] is not None
               and r["tree_size_before"] > 0]
        ax.plot([r["g0_poseidon_calls"] for r in pos],
                [r["g0_deposit_frame_gas"] for r in pos], "o", ms=3, color=C1, alpha=0.6,
                label="G0 measured")
        ph = decomp.get("poseidon_hash_gas_warm_median")
        if ph and not math.isnan(ph):
            n = sorted({r["g0_poseidon_calls"] for r in pos})
            base0 = min(r["g0_deposit_frame_gas"] for r in pos
                        if r["g0_poseidon_calls"] == min(n)) - min(n) * ph
            ax.plot(n, [base0 + c * ph for c in n], color=C2, lw=1.2,
                    label=f"base + calls x {ph:,.0f} (measured PoseidonT3.hash)")
        ax.set_xlabel("PoseidonT3.hash delegatecalls in the insertion")
        ax.set_ylabel("G0 deposit frame gas")
        ax.set_title("Deposit gas is set by the number of Poseidon calls")
        ax.legend(fontsize=7)
        save(fig, "deposit_gas_vs_poseidon_calls")

    # 7: frozen feasibility envelope
    if env_limits:
        fig, ax = plt.subplots(figsize=(6.2, 4.0))
        xs = [r["tree_size_before"] for r in env_limits]
        ax.plot(xs, [r["min_required_call_gas_limit"] for r in env_limits], "o-", color=C1,
                ms=4, label="minimal sufficient callGasLimit")
        ax.axhline(env_limits[0]["frozen_call_gas_limit"], color=C2, ls="--", lw=1.2,
                   label=f'frozen callGasLimit ({env_limits[0]["frozen_call_gas_limit"]:,})')
        ok = [r["tree_size_before"] for r in env_limits if r["frozen_root_changed"]]
        if ok:
            ax.plot(ok, [env_limits[0]["frozen_call_gas_limit"]] * len(ok), "o", color=C3,
                    ms=7, label="frozen limit inserts")
        ax.set_xscale("symlog", linthresh=1)
        ax.set_xlabel("tree size before insertion")
        ax.set_ylabel("callGasLimit (gas)")
        ax.set_title("Frozen Bootstrap feasibility envelope")
        ax.legend(fontsize=7)
        save(fig, "frozen_feasibility_envelope")

    # 8: failed-Bootstrap state transition
    if grant_rows:
        r = grant_rows[0]
        fig, ax = plt.subplots(figsize=(7.2, 3.4))
        fields = [("grant used", r["grant_before"], r["grant_after"]),
                  ("pool eligible", True, r["pool_eligible_after"]),
                  ("hasDeposited", False, r["pool_has_deposited_after"]),
                  ("account deployed", r["account_code_before"] > 0,
                   r["account_code_after"] > 0),
                  ("nonce", r["nonce_before"], r["nonce_after"]),
                  ("tree size", r["tree_size_before"], r["tree_size_after"])]
        ax.axis("off")
        ax.set_title("Failed Bootstrap (frozen callGasLimit): state before → after",
                     color=INK)
        for i, (name, b, a) in enumerate(fields):
            y = len(fields) - i
            ax.text(0.02, y, name, color=INK2, va="center", fontsize=9)
            ax.text(0.40, y, str(b), color=INK, va="center", fontsize=9)
            ax.text(0.55, y, "→", color=NEUTRAL, va="center", fontsize=9)
            ax.text(0.62, y, str(a), va="center", fontsize=9,
                    color=(C2 if str(b) != str(a) else INK))
        ax.text(0.02, 0.2,
                f'sponsor charged {r["sponsor_loss_wei"]:,} wei; sponsored retry: '
                f'{r["sponsored_retry_result"]}; self-funded UserOp included: '
                f'{r["self_funded_userop_included"]}',
                color=INK2, fontsize=8, va="center")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, len(fields) + 1)
        save(fig, "failed_bootstrap_state_transition")
    return made


# --- entry point -----------------------------------------------------------------------------


def analyze(batch: str, cfg: Dict[str, Any], dirs: Dict[str, Path],
            write_doc: bool = False) -> Dict[str, Any]:
    d = Data(dirs)
    tables = dirs["results"] / "tables"
    tables.mkdir(parents=True, exist_ok=True)
    sections: List[Tuple[str, str]] = []
    out: Dict[str, Any] = {"batch": batch}

    def add(title: str, md: str, name: str, rows: Any) -> None:
        sections.append((title, md))
        if isinstance(rows, list):
            write_csv(tables / f"{name}.csv", rows)
        (tables / f"{name}.json").write_text(json.dumps(rows, indent=1, default=str))

    md, rows = boundary_table(d)
    add("K1. Deterministic retention boundary (Section 13)", md, "boundary", rows)
    out["boundary"] = rows

    md, rows = security_table(d)
    add("K2. Security invariants with real proofs (Section 6)", md, "security", rows)
    out["security"] = rows

    md_pool, md_fit, stoch, cells = stochastic_tables(d)
    add("K3. Stochastic contention pooled by variant (Sections 9/10)", md_pool,
        "stochastic_pooled", stoch["pooled"])
    write_csv(tables / "stochastic_cells.csv", cells)
    (tables / "stochastic_cells.json").write_text(json.dumps(cells, indent=1, default=str))
    md_fit += (f"\n\n{stoch['total_attempts']} attempts; "
               f"{stoch['cells_lambda_pos']} λ>0 cells, "
               f"{stoch['cells_outside_ci']} whose Wilson interval excludes the analytical "
               f"value; inconsistent classifications {stoch['total_inconsistent']}; "
               f"retention-model mismatches {stoch['total_model_mismatch']}. "
               f"Outcome classes: {json.dumps(stoch['outcome_classes'])}.")
    add("K4. Analytical vs measured retention (Section 8)", md_fit, "stochastic_fit",
        stoch["fit"])
    out["stochastic"] = stoch

    md, rows = retry_table(d)
    add("K5. Retries, proofs, simulations and latency by K (Section 10)", md, "retry", rows)
    out["retry"] = rows

    md, rows = bundle_table(d)
    add("K6. Bundle behaviour (Section 14)", md, "bundle", rows)
    out["bundle"] = rows

    md_val, md_upd, md_dep, over = overhead_tables(d)
    add("K7. Spend-validation overhead by K (Section 11)", md_val, "overhead_validation",
        over["validation"])
    add("K8. Root-update overhead by K (Section 11)", md_upd, "overhead_root_update",
        over["root_update"])
    add("K9. Deployment, code size and storage by K (Section 11)", md_dep,
        "overhead_deployment", over["deployment"])
    out["overhead"] = over

    md, rows = kill_condition(cfg, stoch, cells, over)
    add("K10. Pre-registered kill-condition thresholds (Section 12)", md, "kill_condition",
        rows)
    out["kill_condition"] = rows

    md_curve, md_level, decomp, curve = decomp_tables(d)
    add("G1. CreditPool.deposit gas decomposition (Sections 16-18)", md_curve,
        "gas_decomposition", curve)
    (tables / "gas_decomposition_summary.json").write_text(
        json.dumps(decomp, indent=1, default=str))
    md_level += (
        f"\n\nMeasured cost of one `PoseidonT3.hash` delegatecall (G5, warm): "
        f"{fmt(decomp.get('poseidon_hash_gas_warm_median'))} gas "
        f"({fmt(decomp.get('poseidon_hash_gas_first'))} on the first, cold call). "
        f"External-call floor (G4): {fmt(decomp.get('g4_call_floor_gas'))} gas. "
        f"Root mirror only (G2, steady state): {fmt(decomp.get('g2_frozen_mirror_steady_gas'))} "
        f"gas. B3 surrounding logic without tree work (G3a): "
        f"{fmt(decomp.get('g3a_surround_gas'))} gas; with the tree's size/leaf bookkeeping "
        f"(G3b): {fmt(decomp.get('g3b_surround_plus_bookkeeping_gas'))} gas "
        f"(difference {fmt(decomp.get('g3b_minus_g3a'))}). "
        f"Residual of G0 − (G1 + G3a): median {fmt(decomp.get('residual_median_gas'))} gas, "
        f"worst {fmt(decomp.get('residual_max_abs_gas'))} gas "
        f"({fmt((decomp.get('residual_max_fraction') or 0) * 100, 3)}% of G0). "
        f"Identical across seeds: {decomp.get('seed_agreement')}. "
        f"Reproduction checks: {json.dumps({k: {kk: vv for kk, vv in v.items() if kk != 'contracts'} for k, v in (decomp.get('checks') or {}).items()})}.")
    add("G2. Per-level growth explained (Section 19)", md_level, "gas_per_level", [])
    out["decomp"] = decomp

    md_lim, md_fee, env_limits, fee_rows = envelope_tables(d)
    add("G3. Frozen-parameter feasibility (Section 20)", md_lim, "frozen_limits", env_limits)
    add("G4. Gas-price / budget envelope (Section 23)", md_fee, "fee_envelope", fee_rows)
    out["envelope"] = {"limits": env_limits, "fees": fee_rows}

    md, rows = grant_table(d)
    add("G5. Failed-Bootstrap state transition (Section 21)", md, "grant", rows)
    out["grant"] = rows

    md, drows = detect_table(d)
    add("G6. Bundler-side detection before inclusion (Section 22)", md, "detect", drows)
    out["detect"] = drows

    figs = figures(d, cells, over, curve, decomp, env_limits, rows, dirs["figures"])
    out["figures"] = figs

    header = (f"_Generated by `python3 -m experiments.liveness.d2k analyze --batch {batch} "
              f"--write-doc` from `results/d2-killcondition/{batch}/` and "
              f"`data/private/d2-killcondition/{batch}/`. Do not edit by hand._\n")
    body = header + "\n" + "\n\n".join(f"### {t}\n\n{m}" for t, m in sections)
    if figs:
        body += ("\n\n### Figures\n\n"
                 + "\n".join(f"- `figures/d2-killcondition/{batch}/{f}.png` (`.svg`)"
                             for f in figs))
    (dirs["results"] / "generated.md").write_text(body)
    if write_doc:
        doc = repo_root() / DOC
        text = doc.read_text(encoding="utf-8")
        if BEGIN not in text or END not in text:
            raise RuntimeError(f"{DOC} has no generated block markers")
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        doc.write_text(f"{pre}{BEGIN}\n{body}\n{END}{post}", encoding="utf-8")
    (dirs["results"] / "analysis_summary.json").write_text(
        json.dumps(out, indent=1, default=str))
    return out
