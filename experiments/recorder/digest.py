"""Content digests shared by both sides of the public/private boundary.

Neutral by design: the attacker side uses it to freeze a predictions file,
the evaluation side uses it to verify that the file it is about to join
labels against is byte-identical to the one that was frozen. Keeping the
function in one place is what makes those two computations comparable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(obj: Any) -> bytes:
    """Stable serialisation: sorted keys, no insignificant whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def commit_to_value(namespace: str, value: Any) -> str:
    """A binding commitment used to publish *that* a value was fixed.

    Used for the experiment seed: the seed is secret during the attack phase
    (it determines the hidden assignment of actors to accounts), but the
    public run manifest must still pin it down so a later reveal can be
    checked. ``namespace`` is the run_id, which makes the commitment unique
    per run and stops the same seed producing the same digest across runs.

    Not a hiding commitment against a determined adversary: the seed space is
    small and enumerable. It proves the seed was not changed after the fact;
    it is not a privacy mechanism and nothing in this repository should treat
    it as one.
    """
    return hashlib.sha256(
        canonical_json({"namespace": namespace, "value": value})
    ).hexdigest()
