"""Raw W1 dumps -> Observations -> the existing experiment recorder.

Public and bundler observations are derived **only** from the role-free chain
dump and the raw bundler log. Every public row is classified from on-chain
content (transaction target, selector, value, emitted logs), never from the
private step labels, so ``public_events.jsonl`` is exactly what an archive-node
observer could rebuild. Only the ground-truth row uses the private role file
and the (secret) seed.

Which rows a W1 run produces
----------------------------
per workflow transaction, in block order:

* ERC20.transfer tx            -> ``asset_transfer``
* plain ETH transfer           -> ``native_transfer``
* ObservablePaymaster.setSponsored -> ``paymaster_event`` (``subject_account``
  = the account named in ``SponsorshipSet``)
* EntryPoint.handleOps tx      -> ``eoa_transaction`` with calldata class
  ``entrypoint_handle_ops`` (the bundle transaction's own receipt gas), then
  one row per W1-relevant log in log order: ``entrypoint_deposit``
  (Deposited), ``account_deployment`` (AccountDeployed), ``asset_transfer``
  (Transfer), ``user_operation_event`` (UserOperationEvent).

Deliberately not recorded as rows (no schema field would carry them without
a free-form bag): SimpleAccountInitialized / ERC1967 Upgraded / Initialized
logs of the account deployment, and EntryPoint BeforeExecution. They are in
the raw dump.

All rows are ``observer_tier: "A0"``: the in-repo bundler exposes no public
mempool, so no A1 observation exists for these runs, and a UserOperation the
bundler rejected is recorded in ``bundler_private`` only.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ...recorder import paths as paths_mod
from ...recorder.adapters import (
    BundlerObservation,
    GroundTruth,
    Observation,
    RelationLabel,
    UserOpObservation,
    for_baseline,
)
from ...recorder.provenance import environment_report, software_revision
from ...recorder.writers import ExperimentRecorder
from . import abi
from .config import BASELINE_EXPERIMENT_IDS, ENTRYPOINT_VERSION
from .keys import opaque_handle
from .userop import unpack

RE_ADDRESS_ANY = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _u(x: Any) -> Optional[int]:
    if x is None:
        return None
    return int(x, 16) if isinstance(x, str) and x.startswith("0x") else int(x)


def _iso(ts_hex: str) -> str:
    return datetime.fromtimestamp(int(ts_hex, 16), tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _lower(addr: Optional[str]) -> Optional[str]:
    return None if addr is None else addr.lower()


def public_observations(chain_dump: Dict[str, Any]) -> List[Observation]:
    contracts = chain_dump["contracts"]
    token = contracts["W1Token"].lower()
    ep = contracts["EntryPoint"].lower()
    pm = contracts["ObservablePaymaster"].lower()
    deposit_before = chain_dump["state"].get("entrypoint_deposit_before_tx", {})
    out: List[Observation] = []

    for t in chain_dump["transactions"]:
        if t["phase"] != "workflow":
            continue
        tx, rc, blk = t["tx"], t["receipt"], t["block"]
        to = _lower(tx.get("to"))
        data = abi.data_bytes(tx["input"])
        sel = "0x" + data[:4].hex() if len(data) >= 4 else None
        status_ok = _u(rc["status"]) == 1
        common = dict(
            scenario_id="scn-0", observer_tier="A0",
            block_number=_u(rc["blockNumber"]), block_hash=blk["hash"],
            block_timestamp_utc=_iso(blk["timestamp"]),
            transaction_index=_u(rc["transactionIndex"]),
            transaction_hash=tx["hash"],
            outcome="success" if status_ok else "reverted", success=status_ok,
        )
        tx_gas = dict(actual_gas_used=_u(rc["gasUsed"]),
                      actual_gas_cost=_u(rc["gasUsed"]) * _u(rc["effectiveGasPrice"]),
                      effective_gas_price=_u(rc["effectiveGasPrice"]))
        logs = [(l, abi.decode_log(l)) for l in rc["logs"]]

        if to == token and sel == abi.SELECTOR_ERC20_TRANSFER:
            _, amount = abi.decode_erc20_transfer(data)
            transfer_log = next((l for l, d in logs if d and d["event"] == "Transfer"), None)
            out.append(Observation(
                event_type="asset_transfer", asset_type="erc20",
                log_index=_u(transfer_log["logIndex"]) if transfer_log else None,
                sender=tx["from"], target=tx["to"], method_selector=sel,
                calldata_class="erc20_transfer", nonce=_u(tx["nonce"]),
                asset_contract=tx["to"], asset_amount=amount,
                revert_reason_class=None if status_ok else "target_reverted",
                **tx_gas, **common))
        elif not data and _u(tx["value"]) > 0:
            out.append(Observation(
                event_type="native_transfer", asset_type="native",
                sender=tx["from"], target=tx["to"], calldata_class="native_value_only",
                nonce=_u(tx["nonce"]), asset_amount=_u(tx["value"]),
                **tx_gas, **common))
        elif to == pm and sel == abi.SELECTOR_SET_SPONSORED:
            ev = next(((l, d) for l, d in logs if d and d["event"] == "SponsorshipSet"),
                      (None, None))
            out.append(Observation(
                event_type="paymaster_event", asset_type="none",
                log_index=_u(ev[0]["logIndex"]) if ev[0] else None,
                sender=tx["from"], target=tx["to"], paymaster=tx["to"],
                subject_account=ev[1]["account"] if ev[1] else None,
                method_selector=sel, calldata_class="paymaster_policy",
                nonce=_u(tx["nonce"]), **tx_gas, **common))
        elif to == ep and sel == abi.SELECTOR_HANDLE_OPS:
            out.extend(_bundle_observations(chain_dump, t, data, logs, common,
                                            tx_gas, deposit_before.get(tx["hash"], {})))
        else:
            raise ValueError(f"unclassifiable W1 workflow transaction {tx['hash']}")
    return out


def _bundle_observations(chain_dump, t, data, logs, common, tx_gas,
                         deposit_before) -> List[Observation]:
    tx = t["tx"]
    ep = chain_dump["contracts"]["EntryPoint"]
    ops, beneficiary = abi.decode_handle_ops(data)
    decoded_ops = [unpack(o) for o in ops]
    rows = [Observation(
        event_type="eoa_transaction", asset_type="none", sender=tx["from"],
        target=tx["to"], bundler_beneficiary=beneficiary,
        method_selector=abi.SELECTOR_HANDLE_OPS, calldata_class="entrypoint_handle_ops",
        nonce=_u(tx["nonce"]), **tx_gas, **common)]
    log_common = {k: v for k, v in common.items() if k not in ("outcome", "success")}

    def op_for(sender: str) -> Dict[str, Any]:
        return next(o for o in decoded_ops if o["sender"].lower() == sender.lower())

    def userop_obs(userop_hash: str, op: Dict[str, Any]) -> UserOpObservation:
        return UserOpObservation(
            userop_hash=userop_hash, entrypoint_address=ep,
            entrypoint_version=ENTRYPOINT_VERSION,
            max_fee_per_gas=op["max_fee_per_gas"],
            max_priority_fee_per_gas=op["max_priority_fee_per_gas"],
            verification_gas_limit=op["verification_gas_limit"],
            call_gas_limit=op["call_gas_limit"],
            pre_verification_gas=op["pre_verification_gas"],
            factory=op["factory"],
            paymaster_verification_gas_limit=op["paymaster_verification_gas_limit"],
            paymaster_post_op_gas_limit=op["paymaster_post_op_gas_limit"])

    for log, d in logs:
        if d is None:
            continue
        li = _u(log["logIndex"])
        if d["event"] == "Deposited":
            before = _u(deposit_before.get(d["account"], "0"))
            rows.append(Observation(
                event_type="entrypoint_deposit", asset_type="native", log_index=li,
                target=log["address"], subject_account=d["account"],
                asset_amount=d["total_deposit"] - before,
                outcome="success", success=True, **log_common))
        elif d["event"] == "AccountDeployed":
            op = op_for(d["sender"])
            rows.append(Observation(
                event_type="account_deployment", asset_type="none", log_index=li,
                sender=d["sender"], target=d["factory"], paymaster=d["paymaster"],
                calldata_class="account_deploy",
                userop=userop_obs(d["userop_hash"], op),
                outcome="success", success=True, **log_common))
        elif d["event"] == "Transfer":
            op = op_for(d["from"]) if any(
                o["sender"].lower() == d["from"].lower() for o in decoded_ops) else None
            inner_sel = None
            if op is not None:
                _, _, inner = abi.decode_execute(op["call_data"])
                inner_sel = "0x" + inner[:4].hex()
            rows.append(Observation(
                event_type="asset_transfer", asset_type="erc20", log_index=li,
                sender=d["from"], target=log["address"], method_selector=inner_sel,
                calldata_class="erc20_transfer" if inner_sel == abi.SELECTOR_ERC20_TRANSFER
                else None,
                asset_contract=log["address"], asset_amount=d["amount"],
                outcome="success", success=True, **log_common))
        elif d["event"] == "UserOperationEvent":
            op = op_for(d["sender"])
            target, _, _ = abi.decode_execute(op["call_data"])
            rows.append(Observation(
                event_type="user_operation_event", asset_type="none", log_index=li,
                sender=d["sender"], target=target, paymaster=d["paymaster"],
                bundler_beneficiary=beneficiary,
                method_selector="0x" + op["call_data"][:4].hex(),
                calldata_class="account_execute", nonce=d["nonce"],
                userop=userop_obs(d["userop_hash"], op),
                actual_gas_used=d["actual_gas_used"], actual_gas_cost=d["actual_gas_cost"],
                effective_gas_price=tx_gas["effective_gas_price"],
                outcome="success" if d["success"] else "reverted", success=d["success"],
                revert_reason_class=None if d["success"] else "target_reverted",
                **log_common))
    return rows


def bundler_observations(bundler_log: List[Dict[str, Any]]) -> List[BundlerObservation]:
    by_op: Dict[Tuple[str, int], Dict[str, Dict[str, Any]]] = {}
    order: List[Tuple[str, int]] = []
    attempt = 0
    for e in bundler_log:
        if e["event"] == "received":
            attempt = e["submission_attempt"]
            key = (e["userop_hash"], attempt)
            by_op[key] = {}
            order.append(key)
        by_op[(e["userop_hash"], attempt)][e["event"]] = e
    out = []
    for key in order:
        ev = by_op[key]
        rec, sim = ev["received"], ev.get("simulation")
        sub, inc = ev.get("submitted"), ev.get("included")
        out.append(BundlerObservation(
            bundler_id=rec["bundler_id"], userop_hash=rec["userop_hash"],
            sender=rec["sender"], nonce=int(rec["nonce"]), scenario_id="scn-0",
            submission_attempt=rec["submission_attempt"],
            receive_timestamp_utc=rec["timestamp_utc"],
            simulation_timestamp_utc=sim["timestamp_utc"] if sim else None,
            simulation_result=sim["result"] if sim else "not_simulated",
            rejection_category=sim["rejection_category"] if sim else None,
            rejection_message_class=sim["rejection_message_class"] if sim else None,
            # Observed: this bundler performs no replacement, so the lineage is
            # empty rather than unknown.
            replacement_lineage=[],
            inclusion_timestamp_utc=inc["timestamp_utc"] if inc else None,
            bundle_submission_timestamp_utc=sub["timestamp_utc"] if sub else None,
            submitted_bundle_transaction_hash=(
                sub["submitted_bundle_transaction_hash"] if sub else None),
            rpc_endpoint_id=rec["rpc_endpoint_id"]))
    return out


def ground_truth(chain_dump: Dict[str, Any], private: Dict[str, Any], seed: int,
                 action_record_ids: List[str]) -> GroundTruth:
    b = chain_dump["baseline_id"]
    roles = private["roles"]
    labels = {v: k for k, v in private["tx_labels"].items()}
    userop_hash = chain_dump["userops"][0]["userop_hash"] if chain_dump["userops"] else None
    action_tx = labels.get("w3_recipient_action") or labels.get("w3_bundle")
    subject = action_tx if b == "B0" else userop_hash
    funder_handle = (opaque_handle(seed, "sponsor", "sponsor_operator") if b == "B2"
                     else opaque_handle(seed, "sender", "asset_sender"))
    actor = opaque_handle(seed, "actor", "actor")
    return GroundTruth(
        scenario_id="scn-0", subject_kind="operation",
        actor_id=actor,
        established_wallet_id=opaque_handle(seed, "wallet", "established_wallet"),
        funding_wallet_id=funder_handle,
        asset_sender_id=opaque_handle(seed, "sender", "asset_sender"),
        stealth_account_id=opaque_handle(seed, "stealth", f"recipient_account/{b}"),
        r1=RelationLabel("R1", "observed", subject_ref=subject, true_value=funder_handle,
                         candidate_set_id="w1-funders"),
        r2=RelationLabel("R2", "not_applicable"),
        r3=RelationLabel("R3", "observed", subject_ref=subject, true_value=actor,
                         candidate_set_id="w1-actors"),
        public_anchors={
            "stealth_account_address": roles["recipient_account"],
            "funding_address": (chain_dump["contracts"]["ObservablePaymaster"] if b == "B2"
                                else roles["asset_sender"]),
            "asset_sender_address": roles["asset_sender"],
            "established_wallet_address": roles["established_wallet"],
            "transaction_hash": action_tx,
            "userop_hash": userop_hash,
            "public_event_record_ids": action_record_ids,
        })


def _lower_addresses(obj: Any) -> Any:
    """Apply the schema's lowercase-address rule inside the manifest too."""
    if isinstance(obj, dict):
        return {k: _lower_addresses(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_lower_addresses(v) for v in obj]
    if isinstance(obj, str) and RE_ADDRESS_ANY.match(obj):
        return obj.lower()
    return obj


def components(chain_dump: Dict[str, Any], private: Dict[str, Any]) -> Dict[str, Any]:
    return _lower_addresses(_components(chain_dump, private))


def _components(chain_dump: Dict[str, Any], private: Dict[str, Any]) -> Dict[str, Any]:
    b = chain_dump["baseline_id"]
    c = chain_dump["contracts"]
    cfg = chain_dump["config"]
    arts = chain_dump["artifacts"]
    aa = b in ("B1", "B2")
    return {
        "entrypoint": ({"address": c["EntryPoint"], "version": ENTRYPOINT_VERSION,
                        "source": chain_dump["entrypoint_provenance"]} if aa else None),
        "account_implementation": (
            {"kind": "erc4337_smart_account", "name": "SimpleAccount",
             "version": f"eth-infinitism account-abstraction {ENTRYPOINT_VERSION}",
             "source_commit": chain_dump["entrypoint_provenance"]["source_commit"],
             "factory": c["SimpleAccountFactory"],
             "implementation": c["SimpleAccount_implementation"],
             "implementation_deployed_bytecode_sha256":
                 arts["SimpleAccount"]["deployed_bytecode_sha256"]}
            if aa else {"kind": "eoa", "version": None,
                        "note": "fresh externally-owned account; no contract code"}),
        "paymaster": ({"kind": "observable_paymaster", "name": "ObservablePaymaster",
                       "address": c["ObservablePaymaster"],
                       "version": "baselines/w1_b0_b2/src/ObservablePaymaster.sol",
                       "deployed_bytecode_sha256":
                           arts["ObservablePaymaster"]["deployed_bytecode_sha256"],
                       "authorization_rule": "sponsored[userOp.sender] == true "
                                             "(owner-managed public allowlist)",
                       "privacy_mechanism": None} if b == "B2" else None),
        "bundler": ({"kind": "in_repo_instrumented_bundler", **chain_dump["bundler"],
                     "erc7562_enforced": False, "public_mempool": False}
                    if aa else None),
        "asset": {"kind": "erc20", "address": c["W1Token"],
                  "decimals": cfg["token"]["decimals"],
                  "deployed_bytecode_sha256": arts["W1Token"]["deployed_bytecode_sha256"]},
        "destination": private["roles"]["destination"],
        "transfer_amount": cfg["token"]["transfer_amount"],
        "fee_policy": cfg["fees"],
        "chain_environment": chain_dump["environment"],
        "matched_config_sha256": hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
        "environment_contracts_deployed_in_identical_setup": c,
    }


NOTES = {
    "B0": "MEASURED. Real signed transactions on a private local anvil devnet "
          "(chain id 31337). W1 via a sender-funded fresh EOA. Setup-phase "
          "transactions (faucet funding, contract deployment, Paymaster deposit) "
          "are identical for B0/B1/B2 and are not recorded as events.",
    "B1": "MEASURED. Real signed transactions on a private local anvil devnet "
          "(chain id 31337). W1 via a sender-funded eth-infinitism SimpleAccount "
          "v0.9.0 through the in-repo instrumented bundler (no public mempool, no "
          "ERC-7562 enforcement). Setup phase identical for B0/B1/B2, not recorded "
          "as events.",
    "B2": "MEASURED. Real signed transactions on a private local anvil devnet "
          "(chain id 31337). W1 via the same SimpleAccount and bundler as B1, "
          "sponsored by ObservablePaymaster (public allowlist). Setup phase "
          "identical for B0/B1/B2, not recorded as events.",
}


def record_run(chain_dump: Dict[str, Any], bundler_log: List[Dict[str, Any]],
               private: Dict[str, Any], seed: int, run_id: str,
               root: Path, clock: Optional[Callable[[], str]] = None,
               env_report=None, revision=None) -> Dict[str, Any]:
    b = chain_dump["baseline_id"]
    experiment_id = BASELINE_EXPERIMENT_IDS[b]
    rp = paths_mod.run_paths(experiment_id, run_id, root)
    adapter = for_baseline(b)()
    adapter.chain_id = chain_dump["environment"]["chain_id"]

    rec = ExperimentRecorder(
        experiment_id=experiment_id, run_id=run_id, baseline_id=b, workload_id="W1",
        seed=seed, chain_id=adapter.chain_id, components=components(chain_dump, private),
        data_origin="measured", paths=rp,
        revision=revision or software_revision(root),
        env_report=env_report or environment_report(root), clock=clock, notes=NOTES[b])

    written: Dict[str, List[Dict[str, Any]]] = {
        "public_events": [], "bundler_private": [], "ground_truth": []}
    with rec:
        for obs in public_observations(chain_dump):
            written["public_events"].append(rec.record_public_event(adapter.public_event(obs)))
        for bobs in bundler_observations(bundler_log):
            written["bundler_private"].append(
                rec.record_bundler_private(adapter.bundler_private(bobs)))
        action_hash = next((h for h, l in private["tx_labels"].items()
                            if l in ("w3_recipient_action", "w3_bundle")), None)
        action_ids = [r["record_id"] for r in written["public_events"]
                      if r["transaction_hash"] == action_hash]
        written["ground_truth"].append(rec.record_ground_truth(
            adapter.ground_truth(ground_truth(chain_dump, private, seed, action_ids))))
    return {"experiment_id": experiment_id, "run_id": run_id, "paths": rp,
            "rows": written}
