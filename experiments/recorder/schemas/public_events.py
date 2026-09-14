"""public_events.jsonl -- what the declared public observer (A0/A1) can see.

Every field here must be recoverable by someone with an ordinary archive node
and, for A1, ordinary public mempool/RPC visibility of UserOperations. If a
value would require an instrumented bundler it belongs in
``bundler_private.jsonl`` (tier A2) instead; if it is an experiment construct
that answers a linkage question it belongs in ``ground_truth.jsonl``.

Observer-tier rule (docs/threat-model.md): ``observer_tier`` is "A0" or "A1"
only. A2 is rejected in this stream, and A2 rows live in a separate file and
a separate directory, so an A0/A1 dataset cannot silently acquire bundler
knowledge.

ERC-4337 note (recorded ambiguity, not a guess): the fee/gas field set below
follows EntryPoint v0.7/v0.8/v0.9, where the account's gas limits and the
paymaster's are separate and ``paymasterAndData`` is decomposed into
``paymaster`` + ``paymasterVerificationGasLimit`` + ``paymasterPostOpGasLimit``.
The B3 specimen vendored in this repository pins
``@account-abstraction/contracts@0.9.0`` (docs/b3-reproduction.md). For an
EntryPoint v0.6 run the two paymaster gas limits do not exist as separate
fields; record them as null and record the actual version in
``entrypoint_version`` rather than inventing a decomposition.

Tier note (corrected in 2.0.0): a UserOperation that has been *included* is
fully recoverable by an A0 archive-node observer -- every UserOperation field
is in the mined ``handleOps`` calldata and the outcome is in EntryPoint logs
(docs/research-plan.md Sec. 7 lists "on-chain UserOperations" under A0).
Rows derived from mined data are therefore ``observer_tier: "A0"``. ``"A1"``
is only for rows obtained from a *public* UserOperation mempool / RPC before
or without inclusion. A UserOperation submitted to a private bundler and
never included is not public at all and belongs only in
``bundler_private.jsonl``.
"""

from __future__ import annotations

from typing import Any, Mapping

from .. import baselines
from ..fieldtypes import (
    check_address,
    check_bool,
    check_enum,
    check_hash32,
    check_int,
    check_selector,
    check_string,
    check_timestamp,
    check_uint256_string,
    RE_SCENARIO_ID,
)
from .common import (
    CLASS_PUBLIC,
    FieldSpec,
    StreamSchema,
    envelope_fields,
    require_null_fields,
    rule_record_id_matches,
    rule_synthetic_run_id_prefix,
    rule_workload_matches_baseline,
)

STREAM = "public_events"

EVENT_TYPES = (
    "eoa_transaction",          # a plain externally-owned-account transaction
    "native_transfer",          # ETH moved
    "asset_transfer",           # ERC-20/721 Transfer observed in logs
    "account_deployment",       # smart account / factory deployment
    "user_operation_event",     # EntryPoint UserOperationEvent
    "user_operation_revert",    # EntryPoint UserOperationRevertReason
    "paymaster_event",          # paymaster-emitted log (e.g. allowlist change) or its stake/withdraw
    "entrypoint_deposit",       # EntryPoint Deposited log: an account's or paymaster's deposit credited
    "privacy_pool_event",       # commitment insert / root update / nullifier use
)

CALLDATA_CLASSES = (
    "erc20_transfer",
    "erc20_approve",
    "erc721_transfer",
    "native_value_only",
    "account_execute",
    "entrypoint_handle_ops",    # the bundle transaction itself: EntryPoint.handleOps
    "paymaster_policy",         # a paymaster configuration call, e.g. setSponsored
    "account_deploy",
    "paymaster_deposit",
    "pool_deposit",
    "pool_redeem",
    "other",
)

ASSET_TYPES = ("native", "erc20", "erc721", "none")

OUTCOMES = ("success", "reverted", "not_included", "unknown")

REVERT_CLASSES = (
    "out_of_gas",
    "insufficient_balance",
    "insufficient_allowance",
    "aa_validation_failure",
    "paymaster_rejected",
    "target_reverted",
    "other",
)

#: ERC-4337-specific fields. Must all be empty for a baseline that does not
#: use account abstraction at all (B0).
ERC4337_FIELDS = (
    "userop_hash",
    "entrypoint_address",
    "entrypoint_version",
    "factory",
    "max_fee_per_gas",
    "max_priority_fee_per_gas",
    "verification_gas_limit",
    "call_gas_limit",
    "pre_verification_gas",
    "paymaster_verification_gas_limit",
    "paymaster_post_op_gas_limit",
)

