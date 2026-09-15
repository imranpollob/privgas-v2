"""Simple probabilistic ranking model for linkage relations. NEUTRAL (no data).

Conditional logit (multinomial logistic regression over a variable candidate
set; McFadden's choice model): for subject s with candidates c_1..c_n and pair
features x(s, c),

    P(c | s) = exp(w . z(x(s, c))) / sum_c' exp(w . z(x(s, c')))

with z() the training-set standardisation and an L2 penalty on w. It is a
regularised linear classifier, the natural generalisation of logistic
regression to "which of these candidates", and its held-out log loss is the
quantity the incremental-information estimate uses. No intercept is possible
(it cancels in the softmax), so features that are constant across one
subject's candidates carry no information by construction.

With no features (or all-constant features) the model is exactly uniform.
The objective is vectorised over all candidate rows (group-wise logsumexp).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy.optimize import minimize

MODEL_ID = "conditional-logit-l2-v1"


def _group_logsumexp(s: np.ndarray, starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    smax = np.maximum.reduceat(s, starts)
    rep = np.repeat(smax, counts)
    return np.log(np.add.reduceat(np.exp(s - rep), starts)) + smax


@dataclass
class ConditionalLogit:
    l2: float = 1.0
    feature_names: List[str] = field(default_factory=list)
    mean_: Optional[np.ndarray] = None
    scale_: Optional[np.ndarray] = None
    coef_: Optional[np.ndarray] = None
    converged_: Optional[bool] = None
    train_subjects_: int = 0

    def fit(self, groups: Sequence[np.ndarray], true_index: Sequence[int]) -> "ConditionalLogit":
        d = len(self.feature_names)
        self.train_subjects_ = len(groups)
        if d == 0 or not groups:
            self.mean_, self.scale_, self.coef_ = np.zeros(d), np.ones(d), np.zeros(d)
            self.converged_ = True
            return self
        X = np.vstack(groups)
        self.mean_ = X.mean(axis=0)
        sd = X.std(axis=0)
        active = sd > 1e-12
        self.scale_ = np.where(active, sd, 1.0)
        Z = (X - self.mean_) / self.scale_
        counts = np.array([len(g) for g in groups])
        starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
        true_rows = starts + np.asarray(true_index)
        z_true_sum = Z[true_rows].sum(axis=0)
        l2 = self.l2

        def objective(w):
            w = np.where(active, w, 0.0)
            s = Z @ w
            lse = _group_logsumexp(s, starts, counts)
            nll = float(lse.sum() - s[true_rows].sum()) + 0.5 * l2 * float(w @ w)
            p = np.exp(s - np.repeat(lse, counts))
            grad = Z.T @ p - z_true_sum + l2 * w
            return nll, np.where(active, grad, 0.0)

        res = minimize(objective, np.zeros(d), jac=True, method="L-BFGS-B",
                       options={"maxiter": 1000})
        self.coef_ = np.where(active, res.x, 0.0)
        self.converged_ = bool(res.success)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if X.shape[0] == 0:
            return np.zeros(0)
        if len(self.feature_names) == 0:
            return np.full(X.shape[0], 1.0 / X.shape[0])
        s = ((X - self.mean_) / self.scale_) @ self.coef_
        s = s - s.max()
        e = np.exp(s)
        return e / e.sum()

    def describe(self) -> Dict[str, object]:
        return {"model_id": MODEL_ID, "l2": self.l2, "features": list(self.feature_names),
                "coefficients_standardised": [float(c) for c in (self.coef_ if self.coef_
                                                                 is not None else [])],
                "converged": self.converged_, "train_subjects": self.train_subjects_}
