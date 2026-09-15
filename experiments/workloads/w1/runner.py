"""Execute one real W1 run against a throwaway anvil.

Baselines: B0, B1, B2-Allowlist, B2-Signature, and the frozen B3 specimen
B3-PrivGas-v1. Workloads: W1-cold (primary) and W1-warm (AA-only ablation,
implemented for B1). Evaluation profiles (``profiles.py``): ``eip170_standard``
(default) and ``b3_compat_local`` (NON-PRODUCTION, NON-EIP-170-DEPLOYABLE-AS-BUILT,
PRIVACY-EVALUATION-ONLY; required for B3).

Phases
------
**setup** -- byte-for-byte the same transaction sequence for every baseline
and workload ON ONE PROFILE, so contract addresses and chain state match when
the workflow starts: the faucet funds deployer / asset sender / bundler /
sponsor operator / beneficiary; the deployer deploys EntryPoint,
SimpleAccountFactory, W1Token, ObservablePaymaster and
SignatureVerifyingPaymaster; the sponsor operator deposits into the EntryPoint
for both paymasters. On ``b3_compat_local`` the setup then also deploys the
frozen B3 contracts unchanged (PoseidonT3, SemaphoreVerifier, MockAnnouncer,
CreditPaymaster, CreditPool, BootstrapPaymaster, AnnouncementRegistry) and the
sponsor operator funds both B3 Paymasters with ``EntryPoint.depositTo`` -- for
every baseline, not only B3. Environment, not W1 cost.

**warmup** (W1-warm only) -- the sender funds the counterfactual account's
prefund and the bundler includes a deploy-only UserOperation (initCode, empty
callData). Excluded from the measured action cost; recorded separately.

**workflow** (the measured W1 action)::

    step  B0                    B1                        B2-Allowlist              B2-Signature
    w1    sender: token.transfer -> recipient account (identical in all)
    w2    sender: ETH allowance sender: ETH = prefund     sponsor operator:         (none: authorization
                                                          setSponsored(account)      is off chain)
    w3    EOA: token.transfer   bundler: handleOps([op])  bundler: handleOps([op])  bundler: handleOps([op])

    B3-PrivGas-v1 (W1-cold; the frozen protocol's three stages around the same application call)
    w1    sender: token.transfer -> counterfactual SimpleAccount (identical to B1/B2)
    w2    Stage 1 FUND:      sender: AnnouncementRegistry.announceAndFund{vMin + F}(1, account, ephPub, "")
    w3    Stage 2 BOOTSTRAP: bundler: handleOps([op]); op = initCode (deploys the account)
                             + execute(CreditPool, 0, deposit(commitment)), BootstrapPaymaster
    w4    Stage 3 SPEND:     bundler: handleOps([op]); SAME sender, op = execute(token, 0,
                             transfer(destination, amount)), CreditPaymaster + real Semaphore proof

For every AA operation the bundler first prices preVerificationGas; the
wallet then signs the final op (for B3 Spend: proves over the final userOpHash,
then signs). ``pvg_mode``:

* ``"calibrated_overhead"`` (default, experiment mode): PVG = 21,000 +
  calldata gas of the exact final bundle + the EntryPoint overhead from the
  profile's calibration artifact (``calibration.py``); nothing is executed to
  price the op and no ``evm_snapshot`` is taken (``chain_dump.environment.
  evm_snapshots_taken`` is recorded and tested to be 0).
* ``"dry_run"`` (calibration / diagnostic mode): the exact-bundle snapshot dry
  run of ``pvg.calibrate``; used by ``python3 -m experiments.workloads.w1.calibrate``.

Outputs: a role-free chain dump and bundler log under data/raw/, and role
assignments (plus B3 proof timings) under data/private/ (see package docstring).
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from eth_abi import decode, encode
from eth_utils import to_checksum_address

from ...recorder.digest import commit_to_value
from ...recorder.provenance import repo_root
from . import abi, b3, profiles
from .artifacts import Artifact, dependency_tree_digest, forge_build, load_all
from .bundler import BUNDLER_ID, SIMULATION_METHOD, InstrumentedBundler
from .chain import Chain, SentTx, TxRejected
from .config import (
    ALL_PAYMASTERS,
    B3_BASELINE_ID,
    ENTRYPOINT_SOURCE_COMMIT,
    ENTRYPOINT_SOURCE_REPO,
    ENTRYPOINT_VERSION,
    PAYMASTER_OF,
    STANDARD_PROFILE,
    W1Config,
    experiment_ids,
    load_config,
)
from .keys import RoleKeys, faucet, role_keys, semaphore_identity_secret
from . import calibration
from .pvg import CalibrationError
from .rpc import ANVIL_HARDFORK, AnvilProcess
from .userop import (
    UserOp,
    counterfactual_address,
    ep_deposit,
    ep_nonce,
    get_userop_hash,
    init_code,
    sign_paymaster,
    sign_userop,
)

BASELINES = ("B0", "B1", "B2-Allowlist", "B2-Signature", B3_BASELINE_ID)
PVG_MODES = ("calibrated_overhead", "dry_run")
WORKLOADS = ("W1-cold", "W1-warm")
DUMP_VERSION = "3"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
BN254_SCALAR_FIELD = 21888242871839275222246405745257275088548364400416034343698204186575808495617


class WorkflowFailure(RuntimeError):
    """A W1 step failed in the way a negative test expects to observe."""

    def __init__(self, step: str, detail: Dict[str, Any]) -> None:
        self.step = step
        self.detail = detail
        super().__init__(f"W1 step {step} failed: {detail}")


@dataclass
class Variation:
    """Deliberate deviations used ONLY by negative tests. Default = canonical W1."""

    eth_allowance_delta: int = 0          # B0/B1: add (negative: subtract) wei
    skip_sponsorship: bool = False        # B2-Allowlist: do not allowlist the account
    wrong_sponsor_signature: bool = False  # B2-Signature: sign with a non-sponsor key
    b3_skip_announcement: bool = False    # B3: no announceAndFund -> account not eligible
    b3_tamper_proof: bool = False         # B3: alter one Groth16 proof element after proving
    b3_replay_spend: bool = False         # B3: after Spend, try to redeem the same credit again


@dataclass
class RunResult:
    baseline_id: str
    workload_id: str
    seed: int
    chain_dump: Dict[str, Any]
    bundler_log: List[Dict[str, Any]]
    private: Dict[str, Any]
    failure: Optional[WorkflowFailure] = None


def _python_deps() -> Dict[str, str]:
    out = {}
    for dist in ("eth-account", "eth-abi", "eth-utils"):
        try:
            out[dist] = importlib.metadata.version(dist)
        except importlib.metadata.PackageNotFoundError:  # pragma: no cover
            out[dist] = "not installed"
    return out


def _deploy(chain: Chain, deployer, art: Artifact, ctor_types: List[str],
            ctor_args: List[Any], gas: int, label: str) -> str:
    data = art.bytecode + (encode(ctor_types, ctor_args) if ctor_types else b"")
    st = chain.send(deployer, label=label, phase="setup", to=None, data=data, gas=gas)
    return to_checksum_address(st.receipt["contractAddress"])


@dataclass
class Environment:
    entrypoint: str
    factory: str
    account_implementation: str
    token: str
    allowlist_paymaster: str
    signature_paymaster: str
    b3: Optional[b3.B3Environment] = None

    def paymaster_for(self, baseline_id: str) -> Optional[str]:
        return {"B2-Allowlist": self.allowlist_paymaster,
                "B2-Signature": self.signature_paymaster}.get(baseline_id)

    def contracts(self) -> Dict[str, str]:
        out = {
            "EntryPoint": self.entrypoint,
            "SimpleAccountFactory": self.factory,
            "SimpleAccount_implementation": self.account_implementation,
            "W1Token": self.token,
            "ObservablePaymaster": self.allowlist_paymaster,
            "SignatureVerifyingPaymaster": self.signature_paymaster,
        }
        if self.b3 is not None:
            out.update(self.b3.contracts())
        return out


def setup_environment(chain: Chain, cfg: W1Config, keys: RoleKeys,
                      arts: Dict[str, Artifact],
                      profile: profiles.EvaluationProfile = profiles.STANDARD,
                      b3_arts: Optional[Dict[str, b3.B3Artifact]] = None,
                      b3cfg: Optional[b3.B3Config] = None) -> Environment:
    f = faucet()
    for role, amount in (("deployer", cfg.funding("deployer_eth")),
                         ("asset_sender", cfg.funding("asset_sender_eth")),
                         ("bundler", cfg.funding("bundler_eth")),
                         ("sponsor_operator", cfg.funding("sponsor_operator_eth")),
                         ("beneficiary", cfg.funding("beneficiary_eth"))):
        chain.send(f, label=f"setup_fund_{role}", phase="setup",
                   to=keys.address(role), value=amount,
                   gas=cfg.gas_limit("native_transfer"))

    dep = keys.account("deployer")
    gas = cfg.gas_limit("deployment")
    ep = _deploy(chain, dep, arts["EntryPoint"], [], [], gas, "setup_deploy_entrypoint")
    factory = _deploy(chain, dep, arts["SimpleAccountFactory"], ["address"], [ep], gas,
                      "setup_deploy_factory")
    token = _deploy(chain, dep, arts["W1Token"], ["address", "uint256"],
                    [keys.address("asset_sender"), cfg.token_supply], gas,
                    "setup_deploy_token")
    operator = keys.address("sponsor_operator")
    allow_pm = _deploy(chain, dep, arts["ObservablePaymaster"], ["address", "address"],
                       [ep, operator], gas, "setup_deploy_allowlist_paymaster")
    sig_pm = _deploy(chain, dep, arts["SignatureVerifyingPaymaster"],
                     ["address", "address", "address"],
                     [ep, operator, keys.address("sponsor_signer")], gas,
                     "setup_deploy_signature_paymaster")
    for label, pm in (("setup_allowlist_paymaster_deposit", allow_pm),
                      ("setup_signature_paymaster_deposit", sig_pm)):
        chain.send(keys.account("sponsor_operator"), label=label, phase="setup", to=pm,
                   data=abi.selector(abi.SIG_PM_DEPOSIT),
                   value=cfg.funding("paymaster_deposit"), gas=cfg.gas_limit("setup_call"))

    benv = None
    if profile.includes_b3_infrastructure:
        # Appended after the W1 setup so every W1 contract keeps its address.
        benv = b3.deploy_b3(chain, dep, keys.account("sponsor_operator"), arts=b3_arts,
                            b3cfg=b3cfg, entrypoint=ep, gas=gas,
                            call_gas=cfg.gas_limit("setup_call"))
        # B3 burns the non-refundable fee to address(0). On every public EVM chain
        # address(0) is a non-empty account; on a fresh devnet it is empty, and the
        # first burn would pay a one-time 25,000-gas new-account charge no real
        # deployment pays (same rationale as the pre-funded beneficiary).
        chain.send(f, label="setup_fund_address_zero", phase="setup", to=ZERO_ADDRESS,
                   value=int(b3cfg.raw["funding"]["address_zero_wei"]),
                   gas=cfg.gas_limit("native_transfer"))

    impl_raw = chain.eth_call(factory, abi.selector(abi.SIG_FACTORY_IMPLEMENTATION))
    (impl,) = decode(["address"], bytes.fromhex(impl_raw[2:]))
    return Environment(entrypoint=ep, factory=factory,
                       account_implementation=to_checksum_address(impl), token=token,
                       allowlist_paymaster=allow_pm, signature_paymaster=sig_pm, b3=benv)


def _token_transfer_data(to: str, amount: int) -> bytes:
    return abi.call(abi.SIG_ERC20_TRANSFER, ["address", "uint256"], [to, amount])


def _application_call(cfg: W1Config, env: Environment, keys: RoleKeys) -> bytes:
    """The W1 application call, byte-identical for B1, B2 and B3."""
    return abi.call(abi.SIG_ACCOUNT_EXECUTE, ["address", "uint256", "bytes"],
                    [env.token, 0, _token_transfer_data(keys.address("destination"),
                                                        cfg.transfer_amount)])


def _erc20_balance(chain: Chain, token: str, who: str, block: int) -> int:
    data = abi.call(abi.SIG_ERC20_BALANCE_OF, ["address"], [who])
    return int(chain.eth_call(token, data, block=block), 16)


def _op_builder(chain: Chain, cfg: W1Config, env: Environment, keys: RoleKeys,
                account: str, baseline_id: str, *, deploy: bool, execute: bool,
                variation: Variation) -> Callable[[int], UserOp]:
    """Return ``pvg -> fully signed UserOp`` for this baseline and phase.

    Everything except preVerificationGas is fixed here, so B1, B2-Allowlist and
    B2-Signature operations differ only in paymasterAndData (and the calibrated
    preVerificationGas that follows from it).
    """
    owner = keys.account("recipient")
    call_data = _application_call(cfg, env, keys) if execute else b""
    nonce = ep_nonce(chain, env.entrypoint, account, cfg.nonce_key)
    pm = env.paymaster_for(baseline_id)

    def build(pvg: int) -> UserOp:
        op = UserOp(
            sender=account, nonce=nonce,
            init_code=init_code(env.factory, owner.address, cfg.account_salt) if deploy else b"",
            call_data=call_data,
            verification_gas_limit=cfg.verification_gas_limit,
            call_gas_limit=cfg.call_gas_limit,
            pre_verification_gas=pvg,
            max_priority_fee_per_gas=cfg.max_priority_fee,
            max_fee_per_gas=cfg.max_fee,
        )
        if pm is not None:
            op.paymaster = pm
            op.paymaster_verification_gas_limit = cfg.paymaster_verification_gas_limit
            op.paymaster_post_op_gas_limit = cfg.paymaster_post_op_gas_limit
        if baseline_id == "B2-Signature":
            valid_until, valid_after = cfg.paymaster_signature_validity
            op.paymaster_data = encode(["uint48", "uint48"], [valid_until, valid_after])
            signer = keys.account("intruder" if variation.wrong_sponsor_signature
                                  else "sponsor_signer")
            sign_paymaster(chain, env.entrypoint, op, signer)
        sign_userop(chain, env.entrypoint, op, owner)
        return op

    build.call_data = call_data  # type: ignore[attr-defined]
    return build


def _b3_bootstrap_builder(chain: Chain, cfg: W1Config, b3cfg: b3.B3Config, env: Environment,
                          keys: RoleKeys, account: str,
                          commitment: int) -> Callable[[int], UserOp]:
    """Stage 2: ``execute(CreditPool, 0, deposit(commitment))`` sponsored by
    BootstrapPaymaster. The counterfactual account is deployed by this op's
    initCode (the paper's counterfactual-account model; B3 checks no initCode)."""
    owner = keys.account("recipient")
    call_data = b3.bootstrap_call_data(env.b3.credit_pool, commitment)
    nonce = ep_nonce(chain, env.entrypoint, account, cfg.nonce_key)

    def build(pvg: int) -> UserOp:
        op = UserOp(
            sender=account, nonce=nonce,
            init_code=init_code(env.factory, owner.address, cfg.account_salt),
            call_data=call_data,
            verification_gas_limit=cfg.verification_gas_limit,
            call_gas_limit=b3cfg.userop("bootstrap_call_gas_limit"),
            pre_verification_gas=pvg,
            max_priority_fee_per_gas=cfg.max_priority_fee, max_fee_per_gas=cfg.max_fee,
            paymaster=env.b3.bootstrap_paymaster,
            paymaster_verification_gas_limit=b3cfg.userop(
                "bootstrap_paymaster_verification_gas_limit"),
            paymaster_post_op_gas_limit=b3cfg.userop("paymaster_post_op_gas_limit"))
        sign_userop(chain, env.entrypoint, op, owner)
        return op

    build.call_data = call_data  # type: ignore[attr-defined]
    return build


def _b3_spend_builder(chain: Chain, cfg: W1Config, b3cfg: b3.B3Config, env: Environment,
                      keys: RoleKeys, account: str, prover, secret: str, members: List[int],
                      label: str, variation: Variation) -> Callable[[int], UserOp]:
    """Stage 3: the W1 application call from the SAME account, sponsored by
    CreditPaymaster with a real Semaphore v4 proof over the final userOpHash.

    The proof sits in the v0.9.0 paymaster-signature region, which the
    EntryPoint excludes from userOpHash; so the wallet hashes with a placeholder
    of the final length, proves over that hash, inserts the proof, checks the
    hash is unchanged, then signs the same hash with the account key."""
    owner = keys.account("recipient")
    call_data = _application_call(cfg, env, keys)
    nonce = ep_nonce(chain, env.entrypoint, account, cfg.nonce_key)
    proofs: Dict[str, Any] = {}

    def build(pvg: int) -> UserOp:
        op = UserOp(
            sender=account, nonce=nonce, init_code=b"", call_data=call_data,
            verification_gas_limit=cfg.verification_gas_limit,
            call_gas_limit=cfg.call_gas_limit, pre_verification_gas=pvg,
            max_priority_fee_per_gas=cfg.max_priority_fee, max_fee_per_gas=cfg.max_fee,
            paymaster=env.b3.credit_paymaster,
            paymaster_verification_gas_limit=b3cfg.userop(
                "spend_paymaster_verification_gas_limit"),
            paymaster_post_op_gas_limit=b3cfg.userop("paymaster_post_op_gas_limit"))
        op.paymaster_signature = b3.PLACEHOLDER_PROOF
        h = get_userop_hash(chain, env.entrypoint, op)
        if h not in proofs:
            proofs[h] = prover.prove(identity_secret=secret, members=members,
                                     message=int(h, 16), scope=env.b3.credit_scope,
                                     merkle_tree_depth=b3cfg.merkle_tree_depth, label=label)
        proof = dict(proofs[h].proof)
        if variation.b3_tamper_proof:
            points = [int(p) for p in proof["points"]]
            points[0] = (points[0] + 1) % BN254_SCALAR_FIELD
            proof["points"] = points
        op.paymaster_signature = b3.encode_proof(proof)
        if get_userop_hash(chain, env.entrypoint, op) != h:  # pragma: no cover - v0.9 invariant
            raise RuntimeError("userOpHash changed when inserting the Semaphore proof")
        sign_userop(chain, env.entrypoint, op, owner)
        return op

    build.call_data = call_data  # type: ignore[attr-defined]
    return build


def run_baseline(baseline_id: str, seed: int, root: Optional[Path] = None,
                 variation: Optional[Variation] = None, build: bool = True,
                 workload_id: str = "W1-cold",
                 pvg_mode: str = "calibrated_overhead",
                 profile_id: str = STANDARD_PROFILE) -> RunResult:
    if pvg_mode not in PVG_MODES:
        raise ValueError(f"pvg_mode must be one of {PVG_MODES}")
    profile = profiles.get(profile_id)
    ids = experiment_ids(profile_id)
    if (baseline_id, workload_id) not in ids:
        raise ValueError(f"unsupported (baseline, workload) {(baseline_id, workload_id)} on "
                         f"profile {profile_id}; supported: {sorted(ids)}")
    root = Path(root) if root else repo_root()
    variation = variation or Variation()
    cfg = load_config(root)
    if build:
        forge_build(root)
        if profile.includes_b3_infrastructure:
            b3.forge_build_b3(root)
    arts = load_all(root)
    b3_arts = b3.load_b3_all(root) if profile.includes_b3_infrastructure else None
    b3cfg = b3.load_b3_config(root) if profile.includes_b3_infrastructure else None
    keys = role_keys(seed)
    addrs = keys.addresses()
    is_b3 = baseline_id == B3_BASELINE_ID
    aa = baseline_id != "B0"
    warm = workload_id == "W1-warm"

    prover_ctx = contextlib.nullcontext()
    if is_b3:
        from .prover import SemaphoreProver
        prover_ctx = SemaphoreProver(root)

    with AnvilProcess(cfg.chain_id, cfg.base_fee, profile.anvil_args()) as anvil, \
            prover_ctx as prover:
        chain = Chain(rpc=anvil.rpc, chain_id=cfg.chain_id, base_fee=cfg.base_fee,
                      max_fee=cfg.max_fee, max_priority_fee=cfg.max_priority_fee)
        chain.set_coinbase(addrs["block_producer"])
        fingerprint = calibration.environment_fingerprint(cfg, arts, anvil.version, profile,
                                                          b3_arts)
        pvg_artifact = pvg_artifact_sha = None
        if baseline_id != "B0" and pvg_mode == "calibrated_overhead":
            pvg_artifact = calibration.load_artifact(root, profile_id)
            pvg_artifact_sha = calibration.artifact_sha256(pvg_artifact)
            for shape in calibration.SHAPES:  # fail before any transaction
                if shape in pvg_artifact["entrypoint_unmeasured_overhead_by_shape"]:
                    calibration.overhead_for(pvg_artifact, shape, fingerprint)
        env = setup_environment(chain, cfg, keys, arts, profile, b3_arts, b3cfg)
        setup_end = chain.block_number()

        recipient_account = (addrs["recipient"] if not aa else counterfactual_address(
            chain, env.factory, addrs["recipient"], cfg.account_salt))
        sender = keys.account("asset_sender")
        labels: Dict[str, str] = {}
        userops: List[Dict[str, Any]] = []
        calibrations: Dict[str, Any] = {}
        failure: Optional[WorkflowFailure] = None
        eth_allowance = 0
        b3_private: Optional[Dict[str, Any]] = None
        bundler = (InstrumentedBundler(
            chain=chain, entrypoint=env.entrypoint, account=keys.account("bundler"),
            beneficiary=addrs["beneficiary"], bundle_gas_limit=cfg.gas_limit("bundle"))
            if aa else None)

        def step(tx: SentTx) -> SentTx:
            # Only W1 steps whose failure is itself the measured outcome (the
            # B0 action, bundles) may revert; a reverted setup-like step would
            # silently corrupt the run.
            if tx.label != "w3_recipient_action" and int(tx.receipt["status"], 16) != 1:
                raise RuntimeError(f"{tx.label} reverted")
            labels[tx.hash] = tx.label
            return tx

        def fund(op: UserOp, label: str, phase: str, record: bool, delta: int = 0) -> int:
            value = op.required_prefund + delta
            deployed = chain.code(recipient_account, chain.block_number()) != "0x"
            gas = cfg.gas_limit("native_transfer_to_deployed_account" if deployed
                                else "native_transfer")
            tx = chain.send(sender, label=label, phase=phase, to=recipient_account,
                            value=value, gas=gas, record=record)
            if int(tx.receipt["status"], 16) != 1:
                raise RuntimeError(f"{label}: ETH transfer to the account reverted")
            if record:
                step(tx)
            return value

        def calibrated(label: str, builder, prepare) -> UserOp:
            shape = calibration.op_shape(builder.call_data)
            if pvg_mode == "calibrated_overhead":
                est = bundler.estimate_pre_verification_gas(
                    label=label, overhead=calibration.overhead_for(pvg_artifact, shape,
                                                                   fingerprint),
                    op_shape=shape, artifact_sha256=pvg_artifact_sha,
                    build_signed_op=builder)
                calibrations[label] = est.as_dict()
                return builder(est.pre_verification_gas)
            try:
                cal = bundler.calibrate_pre_verification_gas(
                    label=label, provisional=cfg.provisional_pre_verification_gas,
                    build_signed_op=builder, prepare=prepare)
                calibrations[label] = {**cal.as_dict(), "op_shape": shape}
                return builder(cal.pre_verification_gas)
            except CalibrationError as e:
                # Only negative variations reach this: the dry run itself fails
                # (as a real estimation would), so the op is submitted with the
                # provisional value and the bundler's simulation records why.
                calibrations[label] = {"method": "failed", "error": str(e)}
                return builder(cfg.provisional_pre_verification_gas)

        def submit(op: UserOp, label: str, phase: str = "workflow"):
            out = bundler.send_user_operation(op, label=label, phase=phase)
            userops.append({"label": label, "userop_hash": out.userop_hash,
                            "packed": op.as_json()})
            if out.accepted:
                labels[out.bundle.hash] = label
            return out

        def rejected(label: str, out) -> WorkflowFailure:
            sim = out.log[-1]
            return WorkflowFailure(label, {
                "rejection_category": sim["rejection_category"],
                "reason": sim["raw_error"]["decoded"].get("reason")})

        # --- warmup (W1-warm): deploy the account before the measured action ---
        if warm:
            wbuild = _op_builder(chain, cfg, env, keys, recipient_account, baseline_id,
                                 deploy=True, execute=False, variation=Variation())
            wop = calibrated("warmup_deploy_bundle", wbuild,
                             lambda o: fund(o, "calibration_prefund", "calibration", False))
            fund(wop, "warmup_eth_allowance", "warmup", True)
            out = submit(wop, "warmup_deploy_bundle", phase="warmup")
            if not out.accepted:
                raise RuntimeError(f"warm-up deployment rejected: {out.log[-1]}")
        warmup_end = chain.block_number()

        # --- w1: asset delivery (identical in all baselines) ----------------
        step(chain.send(sender, label="w1_asset_delivery", phase="workflow", to=env.token,
                        data=_token_transfer_data(recipient_account, cfg.transfer_amount),
                        gas=cfg.gas_limit("erc20_transfer")))

        if baseline_id == "B0":
            eth_allowance = cfg.b0_eth_allowance + variation.eth_allowance_delta
            step(chain.send(sender, label="w2_eth_allowance", phase="workflow",
                            to=recipient_account, value=eth_allowance,
                            gas=cfg.gas_limit("native_transfer")))
            try:
                step(chain.send(keys.account("recipient"), label="w3_recipient_action",
                                phase="workflow", to=env.token,
                                data=_token_transfer_data(addrs["destination"],
                                                          cfg.transfer_amount),
                                gas=cfg.gas_limit("b0_action")))
            except TxRejected as e:
                failure = WorkflowFailure("w3_recipient_action",
                                          {"node_error": str(e.rpc_error)})
        elif is_b3:
            benv = env.b3
            # Stage 1 FUND: the asset sender announces the stealth account and
            # pays vMin (forwarded) + the non-refundable fee (burned).
            if not variation.b3_skip_announcement:
                step(chain.send(
                    sender, label="w2_announce_and_fund", phase="workflow", to=benv.registry,
                    value=b3cfg.v_min + b3cfg.non_refundable_fee,
                    data=b3.announce_and_fund_calldata(
                        b3cfg.scheme_id, recipient_account,
                        b3.ephemeral_public_key(keys.account("announcement_ephemeral")),
                        bytes.fromhex(b3cfg.raw["protocol"]["announcement_metadata_hex"][2:])),
                    gas=b3cfg.userop("announce_and_fund_gas_limit")))
            secret = semaphore_identity_secret(seed)
            commitment = prover.commitment(secret)
            b3_private = {"identity_commitment": str(commitment), "proof_log": prover.log}

            # Stage 2 BOOTSTRAP: deploy the account and deposit the commitment.
            bop = calibrated("w3_bootstrap_bundle",
                             _b3_bootstrap_builder(chain, cfg, b3cfg, env, keys,
                                                   recipient_account, commitment), None)
            out = submit(bop, "w3_bootstrap_bundle")
            if not out.accepted:
                failure = rejected("w3_bootstrap_bundle", out)
            else:
                # The latest (only) root; the proof must be made against it.
                root_now = b3.view_uint(chain, benv.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT)
                members = [commitment]
                if root_now != commitment:  # single-leaf LeanIMT: root == leaf
                    raise RuntimeError("CreditPaymaster root is not the single deposited leaf")

                # Stage 3 SPEND: the W1 application call, same account, real proof.
                sop = calibrated("w4_spend_bundle",
                                 _b3_spend_builder(chain, cfg, b3cfg, env, keys,
                                                   recipient_account, prover, secret,
                                                   members, "w4_spend_bundle", variation),
                                 None)
                out = submit(sop, "w4_spend_bundle")
                if not out.accepted:
                    failure = rejected("w4_spend_bundle", out)
                elif variation.b3_replay_spend:
                    # A second, freshly generated real proof for the SAME credit on
                    # the next nonce: B3's nullifier set must refuse it.
                    rbuild = _b3_spend_builder(chain, cfg, b3cfg, env, keys, recipient_account,
                                               prover, secret, members, "replay_spend",
                                               Variation())
                    rop = rbuild(sop.pre_verification_gas)
                    rout = bundler.send_user_operation(rop, label="replay_spend")
                    b3_private["replay_attempt"] = {
                        "accepted": rout.accepted,
                        "rejection_category": rout.log[-1].get("rejection_category"),
                        "reason": (rout.log[-1].get("raw_error") or {}).get(
                            "decoded", {}).get("reason"),
                        "inner_revert": (rout.log[-1].get("raw_error") or {}).get(
                            "decoded", {}).get("inner")}
        else:
            if baseline_id == "B2-Allowlist" and not variation.skip_sponsorship:
                step(chain.send(keys.account("sponsor_operator"), label="w2_sponsor_allowlist",
                                phase="workflow", to=env.allowlist_paymaster,
                                data=abi.call(abi.SIG_PM_SET_SPONSORED, ["address", "bool"],
                                              [recipient_account, True]),
                                gas=cfg.gas_limit("setup_call")))
            builder = _op_builder(chain, cfg, env, keys, recipient_account, baseline_id,
                                  deploy=not warm, execute=True, variation=variation)

            def fund_for_calibration(o: UserOp) -> None:
                fund(o, "calibration_prefund", "calibration", False,
                     variation.eth_allowance_delta)

            op = calibrated("w3_bundle", builder,
                            fund_for_calibration if baseline_id == "B1" else None)
            if baseline_id == "B1":
                eth_allowance = fund(op, "w2_eth_allowance", "workflow", True,
                                     variation.eth_allowance_delta)
            out = submit(op, "w3_bundle")
            if not out.accepted:
                failure = rejected("w3_bundle", out)

        workflow_end = chain.block_number()

        # --- state reads (role-free, keyed by address) ------------------------
        contracts = env.contracts()
        paymasters = [contracts[n] for n in ALL_PAYMASTERS if n in contracts]
        tracked = sorted(set(addrs.values()) - {addrs["established_wallet"]}
                         | {recipient_account, *contracts.values()}
                         | ({ZERO_ADDRESS} if env.b3 is not None else set()))
        blocks = sorted({setup_end, warmup_end, workflow_end})
        state = {
            "eth_balance": {a: {str(b): str(chain.balance(a, b)) for b in blocks}
                            for a in tracked},
            "entrypoint_deposit": {
                a: {str(b): str(ep_deposit(chain, env.entrypoint, a, b)) for b in blocks}
                for a in (recipient_account, *paymasters)},
            "erc20_balance": {
                a: {str(b): str(_erc20_balance(chain, env.token, a, b)) for b in blocks}
                for a in (addrs["asset_sender"], recipient_account, addrs["destination"])},
            "code_size": {a: {str(b): (len(chain.code(a, b)) - 2) // 2 for b in blocks}
                          for a in (recipient_account,)},
            "code_sha256": {a: {str(b): hashlib.sha256(bytes.fromhex(
                                chain.code(a, b)[2:])).hexdigest() for b in blocks}
                            for a in (recipient_account, env.account_implementation)},
        }
        if env.b3 is not None:
            benv = env.b3
            nullifier = _mined_nullifier(chain, userops)
            state["b3"] = {str(b): {
                "credit_pool_tree_size": b3.view_uint(chain, benv.credit_pool,
                                                      b3.SIG_POOL_TREE_SIZE, block=b),
                "credit_pool_current_root": str(b3.view_uint(
                    chain, benv.credit_pool, b3.SIG_POOL_CURRENT_ROOT, block=b)),
                "credit_paymaster_root": str(b3.view_uint(
                    chain, benv.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT, block=b)),
                "bootstrap_eligible": bool(b3.view_uint(
                    chain, benv.bootstrap_paymaster, b3.SIG_BPM_IS_ELIGIBLE, ("address",),
                    (recipient_account,), block=b)),
                "bootstrap_used": bool(b3.view_uint(
                    chain, benv.bootstrap_paymaster, b3.SIG_BPM_IS_USED, ("address",),
                    (recipient_account,), block=b)),
                "pool_has_deposited": bool(b3.view_uint(
                    chain, benv.credit_pool, b3.SIG_POOL_HAS_DEPOSITED, ("address",),
                    (recipient_account,), block=b)),
                "nullifier_spent": (None if nullifier is None else bool(b3.view_uint(
                    chain, benv.credit_paymaster, b3.SIG_CPM_NULLIFIER_SPENT, ("uint256",),
                    (nullifier,), block=b))),
            } for b in blocks}
            # Deployed runtime code of the frozen contracts (public chain data), so
            # tests can compare it with the compiled, unmodified artifacts.
            state["b3_runtime_code"] = {name: chain.code(addr, setup_end)
                                        for name, addr in benv.contracts().items()}
        deposit_before_tx: Dict[str, Dict[str, str]] = {}
        for st in chain.sent:
            if st.phase == "setup":
                labels[st.hash] = st.label
            for log in st.receipt["logs"]:
                d = abi.decode_log(log)
                if d and d["event"] == "Deposited":
                    blk = int(st.receipt["blockNumber"], 16) - 1
                    deposit_before_tx.setdefault(st.hash, {})[d["account"]] = str(
                        ep_deposit(chain, env.entrypoint, d["account"], blk))
        state["entrypoint_deposit_before_tx"] = deposit_before_tx

        artifact_digests = {name: {"deployed_bytecode_sha256": a.deployed_bytecode_sha256,
                                   "bytecode_sha256": hashlib.sha256(a.bytecode).hexdigest()}
                            for name, a in arts.items()}
        if b3_arts is not None:
            artifact_digests.update({
                name: {"deployed_bytecode_sha256": a.deployed_bytecode_sha256,
                       "runtime_size_bytes": a.runtime_size,
                       "link_placeholders_zeroed": bool(a.link_references)}
                for name, a in b3_arts.items()})
        chain_dump = {
            "dump_version": DUMP_VERSION,
            "baseline_id": baseline_id,
            "workload_id": workload_id,
            "evaluation_profile": profile.as_dict(),
            "seed_commitment_sha256": commit_to_value(
                f"w1-dump/{baseline_id}/{workload_id}", seed),
            "config": cfg.raw,
            "b3_config": b3cfg.raw if b3cfg is not None else None,
            "environment": {
                "anvil_version": anvil.version,
                "anvil_args": anvil.args[:2] + ["<port>"] + anvil.args[3:],
                "hardfork": ANVIL_HARDFORK,
                "chain_id": cfg.chain_id,
                "coinbase": addrs["block_producer"],
                "python_dependencies": _python_deps(),
                "rpc_calls": anvil.rpc.calls,
                "evm_snapshots_taken": chain.snapshots_taken,
            },
            "contracts": contracts,
            "paymaster_used": PAYMASTER_OF.get(baseline_id),
            # Public on chain (immutable in SignatureVerifyingPaymaster).
            "signature_paymaster_verifying_signer": addrs["sponsor_signer"],
            "artifacts": artifact_digests,
            "entrypoint_provenance": {
                "version": ENTRYPOINT_VERSION, "source_repo": ENTRYPOINT_SOURCE_REPO,
                "source_commit": ENTRYPOINT_SOURCE_COMMIT,
                "vendored_tree": "baselines/b3_privgas_v1/lib/account-abstraction/contracts",
                "vendored_tree_digest": dependency_tree_digest(
                    root / "baselines/b3_privgas_v1/lib/account-abstraction/contracts"),
            },
            "b3_provenance": (_b3_provenance(root) if env.b3 is not None else None),
            "bundler": ({"bundler_id": BUNDLER_ID, "simulation_method": SIMULATION_METHOD,
                         "pvg_mode": pvg_mode,
                         "pre_verification_gas_method": (
                             "calibrated_overhead_v1" if pvg_mode == "calibrated_overhead"
                             else "break_even_calibration_v1"),
                         "calibration_artifact_sha256": pvg_artifact_sha,
                         "environment_fingerprint": fingerprint}
                        if aa else None),
            "pvg_records": calibrations,
            "blocks": {"setup_end": setup_end, "warmup_end": warmup_end,
                       "workflow_end": workflow_end},
            "transactions": [st.as_dict() for st in chain.sent],
            "userops": userops,
            "state": state,
        }

    private = {
        "note": "SECRET. Role assignment for one W1 run; answers who is who. "
                "Never an attacker input.",
        "baseline_id": baseline_id,
        "workload_id": workload_id,
        "evaluation_profile": profile.profile_id,
        "roles": {**addrs, "recipient_account": recipient_account},
        "recipient_account_kind": "eoa" if not aa else "simple_account_v0.9.0",
        "tx_labels": labels,
        "eth_allowance": str(eth_allowance),
        "variation": asdict(variation),
        "failure": None if failure is None else {"step": failure.step, **failure.detail},
        "b3": b3_private,
    }
    return RunResult(baseline_id=baseline_id, workload_id=workload_id, seed=seed,
                     chain_dump=chain_dump,
                     bundler_log=bundler.log if bundler else [],
                     private=private, failure=failure)


def _mined_nullifier(chain: Chain, userops: List[Dict[str, Any]]) -> Optional[int]:
    """The nullifier carried by the mined Spend op (public calldata), if any."""
    spend = next((u for u in userops if u["label"] == "w4_spend_bundle"), None)
    if spend is None:
        return None
    pmd = bytes.fromhex(spend["packed"]["paymasterAndData"][2:])
    return b3.decode_proof(pmd[52:52 + b3.PROOF_BYTE_LENGTH])["nullifier"]


def _b3_provenance(root: Path) -> Dict[str, Any]:
    sub = root / b3.B3_SUBMODULE
    return {
        "baseline_id": B3_BASELINE_ID,
        "source_repo": b3.B3_SOURCE_REPO,
        "source_commit": b3.B3_SOURCE_COMMIT,
        "submodule_path": str(b3.B3_SUBMODULE),
        "src_tree_digest": dependency_tree_digest(sub / "src"),
        "evaluation_build_project": str(b3.B3_EVAL_DIR),
        "semaphore_verifier": "lib/semaphore/packages/contracts/contracts/base/"
                              "SemaphoreVerifier.sol (real Groth16; no mock verifier)",
        "announcer": "test/mock/MockAnnouncer.sol (B3's own ERC-5564 Announcer stand-in)",
        "profile_labels": list(profiles.B3_COMPAT.labels),
        "staking": "none (B3 Paymasters are not staked; the experimental bundler does not "
                   "enforce ERC-7562)",
    }


def write_raw(result: RunResult, raw_dir: Path, private_dir: Path) -> Dict[str, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    out = {"chain_dump": raw_dir / "chain_dump.json",
           "private": private_dir / "w1_private_run.json"}
    for path in out.values():
        if path.exists():
            raise FileExistsError(f"{path} exists; raw files are never overwritten")
    out["chain_dump"].write_text(json.dumps(result.chain_dump, indent=2, sort_keys=True)
                                 + "\n", encoding="utf-8")
    out["private"].write_text(json.dumps(result.private, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
    if result.bundler_log:
        out["bundler_log"] = raw_dir / "bundler_log.jsonl"
        with open(out["bundler_log"], "w", encoding="utf-8") as fh:
            for entry in result.bundler_log:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return out
