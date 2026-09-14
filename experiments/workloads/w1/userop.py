"""PackedUserOperation construction for B1/B2 (EntryPoint v0.9.0).

No hashing or signature domain is designed here. The UserOperation hash is
obtained from the deployed EntryPoint's own ``getUserOpHash`` (v0.9.0's
EIP-712 domain, bound to chain id and EntryPoint address by upstream code),
and SimpleAccount v0.9.0 verifies ``ECDSA.recover(userOpHash, signature)``
over that raw hash. The runner only signs what the EntryPoint returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from eth_abi import decode, encode
from eth_account import Account
from eth_utils import to_checksum_address

from . import abi
from .chain import Chain


@dataclass
class UserOp:
    sender: str
    nonce: int
    init_code: bytes
    call_data: bytes
    verification_gas_limit: int
    call_gas_limit: int
    pre_verification_gas: int
    max_priority_fee_per_gas: int
    max_fee_per_gas: int
    paymaster: Optional[str] = None
    paymaster_verification_gas_limit: int = 0
    paymaster_post_op_gas_limit: int = 0
    paymaster_data: bytes = b""
    signature: bytes = b""

    @property
    def account_gas_limits(self) -> bytes:
        return ((self.verification_gas_limit << 128)
                | self.call_gas_limit).to_bytes(32, "big")

    @property
    def gas_fees(self) -> bytes:
        return ((self.max_priority_fee_per_gas << 128)
                | self.max_fee_per_gas).to_bytes(32, "big")

    @property
    def paymaster_and_data(self) -> bytes:
        if self.paymaster is None:
            return b""
        return (bytes.fromhex(self.paymaster[2:])
                + self.paymaster_verification_gas_limit.to_bytes(16, "big")
                + self.paymaster_post_op_gas_limit.to_bytes(16, "big")
                + self.paymaster_data)

    def packed(self) -> Tuple[Any, ...]:
        return (to_checksum_address(self.sender), self.nonce, self.init_code,
                self.call_data, self.account_gas_limits, self.pre_verification_gas,
                self.gas_fees, self.paymaster_and_data, self.signature)

    def as_json(self) -> Dict[str, Any]:
        p = self.packed()
        return {"sender": p[0], "nonce": str(p[1]), "initCode": "0x" + p[2].hex(),
                "callData": "0x" + p[3].hex(), "accountGasLimits": "0x" + p[4].hex(),
                "preVerificationGas": str(p[5]), "gasFees": "0x" + p[6].hex(),
                "paymasterAndData": "0x" + p[7].hex(), "signature": "0x" + p[8].hex()}


def unpack(packed: Tuple[Any, ...]) -> Dict[str, Any]:
    """Decode a PackedUserOperation tuple (e.g. from mined handleOps calldata)."""
    sender, nonce, init_code, call_data, agl, pvg, fees, pmd, sig = packed
    agl_i, fees_i = int.from_bytes(agl, "big"), int.from_bytes(fees, "big")
    out = {
        "sender": to_checksum_address(sender), "nonce": nonce,
        "factory": (to_checksum_address("0x" + init_code[:20].hex())
                    if len(init_code) >= 20 else None),
        "init_code_length": len(init_code),
        "call_data": call_data,
        "verification_gas_limit": agl_i >> 128,
        "call_gas_limit": agl_i & ((1 << 128) - 1),
        "pre_verification_gas": pvg,
        "max_priority_fee_per_gas": fees_i >> 128,
        "max_fee_per_gas": fees_i & ((1 << 128) - 1),
        "paymaster": None, "paymaster_verification_gas_limit": None,
        "paymaster_post_op_gas_limit": None,
    }
    if len(pmd) >= 52:
        out["paymaster"] = to_checksum_address("0x" + pmd[:20].hex())
        out["paymaster_verification_gas_limit"] = int.from_bytes(pmd[20:36], "big")
        out["paymaster_post_op_gas_limit"] = int.from_bytes(pmd[36:52], "big")
    return out


def get_userop_hash(chain: Chain, entrypoint: str, op: UserOp) -> str:
    data = abi.call(abi.SIG_EP_GET_USEROP_HASH, [abi.USEROP_TUPLE], [op.packed()])
    return chain.eth_call(entrypoint, data)


def sign_userop(chain: Chain, entrypoint: str, op: UserOp, owner) -> str:
    """Sign the EntryPoint-provided hash with the owner key; returns the hash."""
    h = get_userop_hash(chain, entrypoint, op)
    signed = Account.unsafe_sign_hash(bytes.fromhex(h[2:]), owner.key)
    op.signature = (signed.r.to_bytes(32, "big") + signed.s.to_bytes(32, "big")
                    + bytes([signed.v]))
    # Signing does not change the hash (signature is excluded from it).
    return h


def counterfactual_address(chain: Chain, factory: str, owner: str, salt: int) -> str:
    data = abi.call(abi.SIG_FACTORY_GET_ADDRESS, ["address", "uint256"], [owner, salt])
    (addr,) = decode(["address"], bytes.fromhex(chain.eth_call(factory, data)[2:]))
    return to_checksum_address(addr)


def init_code(factory: str, owner: str, salt: int) -> bytes:
    return bytes.fromhex(factory[2:]) + abi.call(
        abi.SIG_FACTORY_CREATE, ["address", "uint256"], [owner, salt])


def ep_nonce(chain: Chain, entrypoint: str, sender: str, key: int) -> int:
    data = abi.call(abi.SIG_EP_GET_NONCE, ["address", "uint192"], [sender, key])
    return int(chain.eth_call(entrypoint, data), 16)


def ep_deposit(chain: Chain, entrypoint: str, account: str, block: int) -> int:
    data = abi.call(abi.SIG_EP_BALANCE_OF, ["address"], [account])
    return int(chain.eth_call(entrypoint, data, block=block), 16)


def handle_ops_calldata(ops, beneficiary: str) -> bytes:
    return abi.selector(abi.SIG_EP_HANDLE_OPS) + encode(
        [f"{abi.USEROP_TUPLE}[]", "address"], [[o.packed() for o in ops], beneficiary])
