"""ABI encoding/decoding for exactly the calls and events W1 uses.

Kept as explicit signatures rather than generic ABI-JSON dispatch, so a reader
can see every selector and topic the runner and the recorder depend on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address

USEROP_TUPLE = "(address,uint256,bytes,bytes,bytes32,uint256,bytes32,bytes,bytes)"


def selector(signature: str) -> bytes:
    return keccak(text=signature)[:4]


def topic(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


def call(signature: str, types: Sequence[str], args: Sequence[Any]) -> bytes:
    return selector(signature) + encode(list(types), list(args))


# --- selectors ---------------------------------------------------------------
SIG_ERC20_TRANSFER = "transfer(address,uint256)"
SIG_ERC20_BALANCE_OF = "balanceOf(address)"
SIG_ACCOUNT_EXECUTE = "execute(address,uint256,bytes)"
SIG_FACTORY_CREATE = "createAccount(address,uint256)"
SIG_FACTORY_GET_ADDRESS = "getAddress(address,uint256)"
SIG_FACTORY_IMPLEMENTATION = "accountImplementation()"
SIG_EP_HANDLE_OPS = f"handleOps({USEROP_TUPLE}[],address)"
SIG_EP_GET_USEROP_HASH = f"getUserOpHash({USEROP_TUPLE})"
SIG_EP_GET_NONCE = "getNonce(address,uint192)"
SIG_EP_BALANCE_OF = "balanceOf(address)"
SIG_PM_SET_SPONSORED = "setSponsored(address,bool)"
SIG_PM_DEPOSIT = "deposit()"

SELECTOR_ERC20_TRANSFER = "0x" + selector(SIG_ERC20_TRANSFER).hex()
SELECTOR_ACCOUNT_EXECUTE = "0x" + selector(SIG_ACCOUNT_EXECUTE).hex()
SELECTOR_HANDLE_OPS = "0x" + selector(SIG_EP_HANDLE_OPS).hex()
SELECTOR_SET_SPONSORED = "0x" + selector(SIG_PM_SET_SPONSORED).hex()
SELECTOR_PM_DEPOSIT = "0x" + selector(SIG_PM_DEPOSIT).hex()

# --- events ------------------------------------------------------------------
T_TRANSFER = topic("Transfer(address,address,uint256)")
T_USEROP_EVENT = topic(
    "UserOperationEvent(bytes32,address,address,uint256,bool,uint256,uint256)")
T_ACCOUNT_DEPLOYED = topic("AccountDeployed(bytes32,address,address,address)")
T_DEPOSITED = topic("Deposited(address,uint256)")
T_USEROP_REVERT_REASON = topic(
    "UserOperationRevertReason(bytes32,address,uint256,bytes)")
T_SPONSORSHIP_SET = topic("SponsorshipSet(address,bool)")

# --- errors ------------------------------------------------------------------
ERR_FAILED_OP = "0x" + selector("FailedOp(uint256,string)").hex()
ERR_FAILED_OP_WITH_REVERT = "0x" + selector(
    "FailedOpWithRevert(uint256,string,bytes)").hex()


def addr_from_topic(t: str) -> str:
    return to_checksum_address("0x" + t[-40:])


def data_bytes(hexstr: str) -> bytes:
    return bytes.fromhex(hexstr.removeprefix("0x"))


def decode_log(log: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Decode the W1-relevant logs; return None for anything else."""
    t0 = log["topics"][0] if log["topics"] else None
    d = data_bytes(log["data"])
    if t0 == T_TRANSFER and len(log["topics"]) == 3:
        (amount,) = decode(["uint256"], d)
        return {"event": "Transfer", "from": addr_from_topic(log["topics"][1]),
                "to": addr_from_topic(log["topics"][2]), "amount": amount}
    if t0 == T_USEROP_EVENT:
        nonce, success, cost, used = decode(["uint256", "bool", "uint256", "uint256"], d)
        pm = addr_from_topic(log["topics"][3])
        return {"event": "UserOperationEvent", "userop_hash": log["topics"][1],
                "sender": addr_from_topic(log["topics"][2]),
                "paymaster": None if int(pm, 16) == 0 else pm,
                "nonce": nonce, "success": success, "actual_gas_cost": cost,
                "actual_gas_used": used}
    if t0 == T_ACCOUNT_DEPLOYED:
        factory, pm = decode(["address", "address"], d)
        return {"event": "AccountDeployed", "userop_hash": log["topics"][1],
                "sender": addr_from_topic(log["topics"][2]),
                "factory": to_checksum_address(factory),
                "paymaster": None if int(pm, 16) == 0 else to_checksum_address(pm)}
    if t0 == T_DEPOSITED:
        (total,) = decode(["uint256"], d)
        return {"event": "Deposited", "account": addr_from_topic(log["topics"][1]),
                "total_deposit": total}
    if t0 == T_SPONSORSHIP_SET:
        (flag,) = decode(["bool"], d)
        return {"event": "SponsorshipSet",
                "account": addr_from_topic(log["topics"][1]), "sponsored": flag}
    if t0 == T_USEROP_REVERT_REASON:
        return {"event": "UserOperationRevertReason", "userop_hash": log["topics"][1]}
    return None


def decode_revert(data: Optional[str]) -> Dict[str, Any]:
    """Classify EntryPoint revert data. Returns reason text for raw logs only."""
    if not data or len(data) < 10:
        return {"error": "unknown", "op_index": None, "reason": None}
    sel, body = data[:10], data_bytes(data[10:])
    if sel == ERR_FAILED_OP:
        idx, reason = decode(["uint256", "string"], body)
        return {"error": "FailedOp", "op_index": idx, "reason": reason}
    if sel == ERR_FAILED_OP_WITH_REVERT:
        idx, reason, inner = decode(["uint256", "string", "bytes"], body)
        return {"error": "FailedOpWithRevert", "op_index": idx, "reason": reason,
                "inner": "0x" + inner.hex()}
    return {"error": "other", "op_index": None, "reason": None, "selector": sel}


def decode_handle_ops(calldata: bytes) -> Tuple[List[Tuple[Any, ...]], str]:
    if calldata[:4] != selector(SIG_EP_HANDLE_OPS):
        raise ValueError("not a handleOps call")
    ops, beneficiary = decode([f"{USEROP_TUPLE}[]", "address"], calldata[4:])
    return list(ops), to_checksum_address(beneficiary)


def decode_execute(calldata: bytes) -> Tuple[str, int, bytes]:
    if calldata[:4] != selector(SIG_ACCOUNT_EXECUTE):
        raise ValueError("not a SimpleAccount.execute call")
    target, value, inner = decode(["address", "uint256", "bytes"], calldata[4:])
    return to_checksum_address(target), value, inner


def decode_erc20_transfer(calldata: bytes) -> Tuple[str, int]:
    if calldata[:4] != selector(SIG_ERC20_TRANSFER):
        raise ValueError("not an ERC20.transfer call")
    to, amount = decode(["address", "uint256"], calldata[4:])
    return to_checksum_address(to), amount
