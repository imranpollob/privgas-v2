"""Deterministic primitive field validators.

Every check here is a pure function of the value: no network access, no
clock, no filesystem. Same input, same verdict, on every machine.

Numeric representation rule (docs/experiment-schema.md, "Numeric types"):

  * Values in the uint256 domain -- wei amounts, gas limits, gas prices,
    ERC-4337 nonces, token amounts in base units -- are recorded as
    **decimal strings** ("1000000000"). JSON numbers are IEEE-754 doubles in
    most parsers and silently lose precision above 2^53, which would corrupt
    fee and amount comparisons.
  * Small bounded counters -- chain_id, block_number, transaction_index,
    log_index, replacement_count -- are recorded as **JSON integers**.
  * 32-byte hashes and field elements are recorded as 0x-prefixed lowercase
    hex of the exact byte length.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .errors import RecordValidationError

# --- patterns ---------------------------------------------------------------

#: Lowercase only (schema 2.0.0). 1.0.0 accepted EIP-55 checksummed and
#: lowercase spellings side by side, and the first real runs produced both
#: (RPC transaction fields are lowercase, decoded logs are checksummed), which
#: would make the same account compare unequal across rows.
RE_ADDRESS = re.compile(r"^0x[0-9a-f]{40}$")
RE_HASH32 = re.compile(r"^0x[0-9a-f]{64}$")
RE_SELECTOR = re.compile(r"^0x[0-9a-f]{8}$")
RE_UINT_DEC = re.compile(r"^(?:0|[1-9][0-9]*)$")
RE_HEX_ANY = re.compile(r"^0x[0-9a-fA-F]*$")

#: experiment_id: 1-8 lowercase slash-separated segments, e.g.
#: "privacy/d1-w1-b1". Mirrors the results/<experiment_id>/ convention
#: already used by `make run-local-experiment`.
RE_EXPERIMENT_ID = re.compile(
    r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?(?:/[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?){0,7}$"
)

#: run_id: a UTC-timestamp-shaped identifier, optionally prefixed
#: "synthetic-" for non-measured fixture runs.
RE_RUN_ID = re.compile(r"^(?:synthetic-)?[0-9]{8}T[0-9]{6}Z(?:-[a-z0-9]{1,16})?$")

#: scenario_id: opaque, lowercase, no embedded meaning required. Deliberately
#: forbids anything address- or hex-shaped so a scenario label cannot smuggle
#: an identifier into the public streams.
RE_SCENARIO_ID = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")

#: Opaque hidden identifier, e.g. "actor_a17f3c", "stealth_9b2e01".
#: Must contain an underscore-separated suffix and must not look like an
#: address or a hex string -- see note in ground-truth schema.
RE_OPAQUE_ID = re.compile(r"^[a-z][a-z0-9]{0,15}(?:_[a-z0-9]+)+$")

NOT_APPLICABLE = "not_applicable"

RE_ISO_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)


# --- helpers ----------------------------------------------------------------


def _fail(stream, field, message, code):
    raise RecordValidationError(message, stream=stream, field=field, code=code)


def check_string(value, *, field, stream, pattern: re.Pattern, code: str,
                 max_len: int = 256) -> None:
    if not isinstance(value, str):
        _fail(stream, field, f"expected a string, got {type(value).__name__}",
              "type_error")
    if len(value) > max_len:
        _fail(stream, field, f"longer than {max_len} characters", "too_long")
    if not pattern.match(value):
        _fail(stream, field, f"{value!r} does not match {pattern.pattern}", code)


def check_address(value, *, field, stream) -> None:
    if not isinstance(value, str) or not RE_ADDRESS.match(value):
        _fail(stream, field,
              f"{value!r} is not a 0x-prefixed, lowercase, 20-byte hex Ethereum "
              "address (adapters canonicalise; see adapters.base._a)",
              "malformed_address")


def check_hash32(value, *, field, stream) -> None:
    if not isinstance(value, str) or not RE_HASH32.match(value):
        _fail(stream, field,
              f"{value!r} is not a 0x-prefixed lowercase 32-byte hex hash",
              "malformed_hash")


def check_selector(value, *, field, stream) -> None:
    if not isinstance(value, str) or not RE_SELECTOR.match(value):
        _fail(stream, field,
              f"{value!r} is not a 0x-prefixed lowercase 4-byte selector",
              "malformed_selector")


def check_uint256_string(value, *, field, stream) -> None:
    """uint256-domain value: decimal string, no sign, no leading zeros."""
    if isinstance(value, bool) or isinstance(value, int):
        _fail(stream, field,
              "uint256-domain values must be decimal STRINGS, not JSON numbers "
              "(JSON numbers lose precision above 2^53)",
              "numeric_representation")
    if not isinstance(value, str) or not RE_UINT_DEC.match(value):
        _fail(stream, field,
              f"{value!r} is not a decimal uint256 string", "malformed_uint256")
    if int(value) >= 2 ** 256:
        _fail(stream, field, "value exceeds uint256", "uint256_overflow")


def check_int(value, *, field, stream, minimum: Optional[int] = None,
              maximum: Optional[int] = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(stream, field, f"expected a JSON integer, got {value!r}",
              "type_error")
    if minimum is not None and value < minimum:
        _fail(stream, field, f"{value} < minimum {minimum}", "out_of_range")
    if maximum is not None and value > maximum:
        _fail(stream, field, f"{value} > maximum {maximum}", "out_of_range")


def check_chain_id(value, *, field, stream) -> None:
    """chain_id is a JSON integer >= 1. A string chain id is rejected.

    EIP-155 chain ids are unbounded in principle but every id we target
    (mainnet 1, anvil 31337, testnets) fits comfortably in an integer, and a
    consistent representation is what makes cross-run comparison valid.
    """
    if isinstance(value, str):
        _fail(stream, field,
              f"chain_id must be a JSON integer, not the string {value!r} "
              "(mixed representations break cross-run joins)",
              "incompatible_chain_id")
    check_int(value, field=field, stream=stream, minimum=1, maximum=2 ** 64 - 1)


def check_bool(value, *, field, stream) -> None:
    if not isinstance(value, bool):
        _fail(stream, field, f"expected a boolean, got {value!r}", "type_error")


def check_timestamp(value, *, field, stream) -> None:
    """ISO-8601 UTC with an explicit trailing Z. Local time is rejected."""
    if not isinstance(value, str) or not RE_ISO_UTC.match(value):
        _fail(stream, field,
              f"{value!r} is not an ISO-8601 UTC timestamp of the form "
              "YYYY-MM-DDTHH:MM:SSZ", "invalid_timestamp")
    try:
        # Drop the trailing Z and any fractional part before the calendar
        # check. (Fixed 2026-09-14: the first real bundler timestamps carried
        # microseconds, which the regex allows but the old parse rejected.)
        datetime.strptime(value[:-1].split(".")[0], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        _fail(stream, field, f"{value!r} is not a real calendar instant",
              "invalid_timestamp")


def check_enum(value, *, field, stream, allowed) -> None:
    if value not in allowed:
        _fail(stream, field,
              f"{value!r} is not one of {sorted(map(str, allowed))}",
              "not_in_enum")


def looks_like_onchain_identifier(value: object) -> bool:
    """True if a value looks like an address or hex blob.

    Hidden identifiers must be opaque handles. If a hidden id were set to a
    real address it would legitimately appear in the public streams, and the
    value-leak scan in experiments.labels.selfcheck would be unable to tell
    leakage from normal recording.
    """
    return isinstance(value, str) and bool(RE_HEX_ANY.match(value))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
