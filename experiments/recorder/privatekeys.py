"""The canonical list of field names that may never appear in public output.

Used in three places:

1. ``experiments.recorder.validate`` rejects any attacker-visible record
   containing one of these keys, at any nesting depth.
2. ``experiments.labels.selfcheck`` scans already-written public output for
   them (defence in depth: catches records produced by some future path
   that bypassed the validator).
3. The same scan looks for hidden identifier *values* copied into public
   output under a renamed key.

This is a denylist on top of a strict allow-list schema, not instead of it.
A key not on this list is still rejected by the public streams if it is not
in their schema. Neither check proves the absence of all label leakage --
see docs/experiment-schema.md, "Known limitations".
"""

from __future__ import annotations

#: Hidden identifiers and relation labels. Never in public_events or
#: bundler_private, under any nesting.
FORBIDDEN_PRIVATE_KEYS = frozenset(
    {
        # hidden actor / account identity (docs/research-plan.md Sec. 10)
        "actor_id",
        "established_wallet_id",
        "funding_wallet_id",
        "asset_sender_id",
        "stealth_account_id",
        # credit lifecycle identity
        "credit_id",
        "issuance_id",
        # relation labels (R1 / R2 / R3)
        "payer_to_operation_label",
        "issuance_to_redemption_label",
        "stealth_to_actor_label",
        "intended_relation_labels",
        "relation_labels",
        # experiment randomness: the seed determines the hidden assignment of
        # actors to accounts, so publishing it publishes the answer key.
        # See docs/experiment-schema.md, "Ambiguous classifications".
        "seed",
        # generic aliases that would defeat the point of the list
        "ground_truth",
        "label",
        "labels",
        "true_value",
        "secret",
    }
)

#: Ground-truth fields holding an opaque hidden identifier. The value scan in
#: experiments.labels.selfcheck looks for these values in public output.
HIDDEN_ID_FIELDS = (
    "actor_id",
    "established_wallet_id",
    "funding_wallet_id",
    "asset_sender_id",
    "stealth_account_id",
    "credit_id",
    "issuance_id",
)
