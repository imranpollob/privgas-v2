"""The frozen D2 contention engine, reused with ONE retention-aware override.

``experiments/liveness/d2/engine.py`` (frozen) drives the whole Spend state machine:
the virtual clock, the Poisson arrivals executed as real Bootstraps, the bundler
policies, the failure classification and the consistency cross-check. It is imported
unchanged.

The engine asks exactly one question of the protocol, in one place::

    Trial._root_changes_between(t0, t_checkpoint)   ->  the root changes that
                                                        invalidate this proof

Under latest-root validation that is "every root change since the proof was made", which
is what the frozen method returns. Under bounded root history of capacity K a proof made
against root R stays valid while R is still retained, i.e. while fewer than K root
updates have happened since R was mirrored; the K-th such update is the moment it becomes
invalid, and only that update and its successors are invalidating events.

``HistoryTrial`` therefore overrides that single method and nothing else. Every call site
in the frozen engine passes ``lo = t0`` (the moment the witness was fixed), which is what
makes this a correct, local substitution; a static test
(``tests/test_static.TestEngineOverride``) pins that every call site in the frozen engine
still does. With ``capacity = 1`` the override is the identity, so the frozen behaviour --
and the frozen classification -- is reproduced exactly.

RETENTION MODEL / IMPLEMENTATION AGREEMENT is a stop condition: every attempt record also
carries the model's prediction (``predicted_valid``) and whether the real on-chain outcome
matched it (``prediction_matches_outcome``). A mismatch means the analytical K model and
the deployed contract disagree and the experiment must stop.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..d2.engine import (POLICIES, STALE_CLASSES, VALID_PROOF_INCLUDED, ArrivalProcess,
                         ContenderPool, Segments, SpenderState, Trial, TrialSpec)
from ..d2.harness import HarnessInvariantViolation


class HistoryTrial(Trial):
    """``Trial`` with bounded-root-history retention. ``capacity = 1`` == frozen."""

    def __init__(self, *args: Any, capacity: int = 1, variant: str = "frozen", **kw: Any) -> None:
        super().__init__(*args, **kw)
        if capacity < 1:
            raise ValueError("history capacity must be >= 1")
        self.capacity = int(capacity)
        self.variant = variant
        self._t0_seen: List[float] = []

    def _root_changes_between(self, lo: float, hi: float, strict_hi: bool = False) -> List[float]:
        changes = super()._root_changes_between(lo, hi, strict_hi)
        k = self.capacity
        # The proof root survives the first k-1 updates; the k-th evicts it.
        return changes[k - 1:] if len(changes) >= k else []

    def raw_root_changes(self, lo: float, hi: float, strict_hi: bool = False) -> List[float]:
        """Every root change in the window, retention ignored (the §10 'root updates
        survived' metric and the denominator of the eviction check)."""
        return Trial._root_changes_between(self, lo, hi, strict_hi)


def annotate(tr: HistoryTrial, extra: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Add the history-specific fields to every attempt record of ``tr``.

    ``predicted_valid`` is the ANALYTICAL retention rule (fewer than K root updates in the
    attempt's window); ``prediction_matches_outcome`` compares it with what the chain did.
    """
    out = []
    for r in tr.records:
        t0 = r.get("t0")
        end = r.get("t8", r.get("failure_observed_at", t0))
        raw = tr.raw_root_changes(t0, end, strict_hi=r.get("t8") is not None) if t0 is not None else []
        included = r["outcome_class"] == VALID_PROOF_INCLUDED
        predicted = len(raw) < tr.capacity
        r.update({
            "variant": tr.variant, "history_capacity": tr.capacity,
            "root_updates_in_window": len(raw),
            "root_updates_survived": len(raw) if included else None,
            "evicted_in_window": len(raw) >= tr.capacity,
            "predicted_valid": predicted,
            # A proof can also fail for reasons unrelated to the root (none observed in the
            # pilot); only root-class outcomes are compared with the retention model.
            "prediction_matches_outcome": (
                predicted == included
                if r["outcome_class"] in STALE_CLASSES + (VALID_PROOF_INCLUDED,) else None),
        })
        if extra:
            r.update(extra)
        out.append(r)
    return out


def check_model_agreement(records: Sequence[Dict[str, Any]]) -> int:
    """STOP CONDITION: the analytical K model must agree with the implemented retention."""
    bad = [r for r in records if r.get("prediction_matches_outcome") is False]
    if bad:
        raise HarnessInvariantViolation(
            "STOP: retention model disagrees with the implementation on "
            f"{len(bad)} attempt(s), e.g. {bad[0].get('attempt_id')} "
            f"(K={bad[0].get('history_capacity')}, "
            f"updates={bad[0].get('root_updates_in_window')}, "
            f"outcome={bad[0].get('outcome_class')})")
    return len(records)


__all__ = ["HistoryTrial", "annotate", "check_model_agreement", "POLICIES", "Segments",
           "SpenderState", "TrialSpec", "ArrivalProcess", "ContenderPool", "Trial",
           "VALID_PROOF_INCLUDED", "STALE_CLASSES"]
