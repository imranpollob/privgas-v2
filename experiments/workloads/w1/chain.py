"""Signed transactions, pinned fees, receipts and state reads.

Every transaction the runner sends is an EIP-1559 transaction signed locally
with a real secp256k1 key and submitted with ``eth_sendRawTransaction``. No
``anvil_impersonateAccount``, no unlocked accounts, no ``vm.prank``: the
node enforces nonce, balance and gas rules exactly as it would for any
ordinary sender, which is what makes B0's insufficient-ETH failure a real
failure.

Fee pinning: before every transaction the next block's base fee is set to the
configured value with ``anvil_setNextBlockBaseFeePerGas``. Without this,
anvil's EIP-1559 base fee drifts down block by block and B0/B1/B2 -- which
have different numbers of blocks -- would pay different prices for identical
work. This is a chain-environment control, not a transaction-level override.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from eth_account import Account
from eth_utils import to_checksum_address

from .rpc import Rpc, RpcError


def hx(n: int) -> str:
    return hex(n)


def un(value: Optional[str]) -> Optional[int]:
    return None if value is None else int(value, 16)


@dataclass
class SentTx:
    """One mined transaction plus everything needed to regenerate records."""

    label: str                 # workflow step name, e.g. "w1_asset_delivery"
    phase: str                 # "setup" | "workflow"
    tx: Dict[str, Any]         # eth_getTransactionByHash
    receipt: Dict[str, Any]    # eth_getTransactionReceipt
    block: Dict[str, Any]      # eth_getBlockByNumber (header only)

    @property
    def hash(self) -> str:
        return self.tx["hash"]

    @property
    def fee(self) -> int:
        return un(self.receipt["gasUsed"]) * un(self.receipt["effectiveGasPrice"])

    @property
    def burned(self) -> int:
        return un(self.receipt["gasUsed"]) * un(self.block["baseFeePerGas"])

    @property
    def priority_paid(self) -> int:
        return self.fee - self.burned

    def as_dict(self) -> Dict[str, Any]:
        # The step label ("w2_eth_allowance", "setup_fund_sponsor_operator", ...)
        # names a ROLE, so it is kept out of the raw chain dump and stored only
        # in the private role file (runner.RunResult.private["tx_labels"]).
        return {"phase": self.phase, "tx": self.tx, "receipt": self.receipt,
                "block": self.block}


class TxRejected(RuntimeError):
    """The node refused to accept a signed transaction (never mined)."""

    def __init__(self, label: str, error: RpcError) -> None:
        self.label = label
        self.rpc_error = error
        super().__init__(f"{label}: node rejected transaction: {error}")


@dataclass
class Chain:
    rpc: Rpc
    chain_id: int
    base_fee: int
    max_fee: int
    max_priority_fee: int
    sent: List[SentTx] = field(default_factory=list)
    #: evm_snapshot calls made; experiment-mode runs must leave this at 0.
    snapshots_taken: int = 0

    # --- reads --------------------------------------------------------------

    def block_number(self) -> int:
        return un(self.rpc.call("eth_blockNumber"))

    def balance(self, address: str, block: int) -> int:
        return un(self.rpc.call("eth_getBalance", [address, hx(block)]))

    def nonce(self, address: str, block: str = "latest") -> int:
        return un(self.rpc.call("eth_getTransactionCount", [address, block]))

    def code(self, address: str, block: int) -> str:
        return self.rpc.call("eth_getCode", [address, hx(block)])

    def eth_call(self, to: str, data: bytes, block: Any = "latest",
                 sender: Optional[str] = None, gas: Optional[int] = None) -> str:
        call: Dict[str, Any] = {"to": to, "data": "0x" + data.hex()}
        if sender:
            call["from"] = sender
        if gas:
            call["gas"] = hx(gas)
        blk = hx(block) if isinstance(block, int) else block
        return self.rpc.call("eth_call", [call, blk])

    # --- environment control -------------------------------------------------

    def pin_next_base_fee(self) -> None:
        self.rpc.call("anvil_setNextBlockBaseFeePerGas", [hx(self.base_fee)])

    def set_coinbase(self, address: str) -> None:
        self.rpc.call("anvil_setCoinbase", [address])

    def snapshot(self) -> str:
        """Devnet state snapshot; used only by the preVerificationGas calibration dry run."""
        self.snapshots_taken += 1
        return self.rpc.call("evm_snapshot")

    def revert(self, snapshot_id: str) -> None:
        if self.rpc.call("evm_revert", [snapshot_id]) is not True:
            raise RuntimeError("evm_revert failed; calibration state would leak")

    # --- writes ---------------------------------------------------------------

    def build_tx(self, sender, *, to: Optional[str], data: bytes = b"",
                 value: int = 0, gas: int) -> Dict[str, Any]:
        tx: Dict[str, Any] = {
            "type": 2,
            "chainId": self.chain_id,
            "nonce": self.nonce(sender.address, "pending"),
            "maxFeePerGas": self.max_fee,
            "maxPriorityFeePerGas": self.max_priority_fee,
            "gas": gas,
            "value": value,
            "data": data,
        }
        if to is not None:
            tx["to"] = to_checksum_address(to)
        return tx

    def sign(self, sender, tx: Dict[str, Any]) -> bytes:
        signed = Account.sign_transaction(tx, sender.key)
        return bytes(signed.raw_transaction)

    def broadcast(self, raw: bytes, label: str, phase: str,
                  record: bool = True) -> SentTx:
        """Submit a signed transaction and return it once mined (automine).

        ``record=False`` is for calibration dry runs inside a snapshot that is
        reverted: the transaction is never part of the run's chain history.
        """
        self.pin_next_base_fee()
        try:
            tx_hash = self.rpc.call("eth_sendRawTransaction", ["0x" + raw.hex()])
        except RpcError as e:
            raise TxRejected(label, e) from e
        return self.mined(tx_hash, label, phase, record)

    def send(self, sender, *, label: str, phase: str, to: Optional[str],
             data: bytes = b"", value: int = 0, gas: int, record: bool = True) -> SentTx:
        tx = self.build_tx(sender, to=to, data=data, value=value, gas=gas)
        return self.broadcast(self.sign(sender, tx), label, phase, record)

    def mined(self, tx_hash: str, label: str, phase: str, record: bool = True) -> SentTx:
        receipt = None
        for _ in range(200):  # automine mines immediately; the receipt can lag briefly
            receipt = self.rpc.call("eth_getTransactionReceipt", [tx_hash])
            if receipt is not None:
                break
            time.sleep(0.02)
        if receipt is None:
            raise RuntimeError(f"{label}: no receipt for {tx_hash} (automine expected)")
        tx = self.rpc.call("eth_getTransactionByHash", [tx_hash])
        block = self.rpc.call("eth_getBlockByNumber", [receipt["blockNumber"], False])
        header = {k: block[k] for k in ("number", "hash", "timestamp",
                                        "baseFeePerGas", "miner", "gasLimit")}
        st = SentTx(label=label, phase=phase, tx=tx, receipt=receipt, block=header)
        if un(receipt["status"]) != 1 and phase == "setup":
            raise RuntimeError(f"setup transaction {label} reverted")
        if record:
            self.sent.append(st)
        return st
