"""The single sanctioned path from predictions to labels.

``join_for_evaluation`` is the only function in this repository that puts a
prediction and a secret label in the same data structure. It refuses to do so
unless the predictions were frozen first:

1. the frozen manifest must exist,
2. the predictions file must still hash to the digest recorded in it,
3. the manifest must name which relation and which feature set the attack
   used.

Only then are labels loaded and joined. If the file changed after freezing,
the join raises rather than scoring -- the point is that "look at the
answers, then adjust the predictions" leaves evidence instead of a number.

What this module does NOT do: compute metrics, or return anything that could
be fed back into feature generation. It returns aligned (prediction, label)
pairs plus counts, and the metric code (top-1, top-k, AUPRC, Brier,
posterior entropy, effective candidate-set size -- docs/research-plan.md
Sec. 9.1) is written on top of it. That code does not exist yet: Prompt 3 builds
the recording infrastructure, not the attacks or their evaluation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..recorder import paths as paths_mod
from ..recorder.digest import sha256_file
from .loader import GroundTruthRun, load_ground_truth


class FrozenPredictionsError(RuntimeError):
    """Predictions were missing, unfrozen, or modified after freezing."""


@dataclass(frozen=True)
class JoinedRow:
    subject_ref: str
    prediction: Any
    #: None where the attack predicted a subject that has no label at all.
    label: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class EvaluationJoin:
    experiment_id: str
    run_id: str
    attack_id: str
    relation: str
    feature_set: str
    observer_tier: str
    rows: Tuple[JoinedRow, ...]
    #: Labelled subjects the attack made no prediction about. Kept and
    #: reported: silently dropping them would inflate precision.
    unpredicted_subject_refs: Tuple[str, ...]
    #: Predicted subjects with no corresponding label.
    unlabelled_subject_refs: Tuple[str, ...]

    @property
    def label_status_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in self.rows:
            status = row.label["status"] if row.label else "no_label"
            counts[status] = counts.get(status, 0) + 1
        return counts


def join_for_evaluation(*, experiment_id: str, run_id: str, attack_id: str,
                        relation: str, root: Optional[Path] = None,
                        ground_truth: Optional[GroundTruthRun] = None
                        ) -> EvaluationJoin:
    rp = paths_mod.run_paths(experiment_id, run_id, root)
    pred_dir = rp.predictions_dir / attack_id / relation
    manifest_path = pred_dir / "predictions.manifest.json"
    if not manifest_path.is_file():
        raise FrozenPredictionsError(
            f"{manifest_path} does not exist. Labels are joined only against "
            "predictions that were frozen first by "
            "experiments.attacker_view.freeze_predictions."
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pred_path = pred_dir / manifest["predictions_file"]
    if not pred_path.is_file():
        raise FrozenPredictionsError(
            f"{pred_path} is named by the manifest but does not exist")

    actual = sha256_file(pred_path)
    if actual != manifest["predictions_sha256"]:
        raise FrozenPredictionsError(
            f"{pred_path} has changed since it was frozen "
            f"(recorded {manifest['predictions_sha256'][:16]}..., found "
            f"{actual[:16]}...). Predictions must be final before any label is "
            "read; re-run the attack under a new attack_id instead of editing "
            "a frozen file."
        )
    if manifest["relation"] != relation:
        raise FrozenPredictionsError(
            f"frozen manifest is for relation {manifest['relation']!r}, not "
            f"{relation!r}")

    predictions: List[Dict[str, Any]] = []
    with open(pred_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                predictions.append(json.loads(line))

    gt = ground_truth or load_ground_truth(experiment_id, run_id, root)
    labels = gt.labels_for(relation)

    rows = tuple(
        JoinedRow(subject_ref=p["subject_ref"], prediction=p["prediction"],
                  label=labels.get(p["subject_ref"]))
        for p in predictions
    )
    predicted_refs = {p["subject_ref"] for p in predictions}
    unpredicted = tuple(sorted(set(labels) - predicted_refs))
    unlabelled = tuple(sorted(predicted_refs - set(labels)))

    return EvaluationJoin(
        experiment_id=experiment_id, run_id=run_id, attack_id=attack_id,
        relation=relation, feature_set=manifest["feature_set"],
        observer_tier=manifest["observer_tier"], rows=rows,
        unpredicted_subject_refs=unpredicted,
        unlabelled_subject_refs=unlabelled,
    )
