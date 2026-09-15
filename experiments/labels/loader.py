"""Loading secret ground truth. Evaluation only.

Deliberately *not* provided here: any function that returns labels keyed by
something an attack could feed it, or that merges labels into an observation
table. The only sanctioned consumer of these rows is
``experiments.labels.evaluation``, which requires frozen predictions first.

Two research rules are encoded in the helpers below rather than left to the
reader's discipline:

* ``accounts_by_actor`` makes the many-to-one account/actor mapping explicit
  and is the only aggregation offered. There is no ``actor_by_account``
  inverse that returns a single actor per account with an implied guarantee
  of uniqueness -- an account may be shared, and a scenario may deliberately
  have one actor hold several accounts. Multiple addresses are not multiple
  people.
* ``credits_by_actor`` likewise. Several credits belonging to one actor is
  the normal case in a Sybil-aware experiment; distinct commitments are not
  evidence of distinct honest participants.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..recorder import paths as paths_mod
from ..recorder.version import (
    STREAM_GROUND_TRUTH,
    SUPPORTED_SCHEMA_VERSIONS,
)


@dataclass(frozen=True)
class GroundTruthRun:
    experiment_id: str
    run_id: str
    manifest: Dict[str, Any]
    rows: Tuple[Dict[str, Any], ...]

    @property
    def seed(self) -> int:
        return self.manifest["seed"]

    def labels_for(self, relation: str) -> Dict[str, Dict[str, Any]]:
        """subject_ref -> relation label, for one relation only.

        R1/R2/R3 are always requested one at a time. There is no helper that
        returns all three together, because a combined structure invites a
        single pooled "unlinkability" score, which this project does not
        report (docs/threat-model.md).
        """
        field = {
            "R1": "payer_to_operation_label",
            "R2": "issuance_to_redemption_label",
            "R3": "stealth_to_actor_label",
        }[relation]
        out: Dict[str, Dict[str, Any]] = {}
        for row in self.rows:
            label = row[field]
            if label["status"] == "not_applicable":
                continue
            ref = label["subject_ref"]
            if ref in out and out[ref] != label:
                raise ValueError(
                    f"conflicting {relation} labels for subject_ref {ref!r} in "
                    f"run {self.run_id}")
            out[ref] = label
        return out


def load_ground_truth(experiment_id: str, run_id: str,
                      root: Optional[Path] = None) -> GroundTruthRun:
    rp = paths_mod.run_paths(experiment_id, run_id, root)
    manifest = load_private_manifest(experiment_id, run_id, root)
    rows: List[Dict[str, Any]] = []
    with open(rp.ground_truth_path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
                raise ValueError(
                    f"{rp.ground_truth_path}:{lineno} has unsupported "
                    f"schema_version {row.get('schema_version')!r}")
            if row.get("stream") != STREAM_GROUND_TRUTH:
                raise ValueError(
                    f"{rp.ground_truth_path}:{lineno} is not a ground_truth row")
            rows.append(row)
    return GroundTruthRun(experiment_id=experiment_id, run_id=run_id,
                          manifest=manifest, rows=tuple(rows))


def load_private_manifest(experiment_id: str, run_id: str,
                          root: Optional[Path] = None) -> Dict[str, Any]:
    rp = paths_mod.run_paths(experiment_id, run_id, root)
    return json.loads(rp.private_manifest_path.read_text(encoding="utf-8"))


def accounts_by_actor(run: GroundTruthRun) -> Dict[str, Set[str]]:
    """actor_id -> every account handle attributed to that actor.

    One actor commonly holds several accounts. Callers must not invert this
    into an assumption that distinct accounts imply distinct actors.
    """
    out: Dict[str, Set[str]] = defaultdict(set)
    for row in run.rows:
        actor = row.get("actor_id")
        if not isinstance(actor, str) or actor == "not_applicable":
            continue
        for field in ("stealth_account_id", "established_wallet_id",
                      "economic_funding_source_id", "asset_sender_id"):
            value = row.get(field)
            if isinstance(value, str) and value != "not_applicable":
                out[actor].add(value)
    return dict(out)


def credits_by_actor(run: GroundTruthRun) -> Dict[str, Set[str]]:
    """actor_id -> every credit handle attributed to that actor.

    Several credits per actor is the normal case. Distinct commitments are
    not evidence of distinct honest participants.
    """
    out: Dict[str, Set[str]] = defaultdict(set)
    for row in run.rows:
        actor = row.get("actor_id")
        credit = row.get("credit_id")
        if isinstance(actor, str) and actor != "not_applicable" \
                and isinstance(credit, str) and credit != "not_applicable":
            out[actor].add(credit)
    return dict(out)
