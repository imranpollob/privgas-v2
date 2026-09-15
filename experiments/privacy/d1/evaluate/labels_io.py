"""Ground-truth access for the D1 evaluation (private side only)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ....labels import load_ground_truth
from ....recorder import paths as paths_mod
from .. import splits

ANCHOR_FOR = {"R1": "economic_funding_address", "R2": "issuance_userop_hash",
              "R3": "established_wallet_address"}


def batch_dir(root: Path, batch: str) -> Path:
    return root / "results" / "d1-pilot" / batch


def truth_refs(root: Path, experiment_id: str, run_id: str, relation: str
               ) -> Dict[str, Optional[str]]:
    """subject_ref -> the true candidate's PUBLIC ref (from public_anchors), for
    labels with status observed; None for status absent."""
    gt = load_ground_truth(experiment_id, run_id, root)
    field = {"R1": "payer_to_operation_label", "R2": "issuance_to_redemption_label",
             "R3": "stealth_to_actor_label"}[relation]
    out: Dict[str, Optional[str]] = {}
    for row in gt.rows:
        lab = row[field]
        if lab["status"] == "not_applicable":
            continue
        anchor = row["public_anchors"][ANCHOR_FOR[relation]]
        out[lab["subject_ref"]] = (anchor.lower() if lab["status"] == "observed" and anchor
                                   else None)
    return out


def private_run(root: Path, experiment_id: str, run_id: str) -> Dict[str, Any]:
    rp = paths_mod.run_paths(experiment_id, run_id, root)
    return json.loads((rp.private_run_dir / "d1_private_run.json").read_text())


def load_splits_verified(root: Path, batch: str) -> Tuple[Dict[str, Any], str]:
    d = batch_dir(root, batch)
    body = json.loads((d / "splits.json").read_text())
    sha = splits.canonical_sha256(body)
    if sha != (d / "splits.sha256").read_text().strip():
        raise RuntimeError("splits.json changed after freezing")
    return body, sha


def export_training_labels(root: Path, batch: str) -> Dict[str, Any]:
    """One directory per fold with labels of that fold's TRAINING runs only."""
    body, sha = load_splits_verified(root, batch)
    base = batch_dir(root, batch) / "training_labels"
    if base.exists():
        raise SystemExit(f"{base} exists; training labels are exported once per frozen split")
    summary = {}
    for fold in body["folds"]:
        train = [tuple(x) for x in fold["train_runs"]]
        test = {tuple(x) for x in fold["test_runs"]}
        if test & set(train):
            raise RuntimeError(f"{fold['fold_id']}: refusing to export -- a test run is listed "
                               "as a training run")
        d = base / fold["fold_id"]
        d.mkdir(parents=True)
        files = {}
        for rel in ("R1", "R2", "R3"):
            lines = []
            for exp, run in train:
                if (exp, run) in test:  # pragma: no cover - guarded above
                    raise RuntimeError("test run in export")
                for ref, truth in sorted(truth_refs(root, exp, run, rel).items()):
                    if truth is None:
                        continue
                    lines.append(json.dumps({"experiment_id": exp, "run_id": run,
                                             "subject_ref": ref, "true_candidate_ref": truth},
                                            sort_keys=True))
            if lines:
                data = ("\n".join(lines) + "\n").encode()
                (d / f"{rel}.jsonl").write_bytes(data)
                files[rel] = hashlib.sha256(data).hexdigest()
        (d / "manifest.json").write_text(json.dumps({
            "fold_id": fold["fold_id"], "split_sha256": sha, "train_runs": fold["train_runs"],
            "files": files, "exported_at_utc": datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "note": "Binary pair labels (subject -> true candidate PUBLIC ref) for this fold's "
                    "training runs only. No hidden handle is included."}, indent=2) + "\n")
        summary[fold["fold_id"]] = files
    return summary