#: Paymaster-specific fields. Empty for a baseline with no sponsor (B0/B1).
PAYMASTER_FIELDS = (
    "paymaster",
    "paymaster_verification_gas_limit",
    "paymaster_post_op_gas_limit",
)

#: Publicly visible privacy-protocol artefacts. Empty for a baseline that
#: publishes none (B0/B1/B2).
PRIVACY_ARTIFACT_FIELDS = (
    "commitment",
    "merkle_root",
    "nullifier",
    "pool_id",
    "proof_metadata",
)


def _check_observer_tier(value, *, field, stream):
    check_enum(value, field=field, stream=stream, allowed=("A0", "A1"))


def _check_chain_id_field(value, *, field, stream):
    from ..fieldtypes import check_chain_id
    check_chain_id(value, field=field, stream=stream)


def _check_entrypoint_version(value, *, field, stream):
    check_string(value, field=field, stream=stream,
                 pattern=__import__("re").compile(r"^0\.[0-9]{1,2}\.[0-9]{1,2}$"),
                 code="malformed_entrypoint_version", max_len=16)


def _check_proof_metadata(value, *, field, stream):
    """Publicly visible proof metadata only: sizes, scheme, verifier address.

    Deliberately not a free-form object: an unconstrained bag here would be
    the easiest place for a hidden identifier to arrive under a new name.
    """
    allowed = {"scheme", "verifier_address", "public_signal_count",
               "proof_byte_length", "tree_depth"}
    if not isinstance(value, dict):
        from ..errors import RecordValidationError
        raise RecordValidationError("expected an object", stream=stream,
                                    field=field, code="type_error")
    from ..errors import RecordValidationError
    extra = sorted(set(value) - allowed)
    missing = sorted(allowed - set(value))
    if extra:
        raise RecordValidationError(
            f"unexpected proof_metadata sub-field(s) {extra}; allowed: "
            f"{sorted(allowed)}", stream=stream, field=field,
            code="unknown_field")
    if missing:
        raise RecordValidationError(
            f"missing proof_metadata sub-field(s) {missing}", stream=stream,
            field=field, code="missing_field")
    if value["scheme"] is not None:
        check_enum(value["scheme"], field=f"{field}.scheme", stream=stream,
                   allowed=("groth16", "plonk", "fflonk", "other"))
    if value["verifier_address"] is not None:
        check_address(value["verifier_address"],
                      field=f"{field}.verifier_address", stream=stream)
    for name in ("public_signal_count", "proof_byte_length", "tree_depth"):
        if value[name] is not None:
            check_int(value[name], field=f"{field}.{name}", stream=stream,
                      minimum=0)


def _check_pool_id(value, *, field, stream):
    check_string(value, field=field, stream=stream, pattern=RE_SCENARIO_ID,
                 code="malformed_pool_id", max_len=64)


# --- cross-field rules ------------------------------------------------------


def _rule_baseline_capabilities(record: Mapping[str, Any], stream: str) -> None:
    caps = baselines.get(record["baseline_id"])

    if not caps.uses_erc4337:
        require_null_fields(
            record, stream, ERC4337_FIELDS,
            f"baseline {caps.baseline_id} does not use ERC-4337, so no "
            "UserOperation fields may be populated (a fabricated UserOperation "
            "would make B0 look like an AA baseline)")
    if not caps.uses_paymaster:
        require_null_fields(
            record, stream, PAYMASTER_FIELDS,
            f"baseline {caps.baseline_id} has no Paymaster")
    if not caps.publishes_privacy_artifacts:
        require_null_fields(
            record, stream, PRIVACY_ARTIFACT_FIELDS,
            f"baseline {caps.baseline_id} publishes no privacy-protocol "
            "artefacts")


