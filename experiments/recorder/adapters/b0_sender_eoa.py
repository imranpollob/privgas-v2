"""B0 -- sender-funded fresh stealth EOA.

docs/research-plan.md Sec. 5: the sender transfers the non-native asset plus
enough ETH for the recipient's subsequent transaction. The recipient account
is an ordinary EOA and the action is an ordinary transaction.

What this adapter structurally cannot emit, and why it matters for the
comparison:

* **No UserOperation.** B0 never reaches an EntryPoint, so ``userop_hash``,
  the fee/gas-limit fields and ``entrypoint_version`` are all null. Filling
  them in would make B0 look like an account-abstraction baseline and would
  invent the very gas-sponsorship metadata the D1 experiment is trying to
  isolate.
* **No Paymaster.** Nobody sponsors; the recipient pays from the ETH the
  sender supplied.
* **No bundler observations at all.** There is no mempool admission, no
  validation simulation and no replacement lineage to observe, so the
  recorder does not even open a bundler stream for B0.

Fairness accounting (ETH supplied vs. ETH retained vs. gas actually consumed,
docs/research-plan.md Sec. 5) is a per-run cost measurement, not an event
stream. The W1 runner writes it, role-labelled and therefore secret, to
``data/private/<experiment>/<run>/w1_cost_reconciliation.json``
(experiments/workloads/w1/accounting.py); the recorder does not aggregate
costs and deliberately has no single "cost" field.
"""

from __future__ import annotations

from .base import BaselineAdapter


class B0Adapter(BaselineAdapter):
    baseline_id = "B0"
