"""B2-Allowlist and B2-Signature -- ordinary, fully observable Paymasters.

Two adapters, two baseline_ids (schema 3.0.0). They record identically; they
exist separately so the two Paymaster designs can never be pooled under one
baseline_id. B2-Allowlist publishes a sponsor->account allowlist transaction
before the operation (auxiliary baseline); B2-Signature authorizes off chain
with a sponsor signature carried in paymasterAndData.

docs/research-plan.md Sec. 5: a standard non-private Paymaster sponsors the
same operation B1 performs, using the same account code, same token, same
destination and same amount. Its purpose is to isolate ordinary sponsorship
from ZK/private authorization overhead and leakage.

What separates a B2 record from a B1 record:

* **``paymaster`` is populated and public.** That is the point of the
  baseline: an ordinary Paymaster's identity is on chain, and the record says
  so plainly. Recording it makes no claim either way about what it leaks --
  that is what the D1 experiment measures.
* **Paymaster gas limits are populated** under EntryPoint v0.7+.
* **No privacy-protocol artefacts.** B2 publishes no commitment, root or
  nullifier; those fields stay null and the adapter refuses to set them.
* **Bundler data stays in its own stream.** Sponsorship does not make
  submission timing or rejection reasons public: those remain A2.

The application semantics -- account implementation, target, selector, asset,
amount -- must match B1 exactly. The adapter cannot enforce that on its own;
the matched-run check belongs to the experiment runner and to the fairness
requirements in docs/research-plan.md Sec. 11.
"""

from __future__ import annotations

from .base import BaselineAdapter


class B2AllowlistAdapter(BaselineAdapter):
    """B2-Allowlist: ObservablePaymaster, public on-chain allowlist (auxiliary)."""
    baseline_id = "B2-Allowlist"


class B2SignatureAdapter(BaselineAdapter):
    """B2-Signature: SignatureVerifyingPaymaster, sponsor signature over userOpHash."""
    baseline_id = "B2-Signature"
