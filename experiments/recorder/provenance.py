"""Reproducibility metadata: which code, which environment, which run.

Two rules from Prompt 3 Sec. 6 and Sec. 15 drive this module:

1. **Never manufacture a commit hash.** If the worktree is clean and git
   reports a HEAD, the record carries that SHA and says ``kind:
   "git_commit"``. Otherwise -- dirty worktree, or a repository with no
   commits yet -- the record says ``kind: "git_worktree"`` and carries a
   sha256 over the actual working-tree state. A dirty run is identified
   honestly as a dirty run.

2. **Integrate with the existing environment tooling.** The tool-version
   snapshot comes from ``scripts/env-report.sh``, the script the repository
   already uses (docs/experiment-schema.md), not from a competing
   reimplementation.

Every git invocation here is read-only. ``--no-optional-locks`` is passed at
the top level so ``git status`` cannot refresh and rewrite the index as a
side effect of being asked a question.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .digest import sha256_bytes
from .errors import ProvenanceError

_RE_TOOL_LINE = re.compile(r"^\s{2}([a-z0-9_]+)\s{2,}(.+?)\s*$")


def repo_root(start: Optional[Path] = None) -> Path:
    here = Path(start or __file__).resolve()
    for candidate in [here] + list(here.parents):
        if (candidate / ".git").exists() and (candidate / "docs").is_dir():
            return candidate
    raise ProvenanceError(
        "could not locate the privgas-v2 repository root from "
        f"{here}; provenance cannot be established")


def _git(root: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(root), *args],
        capture_output=True, text=True, check=check)


def software_revision(root: Optional[Path] = None) -> Dict[str, Any]:
    """Return the ``software_revision`` object embedded in every record."""
    root = root or repo_root()

    head = _git(root, "rev-parse", "--verify", "-q", "HEAD", check=False)
    commit = head.stdout.strip() if head.returncode == 0 else ""
    commit = commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None

    status = _git(root, "status", "--porcelain", check=False)
    if status.returncode != 0:
        raise ProvenanceError(
            f"git could not report the state of {root}: "
            f"{status.stderr.strip()[:200]}. Provenance is not optional -- a "
            "record without an honest revision identifier is not reproducible, "
            "and the recorder will not substitute a placeholder.")
    dirty = bool(status.stdout.strip())

    if commit is not None and not dirty:
        short = commit[:12]
        return {
            "kind": "git_commit",
            "git_commit": commit,
            "git_dirty": False,
            "worktree_id": None,
            "describe": f"clean worktree at {short}",
        }

    # No commit, or uncommitted changes: identify the working tree by content.
    # Nothing is written to git; `diff` and `status` are read-only queries.
    parts = [
        b"privgas-v2-worktree-v1\n",
        f"head={commit or 'none'}\n".encode(),
        b"--status--\n", status.stdout.encode("utf-8", "replace"),
        b"--unstaged--\n",
        _git(root, "diff", check=False).stdout.encode("utf-8", "replace"),
        b"--staged--\n",
        _git(root, "diff", "--cached", check=False).stdout.encode("utf-8",
                                                                  "replace"),
    ]
    worktree_id = sha256_bytes(b"".join(parts))
    base = f"based on {commit[:12]}" if commit else "no commits yet"
    return {
        "kind": "git_worktree",
        "git_commit": commit,
        "git_dirty": dirty,
        "worktree_id": worktree_id,
        "describe": f"uncommitted worktree ({base}), digest {worktree_id[:12]}",
    }


@dataclass(frozen=True)
class EnvironmentReport:
    raw_text: str
    tool_versions: Dict[str, str]


def environment_report(root: Optional[Path] = None) -> EnvironmentReport:
    """Run scripts/env-report.sh and keep both the raw text and a parse."""
    root = root or repo_root()
    script = root / "scripts" / "env-report.sh"
    if not script.is_file():
        raise ProvenanceError(
            f"{script} is missing; it is the repository's single source of "
            "tool-version truth (docs/experiment-schema.md) and the recorder "
            "will not substitute its own")
    proc = subprocess.run([str(script)], capture_output=True, text=True,
                          cwd=str(root))
    if proc.returncode != 0:
        raise ProvenanceError(
            f"scripts/env-report.sh exited {proc.returncode}: "
            f"{proc.stderr.strip()[:400]}")
    return EnvironmentReport(raw_text=proc.stdout,
                             tool_versions=parse_env_report(proc.stdout))


def parse_env_report(text: str) -> Dict[str, str]:
    """Extract the 'label   value' lines env-report.sh prints under each section."""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        m = _RE_TOOL_LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out
