"""Execute one real W1 run against a throwaway anvil.

Baselines: B0, B1, B2-Allowlist, B2-Signature. Workloads: W1-cold (primary)
and W1-warm (AA-only ablation, implemented for B1).

Phases
------
**setup** -- byte-for-byte the same transaction sequence for every baseline
and workload, so contract addresses and chain state match when the workflow
starts: the faucet funds deployer / asset sender / bundler / sponsor operator /
beneficiary; the deployer deploys EntryPoint, SimpleAccountFactory, W1Token,
ObservablePaymaster and SignatureVerifyingPaymaster; the sponsor operator
deposits into the EntryPoint for both paymasters. Environment, not W1 cost.

**warmup** (W1-warm only) -- the sender funds the counterfactual account's
prefund and the bundler includes a deploy-only UserOperation (initCode, empty
callData). Excluded from the measured action cost; recorded separately.

**workflow** (the measured W1 action)::

    step  B0                    B1                        B2-Allowlist              B2-Signature
    w1    sender: token.transfer -> recipient account (identical in all)
    w2    sender: ETH allowance sender: ETH = prefund     sponsor operator:         (none: authorization
                                                          setSponsored(account)      is off chain)
    w3    EOA: token.transfer   bundler: handleOps([op])  bundler: handleOps([op])  bundler: handleOps([op])

For every AA operation the bundler first prices preVerificationGas; the
wallet then signs the final op. ``pvg_mode``:

* ``"calibrated_overhead"`` (default, experiment mode): PVG = 21,000 +
  calldata gas of the exact final bundle + the EntryPoint overhead from the
  calibration artifact (``calibration.py``); nothing is executed to price the
  op and no ``evm_snapshot`` is taken (``chain_dump.environment.
  evm_snapshots_taken`` is recorded and tested to be 0).
* ``"dry_run"`` (calibration / diagnostic mode): the exact-bundle snapshot dry
  run of ``pvg.calibrate``; used by ``python3 -m experiments.workloads.w1.calibrate``.

Outputs: a role-free chain dump and bundler log under data/raw/, and role
assignments under data/private/ (see package docstring).
"""

from __future__ import annotations

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
from . import abi
from .artifacts import Artifact, dependency_tree_digest, forge_build, load_all
from .bundler import BUNDLER_ID, SIMULATION_METHOD, InstrumentedBundler
from .chain import Chain, SentTx, TxRejected
from .config import (
    ENTRYPOINT_SOURCE_COMMIT,
    ENTRYPOINT_SOURCE_REPO,
    ENTRYPOINT_VERSION,
    EXPERIMENT_IDS,
    PAYMASTER_OF,
    W1Config,
    load_config,
)
from .keys import RoleKeys, faucet, role_keys
from . import calibration
from .pvg import CalibrationError
from .rpc import ANVIL_HARDFORK, AnvilProcess
from .userop import (
    UserOp,
    counterfactual_address,
    ep_deposit,
    ep_nonce,
    init_code,
    sign_paymaster,
    sign_userop,
)

BASELINES = ("B0", "B1", "B2-Allowlist", "B2-Signature")
PVG_MODES = ("calibrated_overhead", "dry_run")
WORKLOADS = ("W1-cold", "W1-warm")
DUMP_VERSION = "2"


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

    def paymaster_for(self, baseline_id: str) -> Optional[str]:
        return {"B2-Allowlist": self.allowlist_paymaster,
                "B2-Signature": self.signature_paymaster}.get(baseline_id)


def setup_environment(chain: Chain, cfg: W1Config, keys: RoleKeys,
                      arts: Dict[str, Artifact]) -> Environment:
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

    impl_raw = chain.eth_call(factory, abi.selector(abi.SIG_FACTORY_IMPLEMENTATION))
    (impl,) = decode(["address"], bytes.fromhex(impl_raw[2:]))
    return Environment(entrypoint=ep, factory=factory,
                       account_implementation=to_checksum_address(impl), token=token,
                       allowlist_paymaster=allow_pm, signature_paymaster=sig_pm)


def _token_transfer_data(to: str, amount: int) -> bytes:
    return abi.call(abi.SIG_ERC20_TRANSFER, ["address", "uint256"], [to, amount])


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
    call_data = b""
    if execute:
        call_data = abi.call(abi.SIG_ACCOUNT_EXECUTE, ["address", "uint256", "bytes"],
                             [env.token, 0,
                              _token_transfer_data(keys.address("destination"),
                                                   cfg.transfer_amount)])
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

    return build


