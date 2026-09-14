"""JSONL writers and the ExperimentRecorder that owns all three streams.

Serialisation lives here once so no baseline has to reimplement it
(Prompt 3 Sec. 11: "Do not force every baseline to duplicate serialization
logic"). A baseline hands the recorder plain dictionaries of *observations*;
the recorder attaches the envelope, validates, and appends.

Two properties worth stating explicitly:

* **Validate-then-write.** Every row is validated before a byte reaches the
  file. A malformed row raises and is not written, so a stream file on disk
  is always schema-valid in its entirety.
* **Deterministic regeneration.** The recorder takes an explicit clock and an
  explicit run_id, and never reads the wall clock on its own. Re-running an
  adapter over the same raw inputs with the same run_id and clock produces
  byte-identical stream files, which is what makes "public records can be
  regenerated from raw chain/bundler logs" a testable claim rather than an
  aspiration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional

from . import baselines
from .digest import canonical_json, commit_to_value
from .errors import RecorderError
from .paths import RunPaths, run_paths
from .provenance import EnvironmentReport, software_revision
from .schemas.common import build_record_id
from .validate import validate_record
from .version import (
    SCHEMA_VERSION,
    STREAM_BUNDLER_PRIVATE,
    STREAM_GROUND_TRUTH,
    STREAM_PUBLIC_EVENTS,
    STREAMS,
)


def new_run_id(now: Optional[datetime] = None, *, synthetic: bool = False,
               suffix: str = "") -> str:
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    prefix = "synthetic-" if synthetic else ""
    tail = f"-{suffix}" if suffix else ""
    return f"{prefix}{stamp}{tail}"


class JsonlStreamWriter:
    """Append-only JSONL writer for one stream of one run."""

    def __init__(self, stream: str, path: Path) -> None:
        if stream not in STREAMS:
            raise RecorderError(f"unknown stream {stream!r}")
        self.stream = stream
        self.path = path
        self._seq = 0
        self._fh = None

    def open(self) -> "JsonlStreamWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise RecorderError(
                f"{self.path} already exists. Stream files are append-only "
                "within a run and are never rewritten: re-recording produces a "
                "new run_id so the earlier record stays intact.")
        self._fh = open(self.path, "w", encoding="utf-8")
        return self

    @property
    def next_seq(self) -> int:
        return self._seq

    def write(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        if self._fh is None:
            raise RecorderError("writer is not open")
        row = dict(record)
        validate_record(self.stream, row)
        self._fh.write(canonical_json(row).decode("utf-8"))
        self._fh.write("\n")
        self._seq += 1
        return row

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False


class ExperimentRecorder:
    """Owns the three streams for one run and stamps the shared envelope.

    Usage::

        with ExperimentRecorder.start(
                experiment_id="privacy/d1-w1-b2", baseline_id="B2",
                workload_id="W1", seed=42, chain_id=31337,
                components={...}) as rec:
            rec.record_public_event({...})
            rec.record_bundler_private({...})
            rec.record_ground_truth({...})
    """

    def __init__(self, *, experiment_id: str, run_id: str, baseline_id: str,
                 workload_id: str, seed: int, chain_id: int,
                 components: Mapping[str, Any],
                 data_origin: str = "measured",
                 paths: Optional[RunPaths] = None,
                 revision: Optional[Mapping[str, Any]] = None,
                 env_report: Optional[EnvironmentReport] = None,
                 clock: Optional[Callable[[], str]] = None,
                 notes: str = "") -> None:
        self.experiment_id = experiment_id
        self.run_id = run_id
        self.baseline_id = baseline_id
        self.workload_id = workload_id
        self.seed = seed
        self.chain_id = chain_id
        self.components = dict(components)
        self.data_origin = data_origin
        self.notes = notes
        self.capabilities = baselines.get(baseline_id)

        self.paths = paths or run_paths(experiment_id, run_id)
        self.revision = dict(revision) if revision else software_revision(
            self.paths.root)
        self.env_report = env_report
        self._clock = clock or (
            lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        self._started_at = self._clock()

        self._writers: Dict[str, JsonlStreamWriter] = {}
        self._open = False

    # --- construction ------------------------------------------------------

    @classmethod
    def start(cls, **kwargs) -> "ExperimentRecorder":
        rec = cls(**kwargs)
        rec.open()
        return rec

    def open(self) -> "ExperimentRecorder":
        if self._open:
            return self
        self.paths.ensure_dirs()
        self._writers = {
            STREAM_PUBLIC_EVENTS: JsonlStreamWriter(
                STREAM_PUBLIC_EVENTS, self.paths.public_events_path).open(),
            STREAM_GROUND_TRUTH: JsonlStreamWriter(
                STREAM_GROUND_TRUTH, self.paths.ground_truth_path).open(),
        }
        # A baseline with no bundler gets no bundler stream at all -- not an
        # empty file that later reads as "we looked and saw nothing".
        if self.capabilities.uses_bundler:
            self._writers[STREAM_BUNDLER_PRIVATE] = JsonlStreamWriter(
                STREAM_BUNDLER_PRIVATE,
                self.paths.bundler_private_path).open()
        elif _is_empty_dir(self.paths.a2_dir):
            self.paths.a2_dir.rmdir()
        self._open = True
        return self

    # --- envelope -----------------------------------------------------------

    def _envelope(self, stream: str, scenario_id: Optional[str]) -> Dict[str, Any]:
        seq = self._writers[stream].next_seq
        return {
            "schema_version": SCHEMA_VERSION,
            "stream": stream,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "record_id": build_record_id(self.run_id, stream, seq),
            "seq": seq,
            "baseline_id": self.baseline_id,
            "workload_id": self.workload_id,
            "scenario_id": scenario_id,
            "software_revision": dict(self.revision),
            "data_origin": self.data_origin,
            "recorded_at_utc": self._clock(),
        }

    def _record(self, stream: str, observation: Mapping[str, Any]) -> Dict[str, Any]:
        if not self._open:
            raise RecorderError("recorder is not open")
        if stream not in self._writers:
            raise RecorderError(
                f"baseline {self.baseline_id} does not produce {stream!r} rows "
                f"({self.capabilities.description})")
        obs = dict(observation)
        scenario_id = obs.pop("scenario_id", None)
        row = self._envelope(stream, scenario_id)
        overlap = sorted(set(obs) & set(row))
        if overlap:
            raise RecorderError(
                f"observation tried to set recorder-owned envelope field(s) "
                f"{overlap}; the envelope is stamped by the recorder alone")
        row.update(obs)
        return self._writers[stream].write(row)

    # --- public API ---------------------------------------------------------

    def record_public_event(self, observation: Mapping[str, Any]) -> Dict[str, Any]:
        return self._record(STREAM_PUBLIC_EVENTS, observation)

    def record_bundler_private(self, observation: Mapping[str, Any]) -> Dict[str, Any]:
        return self._record(STREAM_BUNDLER_PRIVATE, observation)

    def record_ground_truth(self, observation: Mapping[str, Any]) -> Dict[str, Any]:
        obs = dict(observation)
        obs.setdefault("seed", self.seed)
        return self._record(STREAM_GROUND_TRUTH, obs)

    # --- manifests ----------------------------------------------------------

    def _public_manifest(self, finished_at: str) -> Dict[str, Any]:
        env = self.env_report
        return {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "baseline_id": self.baseline_id,
            "baseline_description": self.capabilities.description,
            "workload_id": self.workload_id,
            "chain_id": self.chain_id,
            "data_origin": self.data_origin,
            "software_revision": dict(self.revision),
            "components": self.components,
            "started_at_utc": self._started_at,
            "finished_at_utc": finished_at,
            # The seed itself is secret: it determines the hidden assignment of
            # actors to accounts. The commitment pins it without revealing it
            # during the attack phase; the private manifest holds the value.
            "seed_commitment_sha256": commit_to_value(self.run_id, self.seed),
            "seed": None,
            "tool_versions": dict(env.tool_versions) if env else {},
            "env_report_text": env.raw_text if env else None,
            "streams": {
                "public_events": str(
                    self.paths.public_events_path.relative_to(self.paths.root)),
                "bundler_private": (
                    str(self.paths.bundler_private_path.relative_to(
                        self.paths.root))
                    if self.capabilities.uses_bundler else None),
            },
            "notes": self.notes,
        }

    def _private_manifest(self, finished_at: str) -> Dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "run_id": self.run_id,
            "baseline_id": self.baseline_id,
            "workload_id": self.workload_id,
            "seed": self.seed,
            "seed_commitment_sha256": commit_to_value(self.run_id, self.seed),
            "software_revision": dict(self.revision),
            "started_at_utc": self._started_at,
            "finished_at_utc": finished_at,
            "ground_truth": str(
                self.paths.ground_truth_path.relative_to(self.paths.root)),
        }

    def close(self) -> None:
        if not self._open:
            return
        finished_at = self._clock()
        for w in self._writers.values():
            w.close()
        _write_json(self.paths.public_manifest_path,
                    self._public_manifest(finished_at))
        _write_json(self.paths.private_manifest_path,
                    self._private_manifest(finished_at))
        self._open = False

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False


def _write_json(path: Path, obj: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not any(path.iterdir())
