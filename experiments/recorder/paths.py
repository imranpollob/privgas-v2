"""On-disk layout for the three streams.

Directory separation is part of the enforcement, not just tidiness
(Prompt 3 Sec. 10, "Do not mix A2 data into A0/A1 datasets"):

    data/public/<experiment_id>/<run_id>/
        observer_a0a1/public_events.jsonl     tier A0/A1
        observer_a2/bundler_private.jsonl     tier A2 -- instrumented bundler
        run_manifest.public.json

    data/private/<experiment_id>/<run_id>/
        ground_truth.jsonl                    SECRET
        run_manifest.private.json             SECRET (holds the seed)

    data/raw/<experiment_id>/<run_id>/        raw chain / bundler dumps

Why the tiers are separate directories rather than separate files in one
directory: an A0/A1 dataset is assembled by pointing at
``observer_a0a1/``. Adding A2 data to such a run then requires naming the
other directory explicitly. A glob over the A0/A1 directory cannot pick up
bundler data by accident.

``data/private/**`` is gitignored by the repository's existing policy
(docs/decision-log.md, 2026-09-13). ``data/public/`` is not, because public
observations are the publishable artefact -- but see
docs/experiment-schema.md, "Known limitations", on running the leakage
self-check before any such directory is committed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .provenance import repo_root
from .version import (
    STREAM_BUNDLER_PRIVATE,
    STREAM_GROUND_TRUTH,
    STREAM_PUBLIC_EVENTS,
)

PUBLIC_ROOT = "data/public"
PRIVATE_ROOT = "data/private"
RAW_ROOT = "data/raw"

DIR_A0A1 = "observer_a0a1"
DIR_A2 = "observer_a2"

PUBLIC_EVENTS_FILE = "public_events.jsonl"
BUNDLER_PRIVATE_FILE = "bundler_private.jsonl"
GROUND_TRUTH_FILE = "ground_truth.jsonl"
PUBLIC_MANIFEST_FILE = "run_manifest.public.json"
PRIVATE_MANIFEST_FILE = "run_manifest.private.json"
PREDICTIONS_DIR = "predictions"


@dataclass(frozen=True)
class RunPaths:
    root: Path
    experiment_id: str
    run_id: str

    # --- attacker-visible ---------------------------------------------------
    @property
    def public_run_dir(self) -> Path:
        return self.root / PUBLIC_ROOT / self.experiment_id / self.run_id

    @property
    def a0a1_dir(self) -> Path:
        return self.public_run_dir / DIR_A0A1

    @property
    def a2_dir(self) -> Path:
        return self.public_run_dir / DIR_A2

    @property
    def public_events_path(self) -> Path:
        return self.a0a1_dir / PUBLIC_EVENTS_FILE

    @property
    def bundler_private_path(self) -> Path:
        return self.a2_dir / BUNDLER_PRIVATE_FILE

    @property
    def public_manifest_path(self) -> Path:
        return self.public_run_dir / PUBLIC_MANIFEST_FILE

    @property
    def predictions_dir(self) -> Path:
        return self.public_run_dir / PREDICTIONS_DIR

    # --- secret --------------------------------------------------------------
    @property
    def private_run_dir(self) -> Path:
        return self.root / PRIVATE_ROOT / self.experiment_id / self.run_id

    @property
    def ground_truth_path(self) -> Path:
        return self.private_run_dir / GROUND_TRUTH_FILE

    @property
    def private_manifest_path(self) -> Path:
        return self.private_run_dir / PRIVATE_MANIFEST_FILE

    # --- raw inputs ----------------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        return self.root / RAW_ROOT / self.experiment_id / self.run_id

    def stream_path(self, stream: str) -> Path:
        return {
            STREAM_PUBLIC_EVENTS: self.public_events_path,
            STREAM_BUNDLER_PRIVATE: self.bundler_private_path,
            STREAM_GROUND_TRUTH: self.ground_truth_path,
        }[stream]

    def ensure_dirs(self) -> None:
        for d in (self.a0a1_dir, self.a2_dir, self.private_run_dir):
            d.mkdir(parents=True, exist_ok=True)


def run_paths(experiment_id: str, run_id: str,
              root: Optional[Path] = None) -> RunPaths:
    return RunPaths(root=Path(root) if root else repo_root(),
                    experiment_id=experiment_id, run_id=run_id)


def is_private_path(path: Path, root: Optional[Path] = None) -> bool:
    """True if ``path`` lies under data/private/. Used by the attacker-side guard."""
    root = Path(root) if root else repo_root()
    try:
        resolved = Path(path).resolve()
    except OSError:  # pragma: no cover - defensive
        return True
    private = (root / PRIVATE_ROOT).resolve()
    return resolved == private or private in resolved.parents
