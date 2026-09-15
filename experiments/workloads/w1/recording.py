"""Raw W1 dumps -> Observations -> the existing experiment recorder.

Public and bundler observations are derived **only** from the role-free chain
dump and the raw bundler log. Every public row is classified from on-chain
content (transaction target, selector, value, emitted logs), never from the
private step labels, so ``public_events.jsonl`` is exactly what an archive-node
observer could rebuild. Only the ground-truth row uses the private role file
and the (secret) seed.

Which rows a W1 run produces (schema 4.0.0: the COMPLETE public trace)
--------------------------------------------------------------------
Every mined transaction of the run -- setup, warm-up and workflow alike -- in
block order. "Setup" is a cost-accounting boundary, not a privacy boundary:
faucet funding, deployments and the sponsor's Paymaster deposits are public
and can establish linkage, so they are recorded. Which rows fall inside the
measured cost window is written privately (``w1_cost_window.json``), never in
the public stream. Each row carries a content-derived ``trace_phase``.

* contract-creation tx         -> ``eoa_transaction`` / ``contract_creation``
  (``subject_account`` = created contract), plus a mint ``asset_transfer``
  (phase ``infrastructure``) for the token's constructor
* ERC20.transfer tx            -> ``asset_transfer`` (``subject_account`` = the token
  recipient; also on mint and in-bundle ``Transfer`` rows -- added 2026-09-15, see
  docs/decision-log.md: the recipient is public in the calldata / Transfer log and
  earlier recordings omitted it)
* plain ETH transfer           -> ``native_transfer`` (phase ``funding``)
* Paymaster ``deposit()`` tx    -> ``paymaster_event`` / ``paymaster_deposit``
  (sender = funding wallet, target = Paymaster), plus ``entrypoint_deposit``
  (``subject_account`` = Paymaster)
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

B3-PrivGas-v1 and every run on the ``b3_compat_local`` profile add (schema 5.0.0):

* ``EntryPoint.depositTo(paymaster)`` tx -> ``paymaster_event`` /
  ``paymaster_deposit`` (sender = funding wallet, target = EntryPoint,
  ``subject_account`` = Paymaster), plus ``entrypoint_deposit``
* ``AnnouncementRegistry.announceAndFund`` tx -> ``eoa_transaction`` /
  ``stealth_announce_and_fund`` (value = vMin + fee, ``subject_account`` = the
  announced account), then per log: ``stealth_announcement`` (MockAnnouncer
  ``AnnounceCalled``), two ``sponsorship_eligibility`` (``EligibilityMirrored``
  from BootstrapPaymaster and CreditPool), and from ``Funded`` two
  ``native_transfer`` rows: registry -> account (forwarded vMin, ``funding``)
  and registry -> address(0) (``fee_burn``, ``authorization``)
* inside B3 bundles: ``paymaster_event`` / ``paymaster_sponsorship``
  (``BootstrapSponsored``), ``privacy_pool_event`` / ``pool_root_update``
  (``RootMirrored``: merkle_root), ``pool_deposit`` (CreditPool ``Deposited``:
  commitment, merkle_root) and ``pool_redeem`` (``CreditSpent``: nullifier, plus
  the proof's public root and proof metadata decoded from the mined
  ``paymasterAndData``)

Each UserOperation row keeps its real ``sender``: B3's Bootstrap and Spend
operations are recorded exactly as mined, including when they share one account.

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

from eth_abi import decode

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
from . import abi, b3
from .config import B3_BASELINE_ID, ENTRYPOINT_VERSION, STANDARD_PROFILE, experiment_id
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


def public_observations(chain_dump: Dict[str, Any],
                        scenario_id: str = "scn-0") -> List[Observation]:
    contracts = chain_dump["contracts"]
    token = contracts["W1Token"].lower()
    ep = contracts["EntryPoint"].lower()
    pm = contracts["ObservablePaymaster"].lower()
    paymasters = {pm, contracts["SignatureVerifyingPaymaster"].lower()}
    registry = _lower(contracts.get("AnnouncementRegistry"))
    deposit_before = chain_dump["state"].get("entrypoint_deposit_before_tx", {})
    out: List[Observation] = []

    for t in chain_dump["transactions"]:
        tx, rc, blk = t["tx"], t["receipt"], t["block"]
        to = _lower(tx.get("to"))
        data = abi.data_bytes(tx["input"])
        sel = "0x" + data[:4].hex() if len(data) >= 4 else None
        status_ok = _u(rc["status"]) == 1
        common = dict(
            scenario_id=scenario_id, observer_tier="A0",
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

        log_common = {k: v for k, v in common.items() if k not in ("outcome", "success")}

        if to is None:
            out.append(Observation(
                event_type="eoa_transaction", asset_type="none", sender=tx["from"],
                subject_account=rc["contractAddress"], calldata_class="contract_creation",
                nonce=_u(tx["nonce"]), **tx_gas, **common))
            for log, d in logs:
                if d and d["event"] == "Transfer":
                    out.append(Observation(
                        event_type="asset_transfer", asset_type="erc20",
                        trace_phase="infrastructure", log_index=_u(log["logIndex"]),
                        sender=d["from"], target=log["address"], subject_account=d["to"],
                        asset_contract=log["address"], asset_amount=d["amount"],
                        outcome="success", success=True, **log_common))
        elif to in paymasters and sel == abi.SELECTOR_PM_DEPOSIT:
            out.append(Observation(
                event_type="paymaster_event", asset_type="native", sender=tx["from"],
                target=tx["to"], method_selector=sel, calldata_class="paymaster_deposit",
                nonce=_u(tx["nonce"]), asset_amount=_u(tx["value"]), **tx_gas, **common))
            for log, d in logs:
                if d and d["event"] == "Deposited":
                    out.append(_deposit_row(log, d, log_common,
                                            deposit_before.get(tx["hash"], {})))
        elif to == token and sel == abi.SELECTOR_ERC20_TRANSFER:
            recipient, amount = abi.decode_erc20_transfer(data)
            transfer_log = next((l for l, d in logs if d and d["event"] == "Transfer"), None)
            out.append(Observation(
                event_type="asset_transfer", asset_type="erc20",
                log_index=_u(transfer_log["logIndex"]) if transfer_log else None,
                sender=tx["from"], target=tx["to"], subject_account=recipient,
                method_selector=sel, calldata_class="erc20_transfer", nonce=_u(tx["nonce"]),
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
        elif to == ep and sel == b3.SELECTOR_EP_DEPOSIT_TO:
            (funded_pm,) = decode(["address"], data[4:])
            out.append(Observation(
                event_type="paymaster_event", asset_type="native", sender=tx["from"],
                target=tx["to"], subject_account=funded_pm, method_selector=sel,
                calldata_class="paymaster_deposit", nonce=_u(tx["nonce"]),
                asset_amount=_u(tx["value"]), **tx_gas, **common))
            for log, d in logs:
                if d and d["event"] == "Deposited":
                    out.append(_deposit_row(log, d, log_common,
                                            deposit_before.get(tx["hash"], {})))
        elif registry is not None and to == registry and sel == b3.SELECTOR_ANNOUNCE_AND_FUND:
            out.extend(_announcement_observations(tx, rc, data, common, log_common, tx_gas))
        else:
            raise ValueError(f"unclassifiable W1 transaction {tx['hash']}")
    return out


def _announcement_observations(tx, rc, data, common, log_common, tx_gas) -> List[Observation]:
    """B3 Stage 1: announceAndFund and the logs it emits (log order)."""
    _, stealth, _, _ = decode(["uint256", "address", "bytes", "bytes"], data[4:])
    rows = [Observation(
        event_type="eoa_transaction", asset_type="native", sender=tx["from"], target=tx["to"],
        subject_account=stealth, method_selector=b3.SELECTOR_ANNOUNCE_AND_FUND,
        calldata_class="stealth_announce_and_fund", nonce=_u(tx["nonce"]),
        asset_amount=_u(tx["value"]), **tx_gas, **common)]
    for log in rc["logs"]:
        d = b3.decode_b3_log(log)
        if d is None:
            continue
        li = _u(log["logIndex"])
        if d["event"] == "AnnounceCalled":
            rows.append(Observation(
                event_type="stealth_announcement", asset_type="none", log_index=li,
                target=log["address"], subject_account=d["stealth_address"],
                outcome="success", success=True, **log_common))
        elif d["event"] == "EligibilityMirrored":
            rows.append(Observation(
                event_type="sponsorship_eligibility", asset_type="none", log_index=li,
                sender=tx["to"], target=log["address"], subject_account=d["stealth_address"],
                outcome="success", success=True, **log_common))
        elif d["event"] == "Funded":
            rows.append(Observation(
                event_type="native_transfer", asset_type="native", log_index=li,
                sender=log["address"], target=d["stealth_address"],
                calldata_class="native_value_only", asset_amount=d["forwarded"],
                outcome="success", success=True, **log_common))
            rows.append(Observation(
                event_type="native_transfer", asset_type="native", log_index=li,
                sender=log["address"], target="0x" + "00" * 20, calldata_class="fee_burn",
                asset_amount=d["fee_burned"], outcome="success", success=True,
                **log_common))
    return rows


def _deposit_row(log, d, log_common, deposit_before) -> Observation:
    before = _u(deposit_before.get(d["account"], "0"))
    return Observation(
        event_type="entrypoint_deposit", asset_type="native", log_index=_u(log["logIndex"]),
        target=log["address"], subject_account=d["account"],
        asset_amount=d["total_deposit"] - before, outcome="success", success=True,
        **log_common)


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

    verifier = chain_dump["contracts"].get("SemaphoreVerifier")
    for log, d in logs:
        if d is None:
            d3 = b3.decode_b3_log(log)
            if d3 is not None:
                rows.append(_b3_bundle_row(log, d3, decoded_ops, log_common, verifier))
            continue
        li = _u(log["logIndex"])
        if d["event"] == "Deposited":
            rows.append(_deposit_row(log, d, log_common, deposit_before))
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
                sender=d["from"], target=log["address"], subject_account=d["to"],
                method_selector=inner_sel,
                calldata_class="erc20_transfer" if inner_sel == abi.SELECTOR_ERC20_TRANSFER
                else None,
                asset_contract=log["address"], asset_amount=d["amount"],
                outcome="success", success=True, **log_common))
        elif d["event"] == "UserOperationEvent":
            op = op_for(d["sender"])
            # A W1-warm warm-up op deploys the account with empty callData:
            # there is no target, selector or call class to record.
            has_call = len(op["call_data"]) >= 4
            target = abi.decode_execute(op["call_data"])[0] if has_call else None
            rows.append(Observation(
                event_type="user_operation_event", asset_type="none", log_index=li,
                sender=d["sender"], target=target, paymaster=d["paymaster"],
                bundler_beneficiary=beneficiary,
                method_selector="0x" + op["call_data"][:4].hex() if has_call else None,
                calldata_class="account_execute" if has_call else None, nonce=d["nonce"],
                userop=userop_obs(d["userop_hash"], op),
                actual_gas_used=d["actual_gas_used"], actual_gas_cost=d["actual_gas_cost"],
                effective_gas_price=tx_gas["effective_gas_price"],
                outcome="success" if d["success"] else "reverted", success=d["success"],
                revert_reason_class=None if d["success"] else "target_reverted",
                **log_common))
    return rows


def _b3_bundle_row(log, d, decoded_ops, log_common, verifier) -> Observation:
    """One B3 protocol log inside a handleOps bundle."""
    li = _u(log["logIndex"])
    if d["event"] == "BootstrapSponsored":
        return Observation(
            event_type="paymaster_event", asset_type="none", log_index=li,
            target=log["address"], paymaster=log["address"],
            subject_account=d["stealth_address"], calldata_class="paymaster_sponsorship",
            outcome="success", success=True, **log_common)
    if d["event"] == "RootMirrored":
        return Observation(
            event_type="privacy_pool_event", asset_type="none", log_index=li,
            target=log["address"], calldata_class="pool_root_update",
            merkle_root=b3.word(d["root"]), outcome="success", success=True, **log_common)
    if d["event"] == "CreditDeposited":
        depositor = next((o["sender"] for o in decoded_ops
                          if len(o["call_data"]) >= 4
                          and abi.decode_execute(o["call_data"])[0].lower()
                          == log["address"].lower()), None)
        return Observation(
            event_type="privacy_pool_event", asset_type="none", log_index=li,
            sender=depositor, target=log["address"], method_selector=b3.SELECTOR_POOL_DEPOSIT,
            calldata_class="pool_deposit", commitment=b3.word(d["commitment"]),
            merkle_root=b3.word(d["root"]), outcome="success", success=True, **log_common)
    if d["event"] == "CreditSpent":
        op = next(o for o in decoded_ops if o["sender"].lower() == d["sender"].lower())
        proof = b3.decode_proof(op["paymaster_and_data"][52:52 + b3.PROOF_BYTE_LENGTH])
        return Observation(
            event_type="privacy_pool_event", asset_type="none", log_index=li,
            sender=d["sender"], target=log["address"], paymaster=log["address"],
            calldata_class="pool_redeem", nullifier=b3.word(d["nullifier"]),
            merkle_root=b3.word(proof["merkle_tree_root"]),
            proof_metadata={"scheme": "groth16", "verifier_address": _lower(verifier),
                            "public_signal_count": 4,
                            "proof_byte_length": b3.PROOF_BYTE_LENGTH,
                            "tree_depth": proof["merkle_tree_depth"]},
            outcome="success", success=True, **log_common)
    raise ValueError(f"unexpected B3 log inside a bundle: {d['event']}")


def bundler_observations(bundler_log: List[Dict[str, Any]],
                         scenario_id: str = "scn-0") -> List[BundlerObservation]:
    by_op: Dict[Tuple[str, int], Dict[str, Dict[str, Any]]] = {}
    order: List[Tuple[str, int]] = []
    attempt = 0
    for e in bundler_log:
        if e["event"] not in ("received", "simulation", "submitted", "included"):
            continue  # pvg_estimate / pvg_calibration: pricing, not a submission
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
            sender=rec["sender"], nonce=int(rec["nonce"]), scenario_id=scenario_id,
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
    measured = [u for u in chain_dump["userops"] if u["label"] == "w3_bundle"]
    userop_hash = measured[0]["userop_hash"] if measured else None
    action_tx = labels.get("w3_recipient_action") or labels.get("w3_bundle")
    subject = action_tx if b == "B0" else userop_hash
    sponsored = chain_dump["paymaster_used"] is not None
    # R1 (schema 4.0.0): economic funding source <-> operation.
    #   B0: the wallet that sent ETH to the recipient EOA   (asset sender)
    #   B1: the wallet that funded the SimpleAccount prefund (asset sender)
    #   B2: the sponsor wallet that funded the Paymaster's EntryPoint deposit
    # The immediate gas payer (EOA balance / account deposit / Paymaster deposit)
    # is public context, recorded separately and never the R1 answer.
    funder_role = "sponsor_operator" if sponsored else "asset_sender"
    funder_handle = (opaque_handle(seed, "sponsor", "sponsor_operator") if sponsored
                     else opaque_handle(seed, "sender", "asset_sender"))
    if sponsored:
        payer_kind = "paymaster_entrypoint_deposit"
        payer_address = chain_dump["contracts"][chain_dump["paymaster_used"]]
    elif b == "B0":
        payer_kind, payer_address = "eoa_balance", roles["recipient_account"]
    else:
        payer_kind, payer_address = ("smart_account_entrypoint_deposit",
                                     roles["recipient_account"])
    actor = opaque_handle(seed, "actor", "actor")
    return GroundTruth(
        scenario_id="scn-0", subject_kind="operation",
        actor_id=actor,
        established_wallet_id=opaque_handle(seed, "wallet", "established_wallet"),
        economic_funding_source_id=funder_handle,
        immediate_gas_payer_kind=payer_kind,
        asset_sender_id=opaque_handle(seed, "sender", "asset_sender"),
        stealth_account_id=opaque_handle(seed, "stealth", f"recipient_account/{b}"),
        r1=RelationLabel("R1", "observed", subject_ref=subject, true_value=funder_handle,
                         candidate_set_id="w1-economic-funders"),
        r2=RelationLabel("R2", "not_applicable"),
        r3=RelationLabel("R3", "observed", subject_ref=subject, true_value=actor,
                         candidate_set_id="w1-actors"),
        public_anchors={
            "stealth_account_address": roles["recipient_account"],
            "economic_funding_address": roles[funder_role],
            "immediate_gas_payer_address": payer_address,
            "asset_sender_address": roles["asset_sender"],
            "established_wallet_address": roles["established_wallet"],
            "transaction_hash": action_tx,
            "userop_hash": userop_hash,
            "public_event_record_ids": action_record_ids,
        })


def b3_ground_truth(chain_dump: Dict[str, Any], private: Dict[str, Any], seed: int,
                    record_ids_by_tx: Dict[str, List[str]]) -> List[GroundTruth]:
    """B3-PrivGas-v1: one row for the Spend operation (the W1 application action)
    and one for the Bootstrap operation, R1/R2/R3 explicit on both.

    R1 (one hop, unchanged): the immediate gas payer of both operations is a B3
    Paymaster's EntryPoint deposit (public); the economic funding source is the
    sponsor-operator wallet that funded those deposits with EntryPoint.depositTo.
    Neither Paymaster contract is ever the economic funder. The asset sender's
    vMin is forwarded to the account but pays no gas, and the non-refundable fee
    is burned, so neither is a one-hop funding source of either operation.
    R2: Spend redeems the credit issued by Bootstrap (observed); Bootstrap
    redeems no credit (absent, a kept negative).
    R3: the account belongs to the actor on both rows.
    """
    roles = private["roles"]
    by_label = {v: k for k, v in private["tx_labels"].items()}
    ops = {u["label"]: u for u in chain_dump["userops"]}
    boot, spend = ops["w3_bootstrap_bundle"], ops["w4_spend_bundle"]
    boot_tx, spend_tx = by_label["w3_bootstrap_bundle"], by_label["w4_spend_bundle"]
    pmd = bytes.fromhex(spend["packed"]["paymasterAndData"][2:])
    nullifier = b3.decode_proof(pmd[52:52 + b3.PROOF_BYTE_LENGTH])["nullifier"]
    commitment = int(private["b3"]["identity_commitment"])
    b = chain_dump["baseline_id"]
    actor = opaque_handle(seed, "actor", "actor")
    sponsor = opaque_handle(seed, "sponsor", "sponsor_operator")
    credit = opaque_handle(seed, "credit", f"{b}/credit/0")
    issuance = opaque_handle(seed, "issuance", f"{b}/issuance/0")
    common = dict(
        scenario_id="scn-0", subject_kind="operation", actor_id=actor,
        established_wallet_id=opaque_handle(seed, "wallet", "established_wallet"),
        economic_funding_source_id=sponsor,
        immediate_gas_payer_kind="paymaster_entrypoint_deposit",
        asset_sender_id=opaque_handle(seed, "sender", "asset_sender"),
        stealth_account_id=opaque_handle(seed, "stealth", f"recipient_account/{b}"),
        credit_id=credit, issuance_id=issuance)
    anchors = {
        "stealth_account_address": roles["recipient_account"],
        "economic_funding_address": roles["sponsor_operator"],
        "asset_sender_address": roles["asset_sender"],
        "established_wallet_address": roles["established_wallet"],
        "issuance_transaction_hash": boot_tx,
        "issuance_userop_hash": boot["userop_hash"],
        "credit_commitment": b3.word(commitment),
        "credit_nullifier": b3.word(nullifier),
    }
    contracts = chain_dump["contracts"]
    rows = []
    for op, tx, pm, r2 in (
            (spend, spend_tx, contracts["CreditPaymaster"],
             RelationLabel("R2", "observed", subject_ref=spend["userop_hash"],
                           true_value=issuance, candidate_set_id="b3-credit-issuances")),
            (boot, boot_tx, contracts["BootstrapPaymaster"],
             RelationLabel("R2", "absent", subject_ref=boot["userop_hash"],
                           candidate_set_id="b3-credit-issuances"))):
        rows.append(GroundTruth(
            **common,
            r1=RelationLabel("R1", "observed", subject_ref=op["userop_hash"],
                             true_value=sponsor, candidate_set_id="w1-economic-funders"),
            r2=r2,
            r3=RelationLabel("R3", "observed", subject_ref=op["userop_hash"],
                             true_value=actor, candidate_set_id="w1-actors"),
            public_anchors={**anchors, "immediate_gas_payer_address": pm,
                            "transaction_hash": tx, "userop_hash": op["userop_hash"],
                            "public_event_record_ids": record_ids_by_tx.get(tx, [])}))
    return rows


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
    aa = b != "B0"
    pm_name = chain_dump["paymaster_used"]
    paymaster = None
    if b == B3_BASELINE_ID:
        paymaster = {
            "kind": "b3_privgas_v1_paymasters", "name": "BootstrapPaymaster+CreditPaymaster",
            "baseline_role": "frozen PrivGas v1 specimen (unmodified)",
            "authorization_rule": (
                "Bootstrap: BootstrapPaymaster sponsors exactly one "
                "execute(CreditPool, 0, deposit(uint256)) per announced (eligible) account; "
                "Spend: CreditPaymaster sponsors any operation carrying a Semaphore v4 proof "
                "over userOpHash against the latest mirrored root, fixed scope, fresh "
                "nullifier (proof in the v0.9.0 PAYMASTER_SIG_MAGIC suffix)"),
            "address": c["CreditPaymaster"],
            "bootstrap_paymaster_address": c["BootstrapPaymaster"],
            "version": f"{chain_dump['b3_provenance']['source_repo']}@"
                       f"{chain_dump['b3_provenance']['source_commit']}",
            "deployed_bytecode_sha256": arts["CreditPaymaster"]["deployed_bytecode_sha256"],
            "bootstrap_deployed_bytecode_sha256":
                arts["BootstrapPaymaster"]["deployed_bytecode_sha256"],
            "staked": False,
            "privacy_mechanism": _b3_privacy_mechanism(chain_dump)}
    elif pm_name == "ObservablePaymaster":
        paymaster = {
            "kind": "observable_paymaster_allowlist", "name": pm_name,
            "baseline_role": "auxiliary (public on-chain sponsor->account allowlist "
                             "transaction before the operation)",
            "authorization_rule": "sponsored[userOp.sender] == true "
                                  "(owner-managed public allowlist)"}
    elif pm_name == "SignatureVerifyingPaymaster":
        paymaster = {
            "kind": "signature_verifying_paymaster", "name": pm_name,
            "baseline_role": "ordinary public Paymaster, off-chain authorization",
            "authorization_rule": "ECDSA.recover(EntryPoint.getUserOpHash(userOp), "
                                  "paymasterSignature) == verifyingSigner; signature in "
                                  "the v0.9.0 PAYMASTER_SIG_MAGIC suffix; signed data "
                                  "abi.encode(uint48 validUntil, uint48 validAfter)",
            "verifying_signer": chain_dump["signature_paymaster_verifying_signer"]}
    if paymaster is not None and b != B3_BASELINE_ID:
        paymaster.update({
            "address": c[pm_name],
            "version": f"baselines/w1_b0_b2/src/{pm_name}.sol",
            "deployed_bytecode_sha256": arts[pm_name]["deployed_bytecode_sha256"],
            "privacy_mechanism": None})
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
        "paymaster": paymaster,
        "bundler": ({"kind": "in_repo_instrumented_experimental_bundler",
                     **chain_dump["bundler"], "erc7562_enforced": False,
                     "public_mempool": False, "production_compatibility": "not established",
                     "pvg_records": chain_dump["pvg_records"]}
                    if aa else None),
        "workload": {"id": chain_dump["workload_id"],
                     "account_deployed_before_measured_action":
                         chain_dump["workload_id"] == "W1-warm",
                     "role": ("primary" if chain_dump["workload_id"] == "W1-cold"
                              else "ablation (not the primary workflow)")},
        "asset": {"kind": "erc20", "address": c["W1Token"],
                  "decimals": cfg["token"]["decimals"],
                  "deployed_bytecode_sha256": arts["W1Token"]["deployed_bytecode_sha256"]},
        "destination": private["roles"]["destination"],
        "transfer_amount": cfg["token"]["transfer_amount"],
        "fee_policy": cfg["fees"],
        "chain_environment": chain_dump["environment"],
        "evaluation_profile": chain_dump.get("evaluation_profile"),
        "b3_provenance": chain_dump.get("b3_provenance"),
        "matched_config_sha256": hashlib.sha256(
            json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
        "environment_contracts_deployed_in_identical_setup": c,
    }


def _b3_privacy_mechanism(chain_dump: Dict[str, Any]) -> Dict[str, Any]:
    from .prover import SEMAPHORE_CORE_VERSION, load_pin
    pin = load_pin()
    cfg = chain_dump["b3_config"]
    depth = cfg["semaphore"]["merkle_tree_depth"]
    return {
        "scheme": "Semaphore v4 membership proof (Groth16, BN254)",
        "verifier": {"contract": "SemaphoreVerifier (B3 vendored, real verification)",
                     "address": chain_dump["contracts"]["SemaphoreVerifier"],
                     "deployed_bytecode_sha256":
                         chain_dump["artifacts"]["SemaphoreVerifier"]["deployed_bytecode_sha256"]},
        "prover_library": f"@semaphore-protocol/core {SEMAPHORE_CORE_VERSION}",
        "circuit": {"name": f"semaphore-{depth}",
                    "artifact_version": pin["semaphore_artifact_version"],
                    "wasm_sha256": pin["artifacts"][str(depth)]["wasm"]["sha256"],
                    "zkey_sha256": pin["artifacts"][str(depth)]["zkey"]["sha256"]},
        "merkle_tree_depth": int(depth),
        "credit_scope": "keccak256('stealth-protocol.credit.v1')",
        "credit_pool": chain_dump["contracts"]["CreditPool"],
        "root_policy": "latest mirrored root only (no root history)",
    }


_COMMON_NOTE = ("MEASURED. Real signed transactions on a private local anvil devnet "
                "(chain id 31337). Setup-phase transactions (faucet funding, all "
                "contract deployments, both Paymaster deposits) are identical for every "
                "baseline and workload; they are excluded from cost accounting but ARE "
                "recorded as public events (complete public trace, schema 4.0.0). AA "
                "operations use the in-repo INSTRUMENTED EXPERIMENTAL bundler (no public "
                "mempool, no ERC-7562 enforcement, not production-compatible); "
                "preVerificationGas = 21,000 + calldata gas + calibrated EntryPoint "
                "overhead from the calibration artifact. ")

NOTES = {
    ("B0", "W1-cold"): _COMMON_NOTE + "W1-cold via a sender-funded fresh EOA.",
    ("B1", "W1-cold"): _COMMON_NOTE + "W1-cold (primary): sender-funded SimpleAccount "
                       "v0.9.0 deployed by the measured UserOperation; no Paymaster.",
    ("B1", "W1-warm"): _COMMON_NOTE + "W1-warm (ABLATION, not the primary workflow): the "
                       "same SimpleAccount is deployed by an earlier sender-funded "
                       "warm-up UserOperation, whose rows are included here but whose "
                       "cost is excluded from the measured action.",
    ("B2-Allowlist", "W1-cold"): _COMMON_NOTE + "W1-cold via the same SimpleAccount, "
                       "sponsored by ObservablePaymaster. AUXILIARY baseline: its public "
                       "setSponsored transaction links sponsor and account before the "
                       "operation.",
    ("B2-Signature", "W1-cold"): _COMMON_NOTE + "W1-cold via the same SimpleAccount, "
                       "sponsored by SignatureVerifyingPaymaster (sponsor ECDSA signature "
                       "over the EntryPoint userOpHash; no on-chain authorization "
                       "transaction).",
    (B3_BASELINE_ID, "W1-cold"): _COMMON_NOTE + "B3-PrivGas-v1, the FROZEN PrivGas v1 "
                       "specimen (baselines/b3_privgas_v1 @ 02a3f0ab, unmodified), W1-cold: "
                       "announceAndFund (Stage 1), a BootstrapPaymaster-sponsored operation "
                       "that deploys the same SimpleAccount and deposits a Semaphore "
                       "commitment (Stage 2), and a CreditPaymaster-sponsored operation from "
                       "the same account carrying a real Groth16 proof and performing the W1 "
                       "application call (Stage 3). Paymasters not staked; no ERC-7562 "
                       "enforcement.",
}

PROFILE_NOTE = {
    STANDARD_PROFILE: "",
    "b3_compat_local": (" EVALUATION PROFILE b3_compat_local: NON-PRODUCTION, "
                        "NON-EIP-170-DEPLOYABLE-AS-BUILT, PRIVACY-EVALUATION-ONLY (anvil "
                        "--code-size-limit 32768; the setup of every run on this profile "
                        "also deploys and funds the frozen B3 contracts)."),
}


def record_run(chain_dump: Dict[str, Any], bundler_log: List[Dict[str, Any]],
               private: Dict[str, Any], seed: int, run_id: str,
               root: Path, clock: Optional[Callable[[], str]] = None,
               env_report=None, revision=None) -> Dict[str, Any]:
    b = chain_dump["baseline_id"]
    w = chain_dump["workload_id"]
    profile_id = (chain_dump.get("evaluation_profile") or {}).get("profile_id",
                                                                  STANDARD_PROFILE)
    exp_id = experiment_id(b, w, profile_id)
    rp = paths_mod.run_paths(exp_id, run_id, root)
    adapter = for_baseline(b)()
    adapter.chain_id = chain_dump["environment"]["chain_id"]

    rec = ExperimentRecorder(
        experiment_id=exp_id, run_id=run_id, baseline_id=b, workload_id=w,
        seed=seed, chain_id=adapter.chain_id, components=components(chain_dump, private),
        data_origin="measured", paths=rp,
        revision=revision or software_revision(root),
        env_report=env_report or environment_report(root), clock=clock,
        notes=NOTES[(b, w)] + PROFILE_NOTE[profile_id])

    written: Dict[str, List[Dict[str, Any]]] = {
        "public_events": [], "bundler_private": [], "ground_truth": []}
    with rec:
        for obs in public_observations(chain_dump):
            written["public_events"].append(rec.record_public_event(adapter.public_event(obs)))
        for bobs in bundler_observations(bundler_log):
            written["bundler_private"].append(
                rec.record_bundler_private(adapter.bundler_private(bobs)))
        if b == B3_BASELINE_ID:
            ids_by_tx: Dict[str, List[str]] = {}
            for r in written["public_events"]:
                ids_by_tx.setdefault(r["transaction_hash"], []).append(r["record_id"])
            for gt in b3_ground_truth(chain_dump, private, seed, ids_by_tx):
                written["ground_truth"].append(rec.record_ground_truth(adapter.ground_truth(gt)))
        else:
            action_hash = next((h for h, l in private["tx_labels"].items()
                                if l in ("w3_recipient_action", "w3_bundle")), None)
            action_ids = [r["record_id"] for r in written["public_events"]
                          if r["transaction_hash"] == action_hash]
            written["ground_truth"].append(rec.record_ground_truth(
                adapter.ground_truth(ground_truth(chain_dump, private, seed, action_ids))))

    # Cost window vs privacy trace: the public stream holds every row; which
    # rows the cost analysis counts is private experiment metadata.
    phase_by_tx = {t["tx"]["hash"]: t["phase"] for t in chain_dump["transactions"]}
    window = {
        "note": "SECRET experiment metadata. Maps public_events record_ids to the run "
                "phase used by cost accounting. Not an attacker input.",
        "run_id": run_id,
        "rows": [{"record_id": r["record_id"],
                  "run_phase": phase_by_tx[r["transaction_hash"]],
                  "in_measured_cost_window": phase_by_tx[r["transaction_hash"]] == "workflow"}
                 for r in written["public_events"]],
    }
    rp.private_run_dir.mkdir(parents=True, exist_ok=True)
    (rp.private_run_dir / "w1_cost_window.json").write_text(
        json.dumps(window, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"experiment_id": exp_id, "run_id": run_id, "paths": rp,
            "rows": written}
