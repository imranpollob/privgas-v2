"""PRIVATE-SIDE read access: secret ground truth and the label-join path.

Importing this package claims the PRIVATE side of the data boundary for the
whole process. From that point on, ``import experiments.attacker_view``
raises ``BoundaryViolation``. A process that can see the answer key cannot
also be running feature generation.

Everything here is for evaluation after predictions are frozen, plus the
leakage self-check (which needs the labels in order to look for them in
public output).
"""

from .. import _boundary

_boundary.claim(_boundary.PRIVATE_SIDE)

from .evaluation import (  # noqa: E402,F401
    EvaluationJoin,
    FrozenPredictionsError,
    join_for_evaluation,
)
from .loader import (  # noqa: E402,F401
    GroundTruthRun,
    accounts_by_actor,
    load_ground_truth,
    load_private_manifest,
)
from .selfcheck import LeakFinding, scan_public_output  # noqa: E402,F401

__all__ = [
    "load_ground_truth", "load_private_manifest", "GroundTruthRun",
    "accounts_by_actor", "join_for_evaluation", "EvaluationJoin",
    "FrozenPredictionsError", "scan_public_output", "LeakFinding",
]
