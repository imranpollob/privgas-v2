"""Canonical workload W1 for the matched baselines B0, B1 and B2.

W1 (docs/research-plan.md Sec. 4): an asset sender transfers a fixed ERC-20
amount to a fresh recipient-controlled account; the recipient then transfers
that amount to a fixed destination. B0/B1/B2 differ only in account type and
gas funding mechanism (docs/baseline-spec.md).

Pipeline, deliberately split so public records are regenerable from raw logs:

    runner.run_baseline()   live, signed transactions against a throwaway anvil
        -> data/raw/<experiment>/<run>/chain_dump.json          (role-free)
        -> data/raw/<experiment>/<run>/bundler_log.jsonl        (B1/B2 only)
        -> data/private/<experiment>/<run>/w1_private_run.json  (roles, costs)
    accounting.reconcile()  role-labelled cost table + conservation assertions
    recording.record_run()  raw -> Observations -> experiments.recorder streams

Nothing here is a privacy mechanism, and nothing here draws a privacy
conclusion. The contracts live in baselines/w1_b0_b2/.

Python dependencies (not stdlib): eth-account, eth-abi, eth-utils. Their
versions are captured into every chain dump.
"""
