"""Linkage metrics for candidate-set predictions. NEUTRAL, pure functions.

A prediction for one subject is a probability vector over that subject's public
candidate set (``p``), plus the index of the true candidate (``t``) supplied by
evaluation after predictions are frozen. Set-valued rules are represented as
uniform probability over the selected set (zero elsewhere).

Ties are broken uniformly at random, so top-k is an EXPECTED success rate:
with h candidates scored strictly higher than the truth and m tied with it
(truth included), P(truth within the first k) = clip((k - h) / m, 0, 1).
"""

from __future__ import annotations

import math
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np

TIE_TOL = 1e-12
P_FLOOR = 1e-12


def subject_metrics(p: Sequence[float], t: Optional[int]) -> Dict[str, float]:
    p = np.asarray(p, dtype=float)
    n = len(p)
    out: Dict[str, float] = {"candidate_set_size": float(n),
                             "chance_bits": math.log2(n) if n else float("nan")}
    H = float(-(p[p > 0] * np.log2(p[p > 0])).sum())
    out["posterior_entropy_bits"] = H
    out["effective_candidate_set_size"] = 2 ** H
    support = int((p > TIE_TOL).sum())
    out["support_size"] = float(support)
    out["candidate_set_reduction"] = 1 - support / n if n else float("nan")
    if t is None:
        out["truth_in_candidate_set"] = 0.0
        return out
    out["truth_in_candidate_set"] = 1.0
    pt = p[t]
    higher = int((p > pt + TIE_TOL).sum())
    tied = int((np.abs(p - pt) <= TIE_TOL).sum())
    for k in (1, 3, 5):
        out[f"top{k}"] = float(min(1.0, max(0.0, (k - higher) / tied)))
    out["truth_in_support"] = float(pt > TIE_TOL)
    out["ce_bits"] = float(-math.log2(max(pt, P_FLOOR)))
    onehot = np.zeros(n)
    onehot[t] = 1.0
    out["brier"] = float(((p - onehot) ** 2).sum())
    out["top1_confidence"] = float(p.max())
    # correctness of the arg-max with random tie-breaking
    maxp = p.max()
    winners = np.abs(p - maxp) <= TIE_TOL
    out["top1_correct_expected"] = float(winners[t] / winners.sum())
    return out


def aggregate(rows: Sequence[Mapping[str, float]], keys: Sequence[str]) -> Dict[str, float]:
    out = {}
    for k in keys:
        vals = [r[k] for r in rows if k in r and not (isinstance(r[k], float) and math.isnan(r[k]))]
        out[k] = float(np.mean(vals)) if vals else float("nan")
    out["subjects"] = float(len(rows))
    return out


def calibration_bins(conf: Sequence[float], correct: Sequence[float], bins: int = 5
                     ) -> Dict[str, object]:
    conf = np.asarray(conf)
    correct = np.asarray(correct)
    edges = np.linspace(0, 1, bins + 1)
    table = []
    ece = 0.0
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (conf >= lo) & ((conf < hi) if i < bins - 1 else (conf <= hi))
        if m.sum() == 0:
            table.append({"lo": lo, "hi": hi, "n": 0, "confidence": None, "accuracy": None})
            continue
        c, a = float(conf[m].mean()), float(correct[m].mean())
        ece += m.sum() / len(conf) * abs(c - a)
        table.append({"lo": lo, "hi": hi, "n": int(m.sum()), "confidence": c, "accuracy": a})
    return {"ece": float(ece) if len(conf) else float("nan"), "bins": table}


def cluster_bootstrap(values_by_cluster: Mapping[str, Sequence[float]], reps: int = 2000,
                      seed: int = 20260915, alpha: float = 0.05) -> Dict[str, float]:
    """Two-stage percentile bootstrap of a mean: resample clusters (runs), then
    subjects within each resampled cluster. Returns mean, lo, hi."""
    clusters = [np.asarray(v, dtype=float) for v in values_by_cluster.values() if len(v)]
    if not clusters:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan")}
    allv = np.concatenate(clusters)
    rng = np.random.default_rng(seed)
    k = len(clusters)
    stats = np.empty(reps)
    for r in range(reps):
        picks = rng.integers(0, k, size=k)
        total = 0.0
        count = 0
        for i in picks:
            c = clusters[i]
            s = c[rng.integers(0, len(c), size=len(c))]
            total += s.sum()
            count += len(s)
        stats[r] = total / count
    lo, hi = np.quantile(stats, [alpha / 2, 1 - alpha / 2])
    return {"mean": float(allv.mean()), "lo": float(lo), "hi": float(hi)}


def wilson(successes: float, n: int, z: float = 1.959964) -> Dict[str, float]:
    if n == 0:
        return {"lo": float("nan"), "hi": float("nan")}
    phat = successes / n
    den = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / den
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / den
    return {"lo": max(0.0, centre - half), "hi": min(1.0, centre + half)}
