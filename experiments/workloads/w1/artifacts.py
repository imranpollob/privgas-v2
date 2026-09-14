"""Compiled contract artifacts from baselines/w1_b0_b2 (forge build output)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import baseline_dir

#: (artifact file, contract name) for every contract the runner deploys.
CONTRACTS = {
    "EntryPoint": ("EntryPoint.sol", "EntryPoint"),
    "SimpleAccountFactory": ("SimpleAccountFactory.sol", "SimpleAccountFactory"),
    "SimpleAccount": ("SimpleAccount.sol", "SimpleAccount"),
    "W1Token": ("W1Token.sol", "W1Token"),
    "ObservablePaymaster": ("ObservablePaymaster.sol", "ObservablePaymaster"),
}


@dataclass(frozen=True)
class Artifact:
    name: str
    abi: List[Dict[str, Any]]
    bytecode: bytes
    deployed_bytecode: bytes

    @property
    def deployed_bytecode_sha256(self) -> str:
        return hashlib.sha256(self.deployed_bytecode).hexdigest()


def forge_build(root: Optional[Path] = None) -> str:
    proc = subprocess.run(["forge", "build"], cwd=baseline_dir(root),
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"forge build failed:\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout


def load_artifact(name: str, root: Optional[Path] = None) -> Artifact:
    file_name, contract = CONTRACTS[name]
    path = baseline_dir(root) / "out" / file_name / f"{contract}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return Artifact(
        name=name,
        abi=data["abi"],
        bytecode=bytes.fromhex(data["bytecode"]["object"].removeprefix("0x")),
        deployed_bytecode=bytes.fromhex(
            data["deployedBytecode"]["object"].removeprefix("0x")),
    )


def load_all(root: Optional[Path] = None) -> Dict[str, Artifact]:
    return {name: load_artifact(name, root) for name in CONTRACTS}


def dependency_tree_digest(tree: Path) -> str:
    """sha256 over (relative path, file bytes) of every file under ``tree``."""
    h = hashlib.sha256()
    for p in sorted(tree.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(tree)).encode())
            h.update(b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()
