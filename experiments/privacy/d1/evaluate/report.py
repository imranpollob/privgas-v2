"""Tables (CSV/JSON), plots and generated markdown for the D1 pilot.

Every number in the outputs is computed here from the per-subject score rows;
nothing is typed by hand. The markdown written into docs/d1-pilot-results.md is
confined to BEGIN/END GENERATED markers.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

SCEN = {"S0-clean-shuffled": "S0", "S1-correlated-timing": "S1",
        "S1b-issuance-redemption-timing-only": "S1b"}


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], columns: Optional[List[str]] = None
              ) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    cols = columns or [k for k in rows[0].keys() if not isinstance(rows[0][k], (list, dict))]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k)) for k in cols})


def _fmt(v: Any) -> Any:
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return f"{v:.6g}"
    return v


def _f(v: Any, nd: int = 3) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def _ci(row: Mapping[str, Any], key: str, nd: int = 3) -> str:
    lo, hi = row.get(f"{key}_ci_lo"), row.get(f"{key}_ci_hi")
    if lo is None or (isinstance(lo, float) and math.isnan(lo)):
        return _f(row.get(key), nd)
    return f"{_f(row.get(key), nd)} [{_f(lo, nd)}, {_f(hi, nd)}]"


def md_table(header: List[str], rows: Iterable[List[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------
# plots
# --------------------------------------------------------------------------------------

def plots(out_dir: Path, rules_by_n: List[Dict[str, Any]], learned: List[Dict[str, Any]],
          deltas: List[Dict[str, Any]], learned_by_n: List[Dict[str, Any]]) -> List[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    # R2 timing rules, S0 vs S1, one figure per credit baseline present
    attacks = ["rule.r2-uniform", "rule.r2-insertion-order-fifo", "rule.r2-nearest-prior-issuance",
               "rule.r2-window-k2", "rule.r2-shuffled-fifo-control"]
    for b, fname in (("B3-PrivGas-v1", "r2_timing_rules_s0_vs_s1.png"),
                     ("B4-CrossAccount", "r2_timing_rules_s0_vs_s1_b4.png")):
        if not any(r["relation"] == "R2" and r["baseline_id"] == b for r in rules_by_n):
            continue
        scens = [sc for sc in SCEN if any(r["scenario_id"] == sc and r["baseline_id"] == b
                                          for r in rules_by_n)]
        fig, axes = plt.subplots(1, len(scens), figsize=(5 * len(scens), 3.8), sharey=True,
                                 squeeze=False)
        axes = list(axes[0])
        for ax, scen in zip(axes, scens):
            for a in attacks:
                pts = sorted((r["pool_size"], r["rule_top1"]) for r in rules_by_n
                             if r["relation"] == "R2" and r["baseline_id"] == b
                             and r["scenario_id"] == scen and r["attack"] == a)
                if pts:
                    ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o",
                            label=a.replace("rule.r2-", ""))
            ax.set_xscale("log", base=2)
            ax.set_title(f"{b} R2 timing rules — {SCEN[scen]}")
            ax.set_xlabel("pool size N")
            ax.grid(alpha=0.3)
        axes[0].set_ylabel("top-1 success")
        axes[-1].legend(fontsize=7)
        fig.tight_layout()
        p = out_dir / fname
        fig.savefig(p, dpi=150)
        plt.close(fig)
        written.append(p.name)

    # learned CE by feature set (loro, primary)
    sets = ["none", "T", "T+AA", "G", "T+G", "T+AA+G", "G-minus-eq", "T+G-minus-eq"]
    groups = sorted({(r["relation"], r["baseline_id"], r["scenario_id"]) for r in learned
                     if r["fold_kind"] == "loro" and r["convention"] == "primary"})
    fig, ax = plt.subplots(figsize=(11, 4))
    width = 0.8 / max(1, len(sets))
    for i, s in enumerate(sets):
        xs, ys = [], []
        for j, g in enumerate(groups):
            row = next((r for r in learned if (r["relation"], r["baseline_id"], r["scenario_id"]) == g
                        and r["fold_kind"] == "loro" and r["convention"] == "primary"
                        and r["feature_set"] == s), None)
            if row:
                xs.append(j + i * width)
                ys.append(row["ce_bits"])
        ax.bar(xs, ys, width=width, label=s)
    ax.set_xticks([j + 0.4 for j in range(len(groups))])
    ax.set_xticklabels([f"{g[0]}\n{g[1]}\n{SCEN[g[2]]}" for g in groups], fontsize=7)
    ax.set_ylabel("held-out cross entropy (bits)")
    ax.set_title("Conditional logit, leave-one-replicate-out (pooled N)")
    ax.legend(fontsize=7, ncol=4)
    fig.tight_layout()
    p = out_dir / "learned_cross_entropy.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p.name)

    # R3 negative control: top-1 vs chance by N
    fig, ax = plt.subplots(figsize=(7, 3.8))
    for b in ("B0", "B1", "B2-Signature", "B2-Allowlist", "B3-PrivGas-v1", "B4-CrossAccount"):
        pts = sorted((r["pool_size"], r["top1"]) for r in learned_by_n
                     if r["relation"] == "R3" and r["baseline_id"] == b
                     and r["scenario_id"] == "S0-clean-shuffled" and r["fold_kind"] == "loro"
                     and r["convention"] == "primary" and r["feature_set"] == "T+AA+G")
        if pts:
            ax.plot([p_[0] for p_ in pts], [p_[1] for p_ in pts], marker="o", label=b)
    ns = [4, 8, 16, 32]
    ax.plot(ns, [1 / n for n in ns], "k--", label="chance 1/N")
    ax.set_xscale("log", base=2)
    ax.set_xlabel("pool size N")
    ax.set_ylabel("top-1 (T+AA+G model)")
    ax.set_title("R3 negative control (S0)")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    p = out_dir / "r3_negative_control.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p.name)

    # delta bits
    main = [d for d in deltas if d["fold_kind"] == "loro" and d["convention"] == "primary"
            and (d["from"], d["to"]) in (("T", "T+G"), ("T", "T+AA"), ("T+AA", "T+AA+G"),
                                         ("T", "T+G-minus-eq"))]
    labels = [f"{d['relation']} {d['baseline_id']} {SCEN[d['scenario_id']]}\n{d['from']}→{d['to']}"
              for d in main]
    fig, ax = plt.subplots(figsize=(max(6, 0.55 * len(main)), 4))
    ys = [d["delta_bits"] for d in main]
    err = [[d["delta_bits"] - d["delta_ci_lo"] for d in main],
           [d["delta_ci_hi"] - d["delta_bits"] for d in main]]
    ax.bar(range(len(main)), ys, yerr=err, capsize=2)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_xticks(range(len(main)))
    ax.set_xticklabels(labels, rotation=90, fontsize=6)
    ax.set_ylabel("delta_bits (95% CI)")
    ax.set_title("Operational incremental leakage (held-out, pooled N)")
    fig.tight_layout()
    p = out_dir / "delta_bits.png"
    fig.savefig(p, dpi=150)
    plt.close(fig)
    written.append(p.name)
    return written


# --------------------------------------------------------------------------------------
# markdown
# --------------------------------------------------------------------------------------

def markdown(ctx: Mapping[str, Any]) -> str:
    rules = ctx["rules"]
    learned = ctx["learned"]
    deltas = ctx["deltas"]
    s = []
    s.append(f"Batch `{ctx['batch']}`, attack round `{ctx['round']}`. Generated by "
             "`python3 -m experiments.privacy.d1.evaluate score`; machine-readable tables in "
             f"`results/d1-pilot/{ctx['batch']}/evaluation-{ctx['round']}/`.")
    s.append("\n#### Dataset\n")
    s.append(md_table(["baseline", "scenario", "N", "runs recorded", "runs failed"],
                      [[r["baseline_id"], SCEN[r["scenario_id"]], str(r["pool_size"]),
                        str(r["recorded"]), str(r["failed"])] for r in ctx["dataset"]]))
    s.append("\n#### Candidate sets (per run; identical across replicates)\n")
    s.append(md_table(["baseline", "N", "R1 public candidates", "R1 true funders",
                       "R2 candidates", "R3 candidates", "total commitments",
                       "honest commitments", "attacker commitments"],
                      [[c["baseline_id"], str(c["pool_size"]), c["r1_public_candidates"],
                        str(c["r1_distinct_true_funders"]), str(c["r2_candidates"]),
                        str(c["r3_candidates"]), str(c["total_commitments"]),
                        str(c["honest_commitments"]), str(c["attacker_controlled_commitments"])]
                       for c in ctx["candidate_sets"]]))
    s.append("\n#### R1 structure (public trace)\n")
    s.append(md_table(["baseline", "N", "immediate payer", "distinct immediate payers",
                       "public candidate funders / op", "ops with direct account edge",
                       "funding shared across ops", "R1 classification run"],
                      [[r["baseline_id"], str(r["pool_size"]), r["immediate_gas_payer_kind"],
                        str(r["distinct_immediate_payers"]),
                        ",".join(map(str, r["public_candidate_economic_funders_per_op"])),
                        f"{r['ops_with_direct_account_specific_funding_edge']}/{r['operations']}",
                        str(r["funding_relation_shared_across_ops"]),
                        str(r["r1_classification_run"])] for r in ctx["r1_structure"]]))
    s.append("\n#### Exact / deterministic rules (pooled over N; 95% CIs)\n")
    s.append(md_table(["relation", "baseline", "scen.", "rule", "families", "tier", "coverage",
                       "precision", "top-1", "chance top-1", "mean |C|", "reduction"],
                      [[r["relation"], r["baseline_id"], SCEN[r["scenario_id"]],
                        r["attack"].replace("rule.", ""), r["feature_set"], "A0",
                        _f(r["coverage"]), _ci(r, "precision"), _ci(r, "rule_top1"),
                        _f(r["chance_top1"]), _f(r["candidate_set_size"], 1),
                        _f(r["candidate_set_reduction"])]
                       for r in rules if r["attack_kind"] in ("exact", "control")]))
    s.append("\n#### R2 timing rules by pool size\n")
    s.append(md_table(["baseline", "scen.", "rule", "N", "top-1", "top-3", "top-5", "coverage",
                       "precision", "reduction", "chance top-1"],
                      [[r["baseline_id"], SCEN[r["scenario_id"]], r["attack"].replace("rule.r2-", ""),
                        str(r["pool_size"]), _f(r["rule_top1"]), _f(r["top3"]), _f(r["top5"]),
                        _f(r["coverage"]), _f(r["precision"]), _f(r["candidate_set_reduction"]),
                        _f(r["chance_top1"])]
                       for r in ctx["rules_by_n"] if r["relation"] == "R2"
                       and r["attack_kind"] in ("timing", "control")]))
    s.append("\n#### Learned models (conditional logit; L2 chosen by inner CV on training runs; leave-one-replicate-out, pooled N)\n")
    s.append(md_table(["relation", "baseline", "scen.", "conv.", "feature set", "subjects",
                       "top-1", "top-3", "CE bits", "chance bits", "Brier", "ECE"],
                      [[r["relation"], r["baseline_id"], SCEN[r["scenario_id"]], r["convention"],
                        r["feature_set"], str(r["subjects"]), _ci(r, "top1"), _f(r["top3"]),
                        _ci(r, "ce_bits"), _f(r["chance_bits"]), _f(r["brier"]), _f(r["ece"])]
                       for r in learned if r["fold_kind"] == "loro"]))
    s.append("\n#### delta_bits (held-out CE difference in bits; paired cluster bootstrap 95% CI)\n")
    s.append(md_table(["relation", "baseline", "scen.", "fold", "conv.", "from", "to",
                       "CE from", "CE to", "delta_bits [CI]"],
                      [[d["relation"], d["baseline_id"], SCEN[d["scenario_id"]], d["fold_kind"],
                        d["convention"], d["from"], d["to"], _f(d["ce_from_bits"]),
                        _f(d["ce_to_bits"]),
                        f"{_f(d['delta_bits'])} [{_f(d['delta_ci_lo'])}, {_f(d['delta_ci_hi'])}]"]
                       for d in deltas]))
    s.append("\n#### Feature-family ablations of T+AA+G (positive = the removed family carried "
             "held-out information)\n")
    s.append(md_table(["relation", "baseline", "scen.", "conv.", "removed", "CE full",
                       "CE without", "delta_bits [CI]"],
                      [[d["relation"], d["baseline_id"], SCEN[d["scenario_id"]], d["convention"],
                        d["from"].split("-minus-")[1], _f(d["ce_to_bits"]), _f(d["ce_from_bits"]),
                        f"{_f(d['delta_bits'])} [{_f(d['delta_ci_lo'])}, {_f(d['delta_ci_hi'])}]"]
                       for d in ctx["ablations"]]))
    s.append("\n#### Configuration and scenario holdouts (T+AA+G and T+G-minus-eq)\n")
    s.append(md_table(["relation", "baseline", "scen.", "fold kind", "conv.", "feature set",
                       "subjects", "top-1", "CE bits", "chance bits"],
                      [[r["relation"], r["baseline_id"], SCEN[r["scenario_id"]], r["fold_kind"],
                        r["convention"], r["feature_set"], str(r["subjects"]), _ci(r, "top1"),
                        _ci(r, "ce_bits"), _f(r["chance_bits"])]
                       for r in learned if r["fold_kind"] != "loro"
                       and r["feature_set"] in ("T+AA+G", "T+G-minus-eq", "none")]))
    s.append("\n#### Audits and stop conditions\n")
    s.append(md_table(["check", "result"], [[k, str(v)] for k, v in ctx["stops"].items()]))
    s.append("\nHarness order audit (combined z over runs; |z| > 3.29 flags):\n")
    s.append(md_table(["baseline", "scen.", "pair", "runs", "mean rho", "z"],
                      [[r["baseline_id"], SCEN[r["scenario_id"]], r["pair"], str(r["runs"]),
                        _f(r["mean_rho"]), _f(r["z"], 2)] for r in ctx["harness"]["combined"]
                       if r["pair"].startswith("slot~") or r["pair"] in
                       ("issue~act", "deliver~act", "fund~act", "prepare~act",
                        "setup~setup_issuer", "setup_issuer~deliver", "setup_issuer~act",
                        "fund~deliver", "issue~prepare")]))
    s.append("\nFigures: " + ", ".join(f"`figures/d1-pilot/{ctx['batch']}/{f}`"
                                        for f in ctx["figures"]))
    return "\n".join(s) + "\n"


def write_generated(doc: Path, text: str, begin: str, end: str) -> None:
    body = doc.read_text()
    i, j = body.index(begin) + len(begin), body.index(end)
    doc.write_text(body[:i] + "\n\n" + text + "\n" + body[j:])
