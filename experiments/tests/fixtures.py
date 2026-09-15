"""Minimal valid records for each stream, and helpers to perturb them.

Every test that checks a rejection starts from a record that is *known
valid*, changes exactly one thing, and asserts the specific failure code.
That way a test failing tells you which rule fired, not merely that
something was wrong.
"""

from __future__ import annotations

from typing import Any, Dict

from experiments.recorder import baselines
from experiments.recorder.schemas.common import build_record_id
from experiments.recorder.schemas.public_events import derive_trace_phase
from experiments.recorder.version import SCHEMA_VERSION

CLEAN_REVISION = {
    "kind": "git_commit",
    "git_commit": "d641d306e763548bb522bb40179badc7c0b47438",
    "git_dirty": False,
    "worktree_id": None,
    "describe": "clean worktree at d641d306e763",
}

DIRTY_REVISION = {
    "kind": "git_worktree",
    "git_commit": "d641d306e763548bb522bb40179badc7c0b47438",
    "git_dirty": True,
    "worktree_id": "a" * 64,
    "describe": "uncommitted worktree (based on d641d306e763), digest aaaa",
}

RUN_ID = "synthetic-20260301T120000Z-t"
EXPERIMENT_ID = "tests/recorder-fixture"

ADDRESS = "0x57ea1a0000000000000000000000000000000001"
FUNDER = "0xf0f0000000000000000000000000000000000001"
PAYMASTER = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
ENTRYPOINT = "0x0000000071727de22e5e9d8baf0edac6f37da032"
TOKEN = "0x5fbdb2315678afecb367f032d93f642f64180aa3"
HASH_A = "0x" + "11" * 32
HASH_B = "0x" + "22" * 32
HASH_C = "0x" + "33" * 32


def envelope(stream: str, seq: int = 0, baseline_id: str = "B0",
             scenario_id: str = "scn-a") -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "stream": stream,
        "experiment_id": EXPERIMENT_ID,
        "run_id": RUN_ID,
        "record_id": build_record_id(RUN_ID, stream, seq),
        "seq": seq,
        "baseline_id": baseline_id,
        "workload_id": "W1-cold",
        "scenario_id": scenario_id,
        "software_revision": dict(CLEAN_REVISION),
        "data_origin": "synthetic_fixture",
        "recorded_at_utc": "2026-03-01T12:30:00Z",
    }


def public_event(baseline_id: str = "B0", seq: int = 0, **overrides
                 ) -> Dict[str, Any]:
    row = envelope("public_events", seq, baseline_id)
    row.update({
        "observer_tier": "A0",
        "chain_id": 31337,
        "block_number": 102,
        "block_hash": HASH_C,
        "block_timestamp_utc": "2026-03-01T12:20:00Z",
        "transaction_index": 0,
        "log_index": 0,
        "transaction_hash": HASH_A,
        "userop_hash": None,
        "entrypoint_address": None,
        "entrypoint_version": None,
        "factory": None,
        "sender": ADDRESS,
        "paymaster": None,
        "target": TOKEN,
        "subject_account": None,
        "bundler_beneficiary": None,
        "method_selector": "0xa9059cbb",
        "calldata_class": "erc20_transfer",
        "nonce": "0",
        "asset_type": "erc20",
        "asset_contract": TOKEN,
        "asset_amount": "1000000000000000000",
        "asset_token_id": None,
        "amount_bucket": None,
        "max_fee_per_gas": None,
        "max_priority_fee_per_gas": None,
        "verification_gas_limit": None,
        "call_gas_limit": None,
        "pre_verification_gas": None,
        "paymaster_verification_gas_limit": None,
        "paymaster_post_op_gas_limit": None,
        "actual_gas_used": "51000",
        "actual_gas_cost": "102000000000000",
        "effective_gas_price": "2000000000",
        "success": True,
        "revert_reason_class": None,
        "outcome": "success",
        "event_type": "asset_transfer",
        "trace_phase": "application",
        "commitment": None,
        "merkle_root": None,
        "nullifier": None,
        "pool_id": None,
        "proof_metadata": None,
    })
    row.update(overrides)
    if "trace_phase" not in overrides:
        row["trace_phase"] = derive_trace_phase(row["event_type"], row["calldata_class"])
    return row


