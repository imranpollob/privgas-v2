"""D2 chain harness: the unchanged W1 + frozen-B3 environment, participants, and a staged bundler.

What is reused unchanged
------------------------
* ``experiments.workloads.w1.runner.setup_environment`` on the ``b3_compat_local`` profile
  (W1 contracts, the frozen B3 contracts in the fixture's order, both Paymaster deposits,
  1 wei to ``address(0)``).
* The real Semaphore v4 / Groth16 prover (``SemaphoreProver``) and B3's real
  ``SemaphoreVerifier``; the calibrated preVerificationGas method; real signed transactions.

What is D2-specific (harness, not protocol)
-------------------------------------------
* ``StagedBundler`` separates the steps the W1 ``InstrumentedBundler`` performs atomically:
  ``simulate(ops)`` (the same ``eth_call handleOps`` from the bundler EOA) and
  ``submit(ops)`` (sign + broadcast the bundle transaction). That separation is what lets an
  unrelated Bootstrap land between simulation and inclusion. Bundles may hold >1 op.
* Participants are D2-only identities (``identity``): *members* (issuers whose Bootstraps
  form the initial tree; spenders are members, and spend from their own bootstrapped
  account exactly as B3's W1 flow does), *contenders* (honest issuers whose Bootstraps are
  root-changing arrivals), and *adversary* issuers.
* ``evm_snapshot`` / ``evm_revert`` isolate trials: every trial of one chain starts from the
  same tree. Snapshots price nothing (preVerificationGas stays the calibrated estimate).
* Spend preVerificationGas is priced once per operation with an all-non-zero 416-byte proof
  placeholder (``SPEND_PRICING_PLACEHOLDER``): a real proof has some zero bytes, so the
  estimate always covers the final calldata (the few-hundred-gas surplus is recorded), and
  the userOpHash -- which excludes the proof -- is fixed before proving. Every attempt of
  one Spend (including every retry) therefore proves over the same userOpHash.
* Bootstrap ``callGasLimit`` is a wallet-side parameter. D2-A uses one fixed experimental
  value from the D2 config (the frozen single-actor value cannot build a tree of more than
  one member -- that is D2-B); D2-B measures the frozen value separately.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from eth_account import Account
from eth_utils import keccak, to_checksum_address

from ...recorder.provenance import repo_root
from ...workloads.w1 import abi, b3, calibration, profiles
from ...workloads.w1.artifacts import load_all
from ...workloads.w1.chain import Chain
from ...workloads.w1.config import load_config
from ...workloads.w1.keys import faucet, role_keys
from ...workloads.w1.prover import SemaphoreProver, group_depth
from ...workloads.w1.rpc import AnvilProcess, RpcError
from ...workloads.w1.runner import _application_call, _token_transfer_data, setup_environment
from ...workloads.w1.userop import (UserOp, counterfactual_address, ep_deposit, ep_nonce,
                                    get_userop_hash, handle_ops_calldata, init_code, sign_userop)

D2_BUNDLER_ID = "privgas-minibundler-v1+d2-staged"
SIMULATION_METHOD = "eth_call handleOps(ops, beneficiary) from bundler EOA, pending block"
SPEND_PRICING_PLACEHOLDER = b"\x01" * b3.PROOF_BYTE_LENGTH
SELECTOR_ROOT_MISMATCH = "0x" + abi.selector("RootMismatch(uint256,uint256)").hex()
B3_ERRORS = {"0x" + abi.selector(s).hex(): s.split("(")[0] for s in (
    "RootMismatch(uint256,uint256)", "InvalidProof()", "NullifierSpent(uint256)",
    "GasCapExceeded(uint256,uint256)", "GasPriceCapExceeded(uint256,uint256)",
    "MaxCostExceeded(uint256,uint256)", "WrongScope()", "WrongMessage()",
    "NotEligible(address)", "AlreadyUsed(address)", "AlreadyDeposited(address)")}


class HarnessInvariantViolation(RuntimeError):
    """A D2 stop condition in the harness itself (e.g. proof root != recorded root)."""


# --- identities ------------------------------------------------------------------------------

DOMAIN = "privgas-v2/d2/identity/v1"


def _key(seed: int, role: str, index: int, kind: str) -> bytes:
    counter = 0
    while True:
        d = hashlib.sha256(f"{DOMAIN}/{seed}/{role}/{index}/{kind}/{counter}".encode()).digest()
        if 0 < int.from_bytes(d, "big") < b3_n():
            return d
        counter += 1  # pragma: no cover


def b3_n() -> int:
    return 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141


@dataclass
class Participant:
    """One credit issuer: owner key of a SimpleAccount, the wallet paying its admission,
    its Semaphore identity, and its announcement ephemeral key."""

    role: str                  # "member" | "contender" | "adversary"
    index: int
    owner_key: bytes
    funder_key: bytes
    semaphore_secret: str
    ephemeral_key: bytes
    account: str = ""
    commitment: int = 0
    announced: bool = False
    bootstrap_ops: Dict[int, UserOp] = field(default_factory=dict)  # call gas limit -> op

    @property
    def owner(self):
        return Account.from_key(self.owner_key)

    @property
    def funder(self):
        return Account.from_key(self.funder_key)

    @property
    def ephemeral(self):
        return Account.from_key(self.ephemeral_key)


def make_participant(seed: int, role: str, index: int) -> Participant:
    return Participant(
        role=role, index=index, owner_key=_key(seed, role, index, "owner"),
        funder_key=_key(seed, role, index, "funder"),
        semaphore_secret=hashlib.sha256(
            f"{DOMAIN}/{seed}/{role}/{index}/semaphore".encode()).hexdigest(),
        ephemeral_key=_key(seed, role, index, "ephemeral"))


# --- bundler ----------------------------------------------------------------------------------


@dataclass
class SimResult:
    accepted: bool
    error: Optional[str]           # FailedOp / FailedOpWithRevert / other
    op_index: Optional[int]
    reason: Optional[str]          # AAxx text
    inner_error: Optional[str]     # decoded B3 custom error name
    inner_args: Optional[List[int]]
    wall_ms: float
    block_number: int


@dataclass
class BundleResult:
    tx_hash: str
    status: int
    block_number: int
    block_timestamp: int
    gas_used: int
    fee_wei: int
    beneficiary_compensation_wei: int
    userop_events: List[Dict[str, Any]]
    revert: Optional[SimResult]    # replay of the same calldata at the parent block
    trace_revert: Optional[Dict[str, Any]]
    wall_ms: float


def decode_inner(inner_hex: Optional[str]) -> Tuple[Optional[str], Optional[List[int]]]:
    if not inner_hex or len(inner_hex) < 10:
        return None, None
    name = B3_ERRORS.get(inner_hex[:10])
    body = bytes.fromhex(inner_hex[10:])
    args = [int.from_bytes(body[i:i + 32], "big") for i in range(0, len(body) - len(body) % 32, 32)]
    return (name or f"unknown:{inner_hex[:10]}"), args


class StagedBundler:
    """The in-repo experimental bundler with simulation and submission as separate calls.

    Same simulation method, fee pinning, beneficiary and bundler EOA as
    ``experiments.workloads.w1.bundler.InstrumentedBundler``. No ERC-7562 tracing, no
    reputation, no public mempool. Every call is logged by the caller (``engine``)."""

    def __init__(self, chain: Chain, entrypoint: str, account, beneficiary: str,
                 gas_per_op: int) -> None:
        self.chain = chain
        self.entrypoint = entrypoint
        self.account = account
        self.beneficiary = beneficiary
        self.gas_per_op = gas_per_op
        self.simulations = 0
        self.submissions = 0

    def gas_limit(self, ops: Sequence[UserOp]) -> int:
        """Bundle transaction gas: every op's EntryPoint gas limits plus a fixed per-op
        allowance for the EntryPoint's unmeasured work (``bundle_gas_per_op``)."""
        return sum(o.verification_gas_limit + o.call_gas_limit + o.pre_verification_gas
                   + o.paymaster_verification_gas_limit + o.paymaster_post_op_gas_limit
                   + self.gas_per_op for o in ops)

    def _decode_error(self, e: RpcError, wall_ms: float, blk: int) -> SimResult:
        d = abi.decode_revert(e.data)
        name, args = decode_inner(d.get("inner"))
        return SimResult(False, d["error"], d.get("op_index"), d.get("reason"), name, args,
                         wall_ms, blk)

    def simulate(self, ops: Sequence[UserOp], block: Any = "pending") -> SimResult:
        self.simulations += 1
        calldata = handle_ops_calldata(list(ops), self.beneficiary)
        self.chain.pin_next_base_fee()
        blk = self.chain.block_number()
        t = time.perf_counter()
        try:
            self.chain.eth_call(self.entrypoint, calldata, block=block,
                                sender=self.account.address, gas=self.gas_limit(ops))
        except RpcError as e:
            return self._decode_error(e, (time.perf_counter() - t) * 1000, blk)
        return SimResult(True, None, None, None, None, None, (time.perf_counter() - t) * 1000, blk)

    def submit(self, ops: Sequence[UserOp], label: str = "bundle") -> BundleResult:
        """Sign and broadcast ``handleOps(ops)`` WITHOUT simulating first."""
        self.submissions += 1
        calldata = handle_ops_calldata(list(ops), self.beneficiary)
        gas = self.gas_limit(ops)
        ben_before = self.chain.balance(self.beneficiary, self.chain.block_number())
        t = time.perf_counter()
        tx = self.chain.build_tx(self.account, to=self.entrypoint, data=calldata, gas=gas)
        st = self.chain.broadcast(self.chain.sign(self.account, tx), label=label, phase="workflow")
        wall = (time.perf_counter() - t) * 1000
        blk = int(st.receipt["blockNumber"], 16)
        ben_after = self.chain.balance(self.beneficiary, blk)
        status = int(st.receipt["status"], 16)
        events = [x for x in (abi.decode_log(l) for l in st.receipt["logs"])
                  if x and x["event"] == "UserOperationEvent"]
        revert = trace = None
        if status != 1:
            # Replay the identical call on the parent block's state (automine: one tx per block,
            # so that is exactly the state the mined transaction executed on).
            try:
                self.chain.eth_call(self.entrypoint, calldata, block=blk - 1,
                                    sender=self.account.address, gas=gas)
                revert = SimResult(True, None, None, None, None, None, 0.0, blk - 1)
            except RpcError as e:
                revert = self._decode_error(e, 0.0, blk - 1)
            trace = mined_revert_output(self.chain, st.hash)
        return BundleResult(tx_hash=st.hash, status=status, block_number=blk,
                            block_timestamp=int(st.block["timestamp"], 16),
                            gas_used=int(st.receipt["gasUsed"], 16), fee_wei=st.fee,
                            beneficiary_compensation_wei=ben_after - ben_before,
                            userop_events=events, revert=revert, trace_revert=trace, wall_ms=wall)


