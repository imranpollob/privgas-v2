"""Versioned experiment recorder for privgas-v2.

Neutral write-side package: schemas, validation, JSONL writers, provenance
and baseline adapters. Importable from either side of the public/private
read boundary (see experiments/_boundary.py) because it holds no data.

Canonical documentation: docs/experiment-schema.md.
"""

from .errors import (  # noqa: F401
    PrivateDataLeak,
    ProvenanceError,
    RecorderError,
    RecordValidationError,
)
from .validate import describe_schema, is_valid, validate_many, validate_record  # noqa: F401
from .version import (  # noqa: F401
    SCHEMA_VERSION,
    STREAM_BUNDLER_PRIVATE,
    STREAM_GROUND_TRUTH,
    STREAM_PUBLIC_EVENTS,
    STREAMS,
    SUPPORTED_SCHEMA_VERSIONS,
)
from .writers import ExperimentRecorder, JsonlStreamWriter, new_run_id  # noqa: F401

__all__ = [
    "ExperimentRecorder", "JsonlStreamWriter", "new_run_id",
    "validate_record", "validate_many", "is_valid", "describe_schema",
    "SCHEMA_VERSION", "SUPPORTED_SCHEMA_VERSIONS", "STREAMS",
    "STREAM_GROUND_TRUTH", "STREAM_PUBLIC_EVENTS", "STREAM_BUNDLER_PRIVATE",
    "RecorderError", "RecordValidationError", "PrivateDataLeak",
    "ProvenanceError",
]
