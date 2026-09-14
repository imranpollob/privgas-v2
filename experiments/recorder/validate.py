"""The single entry point for record validation.

Deterministic: same record, same verdict, everywhere. No I/O, no clock, no
network. Malformed records raise; nothing is coerced, defaulted or repaired.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Tuple

from .errors import RecordValidationError
from .schemas import STREAM_SCHEMAS
from .schemas.common import validate_against_schema
from .version import STREAMS


def validate_record(stream: str, record: Any) -> None:
    """Validate one record against one stream schema. Raises on any problem."""
    if stream not in STREAM_SCHEMAS:
        raise RecordValidationError(
            f"unknown stream {stream!r}; known: {list(STREAMS)}",
            stream=stream, code="unknown_stream")
    validate_against_schema(record, STREAM_SCHEMAS[stream])


def is_valid(stream: str, record: Any) -> bool:
    try:
        validate_record(stream, record)
    except RecordValidationError:
        return False
    return True


def validate_many(stream: str, records: Iterable[Any]) -> None:
    for i, record in enumerate(records):
        try:
            validate_record(stream, record)
        except RecordValidationError as exc:
            raise RecordValidationError(
                f"row {i}: {exc}", stream=stream, code="row_invalid") from exc


def describe_schema(stream: str) -> Tuple[Mapping[str, Any], ...]:
    """Machine-readable field documentation, used to generate the schema docs."""
    schema = STREAM_SCHEMAS[stream]
    return tuple(
        {
            "field": f.name,
            "classification": f.classification,
            "observer_tier": f.observer_tier,
            "nullable": f.nullable,
            "not_applicable_allowed": f.na_allowed,
            "doc": f.doc,
        }
        for f in schema.fields
    )
