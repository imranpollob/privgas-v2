"""B1 -- sender-funded ERC-4337 smart account, no Paymaster.

docs/research-plan.md Sec. 5: same logical workflow as B0, executed through
the ERC-4337 smart-account implementation the later baselines also use. Its
purpose is to isolate the effect of account abstraction from the effect of
sponsorship, so B1 and B2 must differ only in the gas mechanism.

What this adapter emits and withholds:

* **Full ERC-4337 fields.** userop_hash, EntryPoint address and version,
  factory, the four account-side gas/fee fields, and the on-chain result.
* **``paymaster`` is null by construction, not by ignorance.** B1 has no
  sponsor at all. The schema's null-vs-not_applicable distinction is doing
  real work here: the field exists in the ERC-4337 sense (there is a
  ``paymaster`` slot in the operation) but is unset for every B1 operation.
* **The two paymaster gas-limit fields are null** for the same reason, and
  would also be null under EntryPoint v0.6 regardless, where
  ``paymasterAndData`` is not decomposed.
* **Bundler observations are separate.** B1 does go through a bundler, so A2
  rows exist -- in ``observer_a2/``, never merged into the A0/A1 dataset.
"""

from __future__ import annotations

from .base import BaselineAdapter


class B1Adapter(BaselineAdapter):
    baseline_id = "B1"
