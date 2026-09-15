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

#: 5.0.0 (2026-09-14): the frozen B3 specimen becomes measurable. baseline_id
#: "B3" renamed "B3-PrivGas-v1"; public_events gains event types
#: stealth_announcement / sponsorship_eligibility and calldata classes
#: stealth_announce_and_fund / fee_burn / paymaster_sponsorship / pool_root_update,
#: with deterministic trace_phase rules for them (privacy_pool_event rows now
#: need a pool calldata class); ground_truth public_anchors gains
#: issuance_transaction_hash / issuance_userop_hash / credit_commitment /
#: credit_nullifier (the R2 join bridge), required non-null for an observed R2
#: label and null for baselines without a credit system. MAJOR: an enum value
#: was renamed and a closed sub-object gained required keys.
#: 4.0.0 (2026-09-14): R1 refined -- ground_truth funding_wallet_id renamed
#: economic_funding_source_id, immediate_gas_payer_kind added, public_anchors
#: funding_address split into economic_funding_address and
#: immediate_gas_payer_address; public_events gains trace_phase so the complete
#: public trace (including setup-time transactions) is recorded.
#: 3.0.0 (2026-09-14): baseline_id "B2" split into "B2-Allowlist" and
#: "B2-Signature"; workload_id "W1" split into "W1-cold" and "W1-warm". An
#: existing enum value changed meaning, hence MAJOR. See
#: docs/experiment-schema.md Sec. 9.0.
#: 2.0.0 (2026-09-14): corrections forced by the first real B0/B1/B2 runs --
#: see docs/decision-log.md "Schema 2.0.0" and docs/w1-baselines.md Sec. 14.
#: MAJOR because a bundler_private field was removed/renamed and field tier
#: semantics changed. 1.0.0 rows (synthetic fixtures only; no measured 1.0.0
#: data ever existed) are not readable by this code.
SCHEMA_VERSION = "5.0.0"

#: Versions this code can read and validate. Explicit allow-list on purpose.
SUPPORTED_SCHEMA_VERSIONS = frozenset({"5.0.0"})

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
