"""B3-PrivGas-v1 -- the frozen PrivGas v1 specimen, measured unmodified.

docs/research-plan.md Sec. 5: "Reproduce the accepted architecture as
faithfully as possible ... evaluate the published design as a specimen, not
silently 'improve' it." The id names ``baselines/b3_privgas_v1`` at commit
``02a3f0abdb979446545aa87149080bfb44e43a3e``; runs exist only on the
NON-PRODUCTION ``b3_compat_local`` evaluation profile (docs/b3-evaluation.md).

What a B3 record carries that B0-B2 records cannot:

* **Privacy-protocol artefacts, public parts only.** The deposited identity
  commitment, the Merkle root, the revealed nullifier and proof metadata
  (scheme, verifier address, public-signal count, proof byte length, tree
  depth) are on chain and are recorded as such. Recording them makes no claim
  that they are unlinkable -- that is what D1 measures.
* **Two sponsored operations from one account.** Bootstrap and Spend rows keep
  their real ``sender``. If both use the same smart account, the public
  stream shows it; nothing normalises or hides it.
* **R2 is defined.** Ground truth names the hidden credit and issuance and the
  public anchors (issuance op, commitment, nullifier) the evaluation joins on.
  Which issuance a redemption consumed stays in ground truth only.
"""

from __future__ import annotations

from .base import BaselineAdapter


class B3PrivGasV1Adapter(BaselineAdapter):
    baseline_id = "B3-PrivGas-v1"
