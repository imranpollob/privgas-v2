"""bundler_private.jsonl -- observations from an instrumented bundler (A2).

Only for a bundler or RPC service we operate, or have written permission to
log (docs/threat-model.md, A2). These values are NOT public: nothing in this
stream may be assumed known to an A0/A1 observer, and this stream is written
to its own directory so an A0/A1 dataset cannot accidentally include it.

Two hard rules the validator enforces:

* A baseline with no bundler produces no rows here at all. B0 executes a
  plain transaction; it has no mempool admission, no simulation and no
  replacement lineage, and inventing rows to make the schema look uniform
  would fabricate data.
* Fields are never filled in with placeholder values to satisfy the schema.
  A value that was not observed is ``null``, and the schema says so
  explicitly; a concept that does not exist for the baseline is
  ``"not_applicable"``.

Recorded ERC-4337 ambiguity (not guessed): "rejection" spans at least three
distinct situations -- a bundler-local policy/reputation drop (ERC-7562
throttling), a ``simulateValidation`` revert, and an operation that simulated
cleanly but failed on-chain inclusion. ``simulation_result`` and
``rejection_category`` distinguish the first two; the third appears as an
included-but-failed row in ``public_events``. Where a bundler implementation
does not let us tell these apart, ``rejection_category`` is "other" and
``rejection_message_class`` records which coarse class the bundler reported.
Do not collapse them.
"""

from __future__ import annotations

from typing import Any, Mapping

from .. import baselines
from ..errors import RecordValidationError
from ..fieldtypes import (
    RE_SCENARIO_ID,
    check_address,
    check_enum,
    check_hash32,
    check_int,
    check_string,
    check_timestamp,
    check_uint256_string,
)
from .common import (
    CLASS_BUNDLER,
    FieldSpec,
    StreamSchema,
    envelope_fields,
    rule_record_id_matches,
    rule_synthetic_run_id_prefix,
    rule_workload_matches_baseline,
    rule_baseline_exists_in_schema_version,
)

STREAM = "bundler_private"

SIMULATION_RESULTS = ("accepted", "rejected", "error", "not_simulated")

REJECTION_CATEGORIES = (
    "aa_validation_revert",      # account/factory validation reverted (AA1x/AA2x)
    "paymaster_validation_revert",  # paymaster validation reverted (AA3x except AA31)
    "insufficient_prefund",      # payer cannot cover the prefund (AA21 account, AA31 paymaster)
    "opcode_rule_violation",     # ERC-7562 forbidden opcode
    "storage_rule_violation",    # ERC-7562 storage access rule
    "stale_root",                # proof built against a root no longer accepted
    "nullifier_already_used",
    "fee_too_low",
    "nonce_conflict",
    "throttled_or_banned",       # bundler-local reputation decision
    "timeout",
    "other",
)

#: Coarse classes only. The raw bundler message is deliberately not recorded:
#: implementations embed addresses, calldata and internal state in error
#: strings, which would move uncontrolled content into an attacker-readable
#: stream.
REJECTION_MESSAGE_CLASSES = (
    "entrypoint_revert",
    "bundler_policy",
    "rpc_transport",
    "internal_error",
    "unclassified",
)


def _check_observer_tier(value, *, field, stream):
    check_enum(value, field=field, stream=stream, allowed=("A2",))


def _check_bundler_id(value, *, field, stream):
    check_string(value, field=field, stream=stream, pattern=RE_SCENARIO_ID,
                 code="malformed_bundler_id", max_len=64)


def _check_replacement_lineage(value, *, field, stream):
    """Ordered list of prior userop hashes this operation replaced.

    Empty list means "observed, and there was no replacement". That is a
    different statement from null, which would mean "we did not observe the
    lineage at all".
    """
    if not isinstance(value, list):
        raise RecordValidationError(
            "expected a list of prior userop hashes (possibly empty)",
            stream=stream, field=field, code="type_error")
    if len(value) > 256:
        raise RecordValidationError("lineage longer than 256 entries",
                                    stream=stream, field=field, code="too_long")
    for i, item in enumerate(value):
        check_hash32(item, field=f"{field}[{i}]", stream=stream)


def _rule_baseline_has_bundler(record: Mapping[str, Any], stream: str) -> None:
    caps = baselines.get(record["baseline_id"])
    if not caps.uses_bundler:
        raise RecordValidationError(
            f"baseline {caps.baseline_id} has no bundler ({caps.description}), "
            "so it cannot produce bundler-private observations. Emitting a row "
            "here would fabricate A2 data for a baseline that never reaches a "
            "mempool.",
            stream=stream, field="baseline_id",
            code="baseline_capability_violation")


def _rule_simulation_consistency(record: Mapping[str, Any],
                                 stream: str) -> None:
    result = record["simulation_result"]
    category = record["rejection_category"]

    if result == "rejected" and category is None:
        raise RecordValidationError(
            "simulation_result 'rejected' requires a rejection_category; "
            "rejection reason distribution is a reported liveness metric "
            "(docs/research-plan.md Sec. 9.3) and must not be discarded",
            stream=stream, field="rejection_category",
            code="rejection_inconsistent")
    if result == "accepted" and category is not None:
        raise RecordValidationError(
            "simulation_result 'accepted' must not carry a rejection_category",
            stream=stream, field="rejection_category",
            code="rejection_inconsistent")
    if result == "not_simulated" and record["simulation_timestamp_utc"] is not None:
        raise RecordValidationError(
            "simulation_result 'not_simulated' contradicts a simulation "
            "timestamp", stream=stream, field="simulation_timestamp_utc",
            code="rejection_inconsistent")
    if result == "rejected":
        for name in ("bundle_submission_timestamp_utc",
                     "submitted_bundle_transaction_hash"):
            if record[name] is not None:
                raise RecordValidationError(
                    "a rejected operation was never placed in a bundle by this "
                    "bundler", stream=stream, field=name,
                    code="rejection_inconsistent")
    if result == "rejected" and record["inclusion_timestamp_utc"] is not None:
        raise RecordValidationError(
            "a rejected operation was not included by this bundler; if it was "
            "later included via another path, record that as a separate row "
            "with its own bundler_id",
            stream=stream, field="inclusion_timestamp_utc",
            code="rejection_inconsistent")


