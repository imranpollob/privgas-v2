"""EVALUATION SIDE of the D1 pilot. Importing this package claims the private
side of the data boundary (``experiments.labels``): attacker-side code is not
importable in this process.

Responsibilities, in pipeline order:
1. leakage self-check of every pilot run (before labels leave this process);
2. export of fold-scoped TRAINING labels (training runs only, per frozen split);
3. after predictions are frozen: digest-verified label join, metrics, split and
   harness audits, stop-condition flags, tables, plots and the generated
   sections of docs/d1-pilot-results.md.
"""

from ....labels import join_for_evaluation, load_ground_truth, scan_public_output  # noqa: F401
