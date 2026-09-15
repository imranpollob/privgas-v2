"""Cost reconciliation of B3-PrivGas-v1 W1-cold (the frozen PrivGas v1 specimen).

Same vocabulary and the same balance-window method as ``accounting.py``
(``start`` = last setup block, ``end`` = last workflow block); every number is
read from receipts, logs or archive state. B3's complete workflow is measured
separately and reported stage by stage:

* w1 ERC-20 asset transfer (sender)
* w2 Stage 1 FUND: ``AnnouncementRegistry.announceAndFund`` -- transaction fee,
  ``vMin`` forwarded to the stealth account (transferred-but-retained ETH, NOT a
  gas cost) and the non-refundable admission fee ``F`` (burned to address(0):
  irrecoverable, but not gas either -- reported as its own line)
* w3 Stage 2 BOOTSTRAP: UserOperation gas, BootstrapPaymaster charge (its
  EntryPoint deposit decrease), bundle transaction, bundler net
* w4 Stage 3 SPEND: the same for CreditPaymaster
* proof generation time (private prover log) and the setup-time B3
  infrastructure deployment gas, reported separately and explicitly NOT a
  production deployment cost (the frozen PoseidonT3 violates EIP-170).

``total_eth_consumed_by_workflow`` stays the sum of workflow transaction fees,
exactly as for B0/B1/B2; ``total_eth_irrecoverable_including_admission_fee`` adds
the burned fee. Transferred-but-unspent ETH (``vMin`` left on the account) is never
counted as consumed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import b3
from .accounting import (
    REQUIRED_STEPS,
    SUBSIDY_TOLERANCE_GAS,
    AccountingError,
    _Check,
    _tx_row,
    _u,
    _userop_event,
    _userop_gas_price,
)
from .config import ALL_PAYMASTERS, B3_BASELINE_ID
from .runner import ZERO_ADDRESS


def reconcile_b3(chain_dump: Dict[str, Any], private: Dict[str, Any]) -> Dict[str, Any]:
    baseline = chain_dump["baseline_id"]
    if baseline != B3_BASELINE_ID:
        raise ValueError(f"not a B3 run: {baseline}")
    roles = private["roles"]
    labels = private["tx_labels"]
    blocks = chain_dump["blocks"]
    start, end = str(blocks["setup_end"]), str(blocks["workflow_end"])
    state = chain_dump["state"]
    contracts = chain_dump["contracts"]
    b3cfg = chain_dump["b3_config"]
    v_min = _u(b3cfg["protocol"]["v_min"])
    fee_f = _u(b3cfg["protocol"]["non_refundable_fee"])
    ep = contracts["EntryPoint"]
    boot_pm, credit_pm = contracts["BootstrapPaymaster"], contracts["CreditPaymaster"]
    recipient = roles["recipient_account"]
    sender = roles["asset_sender"]
    amount = _u(chain_dump["config"]["token"]["transfer_amount"])

    def eth(addr: str, which: str) -> int:
        return _u(state["eth_balance"][addr][which])

    def dep(addr: str, which: str) -> int:
        return _u(state["entrypoint_deposit"][addr][which])

    def tok(addr: str, which: str) -> int:
        return _u(state["erc20_balance"][addr][which])

    rows: Dict[str, Dict[str, Any]] = {}
    for t in chain_dump["transactions"]:
        if t["phase"] == "workflow":
            rows[labels[t["tx"]["hash"]]] = _tx_row(t, labels[t["tx"]["hash"]])
    missing = [s for s in REQUIRED_STEPS[baseline] if s not in rows]
    if missing:
        raise AccountingError(
            f"{baseline} W1-cold is incomplete (never mined: {missing}); a failed run has "
            "no completed-action cost to reconcile")
    workflow = list(rows.values())
    total_fees = sum(r["fee"] for r in workflow)
    total_burned = sum(r["burned"] for r in workflow)
    total_priority = sum(r["priority_fee_paid"] for r in workflow)

    checks: List[_Check] = []

    def check(name: str, expected: int, actual: int, relation: str = "==") -> None:
        checks.append(_Check(name, expected, actual, relation))

    def userop_summary(label: str, paymaster: str) -> Dict[str, Any]:
        bundle = rows[label]
        e = _userop_event(bundle["_raw"])
        op_entry = next(u for u in chain_dump["userops"] if u["label"] == label)
        price = _userop_gas_price(op_entry["packed"], bundle["base_fee_per_gas"])
        s = {
            "userop_hash": e["userop_hash"], "success": e["success"],
            "sender": e["sender"], "paymaster": e["paymaster"],
            "actual_gas_used": e["actual_gas_used"], "actual_gas_cost": e["actual_gas_cost"],
            "userop_gas_price": price,
            "pre_verification_gas": int(op_entry["packed"]["preVerificationGas"]),
            "bundle_transaction_gas_used": bundle["gas_used"],
            "bundle_transaction_fee": bundle["fee"],
            "bundler_net": e["actual_gas_cost"] - bundle["fee"],
            "bundler_net_gas": e["actual_gas_used"] - bundle["gas_used"],
            "pvg_calibration": chain_dump["pvg_records"][label],
            "paymaster_deposit": {"start": dep(paymaster, start), "end": dep(paymaster, end)},
        }
        check(f"{label}: userop success", 1, int(e["success"]))
        check(f"{label}: actual_gas_cost == actual_gas_used * min(maxFee, priority+basefee)",
              e["actual_gas_used"] * price, e["actual_gas_cost"])
        check(f"{label}: userop hash in event == hash signed and submitted",
              int(op_entry["userop_hash"], 16), int(e["userop_hash"], 16))
        check(f"{label}: preVerificationGas priced by a calibrated method", 1,
              int(s["pvg_calibration"].get("method") in ("calibrated_overhead_v1",
                                                         "break_even_calibration_v1")))
        check(f"{label}: no systematic bundler subsidy (net gas >= -{SUBSIDY_TOLERANCE_GAS})",
              -SUBSIDY_TOLERANCE_GAS, s["bundler_net_gas"], ">=")
        check(f"{label}: sponsored by the expected B3 Paymaster", int(paymaster, 16),
              int(e["paymaster"] or "0x0", 16))
        return s

    boot = userop_summary("w3_bootstrap_bundle", boot_pm)
    spend = userop_summary("w4_spend_bundle", credit_pm)

    # --- Paymaster deposits ------------------------------------------------------
    check("BootstrapPaymaster deposit delta == -Bootstrap actualGasCost",
          -boot["actual_gas_cost"], dep(boot_pm, end) - dep(boot_pm, start))
    check("CreditPaymaster deposit delta == -Spend actualGasCost",
          -spend["actual_gas_cost"], dep(credit_pm, end) - dep(credit_pm, start))
    for name in ALL_PAYMASTERS:
        if name in contracts and contracts[name] not in (boot_pm, credit_pm):
            check(f"unused paymaster {name} deposit unchanged",
                  dep(contracts[name], start), dep(contracts[name], end))

    # --- bundler -------------------------------------------------------------------
    check("beneficiary delta == Bootstrap + Spend actualGasCost",
          boot["actual_gas_cost"] + spend["actual_gas_cost"],
          eth(roles["beneficiary"], end) - eth(roles["beneficiary"], start))
    check("bundler EOA delta == -(both bundle transaction fees)",
          -(boot["bundle_transaction_fee"] + spend["bundle_transaction_fee"]),
          eth(roles["bundler"], end) - eth(roles["bundler"], start))

    # --- conservation --------------------------------------------------------------
    sum_delta = sum(_u(v[end]) - _u(v[start]) for v in state["eth_balance"].values())
    check("sum of all tracked ETH balance deltas (incl. address(0)) == -burned base fees",
          -total_burned, sum_delta)
    check("block producer delta == priority fees", total_priority,
          eth(roles["block_producer"], end) - eth(roles["block_producer"], start))
    check("EntryPoint ETH delta == sum of EntryPoint deposit deltas",
          sum(dep(a, end) - dep(a, start) for a in state["entrypoint_deposit"]),
          eth(ep, end) - eth(ep, start))

    # --- Stage 1 FUND --------------------------------------------------------------
    ann = rows["w2_announce_and_fund"]
    funded = [d for d in (b3.decode_b3_log(l) for l in ann["_raw"]["receipt"]["logs"])
              if d and d["event"] == "Funded"]
    check("announceAndFund value == vMin + non-refundable fee", v_min + fee_f, ann["value"])
    check("exactly one Funded event", 1, len(funded))
    check("Funded.forwarded == vMin", v_min, funded[0]["forwarded"] if funded else -1)
    check("Funded.feeBurned == non-refundable fee", fee_f,
          funded[0]["fee_burned"] if funded else -1)
    check("address(0) ETH delta == non-refundable fee (burned)", fee_f,
          eth(ZERO_ADDRESS, end) - eth(ZERO_ADDRESS, start))
    check("registry retains no ETH", 0,
          eth(contracts["AnnouncementRegistry"], end)
          - eth(contracts["AnnouncementRegistry"], start))
    check("sender delta == -(fee w1 + fee w2 + vMin + F)",
          -(rows["w1_asset_delivery"]["fee"] + ann["fee"] + v_min + fee_f),
          eth(sender, end) - eth(sender, start))
    check("recipient starts with zero native ETH", 0, eth(recipient, start))
    check("recipient starts and ends with zero EntryPoint deposit", 0,
          dep(recipient, start) + dep(recipient, end))
    check("recipient ends with exactly vMin (forwarded, never spent on gas)", v_min,
          eth(recipient, end))
    check("sponsor operator sends no workflow transaction", 0,
          eth(roles["sponsor_operator"], end) - eth(roles["sponsor_operator"], start))

    # --- token ---------------------------------------------------------------------
    check("asset sender token delta == -amount", -amount, tok(sender, end) - tok(sender, start))
    check("destination token delta == +amount", amount,
          tok(roles["destination"], end) - tok(roles["destination"], start))
    check("recipient token start == 0", 0, tok(recipient, start))
    check("recipient token end == 0", 0, tok(recipient, end))

    # --- credit lifecycle (archive state reads) ---------------------------------
    s0, s1 = state["b3"][start], state["b3"][end]
    commitment = int((private.get("b3") or {})["identity_commitment"])
    check("CreditPool tree size 0 -> 1", 1, s1["credit_pool_tree_size"] - s0["credit_pool_tree_size"])
    check("CreditPool root == the deposited identity commitment (single leaf)", commitment,
          int(s1["credit_pool_current_root"]))
    check("CreditPaymaster mirrored root == CreditPool root",
          int(s1["credit_pool_current_root"]), int(s1["credit_paymaster_root"]))
    check("BootstrapPaymaster single-use grant consumed", 1, int(s1["bootstrap_used"]))
    check("nullifier unspent before, spent after", 1,
          int(s1["nullifier_spent"] is True and s0["nullifier_spent"] is False))
    check("account deployed by the Bootstrap operation (initCode present)", 1,
          int(len(next(u for u in chain_dump["userops"]
                       if u["label"] == "w3_bootstrap_bundle")["packed"]["initCode"]) > 2))

    failed = [c for c in checks if not c.ok]
    if failed:
        raise AccountingError("B3 W1 accounting does not reconcile:\n" + "\n".join(
            f"  {c.name}: expected {c.relation} {c.expected}, actual {c.actual}"
            for c in failed))

    # --- proof timing (private prover log) --------------------------------------
    proof_log = (private.get("b3") or {}).get("proof_log") or []
    mined = [p for p in proof_log if p["label"] == "w4_spend_bundle"
             and int(p["message"], 16) == int(spend["userop_hash"], 16)]
    spend_proofs = [p for p in proof_log if p["label"] == "w4_spend_bundle"]

    # --- setup-time B3 infrastructure (NOT a production deployment cost) ----------
    infra = [_tx_row(t, labels.get(t["tx"]["hash"], "setup"))
             for t in chain_dump["transactions"] if t["phase"] == "setup"
             and labels.get(t["tx"]["hash"], "").startswith(("setup_deploy_b3_",
                                                             "setup_b3_"))]

    def pair(s: int, e: int) -> Dict[str, str]:
        return {"start": str(s), "end": str(e), "delta": str(e - s)}

    def strip(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if d is None:
            return None
        out = {}
        for k, v in d.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict):
                v = {kk: (str(vv) if isinstance(vv, int) and not isinstance(vv, bool) else vv)
                     for kk, vv in v.items()}
            out[k] = str(v) if isinstance(v, int) and not isinstance(v, bool) else v
        return out

    boot_charge = dep(boot_pm, start) - dep(boot_pm, end)
    spend_charge = dep(credit_pm, start) - dep(credit_pm, end)
    sender_cost = -(eth(sender, end) - eth(sender, start))
    return {
        "baseline_id": baseline,
        "workload_id": chain_dump["workload_id"],
        "evaluation_profile": chain_dump["evaluation_profile"]["profile_id"],
        "blocks": {"setup_end": int(start), "start": int(start), "end": int(end)},
        "balances": {
            "asset_sender_eth": pair(eth(sender, start), eth(sender, end)),
            "recipient_eth": pair(eth(recipient, start), eth(recipient, end)),
            "recipient_entrypoint_deposit": pair(dep(recipient, start), dep(recipient, end)),
            "bootstrap_paymaster_entrypoint_deposit": pair(dep(boot_pm, start),
                                                           dep(boot_pm, end)),
            "credit_paymaster_entrypoint_deposit": pair(dep(credit_pm, start),
                                                        dep(credit_pm, end)),
            "address_zero_eth": pair(eth(ZERO_ADDRESS, start), eth(ZERO_ADDRESS, end)),
            "sponsor_operator_eth": pair(eth(roles["sponsor_operator"], start),
                                         eth(roles["sponsor_operator"], end)),
            "bundler_eth": pair(eth(roles["bundler"], start), eth(roles["bundler"], end)),
            "beneficiary_eth": pair(eth(roles["beneficiary"], start),
                                    eth(roles["beneficiary"], end)),
            "block_producer_eth": pair(eth(roles["block_producer"], start),
                                       eth(roles["block_producer"], end)),
            "entrypoint_contract_eth": pair(eth(ep, start), eth(ep, end)),
        },
        "transactions": [strip(r) for r in workflow],
        "warmup_transactions": [],
        "userop": strip(spend),
        "bootstrap_userop": strip(boot),
        "warmup_userop": None,
        "setup_b3_infrastructure_transactions": [strip(r) for r in infra],
        "summary": {
            # Keys shared with B0/B1/B2 (the application action is the Spend op).
            "setup_gas_used": str(sum(_tx_row(t, "setup")["gas_used"]
                                      for t in chain_dump["transactions"]
                                      if t["phase"] == "setup")),
            "warmup_gas_used": "0",
            "warmup_eth_consumed": "0",
            "asset_transfer_gas_used": str(rows["w1_asset_delivery"]["gas_used"]),
            "eth_transferred_directly_to_recipient": str(v_min),
            "eth_allowance_transfer_gas_used": None,
            "recipient_action_gas_used": str(spend["actual_gas_used"]),
            "recipient_action_gas_units_source": (
                "Spend UserOperationEvent.actualGasUsed (the W1 application operation)"),
            "userop_charge": str(spend["actual_gas_cost"]),
            "paymaster_charge": str(spend_charge),
            "recipient_action_gas_charge": str(spend["actual_gas_cost"]),
            "account_deployment_in_measured_action": False,
            "unused_recipient_eth": str(eth(recipient, end) - eth(recipient, start)),
            "remaining_recipient_entrypoint_deposit": str(dep(recipient, end)),
            "paymaster_deposit_delta": str(-spend_charge),
            "pre_verification_gas": str(spend["pre_verification_gas"]),
            "bundle_transaction_gas_used": str(spend["bundle_transaction_gas_used"]),
            "bundler_reimbursement": str(boot["actual_gas_cost"] + spend["actual_gas_cost"]),
            "bundler_net": str(boot["bundler_net"] + spend["bundler_net"]),
            "bundler_net_gas": str(boot["bundler_net_gas"] + spend["bundler_net_gas"]),
            "sponsor_authorization_cost": "0",
            "sponsor_authorization_kind": "per-account eligibility bought by the announcer "
                                          "(non-refundable fee) + Semaphore proof at Spend",
            "sender_cost": str(sender_cost),
            "recipient_cost_own_funds": "0",
            "sponsor_cost": str(boot_charge + spend_charge),
            "total_eth_consumed_by_workflow": str(total_fees),
            "burned_base_fee": str(total_burned),
            "priority_fees_to_block_producer": str(total_priority),
            # B3-specific stage breakdown.
            "announcement_tx_gas_used": str(ann["gas_used"]),
            "announcement_tx_fee": str(ann["fee"]),
            "eth_forwarded_to_stealth_account": str(v_min),
            "non_refundable_admission_fee_burned": str(fee_f),
            "bootstrap_userop_gas_used": str(boot["actual_gas_used"]),
            "bootstrap_pre_verification_gas": str(boot["pre_verification_gas"]),
            "bootstrap_paymaster_charge": str(boot_charge),
            "bootstrap_bundle_transaction_gas_used": str(boot["bundle_transaction_gas_used"]),
            "bootstrap_bundler_net": str(boot["bundler_net"]),
            "spend_userop_gas_used": str(spend["actual_gas_used"]),
            "spend_pre_verification_gas": str(spend["pre_verification_gas"]),
            "credit_paymaster_charge": str(spend_charge),
            "spend_bundle_transaction_gas_used": str(spend["bundle_transaction_gas_used"]),
            "spend_bundler_net": str(spend["bundler_net"]),
            "bootstrap_paymaster_deposit_delta": str(-boot_charge),
            "credit_paymaster_deposit_delta": str(-spend_charge),
            "transferred_but_retained_eth": str(eth(recipient, end) - eth(recipient, start)),
            "total_eth_irrecoverable_including_admission_fee": str(total_fees + fee_f),
            "bootstrap_and_spend_same_public_sender": boot["sender"].lower()
                                                      == spend["sender"].lower(),
            "proof_generation_ms_mined_proof": (str(round(mined[-1]["prove_ms"], 1))
                                                if mined else None),
            "proof_generation_ms_all_spend_proofs": str(round(sum(p["prove_ms"]
                                                                  for p in spend_proofs), 1)),
            "proofs_generated_for_spend_pricing": str(len(spend_proofs)),
            "b3_infrastructure_setup_gas_used_not_production_comparable": str(
                sum(r["gas_used"] for r in infra)),
        },
        "checks": [c.as_dict() for c in checks],
    }