def mined_revert_output(chain: Chain, tx_hash: str) -> Optional[Dict[str, Any]]:
    """Revert output of the MINED transaction from ``debug_traceTransaction`` (callTracer),
    independent of the parent-block replay. None if the node does not provide it."""
    try:
        tr = chain.rpc.call("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    except RpcError:
        return None
    out = tr.get("output") if isinstance(tr, dict) else None
    if not out:
        return {"available": False}
    d = abi.decode_revert(out)
    name, args = decode_inner(d.get("inner"))
    return {"available": True, "error": d["error"], "reason": d.get("reason"),
            "inner_error": name, "inner_args": [str(a) for a in (args or [])]}


# --- the D2 chain ----------------------------------------------------------------------------


@dataclass
class ProofRecord:
    proof: Dict[str, Any]
    root: int
    depth: int
    group_size: int
    prove_ms: float
    verify_off_chain_ms: float
    cache_hit: bool


class D2Chain:
    """One anvil chain on ``b3_compat_local`` with the unchanged W1 + frozen-B3 setup."""

    def __init__(self, seed: int, d2cfg: Dict[str, Any], root: Optional[Path] = None) -> None:
        self.seed = seed
        self.d2 = d2cfg
        self.root_dir = Path(root) if root else repo_root()
        self.cfg = load_config(self.root_dir)
        self.arts = load_all(self.root_dir)
        self.b3arts = b3.load_b3_all(self.root_dir)
        self.b3cfg = b3.load_b3_config(self.root_dir)
        self.profile = profiles.B3_COMPAT
        self.keys = role_keys(seed)
        self._anvil: Optional[AnvilProcess] = None
        self.prover: Optional[SemaphoreProver] = None
        self.members: List[int] = []          # commitments in on-chain insertion order
        self.participants: Dict[Tuple[str, int], Participant] = {}
        self.proof_cache: Dict[Tuple[str, int, int, int], ProofRecord] = {}
        self.proofs_generated = 0
        self.proving_ms_total = 0.0

    # -- lifecycle --
    def __enter__(self) -> "D2Chain":
        self._anvil = AnvilProcess(self.cfg.chain_id, self.cfg.base_fee, self.profile.anvil_args())
        self._anvil.__enter__()
        self.prover = SemaphoreProver(self.root_dir).__enter__()
        try:
            self._setup()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc) -> bool:
        if self.prover is not None:
            self.prover.__exit__(None, None, None)
            self.prover = None
        if self._anvil is not None:
            self._anvil.__exit__(None, None, None)
            self._anvil = None
        return False

    @property
    def anvil_version(self) -> str:
        return self._anvil.version if self._anvil else ""

    def _setup(self) -> None:
        rpc = self._anvil.rpc
        self.chain = Chain(rpc=rpc, chain_id=self.cfg.chain_id, base_fee=self.cfg.base_fee,
                           max_fee=self.cfg.max_fee, max_priority_fee=self.cfg.max_priority_fee)
        self.chain.set_coinbase(self.keys.address("block_producer"))
        self.fingerprint = calibration.environment_fingerprint(
            self.cfg, self.arts, self._anvil.version, self.profile, self.b3arts)
        self.pvg_artifact = calibration.load_artifact(self.root_dir, self.profile.profile_id)
        self.pvg_sha = calibration.artifact_sha256(self.pvg_artifact)
        for shape in calibration.SHAPES:
            calibration.overhead_for(self.pvg_artifact, shape, self.fingerprint)
        self.env = setup_environment(self.chain, self.cfg, self.keys, self.arts, self.profile,
                                     self.b3arts, self.b3cfg)
        # D2 experiment setup (not B3): extra ETH for the bundler / sponsor operator and a
        # larger BootstrapPaymaster and CreditPaymaster EntryPoint deposit, because one chain
        # sponsors hundreds of operations. Plain EntryPoint.depositTo; recorded in manifests.
        f = faucet()
        topup = self.d2["setup"]
        for role, key in (("bundler", "bundler_eth"), ("sponsor_operator", "sponsor_operator_eth")):
            self.chain.send(f, label=f"d2_setup_topup_{role}", phase="setup",
                            to=self.keys.address(role), value=int(topup[key]),
                            gas=self.cfg.gas_limit("native_transfer"))
        for pm in (self.env.b3.bootstrap_paymaster, self.env.b3.credit_paymaster):
            self.chain.send(self.keys.account("sponsor_operator"), label="d2_setup_pm_topup",
                            phase="setup", to=self.env.entrypoint,
                            data=abi.call(b3.SIG_EP_DEPOSIT_TO, ["address"], [pm]),
                            value=int(topup["paymaster_extra_deposit"]),
                            gas=self.cfg.gas_limit("setup_call"))
        self.bundler = StagedBundler(self.chain, self.env.entrypoint, self.keys.account("bundler"),
                                     self.keys.address("beneficiary"),
                                     int(self.d2["bundler"]["bundle_gas_per_op"]))
        self.app_call = _application_call(self.cfg, self.env, self.keys)
        self.setup_end_block = self.chain.block_number()

    # -- reads --
    def root(self) -> int:
        return b3.view_uint(self.chain, self.env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT)

    def pool_root(self) -> int:
        return b3.view_uint(self.chain, self.env.b3.credit_pool, b3.SIG_POOL_CURRENT_ROOT)

    def tree_size(self) -> int:
        return b3.view_uint(self.chain, self.env.b3.credit_pool, b3.SIG_POOL_TREE_SIZE)

    def state_point(self) -> Dict[str, Any]:
        blk = self.chain.rpc.call("eth_getBlockByNumber", ["latest", False])
        return {"root": str(self.root()), "tree_size": self.tree_size(),
                "block_number": int(blk["number"], 16), "block_timestamp": int(blk["timestamp"], 16)}

    def pm_deposit(self, which: str) -> int:
        addr = {"bootstrap": self.env.b3.bootstrap_paymaster,
                "credit": self.env.b3.credit_paymaster}[which]
        return ep_deposit(self.chain, self.env.entrypoint, addr, self.chain.block_number())

    def eth_balance(self, role: str) -> int:
        return self.chain.balance(self.keys.address(role), self.chain.block_number())

    # -- snapshots --
    def snapshot(self) -> Tuple[str, int]:
        return self.chain.snapshot(), len(self.members)

    def revert(self, snap: Tuple[str, int]) -> None:
        self.chain.revert(snap[0])
        del self.members[snap[1]:]

    # -- participants --
    def participant(self, role: str, index: int) -> Participant:
        k = (role, index)
        if k not in self.participants:
            p = make_participant(self.seed, role, index)
            p.account = counterfactual_address(self.chain, self.env.factory, p.owner.address,
                                               self.cfg.account_salt)
            p.commitment = self.prover.commitment(p.semaphore_secret)
            self.participants[k] = p
        return self.participants[k]

    def announce(self, p: Participant) -> None:
        """Stage 1 FUND for participant ``p`` (its own funder wallet pays vMin + F)."""
        if p.announced:
            return
        f = faucet()
        need = self.b3cfg.v_min + self.b3cfg.non_refundable_fee + 10 ** 16
        self.chain.send(f, label="d2_fund_funder", phase="setup", to=p.funder.address, value=need,
                        gas=self.cfg.gas_limit("native_transfer"))
        st = self.chain.send(p.funder, label="d2_announce", phase="workflow", to=self.env.b3.registry,
                             value=self.b3cfg.v_min + self.b3cfg.non_refundable_fee,
                             data=b3.announce_and_fund_calldata(
                                 self.b3cfg.scheme_id, p.account, b3.ephemeral_public_key(p.ephemeral),
                                 b""),
                             gas=self.b3cfg.userop("announce_and_fund_gas_limit"))
        if int(st.receipt["status"], 16) != 1:
            raise HarnessInvariantViolation("announceAndFund reverted")
        p.announced = True
        p.announce_gas = int(st.receipt["gasUsed"], 16)  # type: ignore[attr-defined]
        p.announce_fee_wei = st.fee  # type: ignore[attr-defined]

    def bootstrap_op(self, p: Participant, call_gas_limit: int,
                     max_fee: Optional[int] = None) -> UserOp:
        """The signed Bootstrap op of ``p`` (fixed: nonce 0, initCode, deposit(commitment))."""
        key = (call_gas_limit, max_fee or self.cfg.max_fee)
        if key in p.bootstrap_ops:
            return p.bootstrap_ops[key]
        call_data = b3.bootstrap_call_data(self.env.b3.credit_pool, p.commitment)
        fee = max_fee or self.cfg.max_fee

        def build(pvg: int) -> UserOp:
            op = UserOp(sender=p.account, nonce=0,
                        init_code=init_code(self.env.factory, p.owner.address, self.cfg.account_salt),
                        call_data=call_data, verification_gas_limit=self.cfg.verification_gas_limit,
                        call_gas_limit=call_gas_limit, pre_verification_gas=pvg,
                        max_priority_fee_per_gas=min(self.cfg.max_priority_fee, fee),
                        max_fee_per_gas=fee, paymaster=self.env.b3.bootstrap_paymaster,
                        paymaster_verification_gas_limit=self.b3cfg.userop(
                            "bootstrap_paymaster_verification_gas_limit"),
                        paymaster_post_op_gas_limit=self.b3cfg.userop("paymaster_post_op_gas_limit"))
            sign_userop(self.chain, self.env.entrypoint, op, p.owner)
            return op

        build.call_data = call_data  # type: ignore[attr-defined]
        op = self._estimate(build)
        p.bootstrap_ops[key] = op
        return op

    def _estimate(self, builder) -> UserOp:
        from ...workloads.w1 import pvg as pvg_mod
        shape = calibration.op_shape(builder.call_data)
        est = pvg_mod.estimate(beneficiary=self.bundler.beneficiary,
                               overhead=calibration.overhead_for(self.pvg_artifact, shape,
                                                                 self.fingerprint),
                               op_shape=shape, artifact_sha256=self.pvg_sha, build_signed_op=builder)
        op = builder(est.pre_verification_gas)
        op.pvg_surplus = est.surplus_gas  # type: ignore[attr-defined]
        return op

    def bootstrap_now(self, p: Participant, call_gas_limit: int) -> Dict[str, Any]:
        """Simulate + include ``p``'s Bootstrap immediately (an honest issuer's own bundle).

        Returns an outcome dict; appends the commitment to ``members`` only if a
        ``Deposited`` log with the expected commitment was emitted and the mirrored root
        changed. Nothing is retried."""
        self.announce(p)
        op = self.bootstrap_op(p, call_gas_limit)
        before = self.root()
        size_before = self.tree_size()
        sim = self.bundler.simulate([op])
        out: Dict[str, Any] = {"participant": f"{p.role}/{p.index}", "sim_accepted": sim.accepted,
                               "sim_reason": sim.reason, "root_before": str(before),
                               "tree_size_before": size_before, "included": False,
                               "execution_success": False, "root_changed": False}
        if not sim.accepted:
            return out
        res = self.bundler.submit([op], label="d2_bootstrap")
        out.update({"included": res.status == 1, "tx_hash": res.tx_hash, "gas_used": res.gas_used,
                    "block_number": res.block_number, "bundler_fee_wei": res.fee_wei,
                    "beneficiary_compensation_wei": res.beneficiary_compensation_wei})
        if res.status == 1 and res.userop_events:
            ev = res.userop_events[0]
            out.update({"execution_success": ev["success"], "actual_gas_used": ev["actual_gas_used"],
                        "actual_gas_cost": ev["actual_gas_cost"]})
        receipt = self.chain.sent[-1].receipt
        dep = [d for d in (b3.decode_b3_log(l) for l in receipt["logs"])
               if d and d["event"] == "CreditDeposited"]
        after = self.root()
        if dep and dep[0]["commitment"] == p.commitment and after != before:
            self.members.append(p.commitment)
            out["root_changed"] = True
        out["root_after"] = str(after)
        out["tree_size_after"] = self.tree_size()
        return out

    def build_pool(self, n: int, call_gas_limit: int) -> None:
        """Initial tree of ``n`` members (sequential real Bootstraps); verified against the
        off-chain group and both on-chain roots."""
        for i in range(n):
            out = self.bootstrap_now(self.participant("member", i), call_gas_limit)
            if not out["root_changed"]:
                raise HarnessInvariantViolation(f"initial pool Bootstrap {i} did not insert: {out}")
        g = self.prover.group_root(self.members)
        if not (g["root"] == self.root() == self.pool_root() and self.tree_size() == n):
            raise HarnessInvariantViolation("initial pool: off-chain group root != on-chain roots")

    def give_tokens(self, p: Participant) -> None:
        """The W1 asset for the Spend's application call (from the W1 token treasury)."""
        st = self.chain.send(self.keys.account("asset_sender"), label="d2_token", phase="setup",
                             to=self.env.token,
                             data=_token_transfer_data(p.account, self.cfg.transfer_amount),
                             gas=self.cfg.gas_limit("erc20_transfer"))
        if int(st.receipt["status"], 16) != 1:
            raise HarnessInvariantViolation("token delivery reverted")

    # -- spend --
    def spend_op(self, p: Participant, max_fee: Optional[int] = None) -> Tuple[UserOp, str]:
        """The Spend op of member ``p`` (W1 application call from its own account, nonce from
        the EntryPoint, CreditPaymaster), priced and account-signed; proof NOT yet inserted.
        Returns (op, userOpHash)."""
        fee = max_fee or self.cfg.max_fee
        nonce = ep_nonce(self.chain, self.env.entrypoint, p.account, self.cfg.nonce_key)
        call_data = self.app_call

        def build(pvg: int) -> UserOp:
            op = UserOp(sender=p.account, nonce=nonce, init_code=b"", call_data=call_data,
                        verification_gas_limit=self.cfg.verification_gas_limit,
                        call_gas_limit=self.cfg.call_gas_limit, pre_verification_gas=pvg,
                        max_priority_fee_per_gas=min(self.cfg.max_priority_fee, fee),
                        max_fee_per_gas=fee, paymaster=self.env.b3.credit_paymaster,
                        paymaster_verification_gas_limit=self.b3cfg.userop(
                            "spend_paymaster_verification_gas_limit"),
                        paymaster_post_op_gas_limit=self.b3cfg.userop("paymaster_post_op_gas_limit"))
            op.paymaster_signature = SPEND_PRICING_PLACEHOLDER
            sign_userop(self.chain, self.env.entrypoint, op, p.owner)
            return op

        build.call_data = call_data  # type: ignore[attr-defined]
        op = self._estimate(build)
        op.paymaster_signature = b3.PLACEHOLDER_PROOF
        h = get_userop_hash(self.chain, self.env.entrypoint, op)
        return op, h

    def prove_for(self, p: Participant, message_hex: str, members: Optional[List[int]] = None,
                  use_cache: bool = True) -> ProofRecord:
        """A real Semaphore proof of ``p``'s membership in ``members`` (default: the current
        on-chain insertion order), over ``message``. STOP condition: the proof's group root
        must equal the root of the recorded member list, and when proving against the
        current tree, CreditPaymaster's mirrored root."""
        mem = list(self.members if members is None else members)
        depth = group_depth(len(mem))
        message = int(message_hex, 16)
        key = (p.semaphore_secret, hash(tuple(mem)), message, depth)
        if use_cache and key in self.proof_cache:
            rec = self.proof_cache[key]
            return ProofRecord(rec.proof, rec.root, rec.depth, rec.group_size, rec.prove_ms,
                               rec.verify_off_chain_ms, True)
        res = self.prover.prove(identity_secret=p.semaphore_secret, members=mem, message=message,
                                scope=self.env.b3.credit_scope, merkle_tree_depth=depth,
                                label="d2")
        self.proofs_generated += 1
        self.proving_ms_total += res.prove_ms
        if int(res.proof["merkleTreeRoot"]) != res.group_root:
            raise HarnessInvariantViolation("proof merkleTreeRoot != prover group root")
        if members is None and res.group_root != self.root():
            raise HarnessInvariantViolation(
                "STOP: proof generated against a root different from the recorded on-chain root")
        rec = ProofRecord(res.proof, res.group_root, depth, len(mem), res.prove_ms,
                          res.verify_off_chain_ms, False)
        if use_cache:
            self.proof_cache[key] = rec
        return rec

    def with_proof(self, op: UserOp, h: str, proof: ProofRecord) -> UserOp:
        op2 = UserOp(**{k: getattr(op, k) for k in op.__dataclass_fields__})
        op2.paymaster_signature = b3.encode_proof(proof.proof)
        if get_userop_hash(self.chain, self.env.entrypoint, op2) != h:
            raise HarnessInvariantViolation("userOpHash changed when inserting the proof")
        return op2

    def nullifier_spent(self, proof: ProofRecord) -> bool:
        return bool(b3.view_uint(self.chain, self.env.b3.credit_paymaster, b3.SIG_CPM_NULLIFIER_SPENT,
                                 ("uint256",), (int(proof.proof["nullifier"]),)))

    def ep_nonce_of(self, p: Participant) -> int:
        return ep_nonce(self.chain, self.env.entrypoint, p.account, self.cfg.nonce_key)


def keccak_hex(b: bytes) -> str:
    return "0x" + keccak(b).hex()


def checksum(a: str) -> str:
    return to_checksum_address(a)
