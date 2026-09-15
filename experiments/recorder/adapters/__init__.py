"""Baseline adapters: normalised observations -> schema-valid records.

An adapter is a pure, deterministic function from an ``Observation`` -- the
documented hand-off contract in ``adapters.base`` -- to a stream record. It
contains no clock, no network and no chain access, so replaying the same raw
logs through the same adapter reproduces the same rows.

Why adapters exist at all: the recorder observes the experiment, it does not
redesign it (Prompt 3 Sec. 18). A baseline runner dumps whatever its tooling
gives it into ``data/raw/``; the adapter is the one place that knows how to
map that onto the schema and which fields that baseline is structurally
forbidden from populating.

Available: B0 (sender-funded EOA), B1 (sender-funded smart account),
B2-Allowlist (auxiliary public-allowlist Paymaster) and B2-Signature
(signature-verifying Paymaster) and B3-PrivGas-v1 (the frozen PrivGas v1
specimen; adapter ``b3_privgas_v1``). B4/B5 are out of scope.
"""

from .b0_sender_eoa import B0Adapter  # noqa: F401
from .b1_sender_aa import B1Adapter  # noqa: F401
from .b2_public_paymaster import B2AllowlistAdapter, B2SignatureAdapter  # noqa: F401
from .b3_privgas_v1 import B3PrivGasV1Adapter  # noqa: F401
from .base import (  # noqa: F401
    BaselineAdapter,
    BundlerObservation,
    GroundTruth,
    Observation,
    RelationLabel,
    UserOpObservation,
)

__all__ = [
    "BaselineAdapter", "Observation", "UserOpObservation",
    "BundlerObservation", "GroundTruth", "RelationLabel",
    "B0Adapter", "B1Adapter", "B2AllowlistAdapter", "B2SignatureAdapter",
    "B3PrivGasV1Adapter", "ADAPTERS", "for_baseline",
]

ADAPTERS = {
    "B0": B0Adapter,
    "B1": B1Adapter,
    "B2-Allowlist": B2AllowlistAdapter,
    "B2-Signature": B2SignatureAdapter,
    "B3-PrivGas-v1": B3PrivGasV1Adapter,
}


def for_baseline(baseline_id: str):
    try:
        return ADAPTERS[baseline_id]
    except KeyError:
        raise KeyError(
            f"no adapter for baseline {baseline_id!r}; available: "
            f"{sorted(ADAPTERS)}. Adding one means subclassing "
            "BaselineAdapter, not widening the schema."
        ) from None
