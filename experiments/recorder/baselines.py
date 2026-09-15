"""Per-baseline capability declarations.

These are *structural* facts about each baseline as defined in
docs/research-plan.md Sec. 5 and docs/baseline-spec.md. The validator uses them
to reject records that claim machinery a baseline does not have — e.g. a
bundler observation for B0, which has no bundler at all (Prompt 3 Sec. 9:
"If B0 does not use a bundler, it should not generate fake bundler
observations").

This table describes the *baselines*; it does not describe the mechanism a
baseline uses and makes no claim about any baseline's privacy properties.

Status: B0, B1, B2-Allowlist and B2-Signature are implemented in ``baselines/w1_b0_b2`` (runner:
``experiments/workloads/w1``) and their rows were confirmed against real runs
on 2026-09-14 -- the capability flags held; see docs/w1-baselines.md.
B3-PrivGas-v1 is the frozen specimen ``baselines/b3_privgas_v1``, measured
unmodified on the ``b3_compat_local`` evaluation profile (docs/b3-evaluation.md);
its row was confirmed against those real runs (schema 5.0.0). B4-B6 rows still encode docs/research-plan.md Sec. 5, not an
implementation. If an implemented baseline turns out to differ, the fix is to
update this table together with a docs/decision-log.md entry, not to relax
the validator ad hoc.
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
        "abstraction and no sponsor (baselines/w1_b0_b2).",
        implemented_in_repo=True,
    ),
    "B1": BaselineCapabilities(
        "B1", True, True, False, False, False,
        "Sender-funded ERC-4337 smart account (eth-infinitism SimpleAccount "
        "v0.9.0); same application action as B0, sender-supplied native "
        "prefund, no Paymaster (baselines/w1_b0_b2).",
        implemented_in_repo=True,
    ),
    # Schema 3.0.0: the former single "B2" is split. The two ordinary
    # Paymaster designs leak different public relationships and must never
    # share a baseline_id.
    "B2-Allowlist": BaselineCapabilities(
        "B2-Allowlist", True, True, True, False, False,
        "AUXILIARY ordinary Paymaster with a public on-chain allowlist: a "
        "setSponsored(account,true) transaction links sponsor and account "
        "before the operation. Same operation as B1 (baselines/w1_b0_b2).",
        implemented_in_repo=True,
    ),
    "B2-Signature": BaselineCapabilities(
        "B2-Signature", True, True, True, False, False,
        "Ordinary signature-verifying Paymaster: sponsors an operation "
        "carrying the sponsor's ECDSA signature over the EntryPoint v0.9.0 "
        "userOpHash; no on-chain per-account authorization. Same operation as "
        "B1 (baselines/w1_b0_b2).",
        implemented_in_repo=True,
    ),
    # Schema 5.0.0: renamed from "B3". The id names the UNMODIFIED specimen at
    # commit 02a3f0abdb979446545aa87149080bfb44e43a3e; a changed protocol would
    # need a new id.
    "B3-PrivGas-v1": BaselineCapabilities(
        "B3-PrivGas-v1", True, True, True, True, True,
        "PrivGas v1 frozen specimen (baselines/b3_privgas_v1 @ 02a3f0ab, unmodified): "
        "AnnouncementRegistry fund, BootstrapPaymaster-sponsored CreditPool deposit, "
        "CreditPaymaster-sponsored spend with a real Semaphore v4 / Groth16 proof. "
        "Evaluated only on the NON-PRODUCTION b3_compat_local profile (frozen "
        "PoseidonT3 exceeds EIP-170; docs/b3-reproduction.md, docs/b3-evaluation.md).",
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

#: Workloads and which baselines may run them. W1-warm is an AA-only
#: ablation (the smart account is deployed before the measured action);
#: a plain EOA has nothing to pre-deploy.
WORKLOAD_IDS = ("W1-cold", "W1-warm", "W2", "W3", "W4")
ERC4337_ONLY_WORKLOADS = ("W1-warm",)


def get(baseline_id: str) -> BaselineCapabilities:
    try:
        return _TABLE[baseline_id]
    except KeyError:
        raise KeyError(
            f"unknown baseline_id {baseline_id!r}; known: {', '.join(BASELINE_IDS)}"
        ) from None


def is_known(baseline_id: object) -> bool:
    return isinstance(baseline_id, str) and baseline_id in _TABLE
