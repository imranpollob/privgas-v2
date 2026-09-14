"""The in-repo instrumented bundler shared by B1 and B2.

Why an in-repo bundler rather than an external one: threat tier A2
(docs/threat-model.md) is only usable with bundlers we operate and can log,
and B1/B2 must use the *same* bundler (docs/research-plan.md Sec. 11). This
one is small enough that every observation it records is auditable here.

What it does, per UserOperation:

1. **receive** -- timestamp; compute the hash via ``EntryPoint.getUserOpHash``.
2. **simulate** -- ``eth_call`` of ``handleOps([op], beneficiary)`` from the
   bundler EOA against the pending block. A revert is decoded
   (``FailedOp`` / ``FailedOpWithRevert``) and the op is rejected with a
   coarse category; nothing is broadcast.
3. **submit** -- sign the bundle transaction, compute its hash locally
   *before* broadcasting (the pre-inclusion association between this
   UserOperation and a prospective bundle, which is A2 knowledge), then
   broadcast.
4. **observe inclusion** -- receipt, inclusion timestamp, and the mined hash
   (public on chain from that point on).

Plus, before the wallet signs the final operation, **preVerificationGas
calibration** (``calibrate_pre_verification_gas``; method in ``pvg.py``): a
break-even value derived from a dry run of the exact encoded bundle inside a
reverted devnet snapshot, logged to the raw bundler log as a
``pvg_calibration`` event (it is the analogue of an
``eth_estimateUserOperationGas`` request, not a submission, and produces no
``bundler_private`` row).

THIS IS AN INSTRUMENTED EXPERIMENTAL BUNDLER. It does not establish ERC-7562
or production compatibility. What it deliberately does NOT do, and therefore
what B1/B2 results do not cover: no ERC-7562 opcode/storage tracing, no
reputation or staking policy (staking requirements are untested, not
inferred), no public alt-mempool (so no A1 observer exists for these runs), no
multi-op bundling, no fee replacement, no profit margin. An independent,
ERC-7562-compatible bundler is required before any D2 liveness claim, any
production-compatibility claim, and to replicate D1 results.

Raw bundler errors (which embed addresses and revert data) go only to the raw
log under data/raw/. The recorder receives coarse classes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from eth_utils import keccak

from . import abi, pvg
from .chain import Chain, SentTx
from .rpc import RpcError
from .userop import UserOp, get_userop_hash, handle_ops_calldata

BUNDLER_ID = "privgas-minibundler-v1"
RPC_ENDPOINT_ID = "local-anvil"
SIMULATION_METHOD = "eth_call handleOps([op], beneficiary) from bundler EOA, pending block"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def classify_rejection(reason: Optional[str]) -> str:
    """Map an EntryPoint FailedOp reason code to a bundler_private category."""
    if not reason:
        return "other"
    code = reason[:4]
    if code in ("AA21", "AA31"):
        return "insufficient_prefund"   # payer (account / paymaster) cannot cover prefund
    if code == "AA25":
        return "nonce_conflict"
    if code.startswith("AA3"):
        return "paymaster_validation_revert"
    if code.startswith("AA1") or code.startswith("AA2"):
        return "aa_validation_revert"
    return "other"


@dataclass
class BundlerOutcome:
    userop_hash: str
    accepted: bool
    bundle: Optional[SentTx]
    log: List[Dict[str, Any]]


@dataclass
class InstrumentedBundler:
    chain: Chain
    entrypoint: str
    account: Any          # bundler EOA (eth_account LocalAccount)
    beneficiary: str
    bundle_gas_limit: int
    clock: Callable[[], str] = utc_now
    log: List[Dict[str, Any]] = field(default_factory=list)
    _attempts: Dict[str, int] = field(default_factory=dict)

    def _emit(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        entry = {"bundler_id": BUNDLER_ID, "rpc_endpoint_id": RPC_ENDPOINT_ID, **entry}
        self.log.append(entry)
        return entry

    def calibrate_pre_verification_gas(self, *, label: str, provisional: int,
                                       build_signed_op, prepare=None) -> pvg.PvgCalibration:
        cal = pvg.calibrate(self.chain, entrypoint=self.entrypoint,
                            bundler_account=self.account, beneficiary=self.beneficiary,
                            bundle_gas_limit=self.bundle_gas_limit, provisional=provisional,
                            build_signed_op=build_signed_op, prepare=prepare)
        self._emit({"event": "pvg_calibration", "label": label,
                    "timestamp_utc": self.clock(), **cal.as_dict()})
        return cal

    def send_user_operation(self, op: UserOp, label: str, phase: str = "workflow") -> BundlerOutcome:
        entries: List[Dict[str, Any]] = []
        received = self.clock()
        userop_hash = get_userop_hash(self.chain, self.entrypoint, op)
        key = f"{op.sender}:{op.nonce}"
        self._attempts[key] = self._attempts.get(key, 0) + 1
        entries.append(self._emit({
            "event": "received", "timestamp_utc": received,
            "userop_hash": userop_hash, "sender": op.sender, "nonce": str(op.nonce),
            "submission_attempt": self._attempts[key], "userop": op.as_json()}))

        calldata = handle_ops_calldata([op], self.beneficiary)
        self.chain.pin_next_base_fee()
        sim_ts = self.clock()
        try:
            self.chain.eth_call(self.entrypoint, calldata, block="pending",
                                sender=self.account.address, gas=self.bundle_gas_limit)
        except RpcError as e:
            decoded = abi.decode_revert(e.data)
            entries.append(self._emit({
                "event": "simulation", "timestamp_utc": sim_ts,
                "userop_hash": userop_hash, "result": "rejected",
                "rejection_category": classify_rejection(decoded.get("reason")),
                "rejection_message_class": ("entrypoint_revert"
                                            if decoded["error"].startswith("FailedOp")
                                            else "unclassified"),
                "raw_error": {"message": str(e), "revert_data": e.data, "decoded": decoded},
                "simulation_method": SIMULATION_METHOD}))
            return BundlerOutcome(userop_hash, False, None, entries)

        entries.append(self._emit({
            "event": "simulation", "timestamp_utc": sim_ts, "userop_hash": userop_hash,
            "result": "accepted", "rejection_category": None,
            "rejection_message_class": None, "simulation_method": SIMULATION_METHOD}))

        tx = self.chain.build_tx(self.account, to=self.entrypoint, data=calldata,
                                 gas=self.bundle_gas_limit)
        raw = self.chain.sign(self.account, tx)
        submitted_hash = "0x" + keccak(raw).hex()
        entries.append(self._emit({
            "event": "submitted", "timestamp_utc": self.clock(),
            "userop_hash": userop_hash,
            "submitted_bundle_transaction_hash": submitted_hash}))

        mined = self.chain.broadcast(raw, label=label, phase=phase)
        included = self.clock()
        if mined.hash != submitted_hash:  # pragma: no cover - automine, no replacement
            raise RuntimeError("mined bundle hash differs from the submitted hash")
        entries.append(self._emit({
            "event": "included", "timestamp_utc": included, "userop_hash": userop_hash,
            "transaction_hash": mined.hash,
            "block_number": int(mined.receipt["blockNumber"], 16)}))
        return BundlerOutcome(userop_hash, True, mined, entries)
