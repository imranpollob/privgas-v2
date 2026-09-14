"""Validation and recording errors."""

from __future__ import annotations

from typing import Optional


class RecorderError(Exception):
    """Base class for every error raised by experiments.recorder."""


class RecordValidationError(RecorderError):
    """A record failed schema validation.

    Carries enough structure that tests can assert on *why* a record was
    rejected rather than on error-message substrings.
    """

    def __init__(
        self,
        message: str,
        *,
        stream: Optional[str] = None,
        field: Optional[str] = None,
        code: Optional[str] = None,
    ) -> None:
        self.stream = stream
        self.field = field
        self.code = code
        prefix = f"[{stream or '?'}]"
        if field:
            prefix += f" field {field!r}"
        if code:
            prefix += f" ({code})"
        super().__init__(f"{prefix}: {message}")


class PrivateDataLeak(RecordValidationError):
    """A secret label / hidden identifier reached an attacker-visible stream."""


class ProvenanceError(RecorderError):
    """Software revision identity could not be established honestly."""
