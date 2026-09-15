"""B4-CrossAccount -- cross-account ablation of the frozen PrivGas v1 specimen.

Same contracts, proofs, profile and record shape as ``B3-PrivGas-v1``; the only
difference is the actor workflow: the Bootstrap (issuance) operation and the
Spend (redemption) operation are sent by two DISTINCT public accounts of the same
hidden actor. Rows keep their real senders. Which issuance a redemption
consumed, and which issuer account hands its credit witness to which spender
account, stay in ground truth only (docs/d1-b4-results.md).
"""

from __future__ import annotations

from .base import BaselineAdapter


class B4CrossAccountAdapter(BaselineAdapter):
    baseline_id = "B4-CrossAccount"
