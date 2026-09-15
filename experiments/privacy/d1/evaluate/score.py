"""Join frozen predictions with labels and compute every D1 pilot metric.

Only ``experiments.labels.join_for_evaluation`` puts a prediction next to a
label; it refuses unless the predictions file still hashes to its frozen
digest. Truth is expressed as the true candidate's PUBLIC ref from the ground
truth anchors (R1 funder address, R2 issuance userop hash, R3 wallet address).

Metric definitions: ``experiments/privacy/d1/metrics.py``. Rule metrics:
fired = the rule selected a non-empty set smaller than the candidate set;
coverage = P(fired); precision = P(truth in selected | fired); rule top-1 =
E[1(truth in S)/|S|] when fired, 1/|C| otherwise; candidate-set reduction =
mean(1 - |S|/|C|) over fired subjects. Cross entropy is reported only for
probabilistic (learned) predictions.

delta_bits(A -> B) = (CE_A - CE_B), CE in bits (i.e. the natural-log difference
divided by ln 2), averaged over the same held-out subjects; its CI is a paired
two-stage (run, subject) bootstrap. An operational predictive-information
estimate, not a mutual-information value.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np

from ....labels import join_for_evaluation
from ....recorder import paths as paths_mod
from ....workloads.d1.config import parse_experiment_id
from .. import metrics
from .labels_io import truth_refs


def prediction_sets(root: Path, runs: List[Mapping[str, Any]], round_id: str
                    ) -> List[Dict[str, Any]]:
    out = []
    for r in runs:
        rp = paths_mod.run_paths(r["experiment_id"], r["run_id"], root)
        base = rp.predictions_dir
        if not base.is_dir():
            continue
        for attack_dir in sorted(base.iterdir()):
            if not attack_dir.name.startswith(round_id + "."):
                continue
            for rel_dir in sorted(attack_dir.iterdir()):
                m = json.loads((rel_dir / "predictions.manifest.json").read_text())
                out.append({**m, "_run": r})
    return out


def _attack_family(attack_id: str) -> Dict[str, str]:
    parts = attack_id.split(".", 1)[1]
    if parts.startswith("rule."):
        return {"attack": parts, "kind": "rule", "fold_kind": "", "convention": ""}
    _, fold_kind, convention, feature_set = parts.split(".", 3)
    return {"attack": f"clogit.{convention}.{feature_set}", "kind": "learned",
            "fold_kind": fold_kind, "convention": convention, "feature_set": feature_set}


def score_all(root: Path, runs: List[Mapping[str, Any]], round_id: str
              ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Returns (per-subject rows, prediction manifests)."""
    manifests = prediction_sets(root, runs, round_id)
    truths: Dict[Tuple[str, str, str], Dict[str, Optional[str]]] = {}
    subject_rows: List[Dict[str, Any]] = []
    for m in manifests:
        r = m["_run"]
        exp, run, rel = r["experiment_id"], r["run_id"], m["relation"]
        join = join_for_evaluation(experiment_id=exp, run_id=run, attack_id=m["attack_id"],
                                   relation=rel, root=root)
        key = (exp, run, rel)
        if key not in truths:
            truths[key] = truth_refs(root, exp, run, rel)
        fam = _attack_family(m["attack_id"])
        for row in join.rows:
            if row.label is None or row.label["status"] != "observed":
                continue
            pred = row.prediction
            cands = [c.lower() for c in pred["candidates"]]
            truth = truths[key][row.subject_ref]
            t_idx = cands.index(truth) if truth in cands else None
            scores = np.asarray(pred["scores"], dtype=float)
            base = {"experiment_id": exp, "run_id": run, "relation": rel,
                    "baseline_id": r["baseline_id"], "scenario_id": r["scenario_id"],
                    "pool_size": r["pool_size"], "replicate": r["replicate"],
                    "attack_id": m["attack_id"], "feature_set": m["feature_set"],
                    "subject_ref": row.subject_ref, **fam}
            if pred["kind"] == "probabilities":
                sm = metrics.subject_metrics(scores, t_idx)
            else:
                # ranking from scores (top-k), answer set from `selected`
                order_scores = scores - scores.min() + 1e-9 if len(scores) else scores
                sm = metrics.subject_metrics(order_scores / order_scores.sum(), t_idx)
                for k in ("ce_bits", "brier", "posterior_entropy_bits",
                          "effective_candidate_set_size", "top1_confidence",
                          "top1_correct_expected", "support_size", "truth_in_support"):
                    sm.pop(k, None)
                sel = {c.lower() for c in pred["selected"]}
                n = len(cands)
                fired = 0 < len(sel) < n
                sm["fired"] = float(fired)
                sm["selected_size"] = float(len(sel))
                sm["truth_in_selected"] = float(truth in sel) if fired else float("nan")
                sm["rule_top1"] = (float(truth in sel) / len(sel)) if fired else 1.0 / n
                sm["candidate_set_reduction"] = (1 - len(sel) / n) if fired else float("nan")
            subject_rows.append({**base, **sm})
        if join.unpredicted_subject_refs:
            # R3/B3: Bootstrap operations carry R3 labels but are not attack subjects
            # (the subject is the application operation). Recorded, not dropped.
            subject_rows.append({"experiment_id": exp, "run_id": run, "relation": rel,
                                 "attack_id": m["attack_id"], "_unpredicted_labelled":
                                 len(join.unpredicted_subject_refs), "baseline_id": r["baseline_id"],
                                 "scenario_id": r["scenario_id"], "pool_size": r["pool_size"],
                                 "replicate": r["replicate"], **fam})
    return subject_rows, manifests


