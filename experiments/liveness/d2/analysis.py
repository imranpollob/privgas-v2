"""D2 pilot analysis: tables, statistics and figures, generated only from recorded data.

Nothing here types an experimental number: every table cell and plotted point is read
from ``results/d2-pilot/<batch>/raw/*.json`` and ``data/private/d2-pilot/<batch>/*.jsonl``.
``--write-doc`` replaces the GENERATED block of ``docs/d2-pilot-results.md``.

Statistics
----------
* Proportions: Wilson 95% intervals; per-cell exact two-sided binomial test against the
  analytical baseline p = 1 - exp(-lambda T).
* Stale-root model: complementary log-log binomial regression
  ``P(stale) = 1 - exp(-exp(b0 + b1 log(lambda T) + b2 log2 N))`` fitted by maximum
  likelihood (lambda > 0 cells). The analytical Poisson baseline is b0 = 0, b1 = 1, b2 = 0;
  likelihood-ratio tests compare it with the free fit and test the pool-size term.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from scipy import optimize, stats

from ...recorder.provenance import repo_root
from .engine import (OUTCOME_CLASSES, STALE_CLASSES, VALID_PROOF_INCLUDED)
from .records import read_jsonl

GWEI = 1e9
DOC = Path("docs") / "d2-pilot-results.md"
BEGIN, END = "<!-- BEGIN GENERATED: d2 tables -->", "<!-- END GENERATED: d2 tables -->"

# reference categorical palette (dataviz skill, light mode), slots 1-3 + neutral
C1, C2, C3, NEUTRAL, INK, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984", "#0b0b0b", "#52514e"


# --- helpers -----------------------------------------------------------------------------


def wilson(k: int, n: int, z: float = 1.96) -> Tuple[Optional[float], Optional[float]]:
    if n == 0:
        return None, None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def pct(xs: Sequence[float], q: float) -> Optional[float]:
    return float(np.percentile(xs, q)) if len(xs) else None


def fmt(x: Any, nd: int = 3) -> str:
    if x is None:
        return "–"
    if isinstance(x, bool):
        return str(x)
    if isinstance(x, int):
        return f"{x:,}"
    if isinstance(x, float):
        if math.isnan(x):
            return "–"
        return f"{x:,.{nd}f}"
    return str(x)


def ci(lo: Optional[float], hi: Optional[float], nd: int = 3) -> str:
    return "–" if lo is None else f"[{lo:.{nd}f}, {hi:.{nd}f}]"


def md_table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(fmt(x) if not isinstance(x, str) else x for x in r) + " |")
    return "\n".join(out)


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in r.items()})


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": NEUTRAL, "axes.labelcolor": INK2,
                         "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
                         "grid.color": "#e6e5e0", "grid.linewidth": 0.6, "axes.spines.top": False,
                         "axes.spines.right": False, "legend.frameon": False,
                         "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb",
                         "lines.linewidth": 2})
    return plt


# --- loaders -------------------------------------------------------------------------------


class Data:
    def __init__(self, dirs: Dict[str, Path]) -> None:
        self.dirs = dirs
        self.raw: Dict[str, Any] = {}
        for p in sorted((dirs["results"] / "raw").glob("*.json")):
            self.raw[p.stem] = json.loads(p.read_text())
        self.attempts: Dict[str, List[Dict[str, Any]]] = {}
        self.arrivals: Dict[str, List[Dict[str, Any]]] = {}
        for p in sorted(dirs["private"].glob("*.attempts.jsonl")):
            self.attempts[p.name.split(".")[0]] = read_jsonl(p)
        for p in sorted(dirs["private"].glob("*.arrivals.jsonl")):
            self.arrivals[p.name.split(".")[0]] = read_jsonl(p)
        man = dirs["results"] / "manifest.json"
        self.manifest = json.loads(man.read_text()) if man.is_file() else {}


# --- D2-A analyses -------------------------------------------------------------------------


def control_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    recs = d.attempts.get("control", [])
    by = defaultdict(list)
    for r in recs:
        by[r["n_initial"]].append(r)
    rows = []
    for n in sorted(by):
        rs = by[n]
        inc = [r for r in rs if r["outcome_class"] == VALID_PROOF_INCLUDED]
        rows.append({"n": n, "trials": len(rs),
                     "proof_ok": sum(1 for r in rs if r.get("proof_root")),
                     "simulation_accepted": sum(1 for r in rs if r.get("simulation_result") == "accepted"),
                     "included": len(inc),
                     "prove_ms_mean": float(np.mean([r["proof_generation_ms"] for r in rs if not r.get("proof_cache_hit")] or [np.nan])),
                     "simulation_wall_ms_mean": float(np.mean([r["simulation_wall_ms"] for r in rs])),
                     "inclusion_wall_ms_mean": float(np.mean([r["submission_wall_ms"] for r in inc] or [np.nan])),
                     "sponsor_charge_gwei_mean": float(np.mean([r["sponsor_credit_charge_wei"] for r in inc] or [np.nan])) / GWEI,
                     "inconsistent": sum(1 for r in rs if r.get("consistent") is False)})
    md = md_table(["N", "trials", "proof ok", "sim accepted", "included", "prove ms (mean)",
                   "sim wall ms", "inclusion wall ms", "sponsor charge (gwei)", "inconsistent"],
                  [[r["n"], r["trials"], r["proof_ok"], r["simulation_accepted"], r["included"],
                    r["prove_ms_mean"], r["simulation_wall_ms_mean"], r["inclusion_wall_ms_mean"],
                    r["sponsor_charge_gwei_mean"], r["inconsistent"]] for r in rows])
    return md, rows


def race_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("race") or {}).get("rows", [])
    agg = defaultdict(list)
    for r in rows:
        agg[r["variant"]].append(r)
    out = []
    for v in ("race_P0", "inverse_control", "race_P1_resimulation", "race_then_reprove"):
        rs = agg.get(v, [])
        if not rs:
            continue
        out.append({
            "variant": v, "runs": len(rs), "outcomes": dict(Counter(r["outcome"] for r in rs)),
            "sim_accepted": sum(r["simulation_accepted"] for r in rs),
            "proof_root_equals_R": sum(r["proof_root_equals_R"] for r in rs),
            "revert_stored_root_equals_new_root": sum(
                1 for r in rs if r.get("onchain_revert_stored_root") and
                r["onchain_revert_stored_root"] == r.get("root_after_bootstrap")),
            "trace_confirms": sum(1 for r in rs if (r.get("trace_revert") or {}).get("inner_error") == "RootMismatch"),
            "bundler_net_gwei": sorted({(r.get("bundler_net_wei") or 0) / GWEI for r in rs}),
            "bundle_gas_used": sorted({r.get("bundle_gas_used") for r in rs if r.get("bundle_gas_used")}),
            "credit_pm_delta_gwei": sorted({(r.get("credit_paymaster_deposit_delta_wei") or 0) / GWEI for r in rs}),
            "sender_eth_delta_wei": sorted({r.get("sender_eth_delta_wei") for r in rs if "sender_eth_delta_wei" in r}),
            "sender_ep_deposit_delta_wei": sorted({r.get("sender_entrypoint_deposit_delta_wei") for r in rs
                                                   if "sender_entrypoint_deposit_delta_wei" in r}),
            "nonce_advanced": sum(1 for r in rs if r.get("sender_nonce_after") is not None
                                  and r["sender_nonce_after"] > r["sender_nonce_before"]),
            "nullifier_spent": sum(1 for r in rs if r.get("nullifier_spent")),
            "retry_included": sum(1 for r in rs if r.get("retry_outcome") == "INCLUDED"),
            "reprove_signature_unchanged": sum(1 for r in rs if r.get("reprove_signature_unchanged")),
        })
    md = md_table(["variant", "runs", "outcomes", "sim accepted", "proof root = R",
                   "revert stored root = R'", "mined-tx trace = RootMismatch", "bundler net (gwei)",
                   "bundle gas", "CreditPaymaster Δ (gwei)", "sender ETH Δ", "sender EP deposit Δ",
                   "nonce advanced", "nullifier spent", "re-prove included", "signature unchanged"],
                  [[r["variant"], r["runs"], json.dumps(r["outcomes"]), r["sim_accepted"],
                    r["proof_root_equals_R"], r["revert_stored_root_equals_new_root"], r["trace_confirms"],
                    ", ".join(fmt(x, 0) for x in r["bundler_net_gwei"]),
                    ", ".join(fmt(x) for x in r["bundle_gas_used"]),
                    ", ".join(fmt(x, 0) for x in r["credit_pm_delta_gwei"]),
                    ", ".join(fmt(x) for x in r["sender_eth_delta_wei"]),
                    ", ".join(fmt(x) for x in r["sender_ep_deposit_delta_wei"]),
                    r["nonce_advanced"], r["nullifier_spent"], r["retry_included"],
                    r["reprove_signature_unchanged"]] for r in out])
    return md, out


def latency_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("latency") or {}).get("rows", [])
    by = defaultdict(list)
    for r in rows:
        by[(r["n"], r["depth"])].append(r)
    out = []
    for (n, depth), rs in sorted(by.items()):
        warm = [r["prove_ms"] for r in rs if not r["warmup"]]
        cold = [r["prove_ms"] for r in rs if r["warmup"]]
        ver = [r["verify_off_chain_ms"] for r in rs if not r["warmup"]]
        out.append({"n": n, "depth": depth, "samples": len(warm), "p50_ms": pct(warm, 50),
                    "p95_ms": pct(warm, 95), "mean_ms": float(np.mean(warm)), "std_ms": float(np.std(warm, ddof=1)),
                    "min_ms": min(warm), "max_ms": max(warm), "cold_first_ms": cold[0] if cold else None,
                    "verify_p50_ms": pct(ver, 50),
                    "onchain_verified": any(r.get("onchain_simulation_accepted") for r in rs)})
    md = md_table(["N", "depth", "samples", "p50 ms", "p95 ms", "mean ms", "std ms", "min", "max",
                   "first (cold) ms", "off-chain verify p50 ms", "on-chain verify (sim) ok"],
                  [[r["n"], r["depth"], r["samples"], r["p50_ms"], r["p95_ms"], r["mean_ms"], r["std_ms"],
                    r["min_ms"], r["max_ms"], r["cold_first_ms"], r["verify_p50_ms"], r["onchain_verified"]]
                   for r in out])
    return md, out


def stochastic_cells(d: Data) -> List[Dict[str, Any]]:
    recs = d.attempts.get("stochastic", [])
    by = defaultdict(list)
    for r in recs:
        by[(r["n_initial"], r["lambda"], r["window"])].append(r)
    cells = []
    for (n, lam, T), rs in sorted(by.items()):
        valid = [r for r in rs if r["outcome_class"] != "HARNESS_CAPACITY_EXCEEDED"]
        k = sum(1 for r in valid if r["outcome_class"] in STALE_CLASSES)
        m = len(valid)
        p_an = 1 - math.exp(-lam * T)
        lo, hi = wilson(k, m)
        bt = stats.binomtest(k, m, p_an).pvalue if m and 0 < p_an < 1 else (
            1.0 if (p_an == 0 and k == 0) else 0.0)
        cls = Counter(r["outcome_class"] for r in rs)
        cells.append({"n": n, "lambda": lam, "T": T, "lambdaT": lam * T, "trials": m,
                      "stale": k, "p_stale": k / m if m else None, "ci_lo": lo, "ci_hi": hi,
                      "p_analytic": p_an, "binom_p": bt,
                      "STALE_BEFORE_SUBMISSION": cls.get("STALE_BEFORE_SUBMISSION", 0),
                      "STALE_BEFORE_SIMULATION": cls.get("STALE_BEFORE_SIMULATION", 0),
                      "VALID_AT_SIM_STALE_BEFORE_INCLUSION": cls.get("VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION", 0),
                      "other_failures": sum(v for c, v in cls.items() if c not in STALE_CLASSES
                                            and c != VALID_PROOF_INCLUDED),
                      "capacity_exceeded": len(rs) - m,
                      "inconsistent": sum(1 for r in rs if r.get("consistent") is False),
                      "bundler_loss_gwei": sum((r.get("bundler_loss_wei") or 0) for r in rs) / GWEI})
    return cells


def cloglog_fit(cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    X, k, n = [], [], []
    for c in cells:
        if c["lambda"] > 0 and c["trials"]:
            X.append((math.log(c["lambdaT"]), math.log2(c["n"])))
            k.append(c["stale"])
            n.append(c["trials"])
    if not X:
        return {}
    X, k, n = np.array(X), np.array(k), np.array(n)

    def nll(beta, use_n=True, fixed=None):
        b0, b1, b2 = beta if fixed is None else fixed
        eta = b0 + b1 * X[:, 0] + (b2 * X[:, 1] if use_n else 0)
        p = np.clip(1 - np.exp(-np.exp(eta)), 1e-12, 1 - 1e-12)
        return -np.sum(k * np.log(p) + (n - k) * np.log(1 - p))

    full = optimize.minimize(lambda b: nll(b), [0.0, 1.0, 0.0], method="Nelder-Mead",
                             options={"xatol": 1e-8, "fatol": 1e-10, "maxiter": 20000})
    no_n = optimize.minimize(lambda b: nll([b[0], b[1], 0.0]), [0.0, 1.0], method="Nelder-Mead",
                             options={"xatol": 1e-8, "fatol": 1e-10, "maxiter": 20000})
    base = nll(None, fixed=(0.0, 1.0, 0.0))
    # Wald SEs from a numerical Hessian of the full model
    def hess(f, x, eps=1e-4):
        x = np.asarray(x, float)
        m = len(x)
        H = np.zeros((m, m))
        for i in range(m):
            for j in range(m):
                e_i, e_j = np.eye(m)[i] * eps, np.eye(m)[j] * eps
                H[i, j] = (f(x + e_i + e_j) - f(x + e_i - e_j) - f(x - e_i + e_j) + f(x - e_i - e_j)) / (4 * eps * eps)
        return H
    try:
        se = np.sqrt(np.diag(np.linalg.inv(hess(lambda b: nll(b), full.x))))
    except Exception:
        se = np.array([np.nan] * 3)
    lr_n = 2 * (no_n.fun - full.fun)
    lr_base = 2 * (base - no_n.fun)
    return {"b0": full.x[0], "b1": full.x[1], "b2": full.x[2], "se": se.tolist(),
            "nll_full": full.fun, "nll_no_n": no_n.fun, "nll_poisson_baseline": base,
            "b0_no_n": no_n.x[0], "b1_no_n": no_n.x[1],
            "lr_pool_size": lr_n, "p_pool_size": float(stats.chi2.sf(lr_n, 1)),
            "lr_baseline_vs_free": lr_base, "p_baseline_vs_free": float(stats.chi2.sf(lr_base, 2)),
            "cells": int(len(k)), "trials": int(n.sum())}


def stochastic_tables(d: Data) -> Tuple[str, List[Dict[str, Any]], Dict[str, Any]]:
    cells = stochastic_cells(d)
    fit = cloglog_fit(cells)
    # pooled over N
    pooled = defaultdict(lambda: [0, 0])
    for c in cells:
        pooled[(c["lambda"], c["T"])][0] += c["stale"]
        pooled[(c["lambda"], c["T"])][1] += c["trials"]
    prow = []
    for (lam, T), (k, m) in sorted(pooled.items()):
        lo, hi = wilson(k, m)
        pa = 1 - math.exp(-lam * T)
        bt = stats.binomtest(k, m, pa).pvalue if m and 0 < pa < 1 else (1.0 if k == 0 and pa == 0 else 0.0)
        prow.append({"lambda": lam, "T": T, "lambdaT": lam * T, "trials": m, "stale": k,
                     "p_stale": k / m, "ci_lo": lo, "ci_hi": hi, "p_analytic": pa, "binom_p": bt,
                     "analytic_in_ci": lo <= pa <= hi})
    md = md_table(["λ (/s)", "T (s)", "λT", "trials", "stale", "P̂(stale)", "95% CI",
                   "1−exp(−λT)", "in CI", "binom p"],
                  [[r["lambda"], r["T"], r["lambdaT"], r["trials"], r["stale"], r["p_stale"],
                    ci(r["ci_lo"], r["ci_hi"]), r["p_analytic"], str(r["analytic_in_ci"]), r["binom_p"]]
                   for r in prow])
    cls_rows = []
    tot = Counter()
    for c in cells:
        for key in ("STALE_BEFORE_SUBMISSION", "STALE_BEFORE_SIMULATION", "VALID_AT_SIM_STALE_BEFORE_INCLUSION",
                    "other_failures", "capacity_exceeded", "inconsistent"):
            tot[key] += c[key]
        tot["trials"] += c["trials"]
        tot["stale"] += c["stale"]
    by_n = defaultdict(lambda: [0, 0])
    for c in cells:
        if c["lambda"] > 0:
            by_n[c["n"]][0] += c["stale"]
            by_n[c["n"]][1] += c["trials"]
    summary = {"totals": dict(tot), "fit": fit, "pooled": prow,
               "by_n_lambda_pos": {n: {"stale": v[0], "trials": v[1]} for n, v in by_n.items()},
               "cells_outside_ci": sum(1 for c in cells if c["trials"] and not (c["ci_lo"] <= c["p_analytic"] <= c["ci_hi"])),
               "cells": len(cells),
               "cells_binom_p_lt_0_05": sum(1 for c in cells if c["binom_p"] < 0.05)}
    return md, cells, summary


def _trial_groups(recs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    g = defaultdict(list)
    for r in recs:
        g[(r["trial_id"], r["spender"])].append(r)
    return g


def retry_metrics(recs: List[Dict[str, Any]], arrivals: List[Dict[str, Any]], keys: Sequence[str],
                  trials_summary: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    arr_by_trial = defaultdict(list)
    for a in arrivals:
        arr_by_trial[a["trial_id"]].append(a)
    sum_by_trial = {t["trial_id"]: t for t in trials_summary}
    cells = defaultdict(list)
    for (tid, sp), rs in _trial_groups(recs).items():
        rs.sort(key=lambda r: r["retry_number"])
        key = tuple(rs[0].get(k) for k in keys)
        succ = [r for r in rs if r["outcome_class"] == VALID_PROOF_INCLUDED]
        failed = [r for r in rs if r["outcome_class"] != VALID_PROOF_INCLUDED]
        cells[key].append({
            "trial_id": tid, "success": bool(succ), "attempts": len(rs),
            "proofs": sum(1 for r in rs if r.get("proof_root")),
            "simulations": sum(r.get("simulations") or 0 for r in rs),
            "sim_rejections": sum(1 for r in rs if r.get("failure_observation") == "SIMULATION_ROOT_MISMATCH"),
            "resim_drops": sum(1 for r in rs if r.get("failure_observation") == "RESIMULATION_ROOT_MISMATCH"),
            "onchain_failures": sum(1 for r in rs if r.get("failure_observation") == "ONCHAIN_ROOT_MISMATCH"),
            "stale_failures": sum(1 for r in rs if r["outcome_class"] in STALE_CLASSES),
            "valid_at_sim_failures": sum(1 for r in rs if r["outcome_class"] == "VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION"),
            "other_failures": sum(1 for r in failed if r["outcome_class"] not in STALE_CLASSES),
            "time_to_success": succ[0]["time_to_success"] if succ else None,
            "wasted_proving_ms": sum(r.get("proof_generation_ms") or 0 for r in failed),
            "proving_ms": sum(r.get("proof_generation_ms") or 0 for r in rs),
            "failed_gas": sum(r.get("bundle_gas_used") or 0 for r in failed if r.get("onchain_status") == 0),
            "bundler_loss_wei": sum(r.get("bundler_loss_wei") or 0 for r in failed),
            "bundler_net_success_wei": sum((r.get("beneficiary_compensation_wei") or 0) - (r.get("bundle_fee_wei") or 0)
                                           for r in succ),
            "sponsor_credit_wei": sum(r.get("sponsor_credit_charge_wei") or 0 for r in succ),
            "user_eth_wei": 0,
            "arrivals": len(arr_by_trial[tid]),
            "arrival_sponsor_bootstrap_wei": sum(a.get("sponsor_bootstrap_charge_wei") or 0 for a in arr_by_trial[tid]),
            "rpc_calls_total": sum_by_trial.get(tid, {}).get("rpc_calls_total"),
            "rpc_calls_arrivals": sum_by_trial.get(tid, {}).get("rpc_calls_arrivals"),
            "sim_wall_ms": sum(r.get("simulation_wall_ms") or 0 for r in rs),
            "exhausted": not succ and any(r.get("terminal") for r in rs) and all(
                r["outcome_class"] in STALE_CLASSES for r in rs),
            "capacity": any(r["outcome_class"] == "HARNESS_CAPACITY_EXCEEDED" for r in rs),
            "inconsistent": sum(1 for r in rs if r.get("consistent") is False)})
    out = []
    for key, ts in sorted(cells.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        ok = [t for t in ts if t["success"]]
        ns = len(ok)
        tts = [t["time_to_success"] for t in ok]
        row = dict(zip(keys, key))
        s_lo, s_hi = wilson(ns, len(ts))
        first_attempts = [t for t in ts]
        row.update({
            "trials": len(ts), "successes": ns, "success_rate": ns / len(ts), "success_ci_lo": s_lo,
            "success_ci_hi": s_hi, "exhausted": sum(t["exhausted"] for t in ts),
            "capacity_exceeded": sum(t["capacity"] for t in ts),
            "attempts_total": sum(t["attempts"] for t in ts),
            "retries_per_success": (sum(t["attempts"] for t in ts) - ns) / ns if ns else None,
            "proofs_per_success": sum(t["proofs"] for t in ts) / ns if ns else None,
            "simulations_per_success": sum(t["simulations"] for t in ts) / ns if ns else None,
            "sim_rejections": sum(t["sim_rejections"] for t in ts),
            "resim_drops": sum(t["resim_drops"] for t in ts),
            "onchain_failures": sum(t["onchain_failures"] for t in ts),
            "valid_at_sim_failures": sum(t["valid_at_sim_failures"] for t in ts),
            "other_failures": sum(t["other_failures"] for t in ts),
            "first_attempt_stale_rate": None,
            "tts_p50": pct(tts, 50), "tts_p95": pct(tts, 95), "tts_mean": float(np.mean(tts)) if tts else None,
            "wasted_proving_ms_per_success": sum(t["wasted_proving_ms"] for t in ts) / ns if ns else None,
            "wasted_proving_ms_total": sum(t["wasted_proving_ms"] for t in ts),
            "failed_gas_per_success": sum(t["failed_gas"] for t in ts) / ns if ns else None,
            "bundler_loss_gwei_per_success": sum(t["bundler_loss_wei"] for t in ts) / ns / GWEI if ns else None,
            "bundler_net_gwei_per_success": (sum(t["bundler_net_success_wei"] for t in ts)
                                             - sum(t["bundler_loss_wei"] for t in ts)) / ns / GWEI if ns else None,
            "sponsor_credit_gwei_per_success": sum(t["sponsor_credit_wei"] for t in ts) / ns / GWEI if ns else None,
            "user_eth_wei_per_success": 0 if ns else None,
            "arrivals_total": sum(t["arrivals"] for t in ts),
            "arrival_sponsor_bootstrap_gwei": sum(t["arrival_sponsor_bootstrap_wei"] for t in ts) / GWEI,
            "rpc_calls_per_success_excl_arrivals": (sum((t["rpc_calls_total"] or 0) - (t["rpc_calls_arrivals"] or 0) for t in ts) / ns)
            if ns and ts[0]["rpc_calls_total"] is not None else None,
            "sim_wall_ms_per_success": sum(t["sim_wall_ms"] for t in ts) / ns if ns else None,
            "inconsistent": sum(t["inconsistent"] for t in ts)})
        firsts = [r for r in recs if tuple(r.get(k) for k in keys) == key and r["retry_number"] == 0]
        if firsts:
            row["first_attempt_stale_rate"] = sum(1 for r in firsts if r["outcome_class"] in STALE_CLASSES) / len(firsts)
        out.append(row)
    return out


def policy_tables(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    recs = d.attempts.get("policy", [])
    raw = d.raw.get("policy") or {}
    rows = retry_metrics(recs, d.arrivals.get("policy", []), ("lambda", "window", "policy"),
                         raw.get("trials", []))
    md = md_table(["λ", "T", "policy", "trials", "success (≤10 att.)", "95% CI", "exhausted",
                   "1st-attempt stale", "retries/success", "proofs/success", "sims/success",
                   "sim rejects", "re-sim drops", "on-chain fails", "TTS p50 (s)", "TTS p95 (s)",
                   "wasted prove ms/success", "bundler net gwei/success", "failed gas/success",
                   "RPC/success", "cap.", "incons."],
                  [[r["lambda"], r["window"], r["policy"], r["trials"], r["success_rate"],
                    ci(r["success_ci_lo"], r["success_ci_hi"]), r["exhausted"],
                    r["first_attempt_stale_rate"], r["retries_per_success"], r["proofs_per_success"],
                    r["simulations_per_success"], r["sim_rejections"], r["resim_drops"],
                    r["onchain_failures"], r["tts_p50"], r["tts_p95"], r["wasted_proving_ms_per_success"],
                    r["bundler_net_gwei_per_success"], r["failed_gas_per_success"],
                    r["rpc_calls_per_success_excl_arrivals"], r["capacity_exceeded"], r["inconsistent"]]
                   for r in rows])
    return md, rows


def segments_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    recs = d.attempts.get("segments", [])
    by = defaultdict(list)
    for r in recs:
        by[(r["segment_profile"], r["policy"])].append(r)
    out = []
    for (seg, pol), rs in sorted(by.items(), key=lambda kv: (["prove", "submit", "sim", "queue", "chain"].index(kv[0][0]), kv[0][1])):
        n = len(rs)
        c = Counter(r["failure_observation"] for r in rs)
        k = sum(1 for r in rs if r["outcome_class"] in STALE_CLASSES)
        lo, hi = wilson(k, n)
        T = sum(rs[0]["segments"].values())
        out.append({"dominant_segment": seg, "policy": pol, "trials": n, "stale": k, "p_stale": k / n,
                    "ci_lo": lo, "ci_hi": hi, "p_analytic": 1 - math.exp(-rs[0]["lambda"] * T),
                    "sim_root_mismatch": c.get("SIMULATION_ROOT_MISMATCH", 0),
                    "resim_root_mismatch": c.get("RESIMULATION_ROOT_MISMATCH", 0),
                    "onchain_root_mismatch": c.get("ONCHAIN_ROOT_MISMATCH", 0),
                    "bundler_loss_gwei": sum(r.get("bundler_loss_wei") or 0 for r in rs) / GWEI,
                    "onset": dict(Counter(r.get("stale_onset_segment") for r in rs if r["outcome_class"] in STALE_CLASSES))})
    md = md_table(["dominant segment (2 s; others 0.05 s)", "policy", "trials", "stale", "P̂", "95% CI",
                   "1−exp(−λT)", "sim RootMismatch", "re-sim RootMismatch", "on-chain RootMismatch",
                   "bundler loss (gwei)", "onset segments"],
                  [[r["dominant_segment"], r["policy"], r["trials"], r["stale"], r["p_stale"],
                    ci(r["ci_lo"], r["ci_hi"]), r["p_analytic"], r["sim_root_mismatch"],
                    r["resim_root_mismatch"], r["onchain_root_mismatch"], r["bundler_loss_gwei"],
                    json.dumps(r["onset"])] for r in out])
    return md, out


def measured_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    recs = d.attempts.get("measured", [])
    raw = d.raw.get("measured") or {}
    rows = retry_metrics(recs, d.arrivals.get("measured", []), ("lambda", "block_interval", "policy"),
                         raw.get("trials", []))
    proof_s = [r["proof_generation_ms"] / 1000 for r in recs if r.get("proof_generation_ms")]
    md = md_table(["λ", "block interval (s)", "policy", "trials", "success", "retries/success",
                   "proofs/success", "sims/success", "on-chain fails", "TTS p50 (s)", "TTS p95 (s)",
                   "wasted prove ms/success"],
                  [[r["lambda"], r["block_interval"], r["policy"], r["trials"], r["success_rate"],
                    r["retries_per_success"], r["proofs_per_success"], r["simulations_per_success"],
                    r["onchain_failures"], r["tts_p50"], r["tts_p95"], r["wasted_proving_ms_per_success"]]
                   for r in rows])
    md += f"\n\nMeasured proof segment in these trials: mean {fmt(float(np.mean(proof_s)) if proof_s else None)} s, max {fmt(max(proof_s) if proof_s else None)} s."
    return md, rows


def concurrency_tables(d: Data) -> Tuple[str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    raw = d.raw.get("concurrency") or {}
    det = raw.get("rows", [])
    agg = defaultdict(list)
    for r in det:
        agg[(r["m"], r["variant"])].append(r)
    drows = []
    for (m, v), rs in sorted(agg.items()):
        drows.append({"m": m, "variant": v, "runs": len(rs), "sim_accepted": sum(r["simulations_accepted"] for r in rs),
                      "included": sum(r["included"] for r in rs), "ops": m * len(rs),
                      "onchain_root_mismatch": sum(r["onchain_root_mismatch"] for r in rs),
                      "bundler_net_gwei_per_run": float(np.mean([r["bundler_net_wei"] for r in rs])) / GWEI,
                      "failed_gas_per_run": float(np.mean([r["failed_gas"] for r in rs]))})
    md = md_table(["M", "variant", "runs", "sims accepted", "included / ops", "on-chain RootMismatch",
                   "bundler net per run (gwei)", "failed gas per run"],
                  [[r["m"], r["variant"], r["runs"], r["sim_accepted"], f"{r['included']}/{r['ops']}",
                    r["onchain_root_mismatch"], r["bundler_net_gwei_per_run"], r["failed_gas_per_run"]] for r in drows])
    srows = retry_metrics(d.attempts.get("concurrency", []), d.arrivals.get("concurrency", []),
                          ("cohort_size", "lambda", "policy"), raw.get("trials", []))
    # correlated invalidation: failures per root-change event within a trial
    md2 = md_table(["M", "λ", "policy", "spender-trials", "success", "retries/success", "proofs/success",
                    "on-chain fails", "re-sim drops", "TTS p50 (s)", "TTS p95 (s)"],
                   [[r["cohort_size"], r["lambda"], r["policy"], r["trials"], r["success_rate"],
                     r["retries_per_success"], r["proofs_per_success"], r["onchain_failures"],
                     r["resim_drops"], r["tts_p50"], r["tts_p95"]] for r in srows])
    return md + "\n\n" + md2, drows, srows


def bundle_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    rows = (d.raw.get("bundle") or {}).get("rows", [])
    agg = defaultdict(list)
    for r in rows:
        agg[(r["variant"], r.get("k"))].append(r)
    out = []
    for (v, k), rs in agg.items():
        out.append({"variant": v, "k": k, "runs": len(rs), "ops": sum(r["ops"] for r in rs),
                    "included_ops": sum(r["included_ops"] for r in rs),
                    "bundle_sim_accepted": sum(1 for r in rs if r.get("bundle_simulation_accepted")),
                    "bundle_reverted": sum(1 for r in rs if r["bundle_status"] == 0),
                    "revert_inner": dict(Counter(r.get("onchain_revert_inner_error") for r in rs)),
                    "revert_op_index": dict(Counter(r.get("onchain_revert_op_index") for r in rs)),
                    "bundler_net_gwei_mean": float(np.mean([r["bundler_net_wei"] for r in rs])) / GWEI,
                    "gas_used_mean": float(np.mean([r["bundle_gas_used"] for r in rs]))})
    order = ["same_root_no_bootstrap", "bootstrap_between_sim_and_inclusion", "one_stale_rest_fresh",
             "[Bootstrap, Spend(R)]", "[Spend(R), Bootstrap]", "[Bootstrap, Spend(R')]", "[Spend(R'), Bootstrap]"]
    out.sort(key=lambda r: (order.index(r["variant"]), r["k"] or 0))
    md = md_table(["variant", "k", "runs", "included / ops", "bundle sim accepted", "bundle reverted",
                   "revert inner error", "failing op index", "bundler net (gwei, mean)", "bundle gas (mean)"],
                  [[r["variant"], r["k"], r["runs"], f"{r['included_ops']}/{r['ops']}", r["bundle_sim_accepted"],
                    r["bundle_reverted"], json.dumps(r["revert_inner"]), json.dumps(r["revert_op_index"]),
                    r["bundler_net_gwei_mean"], r["gas_used_mean"]] for r in out])
    return md, out


def adversary_table(d: Data) -> Tuple[str, List[Dict[str, Any]]]:
    recs = d.attempts.get("adversary", [])
    raw = d.raw.get("adversary") or {}
    rows = retry_metrics(recs, d.arrivals.get("adversary", []), ("cohort_size", "adversary_budget", "policy"),
                         raw.get("trials", []))
    arr = d.arrivals.get("adversary", [])
    cfg = d.manifest.get("d2_config", {})
    for r in rows:
        ts = [t for t in raw.get("trials", []) if t["m"] == r["cohort_size"] and t["budget"] == r["adversary_budget"]
              and t["policy"] == r["policy"]]
        deposits = sum(t["adversary_deposits"] for t in ts)
        r["adversary_deposits"] = deposits
        failures = r["attempts_total"] - r["successes"]
        r["victim_failed_attempts_per_adversary_deposit"] = failures / deposits if deposits else None
        a = [x for x in arr if x["kind"] == "adversary" and any(x["trial_id"] == t["trial_id"] for t in ts)]
        r["adversary_sponsor_bootstrap_gwei"] = sum(x.get("sponsor_bootstrap_charge_wei") or 0 for x in a) / GWEI
    md = md_table(["M victims", "adversary budget", "policy", "victim-trials", "success (≤20 att.)",
                   "adversary deposits", "victim failed attempts / adv. deposit", "proofs/success",
                   "on-chain fails", "re-sim drops", "bundler loss gwei/success", "TTS p50 (s)",
                   "wasted prove ms/success", "sponsor-paid adversary Bootstraps (gwei)"],
                  [[r["cohort_size"], r["adversary_budget"], r["policy"], r["trials"], r["success_rate"],
                    r["adversary_deposits"], r["victim_failed_attempts_per_adversary_deposit"],
                    r["proofs_per_success"], r["onchain_failures"], r["resim_drops"],
                    r["bundler_loss_gwei_per_success"], r["tts_p50"], r["wasted_proving_ms_per_success"],
                    r["adversary_sponsor_bootstrap_gwei"]] for r in rows])
    return md, rows


# --- D2-B analyses -------------------------------------------------------------------------


def gas_tables(d: Data, cfg: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    g = d.raw.get("gas") or {}
    rows = g.get("growth", [])
    if not rows:
        return "(no D2-B data)", {}
    by_size = defaultdict(list)
    for r in rows:
        by_size[r["tree_size_before"]].append(r)
    sel = [s for s in sorted(by_size) if s in (0, 1, 2, 3, 4, 7, 8, 15, 16, 31, 32, 63, 64, 127, 128, 255)]
    frozen = g["checks"][0]["frozen_call_gas_limit"] if g.get("checks") else None
    t1 = md_table(["tree size before", "LeanIMT depth after", "CreditPool.deposit frame gas (seeds)",
                   "PoseidonT3 calls", "new CreditPool slots", "min callGasLimit that inserts",
                   f"frozen limit ({fmt(frozen)}) inserts?", "frozen failure class",
                   "Bootstrap actualGasUsed at min limit", "BootstrapPaymaster charge at min limit (gwei)",
                   "Bootstrap actualGasUsed at high limit", "charge at high limit (gwei)"],
                  [[s, by_size[s][0]["leanimt_depth_after"],
                    " / ".join(fmt(r["deposit_frame_gas_used"]) for r in by_size[s]),
                    " / ".join(fmt(r["poseidon_calls"]) for r in by_size[s]),
                    " / ".join(fmt(r.get("pool_storage_slots_new_nonzero")) for r in by_size[s]),
                    " / ".join(fmt(r["min_required_call_gas_limit"]) for r in by_size[s]),
                    " / ".join(str(bool(r.get("frozen_root_changed"))) for r in by_size[s]),
                    " / ".join(str(r.get("frozen_failure_class")) for r in by_size[s]),
                    " / ".join(fmt(r.get("minreq_actual_gas_used")) for r in by_size[s]),
                    " / ".join(fmt((r.get("minreq_paymaster_charge_wei") or 0) / GWEI, 0) for r in by_size[s]),
                    " / ".join(fmt(r.get("high_actual_gas_used")) for r in by_size[s]),
                    " / ".join(fmt((r.get("high_paymaster_charge_wei") or 0) / GWEI, 0) for r in by_size[s])]
                   for s in sel])
    first_fail = {}
    for seed in sorted({r["seed"] for r in rows}):
        rs = sorted((r for r in rows if r["seed"] == seed), key=lambda r: r["tree_size_before"])
        ff = next((r for r in rs if not r.get("frozen_root_changed")), None)
        n_ok = sum(1 for r in rs if r.get("frozen_root_changed"))
        first_fail[seed] = {"first_failing_tree_size": ff["tree_size_before"] if ff else None,
                            "first_failure_class": ff.get("frozen_failure_class") if ff else None,
                            "required_at_first_failure": ff["min_required_call_gas_limit"] if ff else None,
                            "sizes_where_frozen_inserts": [r["tree_size_before"] for r in rs if r.get("frozen_root_changed")],
                            "frozen_grant_consumed_on_failure": all(r.get("frozen_grant_consumed") for r in rs if not r.get("frozen_root_changed")),
                            "frozen_has_deposited_on_failure": any(r.get("frozen_has_deposited") for r in rs if not r.get("frozen_root_changed")),
                            "sizes_ok": n_ok, "sizes_tested": len(rs),
                            "max_required": max(r["min_required_call_gas_limit"] for r in rs),
                            "max_deposit_frame": max(r["deposit_frame_gas_used"] for r in rs),
                            "deposit_frame_size0": rs[0]["deposit_frame_gas_used"]}
    nat = g.get("natural", [])
    t2 = md_table(["seed", "attempt", "tree size before", "sim accepted", "included", "execution success",
                   "root changed", "failure class", "grant consumed", "has deposited", "charge (gwei)"],
                  [[r["seed"], r["attempt"], r["tree_size_before"], r["sim_accepted"], r.get("included"),
                    r.get("execution_success"), r.get("root_changed"), str(r.get("failure_class")),
                    r.get("grant_consumed"), r.get("has_deposited"), (r.get("paymaster_charge_wei") or 0) / GWEI]
                   for r in nat])
    # fee envelope
    env_rows = []
    for fe in g.get("fee_envelope", []):
        for r in fe["bootstrap"]:
            env_rows.append({"what": "Bootstrap", **r})
        for r in fe["spend"]:
            env_rows.append({"what": "Spend", "limit_kind": "W1/B3", "tree_size_before": r["pool_size"], **r})
    cap = 5e15
    grid = defaultdict(dict)
    for r in env_rows:
        key = (r["what"], r["tree_size_before"], r["limit_kind"])
        grid[key][r["max_fee_gwei"]] = (r["sim_accepted"], r["sim_inner_error"], r["gas_limits_sum"])
    fees = sorted({r["max_fee_gwei"] for r in env_rows})
    t3rows = []
    for (what, s, lk), v in sorted(grid.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2])):
        glsum = next(iter(v.values()))[2]
        t3rows.append([what, s, lk, glsum, cap / glsum / GWEI] + [
            ("ok" if v[f][0] else (v[f][1] or "rej")) if f in v else "–" for f in fees])
    t3 = md_table(["op", "tree size", "callGasLimit kind", "Σ gas limits", "analytic p_max (gwei) = 0.005 ETH / Σ"]
                  + [f"{f:g} gwei" for f in fees], t3rows)
    envelope_consistent = all(
        (r["sim_accepted"] == (r["required_prefund_wei"] <= cap)) or r["sim_inner_error"] not in (None, "MaxCostExceeded")
        for r in env_rows)
    summary = {"first_fail": first_fail, "natural": nat, "envelope_rows": env_rows,
               "envelope_analytic_consistent": envelope_consistent, "final_root_checks": g.get("checks")}
    return t1 + "\n\n" + t2 + "\n\n" + t3, summary


# --- figures -------------------------------------------------------------------------------


def figures(d: Data, fig_dir: Path, cells, policy_rows, gas_summary) -> List[str]:
    plt = _plt()
    fig_dir.mkdir(parents=True, exist_ok=True)
    made = []
    # 1 stale probability vs lambda*T
    if cells:
        fig, ax = plt.subplots(figsize=(6.4, 4))
        xs = np.linspace(0, max(c["lambdaT"] for c in cells) * 1.02, 200)
        ax.plot(xs, 1 - np.exp(-xs), color=NEUTRAL, lw=1.5, ls="--", label="1 − exp(−λT)")
        for n, col, mk in zip(sorted({c["n"] for c in cells}), (C1, C2, C3), ("o", "s", "^")):
            cs = [c for c in cells if c["n"] == n and c["trials"]]
            x = np.array([c["lambdaT"] for c in cs]) * (1 + 0.02 * (mk == "s") - 0.02 * (mk == "^"))
            y = np.array([c["p_stale"] for c in cs])
            lo = y - np.array([c["ci_lo"] for c in cs])
            hi = np.array([c["ci_hi"] for c in cs]) - y
            ax.errorbar(x, y, yerr=[lo, hi], fmt=mk, ms=5, color=col, ecolor=col, elinewidth=1,
                        capsize=0, label=f"N = {n} (95% Wilson CI)", mec="#fcfcfb", mew=0.8)
        ax.set_xscale("symlog", linthresh=0.1)
        ax.set_xlabel("λ·T (expected root changes in the vulnerability window)")
        ax.set_ylabel("P(stale-root failure), single attempt, P0")
        ax.set_title("Stale-root probability vs λ·T (frozen B3, real Bootstraps)", color=INK, loc="left")
        ax.legend(loc="upper left")
        fig.tight_layout()
        p = fig_dir / "stale_probability_vs_lambdaT.png"
        fig.savefig(p, dpi=160)
        plt.close(fig)
        made.append(p.name)
    # 2 inclusion success vs root update rate; 3 retries/proofs per success; 4 latency
    if policy_rows:
        lams = sorted({r["lambda"] for r in policy_rows})
        Ts = sorted({r["window"] for r in policy_rows})
        pols = sorted({r["policy"] for r in policy_rows})
        cols = dict(zip(pols, (C1, C2, C3)))
        for metric, fname, ylabel, title in (
                ("first_attempt_stale_rate", "inclusion_success_vs_rate.png",
                 "first-attempt inclusion success", "First-attempt inclusion success vs root-update rate"),
                ("proofs_per_success", "proofs_per_success_vs_rate.png",
                 "proofs per included Spend (log)",
                 "Proofs per included Spend vs root-update rate (10-attempt cap; hollow = some trial hit the cap, × = no success)"),
                ("tts_p50", "latency_vs_contention.png", "time to inclusion, p50 (virtual s, log)",
                 "Time to inclusion (p50) vs root-update rate (hollow = some trial hit the cap, × = no success)")):
            fig, axes = plt.subplots(1, len(Ts), figsize=(2.6 * len(Ts), 3.4), sharey=True)
            marks = dict(zip(pols, ("o", "s", "^")))
            for ax, T in zip(np.atleast_1d(axes), Ts):
                for pol in pols:
                    rs = sorted([r for r in policy_rows if r["window"] == T and r["policy"] == pol],
                                key=lambda r: r["lambda"])
                    y = [r[metric] for r in rs]
                    if metric == "first_attempt_stale_rate":
                        y = [None if v is None else 1 - v for v in y]
                    ax.plot([r["lambda"] for r in rs], [np.nan if v is None else v for v in y],
                            marker=marks[pol], ms=5, mec="#fcfcfb", mew=0.8, color=cols[pol], label=pol)
                    # cells where some trial hit the 10-attempt cap are censored: mark them
                    cens = [r for r in rs if r["successes"] < r["trials"] and r[metric] is not None]
                    if cens and metric != "first_attempt_stale_rate":
                        ax.plot([r["lambda"] for r in cens], [r[metric] for r in cens], marker=marks[pol],
                                ms=9, lw=0, mfc="none", mec=cols[pol], mew=1.2)
                    none_x = [r["lambda"] for r in rs if r[metric] is None]
                    if none_x and metric != "first_attempt_stale_rate":
                        ax.plot(none_x, [ax.get_ylim()[1]] * len(none_x), marker="x", lw=0, ms=6,
                                color=cols[pol])
                if metric == "first_attempt_stale_rate":
                    xs = np.linspace(0, max(lams), 50)
                    ax.plot(xs, np.exp(-xs * T), color=NEUTRAL, ls="--", lw=1.2, label="exp(−λT)")
                else:
                    ax.set_yscale("log")
                ax.set_title(f"T = {T:g} s", color=INK2)
                ax.set_xlabel("root updates / s (λ)")
            np.atleast_1d(axes)[0].set_ylabel(ylabel)
            np.atleast_1d(axes)[0].legend()
            fig.suptitle(title, x=0.01, ha="left", color=INK)
            fig.tight_layout()
            fig.savefig(fig_dir / fname, dpi=160)
            plt.close(fig)
            made.append(fname)
    # 5 deposit gas vs tree size; 6 Bootstrap success under frozen limit
    g = d.raw.get("gas") or {}
    rows = g.get("growth", [])
    if rows:
        seeds = sorted({r["seed"] for r in rows})
        r0 = sorted((r for r in rows if r["seed"] == seeds[0]), key=lambda r: r["tree_size_before"])
        x = [r["tree_size_before"] for r in r0]
        fig, ax = plt.subplots(figsize=(6.4, 4))
        ax.plot(x, [r["deposit_frame_gas_used"] for r in r0], color=C1, lw=1.5, label="CreditPool.deposit frame gas")
        ax.plot(x, [r["min_required_call_gas_limit"] for r in r0], color=C2, lw=1.5,
                label="minimal Bootstrap callGasLimit that inserts")
        ax.plot(x, [r.get("minreq_actual_gas_used") for r in r0], color=C3, lw=1.5,
                label="Bootstrap UserOp actualGasUsed (at minimal limit)")
        # worst case of each level: the insertion that completes a full subtree (size 2^d - 1)
        env = [r for r in r0 if r["tree_size_before"] + 2 == 2 ** (r["tree_size_before"] + 1).bit_length()]
        ax.plot([r["tree_size_before"] for r in env], [r["deposit_frame_gas_used"] for r in env],
                marker="o", ms=5, mec="#fcfcfb", mew=0.8, lw=0, color=C1)
        ax.annotate("worst case per tree level (size 2ᵈ−1)", (env[-1]["tree_size_before"],
                    env[-1]["deposit_frame_gas_used"]), textcoords="offset points", xytext=(-8, -16),
                    ha="right", color=C1, fontsize=8)
        frozen = g["checks"][0]["frozen_call_gas_limit"]
        ax.axhline(frozen, color=NEUTRAL, ls="--", lw=1.2)
        ax.text(x[-1], frozen, f"frozen callGasLimit {frozen:,} ", va="top", ha="right",
                color=INK2, fontsize=8)
        ax.set_xscale("symlog", linthresh=1)
        ax.set_xlim(left=-0.4)
        ax.set_xlabel("tree size before insertion")
        ax.set_ylabel("gas")
        ax.set_title(f"Bootstrap gas vs tree size (seed {seeds[0]}; other seed in tables)", color=INK, loc="left")
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(fig_dir / "deposit_gas_vs_tree_size.png", dpi=160)
        plt.close(fig)
        made.append("deposit_gas_vs_tree_size.png")
        fig, ax = plt.subplots(figsize=(6.4, 2.6))
        for i, seed in enumerate(seeds):
            rs = sorted((r for r in rows if r["seed"] == seed), key=lambda r: r["tree_size_before"])
            ok = [r["tree_size_before"] for r in rs if r.get("frozen_root_changed")]
            bad = [r["tree_size_before"] for r in rs if not r.get("frozen_root_changed")]
            ax.scatter(ok, [i] * len(ok), s=14, color=C3, marker="o", label="inserts" if i == 0 else None)
            ax.scatter(bad, [i] * len(bad), s=14, color=C2, marker="x", label="fails (grant consumed, no insert)" if i == 0 else None)
        ax.set_yticks(range(len(seeds)), [f"seed {s}" for s in seeds])
        ax.set_ylim(-0.6, len(seeds) - 0.4)
        ax.set_xscale("symlog", linthresh=1)
        ax.set_xlim(left=-0.4)
        ax.set_xlabel("tree size before insertion")
        ax.set_title(f"Bootstrap with the frozen callGasLimit ({frozen:,}) at each tree size", color=INK, loc="left")
        ax.legend(loc="center right")
        ax.grid(axis="y", visible=False)
        fig.tight_layout()
        fig.savefig(fig_dir / "bootstrap_frozen_limit_vs_tree_size.png", dpi=160)
        plt.close(fig)
        made.append("bootstrap_frozen_limit_vs_tree_size.png")
    return made


# --- driver --------------------------------------------------------------------------------


def analyze(batch: str, cfg: Dict[str, Any], dirs: Dict[str, Path], write_doc: bool = False) -> Dict[str, Any]:
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

    md, rows = control_table(d); add("T1. Zero-contention control (Experiment 1)", md, "control", rows)
    md, rows = race_table(d); add("T2. Deterministic simulation→inclusion race (Experiments 2, 14)", md, "race", rows)
    md, rows = latency_table(d); add("T3. Real proof-generation latency (Experiment 13)", md, "proof_latency", rows)
    md, cells, stoch = stochastic_tables(d)
    add("T4. Stochastic contention, pooled over N (Experiment 3; P0, one attempt)", md, "stochastic_pooled", stoch.get("pooled", []))
    write_csv(tables / "stochastic_cells.csv", cells)
    (tables / "stochastic_summary.json").write_text(json.dumps(stoch, indent=1, default=str))
    fit = stoch.get("fit") or {}
    if fit:
        fit_md = md_table(["model", "b0", "b1 (log λT)", "b2 (log2 N)", "−log L"], [
            ["Poisson baseline (fixed)", 0.0, 1.0, 0.0, fit["nll_poisson_baseline"]],
            ["free, no N", fit["b0_no_n"], fit["b1_no_n"], 0.0, fit["nll_no_n"]],
            ["free, with N", fit["b0"], fit["b1"], fit["b2"], fit["nll_full"]]])
        fit_md += (f"\n\nWald SE (with N): b0 {fmt(fit['se'][0])}, b1 {fmt(fit['se'][1])}, b2 {fmt(fit['se'][2])}. "
                   f"LR test pool-size term: χ²₁ = {fmt(fit['lr_pool_size'])}, p = {fmt(fit['p_pool_size'])}. "
                   f"LR test Poisson baseline vs free (no N): χ²₂ = {fmt(fit['lr_baseline_vs_free'])}, "
                   f"p = {fmt(fit['p_baseline_vs_free'])}. {fit['cells']} λ>0 cells, {fit['trials']} trials. "
                   f"Cells (of {stoch['cells']}) whose Wilson CI excludes 1−exp(−λT): {stoch['cells_outside_ci']}; "
                   f"cells with exact binomial p < 0.05: {stoch['cells_binom_p_lt_0_05']}.")
        tot = stoch["totals"]
        fit_md += (f"\n\nFailure classes over all {fmt(tot.get('trials'))} trials: STALE_BEFORE_SUBMISSION "
                   f"{fmt(tot.get('STALE_BEFORE_SUBMISSION'))}, STALE_BEFORE_SIMULATION {fmt(tot.get('STALE_BEFORE_SIMULATION'))}, "
                   f"VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION {fmt(tot.get('VALID_AT_SIM_STALE_BEFORE_INCLUSION'))}, "
                   f"other failures {fmt(tot.get('other_failures'))}, capacity exceeded {fmt(tot.get('capacity_exceeded'))}, "
                   f"inconsistent classifications {fmt(tot.get('inconsistent'))}. Stale / trials with λ>0 by N: "
                   + ", ".join(f"N={n}: {v['stale']}/{v['trials']}" for n, v in sorted(stoch["by_n_lambda_pos"].items(), key=lambda kv: int(kv[0]))) + ".")
        sections.append(("T5. Stale-root model fit (complementary log-log)", fit_md))
    md, prow = policy_tables(d); add("T6. Bundler policies P0/P1/P2 with client retry (Experiments 15, 16; N=16)", md, "policy_retry", prow)
    md, rows = segments_table(d); add("T7. Vulnerability-window decomposition (Experiment 12; λ=1/s)", md, "segments", rows)
    md, rows = measured_table(d); add("T8. Retry loop with measured proof time and assumed block intervals", md, "measured_latency", rows)
    md, drows, srows = concurrency_tables(d); add("T9. Concurrent spenders (Experiment 18; N=16)", md, "concurrency_deterministic", drows)
    write_csv(tables / "concurrency_stochastic.csv", srows)
    md, rows = bundle_table(d); add("T10. Bundle size and mixed bundles (Experiment 19; N=16)", md, "bundle", rows)
    md, rows = adversary_table(d); add("T11. A2 adversarial schedule (Experiment 25; λ=0 honest, T=2 s)", md, "adversary", rows)
    md, gsum = gas_tables(d, cfg); add("T12. D2-B deposit gas growth, frozen Bootstrap limit, fee envelope", md, "gas_summary", gsum)
    made = figures(d, dirs["figures"], cells, prow, gsum)
    out.update({"figures": made, "stochastic": stoch, "gas": {k: v for k, v in gsum.items() if k != "envelope_rows"}})
    body = [BEGIN, f"_Generated by `python3 -m experiments.liveness.d2 analyze --batch {batch} --write-doc` "
                   f"from `results/d2-pilot/{batch}/` and `data/private/d2-pilot/{batch}/`. Do not edit by hand._", ""]
    for title, md in sections:
        body += [f"### {title}", "", md, ""]
    body += ["Figures (`figures/d2-pilot/%s/`): %s" % (batch, ", ".join(f"`{m}`" for m in made)), END]
    gen = "\n".join(body)
    (tables / "generated.md").write_text(gen)
    (dirs["results"] / "analysis_summary.json").write_text(json.dumps(out, indent=1, default=str))
    if write_doc:
        doc = repo_root() / DOC
        text = doc.read_text() if doc.is_file() else f"# D2 pilot results\n\n{BEGIN}\n{END}\n"
        if BEGIN not in text:
            text += f"\n{BEGIN}\n{END}\n"
        pre, rest = text.split(BEGIN, 1)
        _, post = rest.split(END, 1)
        doc.write_text(pre + gen + post)
    print(f"[d2] analysis written: {tables}")
    return out
