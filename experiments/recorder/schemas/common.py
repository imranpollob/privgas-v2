"""Shared record envelope and the spec-driven validator.

Every row in every stream carries the same envelope so that any row can be
traced back to (which schema, which experiment, which run, which code
revision, which baseline, measured or synthetic) without consulting anything
outside the row itself.

Design choice -- *required key, explicit value* (docs/experiment-schema.md,
"Null and not-applicable semantics"):

  * Every field defined by a stream's schema MUST be present as a key.
    Absence-by-omission is never valid. This is what makes validation
    deterministic and stops "the field is missing" and "the field is empty"
    from being indistinguishable.
  * ``null``               -> the field is meaningful for this baseline and
                              this row, but the value is genuinely unknown or
                              did not occur (e.g. block_number for an
                              operation that was never included).
  * ``"not_applicable"``   -> the concept does not exist for this baseline or
                              stream at all (e.g. credit_id under B0, which
                              has no credit system).
  * A field not in the schema -> rejected.

The two "empty" values are not interchangeable, and the validator will not
accept one where the schema allows only the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Dict, Iterable, Mapping, Tuple

from .. import baselines, version as schema_version_mod
from ..errors import PrivateDataLeak, RecordValidationError
from ..fieldtypes import (
    NOT_APPLICABLE,
    RE_EXPERIMENT_ID,
    RE_RUN_ID,
    RE_SCENARIO_ID,
    check_enum,
    check_int,
    check_string,
    check_timestamp,
)
from ..privatekeys import FORBIDDEN_PRIVATE_KEYS

# Classification vocabulary used by every FieldSpec and reproduced verbatim
# in docs/experiment-schema.md.
CLASS_PUBLIC = "public"  # observable by A0/A1
CLASS_BUNDLER = "bundler_private"  # observable only by A2
CLASS_SECRET = "secret"  # experiment ground truth; never attacker input


@dataclass(frozen=True)
class FieldSpec:
    name: str
    validator: Callable[..., None]
    classification: str
    observer_tier: str
    doc: str
    nullable: bool = False
    na_allowed: bool = False
    #: Optional extra kwargs handed to the validator.
    options: Mapping[str, Any] = dc_field(default_factory=dict)


@dataclass(frozen=True)
class StreamSchema:
    stream: str
    fields: Tuple[FieldSpec, ...]
    #: Cross-field rules: callables taking (record, stream) and raising.
    cross_field_rules: Tuple[Callable[[Mapping[str, Any], str], None], ...] = ()
    #: True when this stream may carry secret values.
    is_secret: bool = False

    def field_map(self) -> Dict[str, FieldSpec]:
        return {f.name: f for f in self.fields}

    def field_names(self) -> Tuple[str, ...]:
        return tuple(f.name for f in self.fields)


# --- envelope validators ----------------------------------------------------


def _check_schema_version(value, *, field, stream):
    if value not in schema_version_mod.SUPPORTED_SCHEMA_VERSIONS:
        raise RecordValidationError(
            f"{value!r} is not a supported schema version; this code supports "
            f"{sorted(schema_version_mod.SUPPORTED_SCHEMA_VERSIONS)}. Records "
            "are never migrated in place -- re-record the run under the "
            "current version instead.",
            stream=stream, field=field, code="unsupported_schema_version",
        )


def _check_baseline_id(value, *, field, stream):
    if not baselines.is_known(value):
        raise RecordValidationError(
            f"{value!r} is not a known baseline id; known: "
            f"{', '.join(baselines.BASELINE_IDS)}",
            stream=stream, field=field, code="unknown_baseline",
        )


def _check_software_revision(value, *, field, stream):
    """Reproducibility identifier; see experiments.recorder.provenance.

    A commit hash is only ever recorded when git actually reports one. When
    the worktree is dirty or has no commits, the row says so explicitly and
    carries a content-derived worktree identifier instead. A commit hash is
    never manufactured.
    """
    if not isinstance(value, dict):
        raise RecordValidationError(
            "expected an object", stream=stream, field=field, code="type_error")

    required = {"kind", "git_commit", "git_dirty", "worktree_id", "describe"}
    missing = required - set(value)
    extra = set(value) - required
    if missing:
        raise RecordValidationError(
            f"missing sub-fields {sorted(missing)}", stream=stream, field=field,
            code="missing_field")
    if extra:
        raise RecordValidationError(
            f"unexpected sub-fields {sorted(extra)}", stream=stream, field=field,
            code="unknown_field")

    check_enum(value["kind"], field=f"{field}.kind", stream=stream,
               allowed=("git_commit", "git_worktree"))

    commit = value["git_commit"]
    if commit is not None:
        if not (isinstance(commit, str) and len(commit) == 40
                and all(c in "0123456789abcdef" for c in commit)):
            raise RecordValidationError(
                f"{commit!r} is not a full 40-character lowercase commit SHA",
                stream=stream, field=f"{field}.git_commit",
                code="malformed_commit")

    if not isinstance(value["git_dirty"], bool):
        raise RecordValidationError(
            "git_dirty must be a boolean", stream=stream,
            field=f"{field}.git_dirty", code="type_error")

    wt = value["worktree_id"]
    if value["kind"] == "git_commit":
        if value["git_dirty"]:
            raise RecordValidationError(
                "kind 'git_commit' requires git_dirty=false; a dirty worktree "
                "is not identified by its HEAD commit",
                stream=stream, field=field, code="provenance_inconsistent")
        if commit is None:
            raise RecordValidationError(
                "kind 'git_commit' requires a git_commit value",
                stream=stream, field=field, code="provenance_inconsistent")
        if wt is not None:
            raise RecordValidationError(
                "kind 'git_commit' must not also carry a worktree_id",
                stream=stream, field=field, code="provenance_inconsistent")
    else:
        if not (isinstance(wt, str) and len(wt) == 64
                and all(c in "0123456789abcdef" for c in wt)):
            raise RecordValidationError(
                "kind 'git_worktree' requires worktree_id to be a 64-character "
                "lowercase sha256 of the working-tree state",
                stream=stream, field=f"{field}.worktree_id",
                code="provenance_inconsistent")

    if not isinstance(value["describe"], str) or len(value["describe"]) > 256:
        raise RecordValidationError(
            "describe must be a string of at most 256 characters",
            stream=stream, field=f"{field}.describe", code="type_error")


def _check_experiment_id(value, *, field, stream):
    check_string(value, field=field, stream=stream, pattern=RE_EXPERIMENT_ID,
                 code="malformed_experiment_id", max_len=128)


def _check_run_id(value, *, field, stream):
    check_string(value, field=field, stream=stream, pattern=RE_RUN_ID,
                 code="malformed_run_id", max_len=64)


def _check_record_id(value, *, field, stream):
    if not isinstance(value, str) or not (1 <= len(value) <= 192):
        raise RecordValidationError("expected a non-empty string", stream=stream,
                                    field=field, code="type_error")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
                  "0123456789._:/-")
    if not set(value) <= allowed:
        raise RecordValidationError(
            "record_id may only contain [A-Za-z0-9._:/-]", stream=stream,
            field=field, code="malformed_record_id")


def _check_scenario_id(value, *, field, stream):
    check_string(value, field=field, stream=stream, pattern=RE_SCENARIO_ID,
                 code="malformed_scenario_id", max_len=64)


def _check_seq(value, *, field, stream):
    check_int(value, field=field, stream=stream, minimum=0)


def _check_workload_id(value, *, field, stream):
    check_enum(value, field=field, stream=stream,
               allowed=baselines.WORKLOAD_IDS)


def _check_data_origin(value, *, field, stream):
    check_enum(value, field=field, stream=stream,
               allowed=("measured", "synthetic_fixture"))


# --- envelope field specs ---------------------------------------------------

def envelope_fields(*, scenario_nullable: bool) -> Tuple[FieldSpec, ...]:
    return (
        FieldSpec("schema_version", _check_schema_version, CLASS_PUBLIC, "A0",
                  "Version of this record schema; explicit allow-list."),
        FieldSpec("stream", _check_stream, CLASS_PUBLIC, "A0",
                  "Which of the three streams this row belongs to. Guards "
                  "against a row being written to, or concatenated into, the "
                  "wrong file."),
        FieldSpec("experiment_id", _check_experiment_id, CLASS_PUBLIC, "A0",
                  "Identifier matching a definition under experiments/."),
        FieldSpec("run_id", _check_run_id, CLASS_PUBLIC, "A0",
                  "One execution of one experiment. UTC-timestamp shaped; "
                  "prefixed 'synthetic-' for non-measured fixture runs."),
        FieldSpec("record_id", _check_record_id, CLASS_PUBLIC, "A0",
                  "Stable per-row identity, '<run_id>/<stream>/<seq>'. This is "
                  "the join key that frozen predictions refer to."),
        FieldSpec("seq", _check_seq, CLASS_PUBLIC, "A0",
                  "0-based position of this row within its stream for this run."),
        FieldSpec("baseline_id", _check_baseline_id, CLASS_PUBLIC, "A0",
                  "Which baseline produced the row (B0, B1, B2-Allowlist, "
                  "B2-Signature, B3..B6). The experimental "
                  "condition, known to the attacker by construction."),
        FieldSpec("workload_id", _check_workload_id, CLASS_PUBLIC, "A0",
                  "Canonical workload (docs/research-plan.md Sec. 4): W1-cold "
                  "(primary ERC-20 W1; a smart account is deployed by the "
                  "measured operation), W1-warm (AA-only ablation; account "
                  "deployed beforehand), W2 ERC-721, W3 native ETH, W4 "
                  "repeated actions. Like "
                  "baseline_id this is an experimental condition the attacker "
                  "knows by construction, not a hidden label."),
        FieldSpec("scenario_id", _check_scenario_id, CLASS_PUBLIC, "A0",
                  "Opaque identifier for the scenario / candidate set this row "
                  "belongs to. Must carry no meaning: it is visible to the "
                  "attacker, so an id like 'actor7-links-wallet3' would be a "
                  "label leak. null only where a row is genuinely not "
                  "scenario-scoped.",
                  nullable=scenario_nullable),
        FieldSpec("software_revision", _check_software_revision, CLASS_PUBLIC,
                  "A0",
                  "Reproducibility identity of the code that produced the row: "
                  "a real commit SHA when the worktree is clean, otherwise an "
                  "explicit working-tree digest. Never a manufactured hash."),
        FieldSpec("data_origin", _check_data_origin, CLASS_PUBLIC, "A0",
                  "'measured' for rows derived from an actual execution; "
                  "'synthetic_fixture' for hand-written examples and test "
                  "data. Synthetic rows are confined to run_ids prefixed "
                  "'synthetic-'."),
        FieldSpec("recorded_at_utc", check_timestamp, CLASS_PUBLIC, "A0",
                  "When the recorder wrote the row (harness wall clock). "
                  "Distinct from block_timestamp_utc, which is chain time."),
    )


def _check_stream(value, *, field, stream):
    if value != stream:
        raise RecordValidationError(
            f"row declares stream {value!r} but is being validated as "
            f"{stream!r}", stream=stream, field=field, code="wrong_stream")


# --- shared cross-field rules ----------------------------------------------


def rule_synthetic_run_id_prefix(record: Mapping[str, Any], stream: str) -> None:
    """A synthetic fixture cannot be mistaken for a measured run, and vice versa."""
    origin = record.get("data_origin")
    run_id = record.get("run_id")
    if not isinstance(run_id, str):
        return
    is_prefixed = run_id.startswith("synthetic-")
    if origin == "synthetic_fixture" and not is_prefixed:
        raise RecordValidationError(
            "data_origin='synthetic_fixture' requires a run_id prefixed "
            "'synthetic-' so fixtures can never be read as measured results",
            stream=stream, field="run_id", code="origin_mismatch")
    if origin == "measured" and is_prefixed:
        raise RecordValidationError(
            "run_id is prefixed 'synthetic-' but data_origin claims 'measured'",
            stream=stream, field="data_origin", code="origin_mismatch")


def rule_workload_matches_baseline(record: Mapping[str, Any], stream: str) -> None:
    """W1-warm pre-deploys a smart account, so it exists only for AA baselines."""
    workload = record.get("workload_id")
    if workload in baselines.ERC4337_ONLY_WORKLOADS and baselines.is_known(
            record.get("baseline_id")):
        if not baselines.get(record["baseline_id"]).uses_erc4337:
            raise RecordValidationError(
                f"workload {workload!r} pre-deploys an ERC-4337 account; "
                f"baseline {record['baseline_id']} has no account to deploy",
                stream=stream, field="workload_id",
                code="baseline_capability_violation")


def rule_record_id_matches(record: Mapping[str, Any], stream: str) -> None:
    expected = build_record_id(record.get("run_id"), stream, record.get("seq"))
    if record.get("record_id") != expected:
        raise RecordValidationError(
            f"record_id {record.get('record_id')!r} is not the canonical "
            f"'<run_id>/<stream>/<seq:06d>' form {expected!r}",
            stream=stream, field="record_id", code="malformed_record_id")


def build_record_id(run_id, stream, seq) -> str:
    try:
        return f"{run_id}/{stream}/{int(seq):06d}"
    except (TypeError, ValueError):
        return f"{run_id}/{stream}/<invalid-seq>"


# --- generic validation -----------------------------------------------------


def _walk_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_keys(item)


def reject_forbidden_keys(record: Mapping[str, Any], stream: str) -> None:
    """Reject hidden identifiers / relation labels anywhere in a public record.

    Runs at any nesting depth, before the allow-list check, so that the error
    names the actual problem ("a secret label reached a public stream")
    rather than the generic "unknown field".
    """
    for key in _walk_keys(record):
        if key in FORBIDDEN_PRIVATE_KEYS:
            raise PrivateDataLeak(
                f"forbidden private field {key!r} appears in an "
                f"attacker-visible record. Hidden identifiers and relation "
                f"labels belong only in ground_truth.jsonl.",
                stream=stream, field=key, code="private_field_in_public_stream")


def validate_against_schema(record: Any, schema: StreamSchema) -> None:
    stream = schema.stream
    if not isinstance(record, dict):
        raise RecordValidationError(
            f"expected a JSON object, got {type(record).__name__}",
            stream=stream, code="type_error")

    # Checked before anything else, including nullability: a row whose version
    # this code does not know must be reported as a version problem, not as
    # whichever field happens to fail first under the wrong schema.
    if "schema_version" in record:
        _check_schema_version(record["schema_version"],
                              field="schema_version", stream=stream)

    if not schema.is_secret:
        reject_forbidden_keys(record, stream)

    spec_by_name = schema.field_map()
    unknown = sorted(set(record) - set(spec_by_name))
    if unknown:
        raise RecordValidationError(
            f"unknown field(s) {unknown}; the schema is a strict allow-list. "
            "Adding a field requires a schema version bump "
            "(docs/experiment-schema.md).",
            stream=stream, field=unknown[0], code="unknown_field")

    missing = sorted(set(spec_by_name) - set(record))
    if missing:
        raise RecordValidationError(
            f"missing required field(s) {missing}; every schema field must be "
            "present as a key, with null or 'not_applicable' used to express "
            "emptiness explicitly",
            stream=stream, field=missing[0], code="missing_field")

    for name, spec in spec_by_name.items():
        value = record[name]
        if value is None:
            if not spec.nullable:
                raise RecordValidationError(
                    "null is not permitted for this field; if the concept does "
                    "not exist for this baseline the schema would allow "
                    "'not_applicable' instead",
                    stream=stream, field=name, code="null_not_allowed")
            continue
        if value == NOT_APPLICABLE and isinstance(value, str):
            if not spec.na_allowed:
                raise RecordValidationError(
                    "'not_applicable' is not permitted for this field",
                    stream=stream, field=name, code="na_not_allowed")
            continue
        spec.validator(value, field=name, stream=stream, **dict(spec.options))

    for rule in schema.cross_field_rules:
        rule(record, stream)


def require_null_fields(record: Mapping[str, Any], stream: str,
                        names: Iterable[str], reason: str) -> None:
    offenders = [n for n in names if record.get(n) not in (None, NOT_APPLICABLE)]
    if offenders:
        raise RecordValidationError(
            f"{reason}; field(s) {sorted(offenders)} must be null or "
            "'not_applicable' for this baseline",
            stream=stream, field=sorted(offenders)[0],
            code="baseline_capability_violation")
