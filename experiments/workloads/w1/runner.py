"""Execute one real W1 run for B0, B1 or B2 against a throwaway anvil.

Phases
------
**Setup** (byte-for-byte the same transaction sequence for every baseline,
so contract addresses and chain state are identical when the workflow
starts): the faucet funds deployer / asset sender / bundler / sponsor
operator; the deployer deploys EntryPoint, SimpleAccountFactory, W1Token and
ObservablePaymaster; the sponsor operator deposits into the EntryPoint for
the Paymaster. Setup is environment, not W1 cost.

**Workflow** (W1; the only part that is costed and recorded as events):

    step  B0 sender-funded EOA       B1 sender-funded account     B2 observable Paymaster
    w1    sender: token.transfer     sender: token.transfer       sender: token.transfer
          -> fresh EOA               -> counterfactual account    -> counterfactual account
    w2    sender: ETH allowance      sender: ETH = required       sponsor operator:
          -> fresh EOA               prefund -> account           paymaster.setSponsored(account)
    w3    fresh EOA: token.transfer  bundler: handleOps([op])     bundler: handleOps([op])
          -> destination             op = deploy + execute(       op = same as B1 + paymasterAndData
                                     token.transfer(dest))

Outputs (see package docstring): a role-free chain dump and bundler log under
data/raw/, and role assignments + cost reconciliation under data/private/.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from eth_abi import decode, encode
from eth_utils import to_checksum_address

from ...recorder.digest import commit_to_value
from ...recorder.provenance import repo_root
from . import abi
from .artifacts import Artifact, dependency_tree_digest, forge_build, load_all
from .bundler import BUNDLER_ID, SIMULATION_METHOD, BundlerOutcome, InstrumentedBundler
from .chain import Chain, SentTx, TxRejected
from .config import (
    ENTRYPOINT_SOURCE_COMMIT,
    ENTRYPOINT_SOURCE_REPO,
    ENTRYPOINT_VERSION,
    W1Config,
    load_config,
)
from .keys import RoleKeys, faucet, role_keys
from .rpc import ANVIL_HARDFORK, AnvilProcess
from .userop import (
    UserOp,
    counterfactual_address,
    ep_deposit,
    ep_nonce,
    init_code,
    sign_userop,
)

BASELINES = ("B0", "B1", "B2")
DUMP_VERSION = "1"


class WorkflowFailure(RuntimeError):
    """A W1 step failed in the way a negative test expects to observe."""

    def __init__(self, step: str, detail: Dict[str, Any]) -> None:
        self.step = step
        self.detail = detail
        super().__init__(f"W1 step {step} failed: {detail}")


@dataclass
class Variation:
    """Deliberate deviations used ONLY by negative tests. Default = canonical W1."""

    eth_allowance_delta: int = 0       # B0/B1: add (negative: subtract) wei
    skip_sponsorship: bool = False     # B2: do not allowlist the account


@dataclass
class RunResult:
    baseline_id: str
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
    paymaster: str


def setup_environment(chain: Chain, cfg: W1Config, keys: RoleKeys,
                      arts: Dict[str, Artifact]) -> Environment:
    f = faucet()
    for role, amount in (("deployer", cfg.funding("deployer_eth")),
                         ("asset_sender", cfg.funding("asset_sender_eth")),
                         ("bundler", cfg.funding("bundler_eth")),
                         ("sponsor_operator", cfg.funding("sponsor_operator_eth"))):
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
    paymaster = _deploy(chain, dep, arts["ObservablePaymaster"], ["address", "address"],
                        [ep, keys.address("sponsor_operator")], gas,
                        "setup_deploy_paymaster")
    chain.send(keys.account("sponsor_operator"), label="setup_paymaster_deposit",
               phase="setup", to=paymaster, data=abi.selector(abi.SIG_PM_DEPOSIT),
               value=cfg.funding("paymaster_deposit"), gas=cfg.gas_limit("setup_call"))

    impl_raw = chain.eth_call(factory, abi.selector(abi.SIG_FACTORY_IMPLEMENTATION))
    (impl,) = decode(["address"], bytes.fromhex(impl_raw[2:]))
    return Environment(entrypoint=ep, factory=factory,
                       account_implementation=to_checksum_address(impl),
                       token=token, paymaster=paymaster)


def _token_transfer_data(to: str, amount: int) -> bytes:
    return abi.call(abi.SIG_ERC20_TRANSFER, ["address", "uint256"], [to, amount])


def _erc20_balance(chain: Chain, token: str, who: str, block: int) -> int:
    data = abi.call(abi.SIG_ERC20_BALANCE_OF, ["address"], [who])
    return int(chain.eth_call(token, data, block=block), 16)


def _build_userop(chain: Chain, cfg: W1Config, env: Environment, keys: RoleKeys,
                  account: str, with_paymaster: bool) -> UserOp:
    owner = keys.address("recipient")
    execute = abi.call(abi.SIG_ACCOUNT_EXECUTE, ["address", "uint256", "bytes"],
                       [env.token, 0,
                        _token_transfer_data(keys.address("destination"),
                                             cfg.transfer_amount)])
    op = UserOp(
        sender=account,
        nonce=ep_nonce(chain, env.entrypoint, account, cfg.nonce_key),
        init_code=init_code(env.factory, owner, cfg.account_salt),
        call_data=execute,
        verification_gas_limit=cfg.verification_gas_limit,
        call_gas_limit=cfg.call_gas_limit,
        pre_verification_gas=cfg.pre_verification_gas,
        max_priority_fee_per_gas=cfg.max_priority_fee,
        max_fee_per_gas=cfg.max_fee,
    )
    if with_paymaster:
        op.paymaster = env.paymaster
        op.paymaster_verification_gas_limit = cfg.paymaster_verification_gas_limit
        op.paymaster_post_op_gas_limit = cfg.paymaster_post_op_gas_limit
    return op


def run_baseline(baseline_id: str, seed: int, root: Optional[Path] = None,
                 variation: Optional[Variation] = None,
                 build: bool = True) -> RunResult:
    if baseline_id not in BASELINES:
        raise ValueError(f"W1 runner supports {BASELINES}, not {baseline_id!r}")
    root = Path(root) if root else repo_root()
    variation = variation or Variation()
    cfg = load_config(root)
    if build:
        forge_build(root)
    arts = load_all(root)
    keys = role_keys(seed)
    addrs = keys.addresses()

    with AnvilProcess(cfg.chain_id, cfg.base_fee) as anvil:
        chain = Chain(rpc=anvil.rpc, chain_id=cfg.chain_id, base_fee=cfg.base_fee,
                      max_fee=cfg.max_fee, max_priority_fee=cfg.max_priority_fee)
        chain.set_coinbase(addrs["block_producer"])
        env = setup_environment(chain, cfg, keys, arts)
        setup_end = chain.block_number()

        # The recipient-controlled account: a fresh EOA for B0, the
        # counterfactual SimpleAccount (owned by the fresh key) for B1/B2.
        if baseline_id == "B0":
            recipient_account = addrs["recipient"]
        else:
            recipient_account = counterfactual_address(
                chain, env.factory, addrs["recipient"], cfg.account_salt)

        sender = keys.account("asset_sender")
        labels: Dict[str, str] = {}
        bundler_obj: Optional[InstrumentedBundler] = None
        userops: List[Dict[str, Any]] = []
        failure: Optional[WorkflowFailure] = None
        eth_allowance = 0

        def step(tx: SentTx) -> SentTx:
            labels[tx.hash] = tx.label
            return tx

        # --- w1: asset delivery (identical in all baselines) ----------------
        step(chain.send(sender, label="w1_asset_delivery", phase="workflow",
                        to=env.token,
                        data=_token_transfer_data(recipient_account, cfg.transfer_amount),
                        gas=cfg.gas_limit("erc20_transfer")))

        # --- w2: gas funding mechanism ---------------------------------------
        if baseline_id in ("B0", "B1"):
            base = cfg.b0_eth_allowance if baseline_id == "B0" else cfg.b1_eth_allowance
            eth_allowance = base + variation.eth_allowance_delta
            step(chain.send(sender, label="w2_eth_allowance", phase="workflow",
                            to=recipient_account, value=eth_allowance,
                            gas=cfg.gas_limit("native_transfer")))
        elif not variation.skip_sponsorship:
            step(chain.send(keys.account("sponsor_operator"),
                            label="w2_sponsor_allowlist", phase="workflow",
                            to=env.paymaster,
                            data=abi.call(abi.SIG_PM_SET_SPONSORED, ["address", "bool"],
                                          [recipient_account, True]),
                            gas=cfg.gas_limit("setup_call")))

        # --- w3: the recipient's application action --------------------------
        if baseline_id == "B0":
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
            bundler_obj = InstrumentedBundler(
                chain=chain, entrypoint=env.entrypoint, account=keys.account("bundler"),
                beneficiary=addrs["beneficiary"],
                bundle_gas_limit=cfg.gas_limit("bundle"))
            op = _build_userop(chain, cfg, env, keys, recipient_account,
                               with_paymaster=(baseline_id == "B2"))
            userop_hash = sign_userop(chain, env.entrypoint, op, keys.account("recipient"))
            userops.append({"userop_hash": userop_hash, "packed": op.as_json()})
            outcome: BundlerOutcome = bundler_obj.send_user_operation(
                op, label="w3_bundle")
            if outcome.accepted:
                labels[outcome.bundle.hash] = "w3_bundle"
            else:
                sim = outcome.log[-1]
                failure = WorkflowFailure("w3_bundle", {
                    "rejection_category": sim["rejection_category"],
                    "reason": sim["raw_error"]["decoded"].get("reason")})

        workflow_end = chain.block_number()

        # --- state reads for accounting (role-free, keyed by address) --------
        tracked = sorted(set(addrs.values()) - {addrs["established_wallet"]}
                         | {recipient_account, env.entrypoint, env.factory,
                            env.token, env.paymaster, env.account_implementation})
        blocks = sorted({setup_end, workflow_end})
        state = {
            "eth_balance": {a: {str(b): str(chain.balance(a, b)) for b in blocks}
                            for a in tracked},
            "entrypoint_deposit": {
                a: {str(b): str(ep_deposit(chain, env.entrypoint, a, b)) for b in blocks}
                for a in (recipient_account, env.paymaster)},
            "erc20_balance": {
                a: {str(b): str(_erc20_balance(chain, env.token, a, b)) for b in blocks}
                for a in (addrs["asset_sender"], recipient_account, addrs["destination"])},
            "code_size": {a: {str(b): (len(chain.code(a, b)) - 2) // 2 for b in blocks}
                          for a in (recipient_account,)},
            "code_sha256": {a: {str(b): hashlib.sha256(bytes.fromhex(
                                chain.code(a, b)[2:])).hexdigest() for b in blocks}
                            for a in (recipient_account, env.account_implementation)},
        }
        # Deposit before each Deposited log's block, so deposit *deltas* are
        # regenerable from the dump without re-querying the chain.
        deposit_before_tx: Dict[str, Dict[str, str]] = {}
        for st in chain.sent:
            if st.phase != "workflow":
                continue
            for log in st.receipt["logs"]:
                d = abi.decode_log(log)
                if d and d["event"] == "Deposited":
                    blk = int(st.receipt["blockNumber"], 16) - 1
                    deposit_before_tx.setdefault(st.hash, {})[d["account"]] = str(
                        ep_deposit(chain, env.entrypoint, d["account"], blk))
        state["entrypoint_deposit_before_tx"] = deposit_before_tx

        chain_dump = {
            "dump_version": DUMP_VERSION,
            "baseline_id": baseline_id,
            "workload_id": "W1",
            "seed_commitment_sha256": commit_to_value(f"w1-dump/{baseline_id}", seed),
            "config": cfg.raw,
            "environment": {
                "anvil_version": anvil.version,
                "anvil_args": anvil.args[:2] + ["<port>"] + anvil.args[3:],
                "hardfork": ANVIL_HARDFORK,
                "chain_id": cfg.chain_id,
                "coinbase": addrs["block_producer"],
                "python_dependencies": _python_deps(),
                "rpc_calls": anvil.rpc.calls,
            },
            "contracts": {
                "EntryPoint": env.entrypoint,
                "SimpleAccountFactory": env.factory,
                "SimpleAccount_implementation": env.account_implementation,
                "W1Token": env.token,
                "ObservablePaymaster": env.paymaster,
            },
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
            "bundler": ({"bundler_id": BUNDLER_ID, "simulation_method": SIMULATION_METHOD}
                        if bundler_obj else None),
            "blocks": {"setup_end": setup_end, "workflow_end": workflow_end},
            "transactions": [st.as_dict() for st in chain.sent],
            "userops": userops,
            "state": state,
        }

    private = {
        "note": "SECRET. Role assignment for one W1 run; answers who is who. "
                "Never an attacker input.",
        "baseline_id": baseline_id,
        "roles": {**addrs, "recipient_account": recipient_account},
        "recipient_account_kind": "eoa" if baseline_id == "B0" else "simple_account_v0.9.0",
        "tx_labels": labels,
        "eth_allowance": str(eth_allowance),
        "variation": variation.__dict__,
        "failure": None if failure is None else {"step": failure.step, **failure.detail},
    }
    return RunResult(baseline_id=baseline_id, seed=seed, chain_dump=chain_dump,
                     bundler_log=bundler_obj.log if bundler_obj else [],
                     private=private, failure=failure)


def write_raw(result: RunResult, raw_dir: Path, private_dir: Path) -> Dict[str, Path]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    out = {"chain_dump": raw_dir / "chain_dump.json",
           "private": private_dir / "w1_private_run.json"}
    for key, path in out.items():
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
