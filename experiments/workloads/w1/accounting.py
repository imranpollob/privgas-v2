"""Full W1 cost reconciliation from a chain dump plus the private role file.

Every number is read from receipts, block headers, logs, or archive state
reads. Balances are compared between two blocks: ``start`` = the block before
the measured workflow (last setup block for W1-cold, last warm-up block for
W1-warm) and ``end`` = last workflow block. Setup and warm-up are reported
separately and never counted as workflow cost.

Vocabulary (kept separate on purpose; docs/research-plan.md Sec. 9.4 forbids a
single vague "cost"):

* **transaction fee** -- ``gasUsed * effectiveGasPrice`` of a mined
  transaction, paid by its signer; splits into the **burned** base fee and the
  **priority fee** paid to the block producer.
* **UserOperation charge** -- ``actualGasCost`` from ``UserOperationEvent``:
  debited from the payer's EntryPoint deposit (account or Paymaster) and paid
  to the beneficiary. A transfer between participants, not ETH consumed.
* **Paymaster charge** -- the decrease of the sponsoring Paymaster's deposit.
* **bundler reimbursement** -- the beneficiary's balance increase;
  **bundler net** -- reimbursement minus the bundle transaction fee.
* **total ETH consumed by the workflow** -- sum of workflow transaction fees
  (burned + priority). Transferred-but-unspent ETH is never included: it is
  reported as **unused recipient ETH** and **remaining EntryPoint deposit**.

``reconcile`` raises ``AccountingError`` if any conservation identity fails,
including when the bundler subsidises an operation by more than
``SUBSIDY_TOLERANCE_GAS`` gas (systematic preVerificationGas underestimation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import abi

REQUIRED_STEPS = {
    "B0": ("w1_asset_delivery", "w2_eth_allowance", "w3_recipient_action"),
    "B1": ("w1_asset_delivery", "w2_eth_allowance", "w3_bundle"),
    "B2-Allowlist": ("w1_asset_delivery", "w2_sponsor_allowlist", "w3_bundle"),
    "B2-Signature": ("w1_asset_delivery", "w3_bundle"),
}
REQUIRED_WARMUP_STEPS = ("warmup_eth_allowance", "warmup_deploy_bundle")

#: A bundler subsidy larger than this (in gas, i.e. net loss / gas price) fails
#: reconciliation. The calibration is break-even over the exact encoded bundle;
#: the only residual it cannot remove is the re-signing step changing the count
#: of zero bytes in fresh signatures (12 gas per byte flipped, a handful of
#: bytes). 100 gas is far below the ~17,800-gas subsidy this assertion exists
#: to catch.
SUBSIDY_TOLERANCE_GAS = 100


class AccountingError(AssertionError):
    pass


def _u(x: Any) -> int:
    if isinstance(x, int):
        return x
    return int(x, 16) if isinstance(x, str) and x.startswith("0x") else int(x)


@dataclass
class _Check:
    name: str
    expected: int
    actual: int
    relation: str = "=="

    @property
    def ok(self) -> bool:
        if self.relation == ">=":
            return self.actual >= self.expected
        return self.expected == self.actual

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "relation": self.relation,
                "expected": str(self.expected), "actual": str(self.actual), "ok": self.ok}


def _tx_row(t: Dict[str, Any], label: str) -> Dict[str, Any]:
    gas_used = _u(t["receipt"]["gasUsed"])
    price = _u(t["receipt"]["effectiveGasPrice"])
    base_fee = _u(t["block"]["baseFeePerGas"])
    return {
        "label": label, "phase": t["phase"], "transaction_hash": t["tx"]["hash"],
        "signer": t["tx"]["from"], "status": _u(t["receipt"]["status"]),
        "gas_limit": _u(t["tx"]["gas"]), "gas_used": gas_used,
        "effective_gas_price": price, "base_fee_per_gas": base_fee,
        "value": _u(t["tx"]["value"]), "fee": gas_used * price,
        "burned": gas_used * base_fee, "priority_fee_paid": gas_used * (price - base_fee),
        "_raw": t,
    }


def _userop_event(bundle_tx: Dict[str, Any]) -> Dict[str, Any]:
    events = [abi.decode_log(l) for l in bundle_tx["receipt"]["logs"]]
    uoe = [e for e in events if e and e["event"] == "UserOperationEvent"]
    if len(uoe) != 1:
        raise AccountingError(f"expected one UserOperationEvent, found {len(uoe)}")
    return uoe[0]


def _userop_gas_price(op_json: Dict[str, Any], base_fee: int) -> int:
    fees = int(op_json["gasFees"], 16)
    prio, max_fee = fees >> 128, fees & ((1 << 128) - 1)
    return min(max_fee, prio + base_fee)


def reconcile(chain_dump: Dict[str, Any], private: Dict[str, Any]) -> Dict[str, Any]:
    baseline = chain_dump["baseline_id"]
    workload = chain_dump["workload_id"]
    warm = workload == "W1-warm"
    roles = private["roles"]
    labels = private["tx_labels"]
    blocks = chain_dump["blocks"]
    setup_end = str(blocks["setup_end"])
    start = str(blocks["warmup_end"])
    end = str(blocks["workflow_end"])
    state = chain_dump["state"]
    contracts = chain_dump["contracts"]
    ep = contracts["EntryPoint"]
    used_pm = contracts[chain_dump["paymaster_used"]] if chain_dump["paymaster_used"] else None
    other_pms = [contracts[n] for n in ("ObservablePaymaster", "SignatureVerifyingPaymaster")
                 if contracts[n] != used_pm]
    recipient = roles["recipient_account"]
    amount = _u(chain_dump["config"]["token"]["transfer_amount"])
    allowance = _u(private["eth_allowance"])

    def eth(addr: str, which: str) -> int:
        return _u(state["eth_balance"][addr][which])

    def dep(addr: str, which: str) -> int:
        return _u(state["entrypoint_deposit"][addr][which])

    def tok(addr: str, which: str) -> int:
        return _u(state["erc20_balance"][addr][which])

    rows: Dict[str, Dict[str, Any]] = {}
    for t in chain_dump["transactions"]:
        if t["phase"] in ("workflow", "warmup"):
            rows[labels[t["tx"]["hash"]]] = _tx_row(t, labels[t["tx"]["hash"]])
    setup_rows = [_tx_row(t, "setup") for t in chain_dump["transactions"]
                  if t["phase"] == "setup"]

    required = REQUIRED_STEPS[baseline] + (REQUIRED_WARMUP_STEPS if warm else ())
    missing = [s for s in required if s not in rows]
    if missing:
        raise AccountingError(
            f"{baseline} {workload} is incomplete (never mined: {missing}); a failed "
            "run has no completed-action cost to reconcile")

    workflow = [r for r in rows.values() if r["phase"] == "workflow"]
    warmup = [r for r in rows.values() if r["phase"] == "warmup"]
    total_fees = sum(r["fee"] for r in workflow)
    total_burned = sum(r["burned"] for r in workflow)
    total_priority = sum(r["priority_fee_paid"] for r in workflow)

    checks: List[_Check] = []

    def check(name: str, expected: int, actual: int, relation: str = "==") -> None:
        checks.append(_Check(name, expected, actual, relation))

    def userop_summary(label: str) -> Dict[str, Any]:
        bundle = rows[label]
        e = _userop_event(bundle["_raw"])
        op_entry = next(u for u in chain_dump["userops"] if u["label"] == label)
        price = _userop_gas_price(op_entry["packed"], bundle["base_fee_per_gas"])
        cal = chain_dump["pvg_calibrations"][label]
        return {
            "userop_hash": e["userop_hash"], "success": e["success"],
            "paymaster": e["paymaster"], "actual_gas_used": e["actual_gas_used"],
            "actual_gas_cost": e["actual_gas_cost"], "userop_gas_price": price,
            "pre_verification_gas": int(op_entry["packed"]["preVerificationGas"]),
            "bundle_transaction_gas_used": bundle["gas_used"],
            "bundle_transaction_fee": bundle["fee"],
            "bundler_net": e["actual_gas_cost"] - bundle["fee"],
            "bundler_net_gas": e["actual_gas_used"] - bundle["gas_used"],
            "pvg_calibration": cal,
            "_expected_hash": op_entry["userop_hash"],
        }

    # --- UserOperations (AA) --------------------------------------------------
    userop = warm_op = None
    if baseline != "B0":
        userop = userop_summary("w3_bundle")
        check("userop.success", 1, int(userop["success"]))
        check("userop.actual_gas_cost == actual_gas_used * min(maxFee, priority+basefee)",
              userop["actual_gas_used"] * userop["userop_gas_price"], userop["actual_gas_cost"])
        check("userop hash in event == hash signed and submitted",
              int(userop["_expected_hash"], 16), int(userop["userop_hash"], 16))
        check("preVerificationGas was calibrated (not the provisional value)", 1,
              int(userop["pvg_calibration"].get("method") == "break_even_calibration_v1"))
        check(f"no systematic bundler subsidy: bundler net gas >= -{SUBSIDY_TOLERANCE_GAS}",
              -SUBSIDY_TOLERANCE_GAS, userop["bundler_net_gas"], ">=")
        check("beneficiary delta == UserOperation actualGasCost", userop["actual_gas_cost"],
              eth(roles["beneficiary"], end) - eth(roles["beneficiary"], start))
        check("bundler EOA delta == -bundle transaction fee", -rows["w3_bundle"]["fee"],
              eth(roles["bundler"], end) - eth(roles["bundler"], start))
    if warm:
        warm_op = userop_summary("warmup_deploy_bundle")
        check("warm-up op succeeded", 1, int(warm_op["success"]))
        check("account deployed before the measured action", 1,
              int(state["code_size"][recipient][start] > 0))
        check("measured W1-warm op carries no initCode", 0,
              len(bytes.fromhex(next(u for u in chain_dump["userops"]
                                     if u["label"] == "w3_bundle")["packed"]["initCode"][2:])))

    # --- ETH conservation (workflow window) -----------------------------------
    sum_delta = sum(_u(v[end]) - _u(v[start]) for v in state["eth_balance"].values())
    check("sum of all tracked ETH balance deltas == -burned base fees", -total_burned, sum_delta)
    check("block producer delta == priority fees", total_priority,
          eth(roles["block_producer"], end) - eth(roles["block_producer"], start))
    ep_dep_delta = sum(dep(a, end) - dep(a, start) for a in state["entrypoint_deposit"])
    check("EntryPoint ETH delta == sum of EntryPoint deposit deltas",
          ep_dep_delta, eth(ep, end) - eth(ep, start))

    # --- token -------------------------------------------------------------------
    sender = roles["asset_sender"]
    check("asset sender token delta == -amount", -amount, tok(sender, end) - tok(sender, start))
    check("destination token delta == +amount", amount,
          tok(roles["destination"], end) - tok(roles["destination"], start))
    check("recipient token start == 0", 0, tok(recipient, start))
    check("recipient token end == 0", 0, tok(recipient, end))

    # --- baseline-specific identities --------------------------------------------
    sender_delta = eth(sender, end) - eth(sender, start)
    r_eth0, r_eth1 = eth(recipient, start), eth(recipient, end)
    r_dep0, r_dep1 = dep(recipient, start), dep(recipient, end)
    recipient_value_delta = (r_eth1 + r_dep1) - (r_eth0 + r_dep0)
    pm_dep0 = dep(used_pm, start) if used_pm else 0
    pm_dep1 = dep(used_pm, end) if used_pm else 0
    for pm in other_pms:
        check(f"unused paymaster {pm} deposit unchanged", dep(pm, start), dep(pm, end))
    if not warm:
        check("recipient starts with zero native ETH", 0, r_eth0)
        check("recipient starts with zero EntryPoint deposit", 0, r_dep0)

    sponsor_auth_cost = 0
    if baseline == "B0":
        fee3 = rows["w3_recipient_action"]["fee"]
        check("sender delta == -(fee w1 + fee w2 + ETH allowance)",
              -(rows["w1_asset_delivery"]["fee"] + rows["w2_eth_allowance"]["fee"] + allowance),
              sender_delta)
        check("recipient ETH end == allowance - action fee", allowance - fee3, r_eth1)
        action_gas, action_charge = rows["w3_recipient_action"]["gas_used"], fee3
        unused = r_eth1
    elif baseline == "B1":
        check("sender delta == -(fee w1 + fee w2 + ETH allowance)",
              -(rows["w1_asset_delivery"]["fee"] + rows["w2_eth_allowance"]["fee"] + allowance),
              sender_delta)
        check("B1 names no Paymaster", 0, 0 if userop["paymaster"] is None else 1)
        op_json = next(u for u in chain_dump["userops"] if u["label"] == "w3_bundle")["packed"]
        agl, fees = int(op_json["accountGasLimits"], 16), int(op_json["gasFees"], 16)
        prefund = ((agl >> 128) + (agl & ((1 << 128) - 1))
                   + int(op_json["preVerificationGas"])) * (fees & ((1 << 128) - 1))
        check("allowance == EntryPoint required prefund of the measured op", prefund, allowance)
        check("recipient (ETH + deposit) delta == allowance - actualGasCost",
              allowance - userop["actual_gas_cost"], recipient_value_delta)
        action_gas, action_charge = userop["actual_gas_used"], userop["actual_gas_cost"]
        unused = allowance - userop["actual_gas_cost"]
    else:
        check("sender delta == -fee w1 (no ETH allowance)",
              -rows["w1_asset_delivery"]["fee"], sender_delta)
        check("UserOperation names this baseline's Paymaster", int(used_pm, 16),
              int(userop["paymaster"] or "0x0", 16))
        check("Paymaster deposit delta == -actualGasCost",
              -userop["actual_gas_cost"], pm_dep1 - pm_dep0)
        check("recipient ETH and deposit unchanged (zero)", 0, r_eth1 + r_dep1)
        sponsor_delta = (eth(roles["sponsor_operator"], end)
                         - eth(roles["sponsor_operator"], start))
        if baseline == "B2-Allowlist":
            sponsor_auth_cost = rows["w2_sponsor_allowlist"]["fee"]
            check("sponsor operator delta == -allowlist fee", -sponsor_auth_cost, sponsor_delta)
        else:
            check("sponsor operator sends no transaction in B2-Signature", 0, sponsor_delta)
        action_gas, action_charge = userop["actual_gas_used"], userop["actual_gas_cost"]
        unused = 0

    failed = [c for c in checks if not c.ok]
    if failed:
        raise AccountingError("W1 accounting does not reconcile:\n" + "\n".join(
            f"  {c.name}: expected {c.relation} {c.expected}, actual {c.actual}"
            for c in failed))

    def pair(s: int, e: int) -> Dict[str, str]:
        return {"start": str(s), "end": str(e), "delta": str(e - s)}

    def strip(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if d is None:
            return None
        return {k: (str(v) if isinstance(v, int) and not isinstance(v, bool) else v)
                for k, v in d.items() if not k.startswith("_")}

    def s(x: Optional[int]) -> Optional[str]:
        return None if x is None else str(x)

    return {
        "baseline_id": baseline,
        "workload_id": workload,
        "blocks": {"setup_end": int(setup_end), "start": int(start), "end": int(end)},
        "balances": {
            "asset_sender_eth": pair(eth(sender, start), eth(sender, end)),
            "recipient_eth": pair(r_eth0, r_eth1),
            "recipient_entrypoint_deposit": pair(r_dep0, r_dep1),
            "paymaster_entrypoint_deposit": (pair(pm_dep0, pm_dep1) if used_pm else None),
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
        "warmup_transactions": [strip(r) for r in warmup],
        "userop": strip(userop),
        "warmup_userop": strip(warm_op),
        "summary": {
            "setup_gas_used": str(sum(r["gas_used"] for r in setup_rows)),
            "warmup_gas_used": str(sum(r["gas_used"] for r in warmup)),
            "warmup_eth_consumed": str(sum(r["fee"] for r in warmup)),
            "asset_transfer_gas_used": str(rows["w1_asset_delivery"]["gas_used"]),
            "eth_transferred_directly_to_recipient": str(allowance),
            "eth_allowance_transfer_gas_used": s(rows["w2_eth_allowance"]["gas_used"]
                                                 if "w2_eth_allowance" in rows else None),
            "recipient_action_gas_used": str(action_gas),
            "recipient_action_gas_units_source": (
                "EOA transaction receipt gasUsed" if baseline == "B0"
                else "UserOperationEvent.actualGasUsed (preVerificationGas + validation "
                     "+ execution + any penalty)"),
            "userop_charge": s(userop["actual_gas_cost"] if userop else None),
            "paymaster_charge": str(pm_dep0 - pm_dep1) if used_pm else "0",
            "recipient_action_gas_charge": str(action_charge),
            "account_deployment_in_measured_action": baseline != "B0" and not warm,
            "unused_recipient_eth": str(unused),
            "remaining_recipient_entrypoint_deposit": str(r_dep1),
            "paymaster_deposit_delta": str(pm_dep1 - pm_dep0) if used_pm else "0",
            "pre_verification_gas": s(userop["pre_verification_gas"] if userop else None),
            "bundle_transaction_gas_used": s(userop["bundle_transaction_gas_used"]
                                             if userop else None),
            "bundler_reimbursement": s(userop["actual_gas_cost"] if userop else None),
            "bundler_net": s(userop["bundler_net"] if userop else None),
            "bundler_net_gas": s(userop["bundler_net_gas"] if userop else None),
            "sponsor_authorization_cost": str(sponsor_auth_cost),
            "sponsor_authorization_kind": {
                "B2-Allowlist": "on-chain setSponsored transaction",
                "B2-Signature": "off-chain ECDSA signature (no transaction)"}.get(baseline),
            "sender_cost": str(-sender_delta),
            "recipient_cost_own_funds": "0",
            "sponsor_cost": (str(sponsor_auth_cost + (pm_dep0 - pm_dep1))
                             if used_pm else "0"),
            "total_eth_consumed_by_workflow": str(total_fees),
            "burned_base_fee": str(total_burned),
            "priority_fees_to_block_producer": str(total_priority),
        },
        "checks": [c.as_dict() for c in checks],
    }
