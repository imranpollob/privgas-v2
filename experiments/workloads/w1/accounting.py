"""Full W1 cost reconciliation from a chain dump plus the private role file.

Every number is read from receipts, block headers, logs, or archive state
reads taken at two blocks: ``start`` = last setup block, ``end`` = last
workflow block. Nothing is estimated.

Vocabulary (kept separate on purpose; docs/research-plan.md Sec. 9.4 forbids a
single vague "cost"):

* **transaction fee** -- ``gasUsed * effectiveGasPrice`` of a mined
  transaction, paid by its signer. It splits into the **burned** base fee
  (``gasUsed * baseFeePerGas``) and the **priority fee** paid to the block
  producer.
* **UserOperation charge** -- ``actualGasCost`` from ``UserOperationEvent``:
  what the EntryPoint debits from the payer (account deposit or Paymaster
  deposit) and pays to the bundler's beneficiary. It is an ETH *transfer*
  between participants, not ETH leaving the participant set.
* **total workflow ETH expenditure** -- sum of transaction fees of all W1
  workflow transactions = ETH that left the participant set (burned + paid to
  the block producer).
* **unused recipient ETH** -- native value supplied for the recipient's gas
  that is still held by / credited to the recipient after the action.

``reconcile`` raises ``AccountingError`` if any conservation identity fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import abi

REQUIRED_STEPS = {
    "B0": ("w1_asset_delivery", "w2_eth_allowance", "w3_recipient_action"),
    "B1": ("w1_asset_delivery", "w2_eth_allowance", "w3_bundle"),
    "B2": ("w1_asset_delivery", "w2_sponsor_allowlist", "w3_bundle"),
}


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

    @property
    def ok(self) -> bool:
        return self.expected == self.actual

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "expected": str(self.expected),
                "actual": str(self.actual), "ok": self.ok}


def _userop_gas_price(op_json: Dict[str, Any], base_fee: int) -> int:
    fees = int(op_json["gasFees"], 16)
    prio, max_fee = fees >> 128, fees & ((1 << 128) - 1)
    return min(max_fee, prio + base_fee)


def reconcile(chain_dump: Dict[str, Any], private: Dict[str, Any]) -> Dict[str, Any]:
    baseline = chain_dump["baseline_id"]
    roles = private["roles"]
    labels = private["tx_labels"]
    start = str(chain_dump["blocks"]["setup_end"])
    end = str(chain_dump["blocks"]["workflow_end"])
    state = chain_dump["state"]
    contracts = chain_dump["contracts"]
    ep, pm = contracts["EntryPoint"], contracts["ObservablePaymaster"]
    recipient = roles["recipient_account"]
    amount = _u(chain_dump["config"]["token"]["transfer_amount"])
    allowance = _u(private["eth_allowance"])

    def eth(addr: str, which: str) -> int:
        return _u(state["eth_balance"][addr][which])

    def dep(addr: str, which: str) -> int:
        return _u(state["entrypoint_deposit"][addr][which])

    def tok(addr: str, which: str) -> int:
        return _u(state["erc20_balance"][addr][which])

    workflow = [t for t in chain_dump["transactions"] if t["phase"] == "workflow"]
    txs: Dict[str, Dict[str, Any]] = {}
    tx_rows: List[Dict[str, Any]] = []
    for t in workflow:
        label = labels[t["tx"]["hash"]]
        gas_used = _u(t["receipt"]["gasUsed"])
        price = _u(t["receipt"]["effectiveGasPrice"])
        base_fee = _u(t["block"]["baseFeePerGas"])
        row = {
            "label": label,
            "transaction_hash": t["tx"]["hash"],
            "signer": t["tx"]["from"],
            "status": _u(t["receipt"]["status"]),
            "gas_limit": _u(t["tx"]["gas"]),
            "gas_used": gas_used,
            "effective_gas_price": price,
            "base_fee_per_gas": base_fee,
            "value": _u(t["tx"]["value"]),
            "fee": gas_used * price,
            "burned": gas_used * base_fee,
            "priority_fee_paid": gas_used * (price - base_fee),
        }
        txs[label] = {**row, "_raw": t}
        tx_rows.append(row)

    missing = [s for s in REQUIRED_STEPS[baseline] if s not in txs]
    if missing:
        raise AccountingError(
            f"{baseline} W1 workflow is incomplete (never mined: {missing}); a failed "
            "run has no completed-action cost to reconcile")

    total_fees = sum(r["fee"] for r in tx_rows)
    total_burned = sum(r["burned"] for r in tx_rows)
    total_priority = sum(r["priority_fee_paid"] for r in tx_rows)

    checks: List[_Check] = []

    def check(name: str, expected: int, actual: int) -> None:
        checks.append(_Check(name, expected, actual))

    # --- UserOperation (B1/B2) ---------------------------------------------
    userop: Optional[Dict[str, Any]] = None
    if "w3_bundle" in txs:
        bundle = txs["w3_bundle"]["_raw"]
        events = [abi.decode_log(l) for l in bundle["receipt"]["logs"]]
        uoe = [e for e in events if e and e["event"] == "UserOperationEvent"]
        if len(uoe) != 1:
            raise AccountingError(f"expected one UserOperationEvent, found {len(uoe)}")
        e = uoe[0]
        op_json = chain_dump["userops"][0]["packed"]
        base_fee = _u(bundle["block"]["baseFeePerGas"])
        price = _userop_gas_price(op_json, base_fee)
        userop = {
            "userop_hash": e["userop_hash"],
            "success": e["success"],
            "paymaster": e["paymaster"],
            "actual_gas_used": e["actual_gas_used"],
            "actual_gas_cost": e["actual_gas_cost"],
            "userop_gas_price": price,
            "bundle_transaction_gas_used": txs["w3_bundle"]["gas_used"],
        }
        check("userop.success", 1, int(e["success"]))
        check("userop.actual_gas_cost == actual_gas_used * min(maxFee, priority+basefee)",
              e["actual_gas_used"] * price, e["actual_gas_cost"])
        check("userop hash in event == hash signed and submitted",
              int(chain_dump["userops"][0]["userop_hash"], 16), int(e["userop_hash"], 16))

    # --- ETH conservation (all baselines) --------------------------------------
    tracked = state["eth_balance"]
    sum_delta = sum(_u(v[end]) - _u(v[start]) for v in tracked.values())
    check("sum of all tracked ETH balance deltas == -burned base fees",
          -total_burned, sum_delta)
    check("block producer delta == priority fees",
          total_priority, eth(roles["block_producer"], end) - eth(roles["block_producer"], start))
    ep_dep_delta = sum(dep(a, end) - dep(a, start) for a in state["entrypoint_deposit"])
    check("EntryPoint ETH delta == sum of EntryPoint deposit deltas",
          ep_dep_delta, eth(ep, end) - eth(ep, start))

    # --- token (all baselines) ---------------------------------------------------
    sender = roles["asset_sender"]
    check("asset sender token delta == -amount", -amount, tok(sender, end) - tok(sender, start))
    check("destination token delta == +amount", amount,
          tok(roles["destination"], end) - tok(roles["destination"], start))
    check("recipient token start == 0", 0, tok(recipient, start))
    check("recipient token end == 0", 0, tok(recipient, end))

    # --- baseline-specific identities ----------------------------------------------
    sender_delta = eth(sender, end) - eth(sender, start)
    recipient_eth_start, recipient_eth_end = eth(recipient, start), eth(recipient, end)
    recipient_dep_start, recipient_dep_end = dep(recipient, start), dep(recipient, end)
    pm_dep_start, pm_dep_end = dep(pm, start), dep(pm, end)
    bundler_delta = beneficiary_delta = sponsor_delta = None
    if baseline in ("B1", "B2"):
        bundler_delta = eth(roles["bundler"], end) - eth(roles["bundler"], start)
        beneficiary_delta = eth(roles["beneficiary"], end) - eth(roles["beneficiary"], start)
        check("bundler EOA delta == -bundle transaction fee",
              -txs["w3_bundle"]["fee"], bundler_delta)
        check("beneficiary delta == UserOperation actualGasCost",
              userop["actual_gas_cost"], beneficiary_delta)
    if baseline == "B2":
        sponsor_delta = (eth(roles["sponsor_operator"], end)
                         - eth(roles["sponsor_operator"], start))

    check("recipient starts with zero native ETH", 0, recipient_eth_start)
    check("recipient starts with zero EntryPoint deposit", 0, recipient_dep_start)

    if baseline == "B0":
        check("sender delta == -(fee w1 + fee w2 + ETH allowance)",
              -(txs["w1_asset_delivery"]["fee"] + txs["w2_eth_allowance"]["fee"] + allowance),
              sender_delta)
        check("ETH allowance transferred == w2 value", allowance, txs["w2_eth_allowance"]["value"])
        check("recipient ETH end == allowance - action fee",
              allowance - txs["w3_recipient_action"]["fee"], recipient_eth_end)
        recipient_gas_used = txs["w3_recipient_action"]["gas_used"]
        recipient_gas_charge = txs["w3_recipient_action"]["fee"]
        unused = recipient_eth_end
    elif baseline == "B1":
        check("sender delta == -(fee w1 + fee w2 + ETH allowance)",
              -(txs["w1_asset_delivery"]["fee"] + txs["w2_eth_allowance"]["fee"] + allowance),
              sender_delta)
        check("B1 UserOperation names no Paymaster", 0, 0 if userop["paymaster"] is None else 1)
        check("recipient ETH end + deposit end == allowance - actualGasCost",
              allowance - userop["actual_gas_cost"], recipient_eth_end + recipient_dep_end)
        check("Paymaster deposit unchanged in B1", pm_dep_start, pm_dep_end)
        recipient_gas_used = userop["actual_gas_used"]
        recipient_gas_charge = userop["actual_gas_cost"]
        unused = recipient_eth_end + recipient_dep_end
    else:
        check("sender delta == -fee w1 (no ETH allowance in B2)",
              -txs["w1_asset_delivery"]["fee"], sender_delta)
        check("sponsor operator delta == -allowlist fee",
              -txs["w2_sponsor_allowlist"]["fee"], sponsor_delta)
        check("B2 UserOperation names the Paymaster", int(pm, 16),
              int(userop["paymaster"] or "0x0", 16))
        check("Paymaster deposit delta == -actualGasCost",
              -userop["actual_gas_cost"], pm_dep_end - pm_dep_start)
        check("recipient ETH end == 0", 0, recipient_eth_end)
        check("recipient deposit end == 0", 0, recipient_dep_end)
        recipient_gas_used = userop["actual_gas_used"]
        recipient_gas_charge = userop["actual_gas_cost"]
        unused = 0

    failed = [c for c in checks if not c.ok]
    if failed:
        raise AccountingError("W1 accounting does not reconcile:\n" + "\n".join(
            f"  {c.name}: expected {c.expected}, actual {c.actual}" for c in failed))

    def pair(s: int, e: int) -> Dict[str, str]:
        return {"start": str(s), "end": str(e), "delta": str(e - s)}

    def s(x: Optional[int]) -> Optional[str]:
        return None if x is None else str(x)

    return {
        "baseline_id": baseline,
        "blocks": {"start": int(start), "end": int(end)},
        "balances": {
            "asset_sender_eth": pair(eth(sender, start), eth(sender, end)),
            "recipient_eth": pair(recipient_eth_start, recipient_eth_end),
            "recipient_entrypoint_deposit": pair(recipient_dep_start, recipient_dep_end),
            "paymaster_entrypoint_deposit": pair(pm_dep_start, pm_dep_end),
            "sponsor_operator_eth": pair(eth(roles["sponsor_operator"], start),
                                         eth(roles["sponsor_operator"], end)),
            "bundler_eth": pair(eth(roles["bundler"], start), eth(roles["bundler"], end)),
            "beneficiary_eth": pair(eth(roles["beneficiary"], start),
                                    eth(roles["beneficiary"], end)),
            "block_producer_eth": pair(eth(roles["block_producer"], start),
                                       eth(roles["block_producer"], end)),
            "entrypoint_contract_eth": pair(eth(ep, start), eth(ep, end)),
        },
        "transactions": [{k: (str(v) if isinstance(v, int) else v) for k, v in r.items()}
                         for r in tx_rows],
        "userop": None if userop is None else {
            k: (str(v) if isinstance(v, int) and not isinstance(v, bool) else v)
            for k, v in userop.items()},
        "summary": {
            "eth_transferred_directly_to_recipient": str(allowance),
            "recipient_action_gas_used": str(recipient_gas_used),
            "recipient_action_gas_units_source": (
                "EOA transaction receipt gasUsed" if baseline == "B0"
                else "UserOperationEvent.actualGasUsed (incl. preVerificationGas, "
                     "account deployment, validation, execution, penalty)"),
            "recipient_action_effective_gas_price": str(
                txs["w3_recipient_action"]["effective_gas_price"] if baseline == "B0"
                else userop["userop_gas_price"]),
            "recipient_action_gas_charge": str(recipient_gas_charge),
            "recipient_action_charge_paid_by": {
                "B0": "recipient EOA balance (sender-supplied ETH)",
                "B1": "recipient account EntryPoint prefund (sender-supplied ETH)",
                "B2": "ObservablePaymaster EntryPoint deposit"}[baseline],
            "bundle_transaction_gas_used": s(userop["bundle_transaction_gas_used"]) if userop else None,
            "unused_recipient_eth": str(unused),
            "sender_cost": str(-sender_delta),
            "recipient_cost_own_funds": "0",
            "recipient_net_eth_change": str((recipient_eth_end + recipient_dep_end)
                                            - (recipient_eth_start + recipient_dep_start)),
            "sponsor_cost": (str(-(sponsor_delta) + userop["actual_gas_cost"])
                             if baseline == "B2" else "0"),
            "sponsor_deposit_decrease": str(pm_dep_start - pm_dep_end),
            "bundler_net": (s(bundler_delta + beneficiary_delta)
                            if bundler_delta is not None else None),
            "total_workflow_eth_expenditure": str(total_fees),
            "burned_base_fee": str(total_burned),
            "priority_fees_to_block_producer": str(total_priority),
        },
        "checks": [c.as_dict() for c in checks],
    }
