"""Break-even preVerificationGas calibration for the in-repo bundler.

Why: EntryPoint v0.9.0 reimburses the beneficiary ``actualGasUsed * price``,
where ``actualGasUsed = preVerificationGas + gas the EntryPoint measures itself
(validation, execution, postOp, penalty)``. The bundle transaction also pays
gas the EntryPoint does NOT measure: the 21,000 intrinsic transaction gas, the
calldata cost of the encoded ``handleOps`` call, and EntryPoint work outside
its per-operation gas accounting (ABI decoding of the bundle, the validation
loop prologue, ``BeforeExecution``, emitting ``UserOperationEvent``,
``_compensate``), net of any gas refund. preVerificationGas is the field that
must cover exactly that. A fixed value (the former 50,000) under-covered it by
~18k gas per operation.

Method (``break_even_calibration_v1``; single-operation bundles only):

1. Build the operation with a provisional preVerificationGas P0 and REAL
   signatures (account, and sponsor for B2-Signature); run any state
   preparation it needs (B1: the sender's prefund transfer).
2. Inside an ``evm_snapshot``, broadcast the exact ``handleOps([op],
   beneficiary)`` bundle from the bundler EOA, read receipt ``gasUsed`` G0 and
   ``UserOperationEvent.actualGasUsed`` A0, then ``evm_revert``. Nothing from
   the dry run remains in chain state or in the run's transaction list.
3. Unmeasured gas is ``U = G0 - (A0 - P0)``. Decompose it deterministically:
   ``U = 21,000 + calldataGas(bundle0) + O`` where calldataGas uses EIP-2028
   (4 gas per zero byte, 16 per non-zero byte) over the exact encoded bytes and
   O is the EntryPoint's unmeasured overhead (reported, may absorb refunds).
4. Solve ``P = 21,000 + calldataGas(bundle(P)) + O`` for the final operation,
   re-signing at each step because the hash covers P. Changing P alters only
   the calldata bytes (P itself, the signatures), never EntryPoint execution
   gas, so O is invariant. The iteration is monotone non-decreasing and stops
   when the candidate covers its own calldata; any surplus is reported.

Scope and honesty notes: snapshot/revert dry runs are a devnet facility; a
production bundler must estimate instead (and adds margin). The result is a
zero-margin break-even value for THIS bundler, bundle size 1, this chain. The
EIP-7623 (Prague) calldata floor is checked and must not be binding, otherwise
the decomposition above would not describe the receipt.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable, List, Optional

from . import abi
from .chain import Chain
from .userop import UserOp, handle_ops_calldata

METHOD = "break_even_calibration_v1"
TX_BASE_GAS = 21_000          # intrinsic gas of any transaction
ZERO_BYTE_GAS = 4             # EIP-2028
NONZERO_BYTE_GAS = 16         # EIP-2028
STANDARD_TOKEN_COST = 4       # EIP-7623: tokens = zero_bytes + 4 * nonzero_bytes
FLOOR_TOKEN_COST = 10         # EIP-7623 floor per token (Prague)
MAX_ITERATIONS = 8


def calldata_gas(data: bytes) -> int:
    zeros = data.count(0)
    return zeros * ZERO_BYTE_GAS + (len(data) - zeros) * NONZERO_BYTE_GAS


def calldata_tokens(data: bytes) -> int:
    zeros = data.count(0)
    return zeros + 4 * (len(data) - zeros)


class CalibrationError(RuntimeError):
    pass


@dataclass
class PvgCalibration:
    method: str
    provisional_pre_verification_gas: int
    dry_run_bundle_gas_used: int
    dry_run_userop_actual_gas_used: int
    dry_run_calldata_bytes: int
    dry_run_calldata_gas: int
    tx_base_gas: int
    entrypoint_unmeasured_overhead: int
    pre_verification_gas: int
    final_calldata_bytes: int
    final_calldata_gas: int
    surplus_gas: int
    eip7623_floor_binding: bool
    iterations: List[List[int]] = field(default_factory=list)

    def as_dict(self):
        return asdict(self)


def calibrate(chain: Chain, *, entrypoint: str, bundler_account, beneficiary: str,
              bundle_gas_limit: int, provisional: int,
              build_signed_op: Callable[[int], UserOp],
              prepare: Optional[Callable[[UserOp], None]] = None) -> PvgCalibration:
    snap = chain.snapshot()
    try:
        op0 = build_signed_op(provisional)
        if prepare is not None:
            prepare(op0)
        data0 = handle_ops_calldata([op0], beneficiary)
        tx = chain.build_tx(bundler_account, to=entrypoint, data=data0, gas=bundle_gas_limit)
        dry = chain.broadcast(chain.sign(bundler_account, tx), "pvg_calibration_dry_run",
                              "calibration", record=False)
        if int(dry.receipt["status"], 16) != 1:
            raise CalibrationError("calibration dry-run bundle reverted")
        events = [abi.decode_log(l) for l in dry.receipt["logs"]]
        uoe = [e for e in events if e and e["event"] == "UserOperationEvent"]
        if len(uoe) != 1 or not uoe[0]["success"]:
            raise CalibrationError(f"calibration dry run did not execute the op: {uoe}")
        g0 = int(dry.receipt["gasUsed"], 16)
        a0 = uoe[0]["actual_gas_used"]
    finally:
        chain.revert(snap)

    unmeasured = g0 - (a0 - provisional)
    overhead = unmeasured - TX_BASE_GAS - calldata_gas(data0)

    tokens0 = calldata_tokens(data0)
    execution0 = g0 - TX_BASE_GAS - STANDARD_TOKEN_COST * tokens0
    floor_binding = FLOOR_TOKEN_COST * tokens0 > STANDARD_TOKEN_COST * tokens0 + execution0
    if floor_binding:
        raise CalibrationError("EIP-7623 calldata floor is binding; decomposition invalid")

    pvg = unmeasured
    iterations: List[List[int]] = []
    for _ in range(MAX_ITERATIONS):
        data = handle_ops_calldata([build_signed_op(pvg)], beneficiary)
        required = TX_BASE_GAS + calldata_gas(data) + overhead
        iterations.append([pvg, required])
        if required <= pvg:
            break
        pvg = required
    else:
        raise CalibrationError(f"preVerificationGas did not converge: {iterations}")

    final_data = handle_ops_calldata([build_signed_op(pvg)], beneficiary)
    final_required = TX_BASE_GAS + calldata_gas(final_data) + overhead
    return PvgCalibration(
        method=METHOD,
        provisional_pre_verification_gas=provisional,
        dry_run_bundle_gas_used=g0,
        dry_run_userop_actual_gas_used=a0,
        dry_run_calldata_bytes=len(data0),
        dry_run_calldata_gas=calldata_gas(data0),
        tx_base_gas=TX_BASE_GAS,
        entrypoint_unmeasured_overhead=overhead,
        pre_verification_gas=pvg,
        final_calldata_bytes=len(final_data),
        final_calldata_gas=calldata_gas(final_data),
        surplus_gas=pvg - final_required,
        eip7623_floor_binding=floor_binding,
        iterations=iterations,
    )
