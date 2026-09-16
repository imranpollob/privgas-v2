"""D2K record fields: the frozen D2 tiers plus the history-specific ones.

The frozen pilot's classification (``experiments/liveness/d2/records.py``) is imported
unchanged and EXTENDED; no frozen field changes tier or meaning. A field that is not
classified still cannot be written.

New ``control`` fields name the experimental condition (which root-acceptance component,
what capacity). New ``A0`` fields are things a public observer can read off the chain
(the retained roots are public state of the Paymaster). New ``derived`` fields are
analysis labels computed from the arrival timeline and the retention rule.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping

from ..d2.records import ARRIVAL_FIELD_TIERS as D2_ARRIVAL_FIELD_TIERS
from ..d2.records import FIELD_TIERS as D2_FIELD_TIERS
from ..d2.records import UnclassifiedField, check_classified, project, read_jsonl, write_jsonl

D2K_FIELDS: Dict[str, str] = {
    # control -- the experimental condition
    "variant": "control",              # "frozen" | "K<k>"
    "history_capacity": "control",     # K (1 for the frozen control)
    "deployment_shape": "control",     # "fanout" | "dedicated"
    "intervening_root_updates": "control",
    "bundle_size_planned": "control",
    "batch": "control",
    # A0 -- public Paymaster state
    "history_length_at_inclusion": "A0",
    "root_age_at_inclusion": "A0",
    "accepted_root_age": "A0",
    # derived
    "root_updates_in_window": "derived",
    "root_updates_survived": "derived",
    "evicted_in_window": "derived",
    "predicted_valid": "derived",
    "prediction_matches_outcome": "derived",
}

FIELD_TIERS: Dict[str, str] = {**D2_FIELD_TIERS, **D2K_FIELDS}

ARRIVAL_FIELD_TIERS: Dict[str, str] = {
    **D2_ARRIVAL_FIELD_TIERS,
    "variant": "control", "history_capacity": "control", "batch": "control",
    "deployment_shape": "control",
}

__all__ = ["FIELD_TIERS", "ARRIVAL_FIELD_TIERS", "D2K_FIELDS", "UnclassifiedField",
           "check_classified", "project", "read_jsonl", "write_jsonl"]
