"""Readers for attacker-visible streams, with an explicit tier argument.

Two guards beyond the package-level import boundary:

1. **Path guard.** Every read goes through ``_guard_path``, which refuses any
   path under ``data/private/``. Even if an attack script constructs the path
   by hand, it cannot read the ground-truth file through these helpers.

2. **Tier guard.** ``load_run`` takes the observer tier explicitly and returns
   bundler data only for A2. An A0/A1 dataset cannot acquire bundler
   knowledge by forgetting to filter -- the caller has to name the tier, and
   naming A2 is a deliberate, visible act (docs/threat-model.md: A2 is only
   usable with bundlers we operate or have permission to log).

Nothing here validates records a second time: the recorder validated before
writing, so a stream file on disk is schema-valid in full. The readers do
check ``schema_version`` and ``stream``, because a file can be moved, renamed
or concatenated after the fact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..recorder import paths as paths_mod
from ..recorder.version import (
    OBSERVER_TIER_STREAMS,
    STREAM_BUNDLER_PRIVATE,
    STREAM_PUBLIC_EVENTS,
    SUPPORTED_SCHEMA_VERSIONS,
)


class PrivateDataAccessError(PermissionError):
    """Attacker-side code tried to read secret ground truth."""


def _guard_path(path: Path, root: Optional[Path] = None) -> Path:
    path = Path(path)
    if paths_mod.is_private_path(path, root):
        raise PrivateDataAccessError(
            f"{path} is under data/private/. Attacker-side code cannot read "
            "secret ground truth; use experiments.labels in a separate "
            "process, after predictions are frozen."
        )
    if paths_mod.is_raw_path(path, root):
        raise PrivateDataAccessError(
            f"{path} is under data/raw/. Raw chain and bundler dumps carry run "
            "phases and raw bundler errors; attacker-side code reads the recorded "
            "public streams only.")
    if path.name in (paths_mod.GROUND_TRUTH_FILE,
                     paths_mod.PRIVATE_MANIFEST_FILE):
        raise PrivateDataAccessError(
            f"{path.name} is a secret-stream filename and is never readable "
            "from attacker-side code, wherever it has been moved to."
        )
    return path


def _iter_jsonl(path: Path, expect_stream: str) -> Iterator[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
                raise ValueError(
                    f"{path}:{lineno} declares schema_version "
                    f"{row.get('schema_version')!r}, which this code does not "
                    f"support ({sorted(SUPPORTED_SCHEMA_VERSIONS)})")
            if row.get("stream") != expect_stream:
                raise ValueError(
                    f"{path}:{lineno} declares stream {row.get('stream')!r} but "
                    f"was read as {expect_stream!r}")
            yield row


def load_public_events(path: Path, root: Optional[Path] = None
                       ) -> List[Dict[str, Any]]:
    """Tier A0/A1 observations."""
    return list(_iter_jsonl(_guard_path(path, root), STREAM_PUBLIC_EVENTS))


def load_bundler_private(path: Path, root: Optional[Path] = None
                         ) -> List[Dict[str, Any]]:
    """Tier A2 observations from an instrumented bundler we operate."""
    return list(_iter_jsonl(_guard_path(path, root), STREAM_BUNDLER_PRIVATE))


def load_public_manifest(path: Path, root: Optional[Path] = None
                         ) -> Dict[str, Any]:
    p = _guard_path(path, root)
    manifest = json.loads(p.read_text(encoding="utf-8"))
    if manifest.get("seed") is not None:
        raise PrivateDataAccessError(
            f"{p} carries a seed value. The seed determines the hidden actor "
            "assignment and must stay in the private manifest; only its "
            "commitment belongs in public output.")
    return manifest


@dataclass(frozen=True)
class AttackerRun:
    experiment_id: str
    run_id: str
    observer_tier: str
    manifest: Dict[str, Any]
    public_events: Tuple[Dict[str, Any], ...]
    bundler_private: Tuple[Dict[str, Any], ...]

    @property
    def baseline_id(self) -> str:
        return self.manifest["baseline_id"]


def load_run(experiment_id: str, run_id: str, observer_tier: str,
             root: Optional[Path] = None) -> AttackerRun:
    """Load one run at one explicitly named observer tier.

    ``observer_tier`` is required, not defaulted: which tier an attack is
    evaluated at is a claim the experiment has to make out loud
    (docs/threat-model.md, "Process rule").
    """
    if observer_tier not in OBSERVER_TIER_STREAMS:
        raise ValueError(
            f"unknown observer tier {observer_tier!r}; implemented: "
            f"{sorted(OBSERVER_TIER_STREAMS)} (A3 is deliberately not "
            "implemented)")
    rp = paths_mod.run_paths(experiment_id, run_id, root)
    manifest = load_public_manifest(rp.public_manifest_path, root)

    events = load_public_events(rp.public_events_path, root)

    bundler: List[Dict[str, Any]] = []
    if STREAM_BUNDLER_PRIVATE in OBSERVER_TIER_STREAMS[observer_tier]:
        if rp.bundler_private_path.exists():
            bundler = load_bundler_private(rp.bundler_private_path, root)

    if observer_tier in ("A0", "A1"):
        # Defence in depth: an A0/A1 dataset must not contain A2 rows even if
        # someone copied the file into the wrong directory.
        for row in events:
            if row.get("observer_tier") == "A2":
                raise ValueError(
                    f"{rp.public_events_path} contains an A2 row; bundler "
                    "observations must not be mixed into an A0/A1 dataset")

    return AttackerRun(experiment_id=experiment_id, run_id=run_id,
                       observer_tier=observer_tier, manifest=manifest,
                       public_events=tuple(events),
                       bundler_private=tuple(bundler))


def list_runs(experiment_id: str, root: Optional[Path] = None) -> List[str]:
    rp = paths_mod.run_paths(experiment_id, "unused", root)
    base = rp.root / paths_mod.PUBLIC_ROOT / experiment_id
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir())
