"""Load ``experiments/workloads/d1/pilot-config.json`` and name pilot experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ...recorder.provenance import repo_root

CONFIG_RELPATH = Path("experiments") / "workloads" / "d1" / "pilot-config.json"
#: The B3-vs-B4-CrossAccount causal ablation (docs/d1-b4-results.md). Every key it shares
#: with pilot-config.json must be identical (tested); it adds only the variant list and
#: the ``b4`` section.
B4_CONFIG_RELPATH = Path("experiments") / "workloads" / "d1" / "b4-config.json"
EXPERIMENT_PREFIX = "d1-pilot"

SCENARIO_SLUG = {"S0-clean-shuffled": "s0-clean-shuffled",
                 "S1-correlated-timing": "s1-correlated-timing"}
BASELINE_SLUG = {"B0": "b0", "B1": "b1", "B2-Signature": "b2-signature",
                 "B2-Allowlist": "b2-allowlist", "B3-PrivGas-v1": "b3-privgas-v1",
                 "B4-CrossAccount": "b4-crossaccount"}


@dataclass(frozen=True)
class PilotConfig:
    raw: Dict[str, Any]

    @property
    def profile_id(self) -> str:
        return self.raw["evaluation_profile"]

    @property
    def workload_id(self) -> str:
        return self.raw["workload_id"]

    @property
    def pool_sizes(self) -> List[int]:
        return [int(n) for n in self.raw["pool_sizes"]]

    @property
    def replicates(self) -> int:
        return int(self.raw["replicates"])

    @property
    def bootstrap_call_gas_limit(self) -> int:
        return int(self.raw["b3"]["bootstrap_call_gas_limit"])

    @property
    def issuer_funder_eth(self) -> int:
        """B4-CrossAccount: ETH the faucet sends each issuer funder (same value as the
        asset senders receive)."""
        b4 = self.raw.get("b4") or {}
        return int(b4.get("issuer_funder_eth", self.raw["actor_setup"]["asset_sender_eth"]))

    def variants(self) -> List[Tuple[str, str]]:
        return [(v["baseline_id"], s) for v in self.raw["variants"] for s in v["scenarios"]]


def load_pilot_config(root: Optional[Path] = None, relpath: Optional[Path] = None) -> PilotConfig:
    path = (Path(root) if root else repo_root()) / (relpath or CONFIG_RELPATH)
    return PilotConfig(raw=json.loads(path.read_text(encoding="utf-8")))


def experiment_id(baseline_id: str, scenario_id: str, pool_size: int) -> str:
    """e.g. ``d1-pilot/b3-privgas-v1/s0-clean-shuffled/n16``. Baseline, scenario and
    pool size are experimental conditions (known to the attacker, like baseline_id)."""
    return (f"{EXPERIMENT_PREFIX}/{BASELINE_SLUG[baseline_id]}/{SCENARIO_SLUG[scenario_id]}"
            f"/n{pool_size:02d}")


def parse_experiment_id(exp_id: str) -> Dict[str, Any]:
    prefix, b, s, n = exp_id.split("/")
    if prefix != EXPERIMENT_PREFIX:
        raise ValueError(exp_id)
    inv_b = {v: k for k, v in BASELINE_SLUG.items()}
    inv_s = {v: k for k, v in SCENARIO_SLUG.items()}
    return {"baseline_id": inv_b[b], "scenario_id": inv_s[s], "pool_size": int(n[1:])}
