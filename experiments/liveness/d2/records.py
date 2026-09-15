"""D2 attempt records: field visibility tiers and writers.

D2 does not use the linkage recorder's public/private streams (``experiments/recorder``):
D2 records no hidden relation and no ground-truth labels, and every attempt record mixes
three observers' knowledge. Instead every field is classified here, and ``project`` derives
the view of one observer. A field that is not classified cannot be written (tested).

Tiers
-----
``control``         experiment design known to the experimenter (condition, seed, schedule
                    parameters); not an observation of anyone.
``client_private``  known only to the spender's wallet: when it read the root, the witness,
                    proof-generation timing, retry lineage before resubmission. NEVER in A0/A2.
``A2``              known to the bundler we operate: receive / simulation / re-simulation /
                    drop / bundle-submission times and results, pre-inclusion association.
``A0``              public on chain: mined bundle transaction, block, status, gas, the
                    CreditPaymaster root at inclusion, UserOperationEvent.
``derived``         analysis labels computed from several tiers (outcome class, onset,
                    consistency). Not an observation of any single party.

Timestamps ``t0``..``t9`` are VIRTUAL seconds of the trial clock (controlled segments), not
chain time. Wall-clock milliseconds of real work are separate ``*_ms`` fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

TIERS = ("control", "client_private", "A2", "A0", "derived")

FIELD_TIERS: Dict[str, str] = {
    # control
    "experiment": "control", "trial_id": "control", "seed": "control", "n_initial": "control",
    "lambda": "control", "T_total": "control", "segments": "control", "policy": "control",
    "bundle_mode": "control", "cohort_size": "control", "spender": "control",
    "adversary_budget": "control", "block_interval": "control", "window": "control",
    "segment_profile": "control", "scenario": "control",
    # client private
    "attempt_id": "client_private", "retry_number": "client_private",
    "prior_attempt_id": "client_private", "reproved": "client_private",
    "t0": "client_private", "t1": "client_private", "t2": "client_private",
    "root_observed": "client_private", "tree_size_observed": "client_private",
    "block_at_t0": "client_private", "block_timestamp_at_t0": "client_private",
    "proof_root": "client_private", "proof_tree_size": "client_private",
    "proof_depth": "client_private", "proof_generation_ms": "client_private",
    "proof_verify_off_chain_ms": "client_private", "local_verification_ok": "client_private",
    "proof_cache_hit": "client_private", "client_wall_ms": "client_private",
    "proof_root_equals_observed_root": "client_private",
    "root_at_proof_complete": "client_private",
    # A2 bundler
    "t3": "A2", "root_at_submission": "A2", "tree_size_at_submission": "A2", "t4": "A2",
    "t5": "A2", "t6": "A2", "t7": "A2", "root_at_simulation": "A2", "block_at_simulation": "A2",
    "simulation_result": "A2", "simulation_reason": "A2", "simulation_inner_error": "A2",
    "simulation_wall_ms": "A2", "simulations": "A2", "resimulation_results": "A2",
    "dropped_at": "A2", "root_at_bundle_submission": "A2", "submission_wall_ms": "A2",
    "bundle_size": "A2",
    # A0 public
    "t8": "A0", "t9": "A0", "root_at_inclusion": "A0", "block_at_inclusion": "A0",
    "block_timestamp_at_inclusion": "A0", "bundle_tx_hash": "A0", "onchain_status": "A0",
    "bundle_gas_used": "A0", "bundle_fee_wei": "A0", "beneficiary_compensation_wei": "A0",
    "bundle_fee_wei_total": "A0", "bundle_compensation_wei_total": "A0",
    "sponsor_credit_charge_wei": "A0", "sponsor_credit_charge_bundle_wei": "A0",
    "userop_success": "A0", "actual_gas_used": "A0", "onchain_revert_reason": "A0",
    "onchain_revert_inner_error": "A0", "onchain_revert_op_index": "A0",
    "trace_revert_inner_error": "A0", "bundler_loss_wei": "A0",
    # derived
    "outcome_class": "derived", "failure_observation": "derived", "failure_stage": "derived",
    "stale_onset_segment": "derived", "root_change_count": "derived",
    "failure_observed_at": "derived", "consistent": "derived", "terminal": "derived",
    "time_to_success": "derived", "failed_by_other_op_in_bundle": "derived", "detail": "derived",
}

#: Arrival (root-changing Bootstrap) records: an honest issuer's own operation.
ARRIVAL_FIELD_TIERS: Dict[str, str] = {
    "experiment": "control", "trial_id": "control", "kind": "control", "participant": "control",
    "virtual_time": "control", "sim_accepted": "A2", "sim_reason": "A2", "included": "A0",
    "execution_success": "A0", "root_changed": "A0", "root_before": "A0", "root_after": "A0",
    "tree_size_before": "A0", "tree_size_after": "A0", "tx_hash": "A0", "gas_used": "A0",
    "block_number": "A0", "bundler_fee_wei": "A0", "beneficiary_compensation_wei": "A0",
    "actual_gas_used": "A0", "actual_gas_cost": "A0", "sponsor_bootstrap_charge_wei": "A0",
    "rpc_calls": "control",
}


class UnclassifiedField(ValueError):
    pass


def check_classified(record: Mapping[str, Any], tiers: Mapping[str, str] = FIELD_TIERS) -> None:
    missing = sorted(k for k in record if k not in tiers)
    if missing:
        raise UnclassifiedField(f"unclassified D2 record fields: {missing}")


def project(record: Mapping[str, Any], allowed: Iterable[str],
            tiers: Mapping[str, str] = FIELD_TIERS) -> Dict[str, Any]:
    """The view of an observer holding exactly the ``allowed`` tiers."""
    allow = set(allowed)
    check_classified(record, tiers)
    return {k: v for k, v in record.items() if tiers[k] in allow}


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]],
                tiers: Mapping[str, str] = FIELD_TIERS) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            check_classified(r, tiers)
            fh.write(json.dumps(r, sort_keys=True, default=str) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
