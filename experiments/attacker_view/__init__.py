"""ATTACKER-SIDE read access. Public (A0/A1) and bundler (A2) data only.

Importing this package claims the PUBLIC side of the data boundary for the
whole process. From that point on, ``import experiments.labels`` -- direct,
dynamic, or via importlib -- raises ``BoundaryViolation``. That is the
structural protection behind the rule "attack / feature-generation code must
never load secret ground truth": it is not a convention and not a comment, it
is an ImportError.

The intended workflow (docs/experiment-schema.md, "Label-join rule"):

    process 1  (this package)     read public/bundler data
                                  -> generate features
                                  -> predict
                                  -> freeze predictions to disk with a digest
    process 2  (experiments.labels) verify the frozen digest
                                  -> load ground truth
                                  -> join and score

Two processes, not two functions, because only a process boundary makes the
import guard meaningful.
"""

from .. import _boundary

_boundary.claim(_boundary.PUBLIC_SIDE)

from .predictions import freeze_predictions  # noqa: E402,F401
from .readers import (  # noqa: E402,F401
    PrivateDataAccessError,
    load_bundler_private,
    load_public_events,
    load_public_manifest,
    load_run,
    list_runs,
)

__all__ = [
    "load_public_events", "load_bundler_private", "load_public_manifest",
    "load_run", "list_runs", "freeze_predictions", "PrivateDataAccessError",
]