def run_baseline(baseline_id: str, seed: int, root: Optional[Path] = None,
                 variation: Optional[Variation] = None, build: bool = True,
                 workload_id: str = "W1-cold",
                 pvg_mode: str = "calibrated_overhead") -> RunResult:
    if pvg_mode not in PVG_MODES:
        raise ValueError(f"pvg_mode must be one of {PVG_MODES}")
    if (baseline_id, workload_id) not in EXPERIMENT_IDS:
        raise ValueError(f"unsupported (baseline, workload) {(baseline_id, workload_id)}; "
                         f"supported: {sorted(EXPERIMENT_IDS)}")
    root = Path(root) if root else repo_root()
    variation = variation or Variation()
    cfg = load_config(root)
    if build:
        forge_build(root)
    arts = load_all(root)
    keys = role_keys(seed)
    addrs = keys.addresses()
    aa = baseline_id != "B0"
    warm = workload_id == "W1-warm"

    with AnvilProcess(cfg.chain_id, cfg.base_fee) as anvil:
        chain = Chain(rpc=anvil.rpc, chain_id=cfg.chain_id, base_fee=cfg.base_fee,
                      max_fee=cfg.max_fee, max_priority_fee=cfg.max_priority_fee)
        chain.set_coinbase(addrs["block_producer"])
        fingerprint = calibration.environment_fingerprint(cfg, arts, anvil.version)
        pvg_artifact = pvg_artifact_sha = None
        if baseline_id != "B0" and pvg_mode == "calibrated_overhead":
            pvg_artifact = calibration.load_artifact(root)
            pvg_artifact_sha = calibration.artifact_sha256(pvg_artifact)
            for shape in calibration.SHAPES:  # fail before any transaction
                if shape in pvg_artifact["entrypoint_unmeasured_overhead_by_shape"]:
                    calibration.overhead_for(pvg_artifact, shape, fingerprint)
        env = setup_environment(chain, cfg, keys, arts)
        setup_end = chain.block_number()

        recipient_account = (addrs["recipient"] if not aa else counterfactual_address(
            chain, env.factory, addrs["recipient"], cfg.account_salt))
        sender = keys.account("asset_sender")
        labels: Dict[str, str] = {}
        userops: List[Dict[str, Any]] = []
        calibrations: Dict[str, Any] = {}
        failure: Optional[WorkflowFailure] = None
        eth_allowance = 0
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
            shape = calibration.op_shape(builder(0).call_data)
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

        # --- warmup (W1-warm): deploy the account before the measured action ---
        if warm:
            wbuild = _op_builder(chain, cfg, env, keys, recipient_account, baseline_id,
                                 deploy=True, execute=False, variation=Variation())
            wop = calibrated("warmup_deploy_bundle", wbuild,
                             lambda o: fund(o, "calibration_prefund", "calibration", False))
            fund(wop, "warmup_eth_allowance", "warmup", True)
            out = bundler.send_user_operation(wop, label="warmup_deploy_bundle", phase="warmup")
            if not out.accepted:
                raise RuntimeError(f"warm-up deployment rejected: {out.log[-1]}")
            userops.append({"label": "warmup_deploy_bundle", "userop_hash": out.userop_hash,
                            "packed": wop.as_json()})
            labels[out.bundle.hash] = "warmup_deploy_bundle"
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
            out = bundler.send_user_operation(op, label="w3_bundle")
            userops.append({"label": "w3_bundle", "userop_hash": out.userop_hash,
                            "packed": op.as_json()})
            if out.accepted:
                labels[out.bundle.hash] = "w3_bundle"
            else:
                sim = out.log[-1]
                failure = WorkflowFailure("w3_bundle", {
                    "rejection_category": sim["rejection_category"],
                    "reason": sim["raw_error"]["decoded"].get("reason")})

        workflow_end = chain.block_number()

        # --- state reads (role-free, keyed by address) ------------------------
        tracked = sorted(set(addrs.values()) - {addrs["established_wallet"]}
                         | {recipient_account, env.entrypoint, env.factory, env.token,
                            env.allowlist_paymaster, env.signature_paymaster,
                            env.account_implementation})
        blocks = sorted({setup_end, warmup_end, workflow_end})
        state = {
            "eth_balance": {a: {str(b): str(chain.balance(a, b)) for b in blocks}
                            for a in tracked},
            "entrypoint_deposit": {
                a: {str(b): str(ep_deposit(chain, env.entrypoint, a, b)) for b in blocks}
                for a in (recipient_account, env.allowlist_paymaster,
                          env.signature_paymaster)},
            "erc20_balance": {
                a: {str(b): str(_erc20_balance(chain, env.token, a, b)) for b in blocks}
                for a in (addrs["asset_sender"], recipient_account, addrs["destination"])},
            "code_size": {a: {str(b): (len(chain.code(a, b)) - 2) // 2 for b in blocks}
                          for a in (recipient_account,)},
            "code_sha256": {a: {str(b): hashlib.sha256(bytes.fromhex(
                                chain.code(a, b)[2:])).hexdigest() for b in blocks}
                            for a in (recipient_account, env.account_implementation)},
        }
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

        contracts = {
            "EntryPoint": env.entrypoint,
            "SimpleAccountFactory": env.factory,
            "SimpleAccount_implementation": env.account_implementation,
            "W1Token": env.token,
            "ObservablePaymaster": env.allowlist_paymaster,
            "SignatureVerifyingPaymaster": env.signature_paymaster,
        }
        chain_dump = {
            "dump_version": DUMP_VERSION,
            "baseline_id": baseline_id,
            "workload_id": workload_id,
            "seed_commitment_sha256": commit_to_value(
                f"w1-dump/{baseline_id}/{workload_id}", seed),
            "config": cfg.raw,
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
            "artifacts": {name: {"deployed_bytecode_sha256": a.deployed_bytecode_sha256,
                                 "bytecode_sha256": hashlib.sha256(a.bytecode).hexdigest()}
                          for name, a in arts.items()},
            "entrypoint_provenance": {
                "version": ENTRYPOINT_VERSION, "source_repo": ENTRYPOINT_SOURCE_REPO,
                "source_commit": ENTRYPOINT_SOURCE_COMMIT,
                "vendored_tree": "baselines/b3_privgas_v1/lib/account-abstraction/contracts",
                "vendored_tree_digest": dependency_tree_digest(
                    root / "baselines/b3_privgas_v1/lib/account-abstraction/contracts"),
            },
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
        "roles": {**addrs, "recipient_account": recipient_account},
        "recipient_account_kind": "eoa" if not aa else "simple_account_v0.9.0",
        "tx_labels": labels,
        "eth_allowance": str(eth_allowance),
        "variation": asdict(variation),
        "failure": None if failure is None else {"step": failure.step, **failure.detail},
    }
    return RunResult(baseline_id=baseline_id, workload_id=workload_id, seed=seed,
                     chain_dump=chain_dump,
                     bundler_log=bundler.log if bundler else [],
                     private=private, failure=failure)


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