def _rule_inclusion_consistency(record: Mapping[str, Any], stream: str) -> None:
    """An event that was never included must not carry inclusion data."""
    from ..errors import RecordValidationError

    included_fields = ("block_number", "block_hash", "transaction_index",
                       "transaction_hash", "actual_gas_used", "actual_gas_cost",
                       "effective_gas_price")
    if record["outcome"] == "not_included":
        offenders = [f for f in included_fields if record.get(f) is not None]
        if offenders:
            raise RecordValidationError(
                "outcome 'not_included' but inclusion fields "
                f"{sorted(offenders)} are populated",
                stream=stream, field=sorted(offenders)[0],
                code="outcome_inconsistent")
        if record["success"] is not None:
            raise RecordValidationError(
                "outcome 'not_included' means there is no execution result; "
                "success must be null",
                stream=stream, field="success", code="outcome_inconsistent")
    if record["outcome"] == "success" and record["success"] is False:
        raise RecordValidationError(
            "outcome 'success' contradicts success=false", stream=stream,
            field="success", code="outcome_inconsistent")
    if record["outcome"] == "reverted" and record["success"] is True:
        raise RecordValidationError(
            "outcome 'reverted' contradicts success=true", stream=stream,
            field="success", code="outcome_inconsistent")


def _rule_asset_consistency(record: Mapping[str, Any], stream: str) -> None:
    from ..errors import RecordValidationError

    asset_type = record["asset_type"]
    if asset_type == "none":
        for name in ("asset_contract", "asset_amount", "asset_token_id"):
            if record[name] is not None:
                raise RecordValidationError(
                    "asset_type 'none' but asset fields are populated",
                    stream=stream, field=name, code="asset_inconsistent")
    if asset_type == "native" and record["asset_contract"] is not None:
        raise RecordValidationError(
            "native value has no asset contract", stream=stream,
            field="asset_contract", code="asset_inconsistent")
    if asset_type == "erc721" and record["asset_amount"] is not None:
        raise RecordValidationError(
            "ERC-721 transfers carry a token id, not an amount", stream=stream,
            field="asset_amount", code="asset_inconsistent")
    if asset_type == "erc20" and record["asset_token_id"] is not None:
        raise RecordValidationError(
            "ERC-20 transfers carry an amount, not a token id", stream=stream,
            field="asset_token_id", code="asset_inconsistent")


