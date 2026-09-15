"""The adapter hand-off contract.

A baseline runner produces ``Observation`` objects. It does not produce JSON,
does not know about the envelope, and does not know where files live. That
separation is what lets B0-B5 share one recorder.

The two dataclasses below are deliberately flat and optional-heavy: they
mirror what a runner can actually read back from a receipt, a log, or a
bundler RPC, with ``None`` meaning "not observed". Turning ``None`` into the
right schema value -- ``null`` where the field exists but was not observed,
``"not_applicable"`` where the concept does not exist for the baseline -- is
the adapter's job, and the validator then checks the result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from .. import baselines
from ..schemas.public_events import derive_trace_phase


@dataclass
class Observation:
    """One attacker-visible event, as a baseline runner sees it.

    All uint256-domain values are passed as Python ``int`` here and converted
    to decimal strings by the adapter; that keeps the runner from having to
    remember the representation rule.
    """

    event_type: str
    outcome: str
    #: Content-derived public classification; None = derive the default from
    #: event_type/calldata_class (schemas.public_events.derive_trace_phase).
    trace_phase: Optional[str] = None
    asset_type: str = "none"
    scenario_id: Optional[str] = None
    observer_tier: str = "A0"

    block_number: Optional[int] = None
    block_hash: Optional[str] = None
    block_timestamp_utc: Optional[str] = None
    transaction_index: Optional[int] = None
    log_index: Optional[int] = None
    transaction_hash: Optional[str] = None

    sender: Optional[str] = None
    target: Optional[str] = None
    subject_account: Optional[str] = None
    paymaster: Optional[str] = None
    bundler_beneficiary: Optional[str] = None

    method_selector: Optional[str] = None
    calldata_class: Optional[str] = None
    nonce: Optional[int] = None

    asset_contract: Optional[str] = None
    asset_amount: Optional[int] = None
    asset_token_id: Optional[int] = None

    actual_gas_used: Optional[int] = None
    actual_gas_cost: Optional[int] = None
    effective_gas_price: Optional[int] = None
    success: Optional[bool] = None
    revert_reason_class: Optional[str] = None

    #: Populated only by baselines that run through an EntryPoint.
    userop: Optional["UserOpObservation"] = None

    #: Populated only by baselines that publish privacy artefacts.
    commitment: Optional[str] = None
    merkle_root: Optional[str] = None
    nullifier: Optional[str] = None
    pool_id: Optional[str] = None
    proof_metadata: Optional[Mapping[str, Any]] = None


@dataclass
class UserOpObservation:
    """The publicly visible parts of a UserOperation.

    Field set follows EntryPoint v0.7+. Under v0.6 the two paymaster gas
    limits do not exist as separate values; leave them ``None`` and set
    ``entrypoint_version`` accordingly rather than splitting
    ``paymasterAndData`` by guesswork.
    """

    userop_hash: str
    entrypoint_address: str
    entrypoint_version: str
    max_fee_per_gas: int
    max_priority_fee_per_gas: int
    verification_gas_limit: int
    call_gas_limit: int
    pre_verification_gas: int
    factory: Optional[str] = None
    paymaster_verification_gas_limit: Optional[int] = None
    paymaster_post_op_gas_limit: Optional[int] = None


@dataclass
class BundlerObservation:
    """One instrumented-bundler observation (tier A2)."""

    bundler_id: str
    userop_hash: str
    sender: str
    nonce: int
    receive_timestamp_utc: str
    simulation_result: str
    submission_attempt: int = 1
    scenario_id: Optional[str] = None
    simulation_timestamp_utc: Optional[str] = None
    rejection_category: Optional[str] = None
    rejection_message_class: Optional[str] = None
    replacement_lineage: Optional[List[str]] = None
    inclusion_timestamp_utc: Optional[str] = None
    bundle_submission_timestamp_utc: Optional[str] = None
    #: Pre-inclusion association only; the mined hash is public (public_events).
    submitted_bundle_transaction_hash: Optional[str] = None
    rpc_endpoint_id: Optional[str] = None


@dataclass
class RelationLabel:
    relation: str
    status: str
    subject_ref: Optional[str] = None
    true_value: Optional[str] = None
    candidate_set_id: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "relation": self.relation,
            "status": self.status,
            "subject_ref": self.subject_ref,
            "true_value": self.true_value,
            "candidate_set_id": self.candidate_set_id,
        }


@dataclass
class GroundTruth:
    """One secret ground-truth row, as the experiment designer knows it.

    ``actor_id`` is the person. The account fields are accounts. Several rows
    may share one ``actor_id`` and that is the normal case, not an anomaly:
    nothing here or downstream may treat distinct accounts, or distinct
    credits, as evidence of distinct participants.
    """

    scenario_id: str
    subject_kind: str
    r1: RelationLabel
    r2: RelationLabel
    r3: RelationLabel
    actor_id: Optional[str] = None
    established_wallet_id: Optional[str] = None
    #: R1's hidden answer: the wallet whose ETH funded the gas-paying balance.
    economic_funding_source_id: Optional[str] = None
    #: Public context: which balance the mechanism charged (see ground_truth).
    immediate_gas_payer_kind: Optional[str] = None
    asset_sender_id: Optional[str] = None
    stealth_account_id: Optional[str] = None
    credit_id: Optional[str] = None
    issuance_id: Optional[str] = None
    public_anchors: Mapping[str, Any] = field(default_factory=dict)


def _u(value: Optional[int]) -> Optional[str]:
    """uint256 domain -> decimal string (see fieldtypes numeric rule)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"expected an int for a uint256-domain value, got {value!r}")
    if value < 0:
        raise ValueError(f"uint256-domain value cannot be negative: {value}")
    return str(value)


