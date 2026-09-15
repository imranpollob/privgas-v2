"""Evaluation-chain profiles for the W1 runs.

A profile is the anvil CHAIN CONFIGURATION a run executes on. It is recorded in
every chain dump, manifest and calibration fingerprint, and it is part of the
experiment id, so runs on different profiles are never pooled by accident.

``eip170_standard``
    anvil defaults for contract size: EIP-170 (24,576-byte runtime code limit)
    and EIP-3860 enforced. The ordinary configuration used by B0/B1/B2 since the
    first W1 runs. The frozen B3 specimen CANNOT be deployed here: its
    PoseidonT3 library is 29,315 runtime bytes (docs/b3-reproduction.md). That
    finding is unchanged and is re-checked live by
    ``tests/test_b3_live.TestEip170Limitation``.

``b3_compat_local``
    NON-PRODUCTION, NON-EIP-170-DEPLOYABLE-AS-BUILT, PRIVACY-EVALUATION-ONLY.
    Identical to ``eip170_standard`` except that anvil's code-size limit is
    raised to 32,768 bytes (``--code-size-limit 32768``; the initcode limit
    follows as 2x), which is sufficient for the frozen, unmodified PoseidonT3.
    Its setup additionally deploys the frozen B3 contracts and funds the two B3
    Paymasters, and it does so for EVERY baseline run on this profile, so that
    in matched D1 comparisons B3 is not distinguishable merely by a different
    chain configuration or a different set of deployed contracts. This profile
    says nothing about deployability on any real network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

EIP170_CODE_SIZE_LIMIT = 24_576


@dataclass(frozen=True)
class EvaluationProfile:
    profile_id: str
    #: None = anvil default (EIP-170 enforced at 24,576 bytes).
    code_size_limit: Optional[int]
    #: Deploy and fund the frozen B3 contracts in the (identical) setup phase.
    includes_b3_infrastructure: bool
    labels: Tuple[str, ...]
    description: str

    @property
    def effective_code_size_limit(self) -> int:
        return self.code_size_limit or EIP170_CODE_SIZE_LIMIT

    @property
    def eip170_enforced(self) -> bool:
        return self.effective_code_size_limit == EIP170_CODE_SIZE_LIMIT

    def anvil_args(self) -> List[str]:
        return [] if self.code_size_limit is None else [
            "--code-size-limit", str(self.code_size_limit)]

    def as_dict(self) -> Dict[str, object]:
        return {"profile_id": self.profile_id,
                "code_size_limit": self.effective_code_size_limit,
                "eip170_enforced": self.eip170_enforced,
                "includes_b3_infrastructure": self.includes_b3_infrastructure,
                # "profile_labels", not "labels": the recorder denylists a bare
                # "labels" key in public output.
                "profile_labels": list(self.labels), "description": self.description}


STANDARD = EvaluationProfile(
    profile_id="eip170_standard", code_size_limit=None,
    includes_b3_infrastructure=False, labels=(),
    description="anvil defaults: EIP-170 / EIP-3860 enforced; B3 not deployable")

B3_COMPAT = EvaluationProfile(
    profile_id="b3_compat_local", code_size_limit=32_768,
    includes_b3_infrastructure=True,
    labels=("NON-PRODUCTION", "NON-EIP-170-DEPLOYABLE-AS-BUILT",
            "PRIVACY-EVALUATION-ONLY"),
    description="local evaluation chain with anvil --code-size-limit 32768 so the "
                "frozen, unmodified B3 contracts deploy; identical setup (W1 + B3 "
                "infrastructure) for every baseline run on this profile")

PROFILES = {p.profile_id: p for p in (STANDARD, B3_COMPAT)}


def get(profile_id: str) -> EvaluationProfile:
    try:
        return PROFILES[profile_id]
    except KeyError:
        raise ValueError(f"unknown evaluation profile {profile_id!r}; "
                         f"known: {sorted(PROFILES)}") from None