def _rule_replacement_counts(record: Mapping[str, Any], stream: str) -> None:
    lineage = record["replacement_lineage"]
    count = record["replacement_count"]
    if isinstance(lineage, list) and isinstance(count, int) \
            and count != len(lineage):
        raise RecordValidationError(
            f"replacement_count {count} disagrees with a lineage of "
            f"{len(lineage)} entries",
            stream=stream, field="replacement_count",
            code="replacement_inconsistent")


SCHEMA = StreamSchema(
    stream=STREAM,
    is_secret=False,
    fields=envelope_fields(scenario_nullable=True) + (
        FieldSpec("observer_tier", _check_observer_tier, CLASS_BUNDLER, "A2",
                  "Always 'A2'. This stream exists because the data requires "
                  "an instrumented bundler; no A0/A1 observer has it."),
        FieldSpec("bundler_id", _check_bundler_id, CLASS_BUNDLER, "A2",
                  "Which instrumented bundler produced the observation. "
                  "Required: a two-bundler experiment (docs/research-plan.md "
                  "Sec. 13) is meaningless without it."),
        FieldSpec("userop_hash", check_hash32, CLASS_BUNDLER, "A2",
                  "The operation observed. This is the join key against "
                  "public_events for an A2 attacker."),
        FieldSpec("sender", check_address, CLASS_BUNDLER, "A2",
                  "Smart account the operation claims as sender."),
        FieldSpec("nonce", check_uint256_string, CLASS_BUNDLER, "A2",
                  "Full 256-bit nonce as a decimal string."),
        FieldSpec("submission_attempt", check_int, CLASS_BUNDLER, "A2",
                  "1-based attempt counter for this logical operation.",
                  options={"minimum": 1}),
        FieldSpec("receive_timestamp_utc", check_timestamp, CLASS_BUNDLER, "A2",
                  "When the bundler received the operation."),
        FieldSpec("simulation_timestamp_utc", check_timestamp, CLASS_BUNDLER,
                  "A2",
                  "When validation simulation ran; null if it never ran.",
                  nullable=True),
        FieldSpec("simulation_result", check_enum, CLASS_BUNDLER, "A2",
                  "Outcome of the bundler's validation simulation.",
                  options={"allowed": SIMULATION_RESULTS}),
        FieldSpec("rejection_category", check_enum, CLASS_BUNDLER, "A2",
                  "Why the operation was rejected; null when it was not. "
                  "Rejections are recorded, never discarded.",
                  nullable=True, options={"allowed": REJECTION_CATEGORIES}),
        FieldSpec("rejection_message_class", check_enum, CLASS_BUNDLER, "A2",
                  "Coarse class of the bundler's message. The raw message is "
                  "deliberately not recorded: implementations embed addresses "
                  "and internal state in error strings.",
                  nullable=True, options={"allowed": REJECTION_MESSAGE_CLASSES}),
        FieldSpec("replacement_lineage", _check_replacement_lineage,
                  CLASS_BUNDLER, "A2",
                  "Ordered prior userop hashes this operation replaced. An "
                  "empty list means 'observed, no replacement'; that is not "
                  "the same as null, which would mean 'lineage not observed'.",
                  nullable=True),
        FieldSpec("replacement_count", check_int, CLASS_BUNDLER, "A2",
                  "Length of replacement_lineage; kept as its own field "
                  "because it is a reported liveness metric.",
                  nullable=True, options={"minimum": 0}),
        FieldSpec("inclusion_timestamp_utc", check_timestamp, CLASS_BUNDLER,
                  "A2",
                  "When the bundler observed the operation included on chain; "
                  "null if it never was.", nullable=True),
        FieldSpec("bundle_submission_timestamp_utc", check_timestamp,
                  CLASS_BUNDLER, "A2",
                  "When the bundler broadcast the bundle transaction that "
                  "carried this operation; null if it never submitted one.",
                  nullable=True),
        FieldSpec("submitted_bundle_transaction_hash", check_hash32,
                  CLASS_BUNDLER, "A2",
                  "The bundler's PRE-INCLUSION association between this "
                  "operation and the bundle transaction it signed and "
                  "broadcast; null if it never submitted one. The A2 "
                  "knowledge is the association before mining (and for "
                  "bundles that are later replaced or dropped). A MINED "
                  "bundle transaction hash is public on chain and is "
                  "recorded in public_events.transaction_hash; this field "
                  "does not make it private. Replaces 1.0.0 "
                  "'bundle_transaction_hash', which classified the mined "
                  "hash as bundler-private.", nullable=True),
        FieldSpec("rpc_endpoint_id", _check_bundler_id, CLASS_BUNDLER, "A2",
                  "Opaque identifier of the RPC endpoint used. Opaque, not a "
                  "URL: URLs carry credentials and host identity.",
                  nullable=True),
    ),
    cross_field_rules=(
        rule_synthetic_run_id_prefix,
        rule_workload_matches_baseline,
        rule_baseline_exists_in_schema_version,
        rule_record_id_matches,
        _rule_baseline_has_bundler,
        _rule_simulation_consistency,
        _rule_replacement_counts,
    ),
)
