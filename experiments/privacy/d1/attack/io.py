"""Attacker-side inputs: public runs, the wallet directory, splits, fold labels."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from ....attacker_view import PrivateDataAccessError, load_run
from ....attacker_view.readers import _guard_path
from ....recorder import paths as paths_mod
from ....workloads.d1.config import parse_experiment_id
from .. import extract, splits

WALLET_DIRECTORY = Path("auxiliary") / "r3_wallet_directory.json"


def batch_dir(root: Path, batch: str) -> Path:
    return root / "results" / "d1-pilot" / batch


def load_dataset_manifest(root: Path, batch: str) -> Dict[str, Any]:
    return json.loads((batch_dir(root, batch) / "dataset_manifest.json").read_text())


def load_splits(root: Path, batch: str) -> Tuple[Dict[str, Any], str]:
    d = batch_dir(root, batch)
    body = json.loads((d / "splits.json").read_text())
    recorded = (d / "splits.sha256").read_text().strip()
    actual = splits.canonical_sha256(body)
    if actual != recorded:
        raise RuntimeError(f"splits.json changed after it was frozen ({actual} != {recorded})")
    return body, actual


def load_trace(root: Path, experiment_id: str, run_id: str) -> extract.RunTrace:
    run = load_run(experiment_id, run_id, "A0", root=root)
    rp = paths_mod.run_paths(experiment_id, run_id, root)
    wd_path = _guard_path(rp.public_run_dir / WALLET_DIRECTORY, root)
    directory = json.loads(wd_path.read_text())["candidate_wallet_addresses"]
    info = parse_experiment_id(experiment_id)
    if info["baseline_id"] != run.baseline_id:
        raise ValueError(f"{experiment_id}: manifest baseline {run.baseline_id} disagrees")
    return extract.make_trace(experiment_id, run_id, run.baseline_id, info["pool_size"],
                              run.manifest, run.public_events, directory)


def load_fold_training_labels(root: Path, batch: str, fold: Mapping[str, Any], relation: str,
                              split_sha: str) -> Tuple[Dict[Tuple[str, str, str], str],
                                                       Dict[str, Any]]:
    """(experiment_id, run_id, subject_ref) -> true candidate ref, for the fold's
    TRAINING runs only. Refuses anything else and returns the provenance record."""
    d = batch_dir(root, batch) / "training_labels" / fold["fold_id"]
    manifest = json.loads((d / "manifest.json").read_text())
    if manifest["fold_id"] != fold["fold_id"] or manifest["split_sha256"] != split_sha:
        raise PrivateDataAccessError(f"training labels in {d} were not exported for this fold "
                                     "and this frozen split")
    train = {tuple(x) for x in fold["train_runs"]}
    test = {tuple(x) for x in fold["test_runs"]}
    path = d / f"{relation}.jsonl"
    if not path.is_file():
        return {}, {"fold_id": fold["fold_id"], "file": None, "sha256": None, "runs": []}
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if sha != manifest["files"][relation]:
        raise PrivateDataAccessError(f"{path} changed after export")
    out: Dict[Tuple[str, str, str], str] = {}
    runs_read = set()
    for line in raw.decode().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        key = (row["experiment_id"], row["run_id"])
        if key in test or key not in train:
            raise PrivateDataAccessError(
                f"{path} carries a label for {key}, which is not a training run of "
                f"{fold['fold_id']}; refusing to train")
        runs_read.add(key)
        out[(row["experiment_id"], row["run_id"], row["subject_ref"])] = row["true_candidate_ref"]
    return out, {"fold_id": fold["fold_id"], "file": str(path.relative_to(root)),
                 "sha256": sha, "runs": sorted(list(r) for r in runs_read)}
