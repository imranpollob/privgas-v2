"""Schema version and the compatibility policy for changing it.

Canonical documentation: docs/experiment-schema.md ("Schema versioning").
This module is the machine-readable copy; the two must not disagree.

Versioning scheme: ``MAJOR.MINOR.PATCH``.

  MAJOR  incompatible change. Any of: removing a field, renaming a field,
         narrowing an enum, changing a field's type or units, changing the
         meaning of an existing value, moving a field between streams, or
         reclassifying a field from private to public (or public to
         private). Old readers must NOT accept the new rows, so the new
         MAJOR is simply absent from SUPPORTED_SCHEMA_VERSIONS of the old
         code and present in the new.

  MINOR  backward-compatible addition. Adding a new optional-but-required-key
         field whose "not present for this row" value is documented, adding
         a new enum member to an open enum, or adding a new stream. Readers
         written for an earlier MINOR of the same MAJOR can still parse the
         rows (they will simply ignore the new key).

  PATCH  no change to record content at all: documentation, error messages,
         validator performance. A PATCH bump never changes what validates.

Rules:
  * Every row carries its own ``schema_version``. Records are never
    rewritten in place to a new version; a re-recorded run gets a new
    run_id.
  * ``SUPPORTED_SCHEMA_VERSIONS`` is an explicit allow-list. An unknown
    version is a hard validation failure, not a warning, in both directions
    (too old and too new).
  * Semantics of an already-released version are frozen. If a definition
    turns out to be wrong, it is corrected under a new MAJOR, and
    docs/decision-log.md records why.
"""

from __future__ import annotations

SCHEMA_VERSION = "1.0.0"

#: Versions this code can read and validate. Explicit allow-list on purpose.
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0.0"})

STREAM_GROUND_TRUTH = "ground_truth"
STREAM_PUBLIC_EVENTS = "public_events"
STREAM_BUNDLER_PRIVATE = "bundler_private"

STREAMS = (STREAM_GROUND_TRUTH, STREAM_PUBLIC_EVENTS, STREAM_BUNDLER_PRIVATE)

#: Which streams a given observer tier is allowed to read.
#: A3 (service collusion) is deliberately not implemented (Prompt 3 Sec. 10).
OBSERVER_TIER_STREAMS = {
    "A0": (STREAM_PUBLIC_EVENTS,),
    "A1": (STREAM_PUBLIC_EVENTS,),
    "A2": (STREAM_PUBLIC_EVENTS, STREAM_BUNDLER_PRIVATE),
}

#: Tiers that may appear in each stream's ``observer_tier`` field.
STREAM_ALLOWED_TIERS = {
    STREAM_PUBLIC_EVENTS: ("A0", "A1"),
    STREAM_BUNDLER_PRIVATE: ("A2",),
}