def erc4337_public_event(baseline_id: str = "B1", seq: int = 0, **overrides
                         ) -> Dict[str, Any]:
    row = public_event(baseline_id=baseline_id, seq=seq)
    row.update({
        # A0: an included UserOperation is recoverable from chain data alone
        # (schema 2.0.0 correction; 1.0.0 fixtures used A1 here).
        "observer_tier": "A0",
        "event_type": "user_operation_event",
        "asset_type": "none",
        "asset_contract": None,
        "asset_amount": None,
        "userop_hash": HASH_B,
        "entrypoint_address": ENTRYPOINT,
        "entrypoint_version": "0.9.0",
        "factory": "0xfaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "method_selector": "0xb61d27f6",
        "calldata_class": "account_execute",
        "max_fee_per_gas": "2000000000",
        "max_priority_fee_per_gas": "1000000000",
        "verification_gas_limit": "150000",
        "call_gas_limit": "120000",
        "pre_verification_gas": "50000",
        "actual_gas_used": "268000",
        "actual_gas_cost": "536000000000000",
        "bundler_beneficiary": "0xbeee000000000000000000000000000000000001",
    })
    if baseline_id.startswith("B2"):
        row.update({
            "paymaster": PAYMASTER,
            "paymaster_verification_gas_limit": "80000",
            "paymaster_post_op_gas_limit": "40000",
        })
    row.update(overrides)
    if "trace_phase" not in overrides:
        row["trace_phase"] = derive_trace_phase(row["event_type"], row["calldata_class"])
    return row


def bundler_private(baseline_id: str = "B1", seq: int = 0, **overrides
                    ) -> Dict[str, Any]:
    row = envelope("bundler_private", seq, baseline_id)
    row.update({
        "observer_tier": "A2",
        "bundler_id": "bundler-alpha",
        "userop_hash": HASH_B,
        "sender": ADDRESS,
        "nonce": "0",
        "submission_attempt": 1,
        "receive_timestamp_utc": "2026-03-01T12:19:10Z",
        "simulation_timestamp_utc": "2026-03-01T12:19:11Z",
        "simulation_result": "accepted",
        "rejection_category": None,
        "rejection_message_class": None,
        "replacement_lineage": [],
        "replacement_count": 0,
        "inclusion_timestamp_utc": "2026-03-01T12:20:02Z",
        "bundle_submission_timestamp_utc": "2026-03-01T12:19:12Z",
        "submitted_bundle_transaction_hash": HASH_A,
        "rpc_endpoint_id": "local-anvil",
    })
    row.update(overrides)
    return row


def label(relation: str, status: str = "observed", subject_ref: str = HASH_B,
          true_value: str = "actor_7c1e",
          candidate_set_id: str = "w1-actors") -> Dict[str, Any]:
    if status == "not_applicable":
        return {"relation": relation, "status": status, "subject_ref": None,
                "true_value": None, "candidate_set_id": None}
    if status == "absent":
        true_value = None
    return {"relation": relation, "status": status, "subject_ref": subject_ref,
            "true_value": true_value, "candidate_set_id": candidate_set_id}


def _payer_kind(baseline_id: str) -> str:
    caps = baselines.get(baseline_id)
    if caps.uses_paymaster:
        return "paymaster_entrypoint_deposit"
    return "smart_account_entrypoint_deposit" if caps.uses_erc4337 else "eoa_balance"


def ground_truth(baseline_id: str = "B0", seq: int = 0, **overrides
                 ) -> Dict[str, Any]:
    row = envelope("ground_truth", seq, baseline_id)
    has_credit = baseline_id in ("B3", "B4", "B5", "B6")
    row.update({
        "seed": 424242,
        "subject_kind": "operation",
        "actor_id": "actor_7c1e",
        "established_wallet_id": "wallet_7c1e_main",
        "economic_funding_source_id": "funder_7c1e",
        "immediate_gas_payer_kind": _payer_kind(baseline_id),
        "asset_sender_id": "sender_7c1e",
        "stealth_account_id": "stealth_a1",
        "credit_id": "credit_0001" if has_credit else "not_applicable",
        "issuance_id": "issuance_0001" if has_credit else "not_applicable",
        "payer_to_operation_label": label(
            "R1", true_value="funder_7c1e", candidate_set_id="w1-funders"),
        "issuance_to_redemption_label": label(
            "R2", status="observed" if has_credit else "not_applicable",
            true_value="issuance_0001", candidate_set_id="w1-issuances"),
        "stealth_to_actor_label": label("R3"),
        "public_anchors": {
            "stealth_account_address": ADDRESS,
            "economic_funding_address": FUNDER,
            "immediate_gas_payer_address": (PAYMASTER if baselines.get(baseline_id).uses_paymaster
                                            else ADDRESS),
            "asset_sender_address": ADDRESS,
            "established_wallet_address": PAYMASTER,
            "transaction_hash": HASH_A,
            "userop_hash": HASH_B,
            "public_event_record_ids": [],
        },
    })
    row.update(overrides)
    return row
