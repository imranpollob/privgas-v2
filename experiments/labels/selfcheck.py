"""Automated privacy-leakage self-check over already-written public output.

Two passes:

**Key scan.** Walks every JSON object in ``data/public/`` (all streams, all
manifests, all frozen prediction files) looking for any key in
``FORBIDDEN_PRIVATE_KEYS`` at any nesting depth. The validator already
rejects these at write time; this pass catches output produced by some future
path that bypassed the validator, or files copied in from elsewhere.

**Value scan.** Loads the run's hidden identifiers and relation ``true_value``
answers from ``data/private/`` and searches the raw text of the public files
for those exact strings. This is the part that catches a hidden identifier
copied into public output under a *renamed* key -- the failure mode the key
scan alone cannot see.

The value scan is only meaningful because the ground-truth schema forces
hidden identifiers to be opaque handles that never coincide with an on-chain
value (see schemas/ground_truth.py). ``public_anchors`` is excluded from the
scan by construction: those are public values, deliberately recorded in the
private stream as the join bridge.

**What this does not prove.** It is defence in depth, not a proof that no
label information leaks. It cannot detect a label that has been encoded,
hashed, bucketed, permuted, or merely correlated with a public field -- and
correlation between public features and hidden relations is exactly what the
D1 experiment exists to measure. A clean self-check means "no verbatim
identifier or known label key appears in public output", and nothing more.
Nothing in this repository may cite it as a privacy result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ..recorder import paths as paths_mod
from ..recorder.privatekeys import FORBIDDEN_PRIVATE_KEYS, HIDDEN_ID_FIELDS
from ..recorder.provenance import repo_root
from .loader import load_ground_truth


@dataclass(frozen=True)
class LeakFinding:
    kind: str           # "forbidden_key" | "hidden_value"
    path: str
    detail: str
    line: Optional[int] = None

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.kind}] {where}: {self.detail}"


def _walk_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item)


def _public_files(root: Path) -> List[Path]:
    base = root / paths_mod.PUBLIC_ROOT
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*")
                  if p.is_file() and p.suffix in (".json", ".jsonl"))


def _scan_keys(files: Iterable[Path], root: Path) -> List[LeakFinding]:
    findings: List[LeakFinding] = []
    for path in files:
        rel = str(path.relative_to(root))
        with open(path, "r", encoding="utf-8") as fh:
            if path.suffix == ".jsonl":
                for lineno, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError as exc:
                        findings.append(LeakFinding(
                            "forbidden_key", rel, f"unparseable JSON: {exc}",
                            lineno))
                        continue
                    for key in _walk_keys(obj):
                        if key in FORBIDDEN_PRIVATE_KEYS:
                            findings.append(LeakFinding(
                                "forbidden_key", rel,
                                f"private field {key!r} in public output",
                                lineno))
            else:
                try:
                    obj = json.load(fh)
                except json.JSONDecodeError as exc:
                    findings.append(LeakFinding(
                        "forbidden_key", rel, f"unparseable JSON: {exc}"))
                    continue
                for key in _walk_keys(obj):
                    if key in FORBIDDEN_PRIVATE_KEYS:
                        # The public manifest carries "seed": null on purpose,
                        # as a visible statement that the value is withheld.
                        if key == "seed" and obj.get("seed") is None:
                            continue
                        findings.append(LeakFinding(
                            "forbidden_key", rel,
                            f"private field {key!r} in public output"))
    return findings


def _hidden_values(experiment_id: str, run_id: str,
                   root: Path) -> Set[str]:
    gt = load_ground_truth(experiment_id, run_id, root)
    values: Set[str] = set()
    for row in gt.rows:
        for field in HIDDEN_ID_FIELDS:
            v = row.get(field)
            if isinstance(v, str) and v != "not_applicable":
                values.add(v)
        for field in ("payer_to_operation_label",
                      "issuance_to_redemption_label",
                      "stealth_to_actor_label"):
            label = row.get(field) or {}
            tv = label.get("true_value")
            if isinstance(tv, str):
                values.add(tv)
    return values


def _scan_values(files: Iterable[Path], values: Set[str],
                 root: Path) -> List[LeakFinding]:
    findings: List[LeakFinding] = []
    if not values:
        return findings
    for path in files:
        rel = str(path.relative_to(root))
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            for value in values:
                if value in line:
                    findings.append(LeakFinding(
                        "hidden_value", rel,
                        f"hidden identifier {value!r} appears verbatim in "
                        "public output (possibly under a renamed key)",
                        lineno))
    return findings


def scan_public_output(experiment_id: Optional[str] = None,
                       run_id: Optional[str] = None,
                       root: Optional[Path] = None
                       ) -> Tuple[List[LeakFinding], Dict[str, Any]]:
    """Scan public output; return (findings, summary).

    With ``experiment_id``/``run_id``, the value scan runs against that run's
    ground truth. Without them only the key scan runs -- report that clearly
    rather than implying a full check happened.
    """
    root = Path(root) if root else repo_root()
    if experiment_id and run_id:
        rp = paths_mod.run_paths(experiment_id, run_id, root)
        files = [p for p in _public_files(root)
                 if rp.public_run_dir in p.parents]
    else:
        files = _public_files(root)

    findings = _scan_keys(files, root)
    value_scan_ran = False
    if experiment_id and run_id:
        values = _hidden_values(experiment_id, run_id, root)
        findings.extend(_scan_values(files, values, root))
        value_scan_ran = True

    summary = {
        "files_scanned": len(files),
        "key_scan": True,
        "value_scan": value_scan_ran,
        "findings": len(findings),
        "caveat": (
            "Defence in depth only. A clean result means no forbidden key and "
            "no verbatim hidden identifier was found in public output. It does "
            "not show that public features carry no information about the "
            "hidden relations -- that is what the D1 experiment measures."
        ),
    }
    return findings, summary


def main(argv: Optional[List[str]] = None) -> int:
    """CLI: python3 -m experiments.labels.selfcheck [EXPERIMENT_ID RUN_ID]

    Exit code 1 if anything was found, so it can gate a commit or a CI step.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Scan data/public/ for private field names and for hidden "
                    "identifier values copied in under renamed keys.")
    parser.add_argument("experiment_id", nargs="?")
    parser.add_argument("run_id", nargs="?")
    parser.add_argument("--root", default=None)
    parser.add_argument("--all-runs", action="store_true",
                        help="run the value scan for every run that has both "
                             "public output and ground truth")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else repo_root()

    targets: List[Tuple[Optional[str], Optional[str]]]
    if args.all_runs:
        targets = _discover_runs(root) or [(None, None)]
    else:
        targets = [(args.experiment_id, args.run_id)]

    total = 0
    files = 0
    value_scans = 0
    for experiment_id, run_id in targets:
        findings, summary = scan_public_output(experiment_id, run_id, root)
        files += summary["files_scanned"]
        value_scans += 1 if summary["value_scan"] else 0
        for f in findings:
            print(str(f))
        total += len(findings)

    scope = (f"{len(targets)} run(s)" if args.all_runs or targets[0][0]
             else "all public output")
    print(f"scanned {files} file(s) across {scope}; "
          f"value scan ran for {value_scans} run(s); {total} finding(s)")
    if total == 0:
        print("No forbidden key and no verbatim hidden identifier found in "
              "public output. This is defence in depth, not a privacy result: "
              "it says nothing about information public features carry about "
              "the hidden relations.")
    return 1 if total else 0


def _discover_runs(root: Path) -> List[Tuple[str, str]]:
    """Every run that has both a public directory and a ground-truth file."""
    public_base = root / paths_mod.PUBLIC_ROOT
    out: List[Tuple[str, str]] = []
    if not public_base.is_dir():
        return out
    for manifest in sorted(public_base.rglob(paths_mod.PUBLIC_MANIFEST_FILE)):
        run_dir = manifest.parent
        rel = run_dir.relative_to(public_base)
        experiment_id = str(rel.parent)
        run_id = rel.name
        gt = (root / paths_mod.PRIVATE_ROOT / experiment_id / run_id
              / paths_mod.GROUND_TRUTH_FILE)
        if gt.is_file():
            out.append((experiment_id, run_id))
    return out
