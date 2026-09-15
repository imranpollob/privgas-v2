"""ATTACKER SIDE of the D1 pilot. Importing this package claims the public side
of the data boundary (``experiments.attacker_view``): ground truth is not
importable in this process.

Inputs: recorded public streams (tier A0), the auxiliary R3 wallet directory,
the public dataset manifest, the frozen split manifest, and -- for learned
attacks only -- the fold-scoped training-label files of that fold's TRAINING
runs (exported by a separate ``experiments.privacy.d1.evaluate`` process).
Output: frozen predictions (``experiments.attacker_view.freeze_predictions``).
"""

from ....attacker_view import freeze_predictions, load_run  # noqa: F401  (claims the side)
