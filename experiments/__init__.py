"""privgas-v2 experiment packages.

Three sibling packages implement the data-separation boundary described in
docs/experiment-schema.md:

  experiments.recorder      write-side: schemas, validation, JSONL writers,
                            baseline adapters. Neutral — importable by both
                            sides of the boundary.
  experiments.attacker_view READ-side for attacker-visible data only
                            (public_events, bundler_private). Importing it
                            makes `experiments.labels` unimportable in the
                            same process.
  experiments.labels        READ-side for secret ground truth and the single
                            sanctioned label-join path. Importing it makes
                            `experiments.attacker_view` unimportable in the
                            same process.

See experiments/_boundary.py for the enforcement mechanism.
"""
