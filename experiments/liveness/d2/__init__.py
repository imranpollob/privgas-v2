"""D2 pilot: validation-state contention and liveness of the frozen B3 specimen.

NON-PRODUCTION | NON-EIP-170-DEPLOYABLE-AS-BUILT | EVALUATION-ONLY (``b3_compat_local``).

Two phenomena, kept apart everywhere (code, records, tables, ``docs/d2-pilot-results.md``):

* **D2-A root contention** -- a Spend proof made against CreditPaymaster's mirrored root R
  becomes invalid when another Bootstrap's ``CreditPool.deposit`` mirrors R' before the
  Spend is validated (``harness``, ``engine``, ``exp_a``).
* **D2-B Bootstrap gas scaling** -- ``CreditPool.deposit`` gas grows with the LeanIMT, and
  the frozen single-actor Bootstrap ``callGasLimit`` stops covering it (``exp_b``).

Nothing here modifies B3: the frozen contracts from ``baselines/b3_eval`` are deployed by
the unchanged W1 setup; root policy, verifier, Paymasters and Semaphore are untouched.
The staged bundler and its re-simulation policies are experimental bundler-side
behaviour, not protocol defenses.
"""