LEARNED_KEYS = ("top1", "top3", "top5", "ce_bits", "chance_bits", "brier",
                "posterior_entropy_bits", "effective_candidate_set_size", "candidate_set_size",
                "truth_in_candidate_set")
RULE_KEYS = ("top1", "top3", "top5", "rule_top1", "fired", "truth_in_selected",
             "selected_size", "candidate_set_reduction", "chance_bits", "candidate_set_size",
             "truth_in_candidate_set")


def _by_cluster(rows: List[Mapping[str, Any]], key: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        v = r.get(key)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        out[f"{r['experiment_id']}|{r['run_id']}"].append(v)
    return out


def summarise(rows: List[Dict[str, Any]], group_keys: Tuple[str, ...], reps: int = 1000
              ) -> List[Dict[str, Any]]:
    scored = [r for r in rows if "_unpredicted_labelled" not in r]
    groups: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in scored:
        groups[tuple(r.get(k) for k in group_keys)].append(r)
    out = []
    for g, rs in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        kind = rs[0]["kind"]
        keys = LEARNED_KEYS if kind == "learned" else RULE_KEYS
        row = dict(zip(group_keys, g))
        row["subjects"] = len(rs)
        row["runs"] = len({(r["experiment_id"], r["run_id"]) for r in rs})
        for k in keys:
            vals = [r[k] for r in rs if k in r and not (isinstance(r[k], float)
                                                         and math.isnan(r[k]))]
            row[k] = float(np.mean(vals)) if vals else float("nan")
        row["chance_top1"] = float(np.mean([1.0 / r["candidate_set_size"] for r in rs]))
        ci_keys = ("top1", "ce_bits") if kind == "learned" else ("rule_top1",)
        for k in ci_keys:
            ci = metrics.cluster_bootstrap(_by_cluster(rs, k), reps=reps)
            row[f"{k}_ci_lo"], row[f"{k}_ci_hi"] = ci["lo"], ci["hi"]
        if kind == "rule":
            fired = [r for r in rs if r.get("fired") == 1.0]
            hits = sum(r["truth_in_selected"] for r in fired)
            row["precision"] = hits / len(fired) if fired else float("nan")
            w = metrics.wilson(hits, len(fired))
            row["precision_ci_lo"], row["precision_ci_hi"] = w["lo"], w["hi"]
            row["coverage"] = len(fired) / len(rs)
        if kind == "learned":
            cal = metrics.calibration_bins([r["top1_confidence"] for r in rs],
                                           [r["top1_correct_expected"] for r in rs])
            row["ece"] = cal["ece"]
            row["calibration_bins"] = cal["bins"]
        out.append(row)
    return out


def delta_bits(rows: List[Dict[str, Any]], comparisons: List[Tuple[str, str]],
               group_keys: Tuple[str, ...], reps: int = 2000) -> List[Dict[str, Any]]:
    learned = [r for r in rows if r.get("kind") == "learned" and "ce_bits" in r]
    index: Dict[tuple, Dict[str, float]] = defaultdict(dict)
    meta: Dict[tuple, Dict[str, Any]] = {}
    for r in learned:
        g = tuple(r[k] for k in group_keys)
        index[(g, r["convention"], r["experiment_id"], r["run_id"], r["subject_ref"])][
            r["feature_set"]] = r["ce_bits"]
        meta[g] = {k: r[k] for k in group_keys}
    out = []
    groups = sorted({(k[0], k[1]) for k in index}, key=lambda x: tuple(map(str, x)))
    for g, conv in groups:
        for a, b in comparisons:
            diffs: Dict[str, List[float]] = defaultdict(list)
            ce_a, ce_b = [], []
            for key, sets in index.items():
                if key[0] != g or key[1] != conv or a not in sets or b not in sets:
                    continue
                diffs[f"{key[2]}|{key[3]}"].append(sets[a] - sets[b])
                ce_a.append(sets[a])
                ce_b.append(sets[b])
            if not ce_a:
                continue
            ci = metrics.cluster_bootstrap(diffs, reps=reps)
            out.append({**meta[g], "convention": conv, "from": a, "to": b,
                        "subjects": len(ce_a), "ce_from_bits": float(np.mean(ce_a)),
                        "ce_to_bits": float(np.mean(ce_b)), "delta_bits": ci["mean"],
                        "delta_ci_lo": ci["lo"], "delta_ci_hi": ci["hi"]})
    return out
