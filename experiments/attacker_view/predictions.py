"""Freezing predictions before any label is ever touched.

The workflow this enforces (docs/experiment-schema.md, "Label-join rule"):
predictions are written to disk together with a sha256 over their exact
bytes. ``experiments.labels.evaluation`` refuses to join labels unless the
file still hashes to the recorded digest. An attack process therefore cannot
see a label, adjust a prediction, and re-score: any edit after freezing
invalidates the digest, and the digest was written by a process that could
not import the labels package at all.

This is a discipline mechanism, not a security mechanism against a
determined author of both scripts. It makes the honest workflow the path of
least resistance and makes a violation visible in the recorded artefacts.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ..recorder import paths as paths_mod
from ..recorder.digest import canonical_json, sha256_file
from ..recorder.version import SCHEMA_VERSION

PREDICTIONS_FILE = "predictions.jsonl"
MANIFEST_FILE = "predictions.manifest.json"

#: Families in canonical order T, AA, G (2026-09-15: AA added for the D1 pilot;
#: the original "T" / "G" / "T+G" values remain valid).
RE_FEATURE_SET = re.compile(
    r"^(?:none|T|AA|G|T\+AA|T\+G|AA\+G|T\+AA\+G)(?:-minus-[a-z]+(?:_[a-z]+)*)*$")


def freeze_predictions(
    *,
    experiment_id: str,
    run_id: str,
    attack_id: str,
    relation: str,
    observer_tier: str,
    predictions: Iterable[Mapping[str, Any]],
    feature_set: str,
    root: Optional[Path] = None,
    now: Optional[datetime] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Write predictions plus a manifest that pins their bytes.

    ``relation`` is "R1", "R2" or "R3": predictions are made and scored per
    relation and are never pooled into one "unlinkability" number
    (docs/threat-model.md).

    ``feature_set`` records which information the attack was allowed to use --
    a combination of the feature families T (application trace), AA
    (account-abstraction trace) and G (gas-mechanism trace) of the D1 feature
    registry (docs/d1-feature-registry.md), e.g. "T", "T+AA", "G", "T+G",
    "T+AA+G", optionally followed by ablation suffixes such as
    "-minus-timing" (docs/research-plan.md Sec. 9.2). "none" is an attack
    that uses no public feature (a chance baseline). Writing it at freeze time
    means the comparison cannot be relabelled afterwards.

    Each prediction row must carry at least ``subject_ref``, which is matched
    against the ``subject_ref`` of the corresponding ground-truth relation
    label at evaluation time.
    """
    if relation not in ("R1", "R2", "R3"):
        raise ValueError(f"relation must be R1, R2 or R3; got {relation!r}")
    if not RE_FEATURE_SET.match(feature_set):
        raise ValueError(
            "feature_set must be 'none' or a '+'-joined combination of T, AA, G "
            "in that order (e.g. 'T+AA+G'), optionally followed by "
            f"'-minus-<family>' ablation suffixes; got {feature_set!r}")

    rp = paths_mod.run_paths(experiment_id, run_id, root)
    out_dir = rp.predictions_dir / attack_id / relation
    out_dir.mkdir(parents=True, exist_ok=True)
    pred_path = out_dir / PREDICTIONS_FILE
    manifest_path = out_dir / MANIFEST_FILE

    if pred_path.exists():
        raise FileExistsError(
            f"{pred_path} already exists. Frozen predictions are never "
            "overwritten -- re-running an attack produces a new attack_id.")

    count = 0
    with open(pred_path, "w", encoding="utf-8") as fh:
        for row in predictions:
            if "subject_ref" not in row:
                raise ValueError(
                    "every prediction row needs a 'subject_ref' naming the "
                    "attacker-visible subject it is about")
            if "prediction" not in row:
                raise ValueError("every prediction row needs a 'prediction'")
            fh.write(canonical_json(dict(row)).decode("utf-8"))
            fh.write("\n")
            count += 1

    frozen_at = (now or datetime.now(timezone.utc)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "attack_id": attack_id,
        "relation": relation,
        "observer_tier": observer_tier,
        "feature_set": feature_set,
        "prediction_count": count,
        "predictions_file": PREDICTIONS_FILE,
        "predictions_sha256": sha256_file(pred_path),
        "frozen_at_utc": frozen_at,
    }
    if extra:
        # Attack provenance (model configuration, training runs and the digests
        # of any training-label files read). Cannot override the fields above.
        clash = sorted(set(extra) & set(manifest))
        if clash:
            raise ValueError(f"extra manifest keys {clash} clash with frozen fields")
        manifest["attack_provenance"] = dict(extra)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest
