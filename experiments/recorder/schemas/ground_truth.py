"""ground_truth.jsonl -- SECRET experiment labels.

This stream is the answer key for the controlled experiment. It is written to
``data/private/`` (gitignored) and it is never an input to attack or
feature-generation code. The only sanctioned consumer is
``experiments.labels``, which is unimportable in any process that has loaded
``experiments.attacker_view``.

Scope discipline enforced here:

* **Hidden identifiers are opaque handles, never on-chain values.** An id like
  ``actor_a17f3c`` is rejected if it looks like an address or a hex blob. Two
  reasons: (a) a hidden id that *is* an address would legitimately appear in
  the public streams, making the value-leak scan in
  ``experiments.labels.selfcheck`` unable to distinguish leakage from normal
  recording; (b) it keeps "who this is" and "which address this is"
  structurally distinct, which is the whole point of the stream separation.
  The mapping from a hidden id to its public on-chain anchors lives in
  ``public_anchors`` -- inside this private stream, where it belongs.

* **Multiple accounts are not multiple people.** ``actor_id`` is the identity;
  ``stealth_account_id``, ``established_wallet_id`` and ``funding_wallet_id``
  are accounts. Many rows may share one ``actor_id``. Nothing in this schema
  or in the loaders assumes a 1:1 mapping, and evaluation code must not infer
  one. Likewise, multiple ``credit_id`` values may belong to one actor:
  distinct commitments are not evidence of distinct honest participants.

* **Negative and failed cases are data.** A relation whose answer is "no link
  for this subject" is recorded with ``status="absent"``, not dropped. A
  rejected or failed operation still gets its ground-truth row.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..errors import RecordValidationError
from ..fieldtypes import (
    RE_OPAQUE_ID,
    RE_SCENARIO_ID,
    check_address,
    check_enum,
    check_hash32,
    check_int,
    check_string,
    looks_like_onchain_identifier,
)
from .common import (
    CLASS_SECRET,
    FieldSpec,
    StreamSchema,
    envelope_fields,
    rule_record_id_matches,
    rule_synthetic_run_id_prefix,
    rule_workload_matches_baseline,
)

STREAM = "ground_truth"

RELATION_FOR_FIELD = {
    "payer_to_operation_label": "R1",
    "issuance_to_redemption_label": "R2",
    "stealth_to_actor_label": "R3",
}

LABEL_SUBFIELDS = ("relation", "status", "subject_ref", "true_value",
                   "candidate_set_id")

LABEL_STATUSES = ("observed", "absent", "not_applicable")

SUBJECT_KINDS = ("operation", "stealth_account", "issuance", "funding_event")


def check_opaque_id(value, *, field, stream):
    """An opaque hidden handle: lowercase, underscore-separated, not on-chain."""
    if looks_like_onchain_identifier(value):
        raise RecordValidationError(
            f"{value!r} looks like an on-chain identifier. Hidden identifiers "
            "must be opaque handles (e.g. 'actor_a17f3c'); record the on-chain "
            "value under public_anchors instead.",
            stream=stream, field=field, code="hidden_id_not_opaque")
    check_string(value, field=field, stream=stream, pattern=RE_OPAQUE_ID,
                 code="malformed_opaque_id", max_len=64)


def _check_seed(value, *, field, stream):
    check_int(value, field=field, stream=stream, minimum=0, maximum=2 ** 64 - 1)


def _check_subject_kind(value, *, field, stream):
    check_enum(value, field=field, stream=stream, allowed=SUBJECT_KINDS)


def _make_label_checker(expected_relation: str):
    def _check(value, *, field, stream):
        if not isinstance(value, dict):
            raise RecordValidationError(
                "a relation label must be an object with sub-fields "
                f"{list(LABEL_SUBFIELDS)}",
                stream=stream, field=field, code="type_error")
        missing = sorted(set(LABEL_SUBFIELDS) - set(value))
        extra = sorted(set(value) - set(LABEL_SUBFIELDS))
        if missing:
            raise RecordValidationError(
                f"missing label sub-field(s) {missing}", stream=stream,
                field=field, code="missing_field")
        if extra:
            raise RecordValidationError(
                f"unexpected label sub-field(s) {extra}", stream=stream,
                field=field, code="unknown_field")

        if value["relation"] != expected_relation:
            raise RecordValidationError(
                f"{field!r} must carry relation {expected_relation!r}, got "
                f"{value['relation']!r}. R1/R2/R3 are reported separately and "
                "are never collapsed (docs/threat-model.md).",
                stream=stream, field=f"{field}.relation",
                code="relation_mismatch")

        status = value["status"]
        check_enum(status, field=f"{field}.status", stream=stream,
                   allowed=LABEL_STATUSES)

        subject_ref = value["subject_ref"]
        true_value = value["true_value"]
        candidate_set_id = value["candidate_set_id"]

        if status == "not_applicable":
            for sub in ("subject_ref", "true_value", "candidate_set_id"):
                if value[sub] is not None:
                    raise RecordValidationError(
                        "status 'not_applicable' means the relation does not "
                        "exist for this baseline, so every other sub-field must "
                        "be null",
                        stream=stream, field=f"{field}.{sub}",
                        code="label_inconsistent")
            return

        if subject_ref is None:
            raise RecordValidationError(
                "subject_ref is required whenever the relation exists for this "
                "baseline; it names the attacker-visible anchor the label "
                "answers about",
                stream=stream, field=f"{field}.subject_ref",
                code="label_inconsistent")
        if not isinstance(subject_ref, str) or not (1 <= len(subject_ref) <= 192):
            raise RecordValidationError(
                "subject_ref must be a non-empty string of at most 192 chars",
                stream=stream, field=f"{field}.subject_ref", code="type_error")

        if status == "absent":
            if true_value is not None:
                raise RecordValidationError(
                    "status 'absent' records a true negative -- the relation is "
                    "defined for this baseline but this subject has no link -- "
                    "so true_value must be null. Negatives are kept, never "
                    "dropped.",
                    stream=stream, field=f"{field}.true_value",
                    code="label_inconsistent")
        else:  # observed
            if true_value is None:
                raise RecordValidationError(
                    "status 'observed' requires a true_value (the hidden "
                    "answer)", stream=stream, field=f"{field}.true_value",
                    code="label_inconsistent")
            check_opaque_id(true_value, field=f"{field}.true_value",
                            stream=stream)

        if candidate_set_id is not None:
            check_string(candidate_set_id, field=f"{field}.candidate_set_id",
                         stream=stream, pattern=RE_SCENARIO_ID,
                         code="malformed_candidate_set_id", max_len=64)

    return _check


PUBLIC_ANCHOR_FIELDS = {
    "stealth_account_address": check_address,
    "funding_address": check_address,
    "asset_sender_address": check_address,
    "established_wallet_address": check_address,
    "transaction_hash": check_hash32,
    "userop_hash": check_hash32,
}


def _check_public_anchors(value, *, field, stream):
    """Bridge from hidden handles to the attacker-visible values.

    These are public-domain values recorded inside the private stream. The
    private stream may hold public data; the reverse is what the validator
    forbids. This object is what makes the post-freeze label join possible
    without ever handing an attacker-side process a hidden identifier.
    """
    if not isinstance(value, dict):
        raise RecordValidationError("expected an object", stream=stream,
                                    field=field, code="type_error")
    allowed = set(PUBLIC_ANCHOR_FIELDS) | {"public_event_record_ids"}
    missing = sorted(allowed - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise RecordValidationError(
            f"missing public_anchors sub-field(s) {missing}", stream=stream,
            field=field, code="missing_field")
    if extra:
        raise RecordValidationError(
            f"unexpected public_anchors sub-field(s) {extra}", stream=stream,
            field=field, code="unknown_field")

    for name, checker in PUBLIC_ANCHOR_FIELDS.items():
        sub = value[name]
        if sub is None:
            continue
        checker(sub, field=f"{field}.{name}", stream=stream)

    refs = value["public_event_record_ids"]
    if not isinstance(refs, list):
        raise RecordValidationError(
            "public_event_record_ids must be a list (possibly empty) of "
            "public_events record_id values",
            stream=stream, field=f"{field}.public_event_record_ids",
            code="type_error")
    for i, ref in enumerate(refs):
        if not isinstance(ref, str) or not (1 <= len(ref) <= 192):
            raise RecordValidationError(
                f"entry {i} is not a record_id string", stream=stream,
                field=f"{field}.public_event_record_ids", code="type_error")


def _rule_credit_fields_match_relation_r2(record: Mapping[str, Any],
                                          stream: str) -> None:
    """R2 only exists where a credit lifecycle exists."""
    from .. import baselines

    caps = baselines.get(record["baseline_id"])
    r2 = record["issuance_to_redemption_label"]
    has_credit = caps.uses_credit_system

    if not has_credit:
        for name in ("credit_id", "issuance_id"):
            if record[name] != "not_applicable":
                raise RecordValidationError(
                    f"baseline {caps.baseline_id} has no credit system, so "
                    f"{name!r} must be the string 'not_applicable' rather than "
                    "null or a value (null would mean 'exists but unknown')",
                    stream=stream, field=name,
                    code="baseline_capability_violation")
        if isinstance(r2, dict) and r2.get("status") != "not_applicable":
            raise RecordValidationError(
                f"baseline {caps.baseline_id} has no credit issuance, so the "
                "R2 label must have status 'not_applicable'",
                stream=stream, field="issuance_to_redemption_label",
                code="baseline_capability_violation")
    else:
        if isinstance(r2, dict) and r2.get("status") == "not_applicable":
            raise RecordValidationError(
                f"baseline {caps.baseline_id} does have a credit lifecycle, so "
                "R2 is defined; use status 'absent' for a subject with no link "
                "rather than 'not_applicable'",
                stream=stream, field="issuance_to_redemption_label",
                code="baseline_capability_violation")


def _rule_hidden_ids_distinct_from_anchors(record: Mapping[str, Any],
                                           stream: str) -> None:
    """No hidden handle may equal one of its own public anchors."""
    anchors = record.get("public_anchors")
    if not isinstance(anchors, dict):
        return
    anchor_values = {v for v in anchors.values() if isinstance(v, str)}
    from ..privatekeys import HIDDEN_ID_FIELDS

    for name in HIDDEN_ID_FIELDS:
        v = record.get(name)
        if isinstance(v, str) and v in anchor_values:
            raise RecordValidationError(
                f"{name!r} equals a public anchor value; hidden handles must be "
                "opaque and distinct from on-chain values",
                stream=stream, field=name, code="hidden_id_not_opaque")


_HIDDEN_ID_DOC = (
    "Opaque hidden handle. 'not_applicable' where the concept does not exist "
    "for this baseline; null where it exists but was not determined for this "
    "row."
)

SCHEMA = StreamSchema(
    stream=STREAM,
    is_secret=True,
    fields=envelope_fields(scenario_nullable=False) + (
        FieldSpec("seed", _check_seed, CLASS_SECRET, "none",
                  "RNG seed for the run. SECRET: the seed determines the hidden "
                  "assignment of actors to accounts and to timing, so it is the "
                  "answer key in compressed form. The public run manifest "
                  "carries only a commitment to it."),
        FieldSpec("subject_kind", _check_subject_kind, CLASS_SECRET, "none",
                  "What this ground-truth row is about: one operation, one "
                  "stealth account, one issuance, or one funding event."),
        FieldSpec("actor_id", check_opaque_id, CLASS_SECRET, "none",
                  "The hidden person/entity. Many accounts may map to one "
                  "actor_id; nothing may infer otherwise. " + _HIDDEN_ID_DOC,
                  nullable=True, na_allowed=True),
        FieldSpec("established_wallet_id", check_opaque_id, CLASS_SECRET, "none",
                  "The actor's pre-existing, publicly known wallet (W). "
                  + _HIDDEN_ID_DOC, nullable=True, na_allowed=True),
        FieldSpec("funding_wallet_id", check_opaque_id, CLASS_SECRET, "none",
                  "The account that supplied gas funding / sponsorship (P). "
                  + _HIDDEN_ID_DOC, nullable=True, na_allowed=True),
        FieldSpec("asset_sender_id", check_opaque_id, CLASS_SECRET, "none",
                  "The account that sent the non-native asset to the stealth "
                  "account. Distinct from funding_wallet_id by design: R1 asks "
                  "about the gas payer, not the asset sender. " + _HIDDEN_ID_DOC,
                  nullable=True, na_allowed=True),
        FieldSpec("stealth_account_id", check_opaque_id, CLASS_SECRET, "none",
                  "The fresh stealth-controlled account (S). " + _HIDDEN_ID_DOC,
                  nullable=True, na_allowed=True),
        FieldSpec("credit_id", check_opaque_id, CLASS_SECRET, "none",
                  "The hidden credit/note (C). 'not_applicable' for baselines "
                  "with no credit system (B0/B1/B2). " + _HIDDEN_ID_DOC,
                  nullable=True, na_allowed=True),
        FieldSpec("issuance_id", check_opaque_id, CLASS_SECRET, "none",
                  "The issuance event (I) that created the credit. "
                  "'not_applicable' for baselines with no credit system. "
                  + _HIDDEN_ID_DOC, nullable=True, na_allowed=True),
        FieldSpec("payer_to_operation_label",
                  _make_label_checker("R1"), CLASS_SECRET, "none",
                  "R1 answer key: which funding source P is truly associated "
                  "with operation O."),
        FieldSpec("issuance_to_redemption_label",
                  _make_label_checker("R2"), CLASS_SECRET, "none",
                  "R2 answer key: which issuance event I truly supplied the "
                  "authorization consumed by O."),
        FieldSpec("stealth_to_actor_label",
                  _make_label_checker("R3"), CLASS_SECRET, "none",
                  "R3 answer key: which actor A / established wallet W the "
                  "stealth account S truly belongs to."),
        FieldSpec("public_anchors", _check_public_anchors, CLASS_SECRET, "none",
                  "Public on-chain values that identify this row's subject in "
                  "the attacker-visible streams. The bridge used by the "
                  "post-freeze evaluation join, and the only place a hidden "
                  "handle is tied to an address."),
    ),
    cross_field_rules=(
        rule_synthetic_run_id_prefix,
        rule_workload_matches_baseline,
        rule_record_id_matches,
        _rule_credit_fields_match_relation_r2,
        _rule_hidden_ids_distinct_from_anchors,
    ),
)