def _a(value: Optional[str]) -> Optional[str]:
    """Address -> canonical lowercase spelling (schema 2.0.0 address rule).

    Checksummed (EIP-55) and lowercase spellings of one account must never
    appear side by side: every join in the analysis compares strings.
    """
    return value.lower() if isinstance(value, str) else value


EMPTY_ANCHORS = {
    "stealth_account_address": None,
    "economic_funding_address": None,
    "immediate_gas_payer_address": None,
    "asset_sender_address": None,
    "established_wallet_address": None,
    "transaction_hash": None,
    "userop_hash": None,
    "public_event_record_ids": [],
}


class BaselineAdapter:
    """Base class. Subclasses declare a baseline id and nothing else, unless
    the baseline genuinely observes something the base class cannot express.
    """

    baseline_id: str = ""

    def __init__(self) -> None:
        if not self.baseline_id:
            raise TypeError("BaselineAdapter subclasses must set baseline_id")
        self.caps = baselines.get(self.baseline_id)

    # --- public events -------------------------------------------------------

    def public_event(self, obs: Observation) -> Dict[str, Any]:
        """Map one Observation onto a public_events record body."""
        self._reject_impossible(obs)
        uo = obs.userop
        return {
            "scenario_id": obs.scenario_id,
            "observer_tier": obs.observer_tier,
            "chain_id": self.chain_id,
            "block_number": obs.block_number,
            "block_hash": obs.block_hash,
            "block_timestamp_utc": obs.block_timestamp_utc,
            "transaction_index": obs.transaction_index,
            "log_index": obs.log_index,
            "transaction_hash": obs.transaction_hash,
            "userop_hash": uo.userop_hash if uo else None,
            "entrypoint_address": _a(uo.entrypoint_address) if uo else None,
            "entrypoint_version": uo.entrypoint_version if uo else None,
            "factory": _a(uo.factory) if uo else None,
            "sender": _a(obs.sender),
            "paymaster": _a(obs.paymaster),
            "target": _a(obs.target),
            "subject_account": _a(obs.subject_account),
            "bundler_beneficiary": _a(obs.bundler_beneficiary),
            "method_selector": obs.method_selector,
            "calldata_class": obs.calldata_class,
            "nonce": _u(obs.nonce),
            "asset_type": obs.asset_type,
            "asset_contract": _a(obs.asset_contract),
            "asset_amount": _u(obs.asset_amount),
            "asset_token_id": _u(obs.asset_token_id),
            # Bucketing is an analysis decision made downstream, where the
            # boundaries are visible in the analysis code.
            "amount_bucket": None,
            "max_fee_per_gas": _u(uo.max_fee_per_gas) if uo else None,
            "max_priority_fee_per_gas": (
                _u(uo.max_priority_fee_per_gas) if uo else None),
            "verification_gas_limit": (
                _u(uo.verification_gas_limit) if uo else None),
            "call_gas_limit": _u(uo.call_gas_limit) if uo else None,
            "pre_verification_gas": _u(uo.pre_verification_gas) if uo else None,
            "paymaster_verification_gas_limit": (
                _u(uo.paymaster_verification_gas_limit) if uo else None),
            "paymaster_post_op_gas_limit": (
                _u(uo.paymaster_post_op_gas_limit) if uo else None),
            "actual_gas_used": _u(obs.actual_gas_used),
            "actual_gas_cost": _u(obs.actual_gas_cost),
            "effective_gas_price": _u(obs.effective_gas_price),
            "success": obs.success,
            "revert_reason_class": obs.revert_reason_class,
            "outcome": obs.outcome,
            "event_type": obs.event_type,
            "trace_phase": obs.trace_phase or derive_trace_phase(
                obs.event_type, obs.calldata_class),
            "commitment": obs.commitment,
            "merkle_root": obs.merkle_root,
            "nullifier": obs.nullifier,
            "pool_id": obs.pool_id,
            "proof_metadata": dict(obs.proof_metadata) if obs.proof_metadata
            else None,
        }

    # --- bundler private -----------------------------------------------------

    def bundler_private(self, obs: BundlerObservation) -> Dict[str, Any]:
        if not self.caps.uses_bundler:
            raise ValueError(
                f"baseline {self.baseline_id} has no bundler; it cannot produce "
                "A2 observations")
        lineage = (list(obs.replacement_lineage)
                   if obs.replacement_lineage is not None else None)
        return {
            "scenario_id": obs.scenario_id,
            "observer_tier": "A2",
            "bundler_id": obs.bundler_id,
            "userop_hash": obs.userop_hash,
            "sender": _a(obs.sender),
            "nonce": _u(obs.nonce),
            "submission_attempt": obs.submission_attempt,
            "receive_timestamp_utc": obs.receive_timestamp_utc,
            "simulation_timestamp_utc": obs.simulation_timestamp_utc,
            "simulation_result": obs.simulation_result,
            "rejection_category": obs.rejection_category,
            "rejection_message_class": obs.rejection_message_class,
            "replacement_lineage": lineage,
            "replacement_count": len(lineage) if lineage is not None else None,
            "inclusion_timestamp_utc": obs.inclusion_timestamp_utc,
            "bundle_submission_timestamp_utc": obs.bundle_submission_timestamp_utc,
            "submitted_bundle_transaction_hash": obs.submitted_bundle_transaction_hash,
            "rpc_endpoint_id": obs.rpc_endpoint_id,
        }

    # --- ground truth --------------------------------------------------------

    def ground_truth(self, gt: GroundTruth) -> Dict[str, Any]:
        na = "not_applicable"
        credit_id = gt.credit_id
        issuance_id = gt.issuance_id
        if not self.caps.uses_credit_system:
            # The concept does not exist for this baseline. That is a stronger
            # and different statement than "unknown", so it gets the sentinel
            # rather than null.
            credit_id = na
            issuance_id = na

        anchors = dict(EMPTY_ANCHORS)
        anchors.update(gt.public_anchors)
        for key in ("stealth_account_address", "economic_funding_address",
                    "immediate_gas_payer_address",
                    "asset_sender_address", "established_wallet_address"):
            anchors[key] = _a(anchors[key])

        return {
            "scenario_id": gt.scenario_id,
            "subject_kind": gt.subject_kind,
            "actor_id": gt.actor_id,
            "established_wallet_id": gt.established_wallet_id,
            "economic_funding_source_id": gt.economic_funding_source_id,
            "immediate_gas_payer_kind": gt.immediate_gas_payer_kind,
            "asset_sender_id": gt.asset_sender_id,
            "stealth_account_id": gt.stealth_account_id,
            "credit_id": credit_id,
            "issuance_id": issuance_id,
            "payer_to_operation_label": gt.r1.as_dict(),
            "issuance_to_redemption_label": gt.r2.as_dict(),
            "stealth_to_actor_label": gt.r3.as_dict(),
            "public_anchors": anchors,
        }

    # --- guards --------------------------------------------------------------

    chain_id: int = 31337

    def _reject_impossible(self, obs: Observation) -> None:
        """Fail loudly in the adapter, before the validator has to.

        The validator would catch these too, but an adapter-level error names
        the baseline and the reason, which is the message a runner author
        needs.
        """
        if obs.userop is not None and not self.caps.uses_erc4337:
            raise ValueError(
                f"baseline {self.baseline_id} does not use ERC-4337 "
                f"({self.caps.description}); it has no UserOperation to record")
        if obs.paymaster is not None and not self.caps.uses_paymaster:
            raise ValueError(
                f"baseline {self.baseline_id} has no Paymaster; recording one "
                "would misrepresent the baseline")
        artefacts = (obs.commitment, obs.merkle_root, obs.nullifier,
                     obs.pool_id, obs.proof_metadata)
        if any(a is not None for a in artefacts) \
                and not self.caps.publishes_privacy_artifacts:
            raise ValueError(
                f"baseline {self.baseline_id} publishes no privacy-protocol "
                "artefacts")


def bind_chain_id(adapter: BaselineAdapter, chain_id: int) -> BaselineAdapter:
    adapter.chain_id = chain_id
    return adapter
