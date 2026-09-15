"""D1 pilot attacks and evaluation (docs/d1-pilot-results.md).

Neutral modules (no data access; importable from both sides of the boundary):
``registry`` (feature partition T / AA / G), ``extract`` (public rows -> pair
features), ``rules`` (deterministic and timing rules), ``models`` (conditional
logit), ``metrics``, ``splits``.

Side-specific packages, run as SEPARATE processes:
``attack``   imports experiments.attacker_view (public data only); freezes predictions.
``evaluate`` imports experiments.labels (ground truth); exports fold-scoped training
             labels, verifies frozen predictions, scores, audits, reports.

Importing this package imports neither side.
"""
