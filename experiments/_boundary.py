"""Process-level mutual exclusion between attacker-visible and secret data.

Research rule (docs/research-plan.md Sec. 10, docs/experiment-schema.md):
attack / feature-generation code must never be able to read secret ground
truth. Comments are not an enforcement mechanism, so this module makes the
two read-side packages *mutually unimportable within a single Python
process*:

  * importing ``experiments.attacker_view`` claims the PUBLIC side;
  * importing ``experiments.labels``       claims the PRIVATE side;
  * whichever is claimed first, importing the other raises
    ``BoundaryViolation`` at import time.

In addition, claiming the PUBLIC side installs a ``sys.meta_path`` finder
that refuses to resolve ``experiments.labels`` (and any submodule) even via
``importlib``, so the failure cannot be worked around by a dynamic import.

Consequence for workflow (docs/experiment-schema.md, "Label-join rule"):
feature generation and prediction must run in one process, evaluation in a
separate process, communicating only through a frozen predictions file.
This module is deliberately neutral: it holds no data and may be imported
by either side.
"""

from __future__ import annotations

import sys
from typing import Optional

PUBLIC_SIDE = "public"
PRIVATE_SIDE = "private"

PUBLIC_PACKAGE = "experiments.attacker_view"
PRIVATE_PACKAGE = "experiments.labels"

_claimed: Optional[str] = None


class BoundaryViolation(ImportError):
    """Raised when one process tries to hold both sides of the boundary."""


class _BlockedFinder:
    """A sys.meta_path finder that refuses to resolve a blocked package."""

    def __init__(self, blocked_package: str, reason: str) -> None:
        self.blocked_package = blocked_package
        self.reason = reason

    def find_module(self, fullname, path=None):  # pragma: no cover - legacy API
        self.find_spec(fullname, path)
        return None

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.blocked_package or fullname.startswith(
            self.blocked_package + "."
        ):
            raise BoundaryViolation(self.reason)
        return None


def claimed_side() -> Optional[str]:
    return _claimed


def claim(side: str) -> None:
    """Claim one side of the boundary for this process.

    Idempotent for repeated claims of the same side; raises on the other.
    """
    global _claimed
    if side not in (PUBLIC_SIDE, PRIVATE_SIDE):
        raise ValueError(f"unknown boundary side: {side!r}")

    if _claimed == side:
        return

    if _claimed is not None:
        raise BoundaryViolation(
            f"this process already claimed the {_claimed!r} side of the "
            f"public/private data boundary and cannot also claim {side!r}. "
            "Feature generation and label evaluation must run in separate "
            "processes (see docs/experiment-schema.md, 'Label-join rule')."
        )

    if side == PUBLIC_SIDE:
        if PRIVATE_PACKAGE in sys.modules:
            raise BoundaryViolation(
                f"{PRIVATE_PACKAGE} is already imported in this process; "
                f"{PUBLIC_PACKAGE} must not be imported alongside it."
            )
        _install_block(
            PRIVATE_PACKAGE,
            f"{PRIVATE_PACKAGE} cannot be imported: this process has loaded "
            f"{PUBLIC_PACKAGE} and is therefore attacker-side code, which must "
            "not read secret ground truth. Run evaluation in a separate "
            "process (see docs/experiment-schema.md, 'Label-join rule').",
        )
    else:
        if PUBLIC_PACKAGE in sys.modules:
            raise BoundaryViolation(
                f"{PUBLIC_PACKAGE} is already imported in this process; "
                f"{PRIVATE_PACKAGE} must not be imported alongside it."
            )
        _install_block(
            PUBLIC_PACKAGE,
            f"{PUBLIC_PACKAGE} cannot be imported: this process has loaded "
            f"{PRIVATE_PACKAGE} (secret ground truth). Attacker-side feature "
            "generation must run in a separate process.",
        )

    _claimed = side


def _install_block(package: str, reason: str) -> None:
    for finder in sys.meta_path:
        if isinstance(finder, _BlockedFinder) and finder.blocked_package == package:
            return
    sys.meta_path.insert(0, _BlockedFinder(package, reason))


def _reset_for_tests() -> None:
    """Undo a claim. Test-support only; never call from experiment code."""
    global _claimed
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, _BlockedFinder)]
    _claimed = None
