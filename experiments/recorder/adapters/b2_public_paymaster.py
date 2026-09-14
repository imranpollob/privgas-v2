"""B2 -- ordinary, fully observable Paymaster.

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


class B2Adapter(BaselineAdapter):
    baseline_id = "B2"
