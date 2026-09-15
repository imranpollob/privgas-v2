"""D1 multi-actor pilot workload (docs/d1-pilot-results.md).

N independent actors each perform W1-cold under one baseline, on one chain, in a
seeded schedule: ``actors.py`` (independent identities), ``schedule.py``
(S0-clean-shuffled / S1-correlated-timing), ``runner.py`` (execution, B3
single-final-root procedure and root verification), ``recording.py`` (recorder
streams, multi-actor ground truth), ``__main__.py`` (pilot matrix CLI).

The attacks live in ``experiments/privacy/d1`` and never import this package's
private outputs.
"""