SCHEMA = StreamSchema(
    stream=STREAM,
    is_secret=False,
    fields=envelope_fields(scenario_nullable=True) + (
        FieldSpec("observer_tier", _check_observer_tier, CLASS_PUBLIC, "A0",
                  "Lowest adversary tier that could have obtained this row: "
                  "'A0' for anything derived from mined blocks, transactions, "
                  "logs or archive state -- including included UserOperations, "
                  "whose fields are all in the handleOps calldata; 'A1' only "
                  "for rows obtained from a public UserOperation mempool/RPC. "
                  "'A2' is rejected here -- bundler observations live in a "
                  "separate stream and directory."),
        # --- chain / block ---------------------------------------------------
        FieldSpec("chain_id", _check_chain_id_field, CLASS_PUBLIC, "A0",
                  "EIP-155 chain id as a JSON integer. A string chain id is "
                  "rejected: mixed representations break cross-run joins."),
        FieldSpec("block_number", check_int, CLASS_PUBLIC, "A0",
                  "Block containing the event; null if never included.",
                  nullable=True, options={"minimum": 0}),
        FieldSpec("block_hash", check_hash32, CLASS_PUBLIC, "A0",
                  "Block hash; null if never included.", nullable=True),
        FieldSpec("block_timestamp_utc", check_timestamp, CLASS_PUBLIC, "A0",
                  "Chain time of the containing block. Distinct from "
                  "recorded_at_utc (harness wall clock).", nullable=True),
        FieldSpec("transaction_index", check_int, CLASS_PUBLIC, "A0",
                  "Position of the transaction within its block; part of the "
                  "block-position signal in the D1 attack ladder.",
                  nullable=True, options={"minimum": 0}),
        FieldSpec("log_index", check_int, CLASS_PUBLIC, "A0",
                  "Position of the log within the block, where the row comes "
                  "from a log.", nullable=True, options={"minimum": 0}),
        FieldSpec("transaction_hash", check_hash32, CLASS_PUBLIC, "A0",
                  "Enclosing transaction hash; null if never included.",
                  nullable=True),
        # --- ERC-4337 identity ----------------------------------------------
        FieldSpec("userop_hash", check_hash32, CLASS_PUBLIC, "A0",
                  "EntryPoint UserOperation hash. A0 once included (it is "
                  "indexed in UserOperationEvent). Null for non-AA baselines "
                  "and for rows that are not about a UserOperation.",
                  nullable=True),
        FieldSpec("entrypoint_address", check_address, CLASS_PUBLIC, "A0",
                  "EntryPoint contract the operation targeted.", nullable=True),
        FieldSpec("entrypoint_version", _check_entrypoint_version, CLASS_PUBLIC,
                  "A0",
                  "EntryPoint semantic version, e.g. '0.9.0'. Recorded per row "
                  "because gas accounting and the field set differ across "
                  "versions.", nullable=True),
        FieldSpec("factory", check_address, CLASS_PUBLIC, "A0",
                  "Account factory from initCode, where the operation deployed "
                  "the account.", nullable=True),
        # --- addresses -------------------------------------------------------
        FieldSpec("sender", check_address, CLASS_PUBLIC, "A0",
                  "The account the operation/transaction originates from. For "
                  "an AA row this is the smart account, not the bundler EOA.",
                  nullable=True),
        FieldSpec("paymaster", check_address, CLASS_PUBLIC, "A0",
                  "Sponsoring Paymaster. Null where the baseline has none -- "
                  "for B1 this is null by construction, not merely unknown.",
                  nullable=True),
        FieldSpec("target", check_address, CLASS_PUBLIC, "A0",
                  "Contract or account the application action addresses.",
                  nullable=True),
        FieldSpec("subject_account", check_address, CLASS_PUBLIC, "A0",
                  "Account an on-chain event is about when it is neither the "
                  "row's sender nor its target: the account named in a "
                  "Paymaster allowlist log, or the account credited by an "
                  "EntryPoint Deposited log. Added in 2.0.0 because an "
                  "ordinary allowlist Paymaster publishes the sponsored "
                  "account before the operation, and the 1.0.0 schema had "
                  "nowhere to record it.", nullable=True),
        FieldSpec("bundler_beneficiary", check_address, CLASS_PUBLIC, "A0",
                  "Beneficiary address paid by the EntryPoint. Public on "
                  "chain -- this is NOT bundler-private data.", nullable=True),
        # --- call ------------------------------------------------------------
        FieldSpec("method_selector", check_selector, CLASS_PUBLIC, "A0",
                  "4-byte selector of the public call.", nullable=True),
        FieldSpec("calldata_class", check_enum, CLASS_PUBLIC, "A0",
                  "Coarse class of the public calldata. A class rather than "
                  "raw calldata so the field cannot become a dumping ground.",
                  nullable=True, options={"allowed": CALLDATA_CLASSES}),
        FieldSpec("nonce", check_uint256_string, CLASS_PUBLIC, "A0",
                  "Account nonce as a decimal uint256 string. For ERC-4337 "
                  "v0.7+ this is the full 256-bit key||sequence value, which "
                  "is why it is a string and not a JSON number.", nullable=True),
        # --- asset -----------------------------------------------------------
        FieldSpec("asset_type", check_enum, CLASS_PUBLIC, "A0",
                  "Kind of value moved by this event.",
                  options={"allowed": ASSET_TYPES}),
        FieldSpec("asset_contract", check_address, CLASS_PUBLIC, "A0",
                  "Token contract; null for native value.", nullable=True),
        FieldSpec("asset_amount", check_uint256_string, CLASS_PUBLIC, "A0",
                  "Amount in base units as a decimal uint256 string.",
                  nullable=True),
        FieldSpec("asset_token_id", check_uint256_string, CLASS_PUBLIC, "A0",
                  "ERC-721 token id as a decimal uint256 string.",
                  nullable=True),
        FieldSpec("amount_bucket", check_string, CLASS_PUBLIC, "A0",
                  "Derived coarse bucket of asset_amount. Always null at "
                  "recording time: bucketing is an analysis decision and is "
                  "computed downstream so the boundaries are visible in the "
                  "analysis code, not frozen into the raw record.",
                  nullable=True,
                  options={"pattern": RE_SCENARIO_ID,
                           "code": "malformed_amount_bucket", "max_len": 64}),
        # --- fee / gas -------------------------------------------------------
        FieldSpec("max_fee_per_gas", check_uint256_string, CLASS_PUBLIC, "A0",
                  "UserOperation maxFeePerGas, wei, decimal string.",
                  nullable=True),
        FieldSpec("max_priority_fee_per_gas", check_uint256_string, CLASS_PUBLIC,
                  "A0", "UserOperation maxPriorityFeePerGas, wei.",
                  nullable=True),
        FieldSpec("verification_gas_limit", check_uint256_string, CLASS_PUBLIC,
                  "A0", "UserOperation verificationGasLimit.", nullable=True),
        FieldSpec("call_gas_limit", check_uint256_string, CLASS_PUBLIC, "A0",
                  "UserOperation callGasLimit.", nullable=True),
        FieldSpec("pre_verification_gas", check_uint256_string, CLASS_PUBLIC,
                  "A0", "UserOperation preVerificationGas.", nullable=True),
        FieldSpec("paymaster_verification_gas_limit", check_uint256_string,
                  CLASS_PUBLIC, "A0",
                  "EntryPoint v0.7+ paymasterVerificationGasLimit. Null under "
                  "v0.6, where paymasterAndData is not decomposed.",
                  nullable=True),
        FieldSpec("paymaster_post_op_gas_limit", check_uint256_string,
                  CLASS_PUBLIC, "A0",
                  "EntryPoint v0.7+ paymasterPostOpGasLimit. Null under v0.6.",
                  nullable=True),
        # --- execution result -------------------------------------------------
        FieldSpec("actual_gas_used", check_uint256_string, CLASS_PUBLIC, "A0",
                  "Gas actually consumed. For a user_operation_event row this "
                  "is UserOperationEvent.actualGasUsed (includes "
                  "preVerificationGas and any unused-gas penalty) and differs "
                  "from the enclosing bundle transaction's receipt gasUsed, "
                  "which is recorded on the entrypoint_handle_ops row.", nullable=True),
        FieldSpec("actual_gas_cost", check_uint256_string, CLASS_PUBLIC, "A0",
                  "Wei actually charged. For a user_operation_event row this is "
                  "UserOperationEvent.actualGasCost (a transfer from the payer's "
                  "EntryPoint deposit to the beneficiary); for a transaction "
                  "row it is gasUsed * effectiveGasPrice.", nullable=True),
        FieldSpec("effective_gas_price", check_uint256_string, CLASS_PUBLIC,
                  "A0", "Effective gas price of the enclosing transaction, wei.",
                  nullable=True),
        FieldSpec("success", check_bool, CLASS_PUBLIC, "A0",
                  "Execution result. Null where the operation was never "
                  "included. A failed operation is kept, never dropped.",
                  nullable=True),
        FieldSpec("revert_reason_class", check_enum, CLASS_PUBLIC, "A0",
                  "Coarse class of the public revert reason. A class rather "
                  "than the raw string, which can carry arbitrary content.",
                  nullable=True, options={"allowed": REVERT_CLASSES}),
        FieldSpec("outcome", check_enum, CLASS_PUBLIC, "A0",
                  "Overall disposition of the row's subject.",
                  options={"allowed": OUTCOMES}),
        FieldSpec("event_type", check_enum, CLASS_PUBLIC, "A0",
                  "What kind of observation this row is.",
                  options={"allowed": EVENT_TYPES}),
        # --- privacy protocol, public parts only ------------------------------
        FieldSpec("commitment", check_hash32, CLASS_PUBLIC, "A0",
                  "Publicly emitted commitment, 0x 32-byte hex. Public because "
                  "it is on chain -- recording it makes no claim that it is "
                  "unlinkable.", nullable=True),
        FieldSpec("merkle_root", check_hash32, CLASS_PUBLIC, "A0",
                  "Publicly visible Merkle root the operation proved against.",
                  nullable=True),
        FieldSpec("nullifier", check_hash32, CLASS_PUBLIC, "A0",
                  "Publicly emitted nullifier.", nullable=True),
        FieldSpec("pool_id", _check_pool_id, CLASS_PUBLIC, "A0",
                  "Public pool / group identifier.", nullable=True),
        FieldSpec("proof_metadata", _check_proof_metadata, CLASS_PUBLIC, "A0",
                  "Publicly visible proof metadata (scheme, verifier, sizes). "
                  "Closed sub-schema on purpose.", nullable=True),
    ),
    cross_field_rules=(
        rule_synthetic_run_id_prefix,
        rule_workload_matches_baseline,
        rule_record_id_matches,
        _rule_baseline_capabilities,
        _rule_inclusion_consistency,
        _rule_asset_consistency,
    ),
)
