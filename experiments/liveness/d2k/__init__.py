"""D2 kill-condition test: bounded root history + gas-scaling decomposition.

NON-PRODUCTION | NON-EIP-170-DEPLOYABLE-AS-BUILT | EVALUATION-ONLY (``b3_compat_local``).

This package is a NEW result namespace (``d2-killcondition``). It does not touch the
frozen D2 pilot (``experiments/liveness/d2``, ``docs/d2-pilot-results.md``, batch
``20260915T223607Z``), which is closed; the pilot's harness, engine and state machine are
imported and reused unchanged.

Two questions, kept apart everywhere (code, records, tables, the result document):

* **Question A — can bounded root history cheaply remove the D2-A race?**
  ``mitigation.py`` deploys the experimental ``D2-History-K`` Paymaster variant
  (``contracts/d2k``) behind an otherwise unmodified frozen B3 deployment;
  ``exp_hist.py`` runs the deterministic retention boundary, the stochastic contention
  matrix, the bundle behaviour and the mitigation's own overhead.
* **Question B — why does CreditPool.deposit gas grow with the tree?**
  ``exp_gas.py`` decomposes it against G0 (frozen pool), G1 (LeanIMT only), G2
  (root mirror only), G3 (B3 surrounding logic without tree work), G4 (call floor) and
  G5 (one Poseidon delegatecall), measures the frozen-parameter feasibility envelope, the
  failed-Bootstrap grant transition, and what a bundler could detect before inclusion.

Nothing modifies ``baselines/b3_privgas_v1`` or ``baselines/b3_eval``. The experimental
Paymaster is reached only through the frozen ``CreditPool``'s own constructor argument.
No epoch roots, reservations, locking, Semaphore redesign, production bundler or staking
is introduced (``docs/decision-log.md``).
"""
