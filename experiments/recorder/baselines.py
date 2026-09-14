"""Per-baseline capability declarations.

These are *structural* facts about each baseline as defined in
docs/research-plan.md Sec. 5 and docs/baseline-spec.md. The validator uses them
to reject records that claim machinery a baseline does not have — e.g. a
bundler observation for B0, which has no bundler at all (Prompt 3 Sec. 9:
"If B0 does not use a bundler, it should not generate fake bundler
observations").

This table describes the *baselines*; it does not describe the mechanism a
baseline uses and makes no claim about any baseline's privacy properties.

Status caveat: at the time this table was written only B3 exists in
``baselines/``. B0-B2 and B4-B6 rows encode the specification in
docs/research-plan.md Sec. 5, not observed implementations. If an implemented
baseline turns out to differ, the fix is to update this table together with a
docs/decision-log.md entry, not to relax the validator ad hoc.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class BaselineCapabilities:
    baseline_id: str
    #: Executes the application action through an ERC-4337 UserOperation.
    uses_erc4337: bool
    #: Operations pass through a bundler we can instrument (enables A2 data).
    uses_bundler: bool
    #: A Paymaster sponsors gas (observable or otherwise).
    uses_paymaster: bool
    #: Has a credit/note issuance+redemption lifecycle, i.e. relation R2 is
    #: defined at all for this baseline.
    uses_credit_system: bool
    #: Publishes privacy-protocol artefacts on chain (commitment / root /
    #: nullifier / pool identifier).
    publishes_privacy_artifacts: bool
    description: str
    #: False where the row encodes docs/research-plan.md Sec. 5 rather than an
    #: implementation that exists in this repository today.
    implemented_in_repo: bool


_TABLE: Dict[str, BaselineCapabilities] = {
    "B0": BaselineCapabilities(
        "B0", False, False, False, False, False,
        "Sender-funded fresh stealth EOA; plain transaction, no account "
        "abstraction and no sponsor.",
        implemented_in_repo=False,
    ),
    "B1": BaselineCapabilities(
        "B1", True, True, False, False, False,
        "Sender-funded ERC-4337 smart account; same application action as B0, "
        "self-funded native balance, no Paymaster.",
        implemented_in_repo=False,
    ),
    "B2": BaselineCapabilities(
        "B2", True, True, True, False, False,
        "Ordinary, fully observable Paymaster sponsoring the same operation as "
        "B1 with no privacy mechanism.",
        implemented_in_repo=False,
    ),
    "B3": BaselineCapabilities(
        "B3", True, True, True, True, True,
        "PrivGas v1 as published, frozen specimen "
        "(baselines/b3_privgas_v1, see docs/b3-reproduction.md).",
        implemented_in_repo=True,
    ),
    "B4": BaselineCapabilities(
        "B4", True, True, True, True, True,
        "Independently issued anonymous credit (issuance decoupled from the "
        "stealth account). Not implemented; reserved.",
        implemented_in_repo=False,
    ),
    "B5": BaselineCapabilities(
        "B5", True, True, True, True, True,
        "Prior-art prepaid / Semaphore Paymaster reconstruction. Not "
        "implemented; reserved.",
        implemented_in_repo=False,
    ),
    "B6": BaselineCapabilities(
        "B6", False, False, False, True, True,
        "Optional shielded-pool / relayer reference. Not implemented; "
        "capability flags are provisional and must be confirmed against a "
        "concrete implementation before use.",
        implemented_in_repo=False,
    ),
}

BASELINE_IDS = tuple(sorted(_TABLE))


def get(baseline_id: str) -> BaselineCapabilities:
    try:
        return _TABLE[baseline_id]
    except KeyError:
        raise KeyError(
            f"unknown baseline_id {baseline_id!r}; known: {', '.join(BASELINE_IDS)}"
        ) from None


def is_known(baseline_id: object) -> bool:
    return isinstance(baseline_id, str) and baseline_id in _TABLE
