"""Execute one D1 multi-actor pilot run against a throwaway anvil.

One run = one chain = one baseline x one scenario x one pool size N x one
replicate. N independent actors (``actors.py``) each perform the W1-cold
workflow of that baseline, interleaved by a seeded schedule (``schedule.py``).
Everything else is the existing W1 machinery, unchanged: the identical
``b3_compat_local`` setup (W1 contracts + frozen B3 contracts + Paymaster
deposits), the matched W1 parameters, the in-repo instrumented bundler, the
calibrated preVerificationGas method, real signed transactions only, and for
B3 the frozen contracts with real Semaphore v4 / Groth16 proofs.

Per actor k (``acct_k`` = the fresh EOA in B0, the counterfactual SimpleAccount
owned by the actor's recipient key elsewhere)::

    setup    faucet -> sender_k ETH; treasury -> sender_k W1T      (all baselines)
    deliver  sender_k: W1Token.transfer(acct_k, amount)             (all baselines)
    fund     B0: sender_k -> acct_k ETH allowance
             B1: sender_k -> acct_k ETH = required prefund of op_k
             B2-Allowlist: sponsor operator: setSponsored(acct_k, true)
             B3: sender_k: announceAndFund{vMin + F}(1, acct_k, ephPub_k, "")
    issue    B3: Bootstrap op (initCode + execute(CreditPool, deposit(C_k)))
    prepare  off chain: build + sign op_k (B3: prove against the FINAL root)
    act      B0: acct_k: W1Token.transfer(destination, amount)
             B1/B2/B3: bundler handleOps([op_k]) -- the W1 application call

B3 single-final-root procedure (``docs/d1-pilot-results.md``): all N
Bootstraps are included first (their insertion order is recorded privately);
the harness then rebuilds ``Group(commitments in on-chain Deposited order)``
off chain, requires its root to equal ``CreditPool.currentRoot()``,
``CreditPaymaster.merkleRoot()`` and every intermediate root emitted by the
Deposited logs, and only then generates every Spend proof against that one
root, in the schedule's independent preparation order. Spends do not change the
root, so no proof can go stale; any unexpected root failure aborts the run and
is recorded. Nothing about B3 is modified.

Chain time is set for every block from the schedule; the bundler's A2
timestamps use the same simulated clock. Operation labels in the raw dump are
opaque ordinals; the ordinal -> (slot, stage) map is private.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from eth_utils import to_checksum_address

from ...recorder.digest import commit_to_value
from ...recorder.provenance import repo_root
from ..w1 import abi, b3, calibration, profiles
from ..w1.artifacts import dependency_tree_digest, load_all
from ..w1.bundler import BUNDLER_ID, SIMULATION_METHOD, InstrumentedBundler
from ..w1.chain import Chain, SentTx
from ..w1.config import (ENTRYPOINT_SOURCE_COMMIT, ENTRYPOINT_SOURCE_REPO, ENTRYPOINT_VERSION,
                         PAYMASTER_OF, B3_BASELINE_ID, load_config)
from ..w1.keys import faucet, role_keys
from ..w1.rpc import ANVIL_HARDFORK, AnvilProcess
from ..w1.runner import (ZERO_ADDRESS, Environment, _application_call, _b3_provenance,
                         _python_deps, _token_transfer_data, setup_environment)
from ..w1.userop import (UserOp, counterfactual_address, ep_deposit, ep_nonce, init_code,
                         get_userop_hash, sign_paymaster, sign_userop)
from .actors import Actor, make_actors
from .config import PilotConfig, load_pilot_config
from .schedule import Schedule, make_schedule

BASELINES = ("B0", "B1", "B2-Signature", "B2-Allowlist", B3_BASELINE_ID)
DUMP_VERSION = "d1-1"
BUNDLER_NET_TOLERANCE_GAS = 100


class PilotRunFailure(RuntimeError):
    """A pilot run could not complete as specified (recorded, never hidden)."""


@dataclass
class RunSpec:
    baseline_id: str
    scenario_id: str
    pool_size: int
    replicate: int
    seed: int


@dataclass
class PilotRunResult:
    spec: RunSpec
    chain_dump: Dict[str, Any]
    bundler_log: List[Dict[str, Any]]
    private: Dict[str, Any]
    checks: List[Dict[str, Any]]


class SimClock:
    """Bundler clock driven by schedule time (microsecond ticks within a block)."""

    def __init__(self, t: int) -> None:
        self.base = t
        self.ticks = 0

    def set(self, t: int) -> None:
        self.base, self.ticks = t, 0

    def __call__(self) -> str:
        self.ticks += 1
        dt = datetime.fromtimestamp(self.base, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{self.ticks:06d}Z"


def run_pilot(spec: RunSpec, root: Optional[Path] = None,
              pilot: Optional[PilotConfig] = None) -> PilotRunResult:
    root = Path(root) if root else repo_root()
    pilot = pilot or load_pilot_config(root)
    if spec.baseline_id not in BASELINES:
        raise ValueError(f"unsupported baseline {spec.baseline_id}")
    profile = profiles.get(pilot.profile_id)
    if not profile.includes_b3_infrastructure:
        raise ValueError("the D1 pilot runs every baseline on the b3_compat_local profile")
    cfg = load_config(root)
    arts = load_all(root)
    b3_arts = b3.load_b3_all(root)
    b3cfg = b3.load_b3_config(root)
    keys = role_keys(spec.seed)
    actors = make_actors(spec.seed, spec.pool_size)
    is_b3 = spec.baseline_id == B3_BASELINE_ID
    aa = spec.baseline_id != "B0"
    sched_params = pilot.raw["schedule"]
    genesis = int(sched_params["genesis_timestamp"])
    interval = int(sched_params["setup_block_interval"])

    prover_ctx = None
    if is_b3:
        from ..w1.prover import SemaphoreProver
        prover_ctx = SemaphoreProver(root)

    anvil_args = profile.anvil_args() + ["--timestamp", str(genesis)]
    checks: List[Dict[str, Any]] = []
    wallclock: Dict[str, Any] = {"prepare_ms": {}, "proofs": []}

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise PilotRunFailure(f"{name}: {detail}")

    with AnvilProcess(cfg.chain_id, cfg.base_fee, anvil_args) as anvil:
        prover = prover_ctx.__enter__() if prover_ctx else None
        try:
            rpc = anvil.rpc
            chain = Chain(rpc=rpc, chain_id=cfg.chain_id, base_fee=cfg.base_fee,
                          max_fee=cfg.max_fee, max_priority_fee=cfg.max_priority_fee)
            chain.set_coinbase(keys.address("block_producer"))
            rpc.call("anvil_setBlockTimestampInterval", [interval])
            fingerprint = calibration.environment_fingerprint(cfg, arts, anvil.version,
                                                              profile, b3_arts)
            pvg_artifact = calibration.load_artifact(root, profile.profile_id)
            pvg_sha = calibration.artifact_sha256(pvg_artifact)
            for shape in calibration.SHAPES:  # fail before any transaction
                calibration.overhead_for(pvg_artifact, shape, fingerprint)

            # ---- setup: unchanged W1 + B3 environment, then per-actor funding ----
            env = setup_environment(chain, cfg, keys, arts, profile, b3_arts, b3cfg)
            workflow_start = int(chain.rpc.call("eth_getBlockByNumber",
                                                ["latest", False])["timestamp"], 16)
            schedule = make_schedule(spec.seed, spec.pool_size, spec.scenario_id,
                                     spec.baseline_id, sched_params,
                                     start_time=workflow_start + int(sched_params["phase_gap"]))
            f = faucet()
            treasury = keys.account("asset_sender")  # W1 token holder; not an actor
            sender_eth = int(pilot.raw["actor_setup"]["asset_sender_eth"])
            for slot in schedule.orders["setup"]:
                a = actors[slot]
                chain.send(f, label=f"setup_fund_sender/{slot}", phase="setup",
                           to=a.asset_sender.address, value=sender_eth,
                           gas=cfg.gas_limit("native_transfer"))
                chain.send(treasury, label=f"setup_token_sender/{slot}", phase="setup",
                           to=env.token,
                           data=_token_transfer_data(a.asset_sender.address, cfg.transfer_amount),
                           gas=cfg.gas_limit("erc20_transfer"))
            rpc.call("anvil_removeBlockTimestampInterval")
            setup_end = chain.block_number()

            accounts = {a.slot: (a.recipient.address if not aa else counterfactual_address(
                chain, env.factory, a.recipient.address, cfg.account_salt)) for a in actors}
            check("distinct_recipient_accounts", len(set(accounts.values())) == len(actors))

            clock = SimClock(workflow_start)
            bundler = (InstrumentedBundler(
                chain=chain, entrypoint=env.entrypoint, account=keys.account("bundler"),
                beneficiary=keys.address("beneficiary"),
                bundle_gas_limit=cfg.gas_limit("bundle"), clock=clock) if aa else None)

            op_labels: Dict[str, Dict[str, Any]] = {}
            tx_labels: Dict[str, str] = {}
            userops: List[Dict[str, Any]] = []
            pvg_records: Dict[str, Any] = {}
            prepared: Dict[int, UserOp] = {}
            prepared_hash: Dict[int, str] = {}
            commitments: Dict[int, int] = {}
            insertion: List[int] = []
            final_group: Dict[str, Any] = {}
            op_counter = [0]

            def at(t: int) -> None:
                rpc.call("anvil_setNextBlockTimestamp", [t])
                clock.set(t)

            def ok_tx(st: SentTx, label: str) -> SentTx:
                if int(st.receipt["status"], 16) != 1:
                    raise PilotRunFailure(f"{label} reverted")
                tx_labels[st.hash] = label
                return st

            def new_label(slot: int, stage: str) -> str:
                label = f"op-{op_counter[0]:04d}"
                op_counter[0] += 1
                op_labels[label] = {"slot": slot, "stage": stage}
                return label

            def estimate(label: str, builder) -> UserOp:
                shape = calibration.op_shape(builder.call_data)
                est = bundler.estimate_pre_verification_gas(
                    label=label, overhead=calibration.overhead_for(pvg_artifact, shape,
                                                                   fingerprint),
                    op_shape=shape, artifact_sha256=pvg_sha, build_signed_op=builder)
                pvg_records[label] = est.as_dict()
                return builder(est.pre_verification_gas)

            def submit(op: UserOp, label: str) -> None:
                out = bundler.send_user_operation(op, label=label)
                userops.append({"label": label, "userop_hash": out.userop_hash,
                                "packed": op.as_json()})
                if not out.accepted:
                    sim = out.log[-1]
                    raise PilotRunFailure(
                        f"{label} ({op_labels[label]}) rejected: {sim.get('rejection_category')} "
                        f"{(sim.get('raw_error') or {}).get('decoded')}")
                tx_labels[out.bundle.hash] = label
                ev = [abi.decode_log(l) for l in out.bundle.receipt["logs"]]
                uoe = next(d for d in ev if d and d["event"] == "UserOperationEvent")
                if not uoe["success"]:
                    raise PilotRunFailure(f"{label} ({op_labels[label]}) included but its "
                                          "execution reverted")

            # ---- builders -------------------------------------------------------
            def app_builder(a: Actor, label: str):
                account = accounts[a.slot]
                owner = a.recipient
                call_data = _application_call(cfg, env, keys)
                nonce = ep_nonce(chain, env.entrypoint, account, cfg.nonce_key)
                pm = env.paymaster_for(spec.baseline_id)

                if is_b3:
                    proofs: Dict[str, Any] = {}
                    members = [commitments[s] for s in insertion]
                    depth = final_group["depth"]

                    def build_b3(pvg: int) -> UserOp:
                        op = UserOp(
                            sender=account, nonce=nonce, init_code=b"", call_data=call_data,
                            verification_gas_limit=cfg.verification_gas_limit,
                            call_gas_limit=cfg.call_gas_limit, pre_verification_gas=pvg,
                            max_priority_fee_per_gas=cfg.max_priority_fee,
                            max_fee_per_gas=cfg.max_fee, paymaster=env.b3.credit_paymaster,
                            paymaster_verification_gas_limit=b3cfg.userop(
                                "spend_paymaster_verification_gas_limit"),
                            paymaster_post_op_gas_limit=b3cfg.userop("paymaster_post_op_gas_limit"))
                        op.paymaster_signature = b3.PLACEHOLDER_PROOF
                        h = get_userop_hash(chain, env.entrypoint, op)
                        if h not in proofs:
                            res = prover.prove(identity_secret=a.semaphore_secret,
                                               members=members, message=int(h, 16),
                                               scope=env.b3.credit_scope,
                                               merkle_tree_depth=depth, label=label)
                            if res.group_root != final_group["root"]:
                                raise PilotRunFailure("proof group root != verified final root")
                            proofs[h] = res
                        op.paymaster_signature = b3.encode_proof(proofs[h].proof)
                        if get_userop_hash(chain, env.entrypoint, op) != h:  # pragma: no cover
                            raise RuntimeError("userOpHash changed when inserting the proof")
                        sign_userop(chain, env.entrypoint, op, owner)
                        return op

                    build_b3.call_data = call_data  # type: ignore[attr-defined]
                    return build_b3

                def build(pvg: int) -> UserOp:
                    op = UserOp(
                        sender=account, nonce=nonce,
                        init_code=init_code(env.factory, owner.address, cfg.account_salt),
                        call_data=call_data, verification_gas_limit=cfg.verification_gas_limit,
                        call_gas_limit=cfg.call_gas_limit, pre_verification_gas=pvg,
                        max_priority_fee_per_gas=cfg.max_priority_fee, max_fee_per_gas=cfg.max_fee)
                    if pm is not None:
                        op.paymaster = pm
                        op.paymaster_verification_gas_limit = cfg.paymaster_verification_gas_limit
                        op.paymaster_post_op_gas_limit = cfg.paymaster_post_op_gas_limit
                    if spec.baseline_id == "B2-Signature":
                        vu, va = cfg.paymaster_signature_validity
                        from eth_abi import encode
                        op.paymaster_data = encode(["uint48", "uint48"], [vu, va])
                        sign_paymaster(chain, env.entrypoint, op, keys.account("sponsor_signer"))
                    sign_userop(chain, env.entrypoint, op, owner)
                    return op

                build.call_data = call_data  # type: ignore[attr-defined]
                return build

            def bootstrap_builder(a: Actor):
                account = accounts[a.slot]
                owner = a.recipient
                call_data = b3.bootstrap_call_data(env.b3.credit_pool, commitments[a.slot])

                def build(pvg: int) -> UserOp:
                    op = UserOp(
                        sender=account, nonce=0,
                        init_code=init_code(env.factory, owner.address, cfg.account_salt),
                        call_data=call_data, verification_gas_limit=cfg.verification_gas_limit,
                        call_gas_limit=pilot.bootstrap_call_gas_limit, pre_verification_gas=pvg,
                        max_priority_fee_per_gas=cfg.max_priority_fee, max_fee_per_gas=cfg.max_fee,
                        paymaster=env.b3.bootstrap_paymaster,
                        paymaster_verification_gas_limit=b3cfg.userop(
                            "bootstrap_paymaster_verification_gas_limit"),
                        paymaster_post_op_gas_limit=b3cfg.userop("paymaster_post_op_gas_limit"))
                    sign_userop(chain, env.entrypoint, op, owner)
                    return op

                build.call_data = call_data  # type: ignore[attr-defined]
                return build

            if is_b3:
                for a in actors:
                    commitments[a.slot] = prover.commitment(a.semaphore_secret)
                check("distinct_commitments", len(set(commitments.values())) == len(actors))

            def verify_final_root() -> None:
                """Rebuild the group from ON-CHAIN Deposited order and compare roots."""
                deposited = []
                for st in chain.sent:
                    for log in st.receipt["logs"]:
                        d = b3.decode_b3_log(log)
                        if d and d["event"] == "CreditDeposited":
                            deposited.append((d["commitment"], d["root"]))
                onchain_order = [c for c, _ in deposited]
                check("b3_onchain_insertion_order_matches_private_record",
                      onchain_order == [commitments[s] for s in insertion])
                for i, (_c, emitted_root) in enumerate(deposited):
                    g = prover.group_root(onchain_order[:i + 1])
                    check(f"b3_intermediate_root_{i + 1}", g["root"] == emitted_root,
                          {"offchain": str(g["root"]), "emitted": str(emitted_root)})
                g = prover.group_root(onchain_order)
                pool_root = b3.view_uint(chain, env.b3.credit_pool, b3.SIG_POOL_CURRENT_ROOT)
                pm_root = b3.view_uint(chain, env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT)
                size = b3.view_uint(chain, env.b3.credit_pool, b3.SIG_POOL_TREE_SIZE)
                check("b3_tree_size_equals_pool_size", size == spec.pool_size, size)
                check("b3_offchain_root_equals_credit_pool_root", g["root"] == pool_root)
                check("b3_offchain_root_equals_credit_paymaster_root", g["root"] == pm_root)
                from ..w1.prover import group_depth
                check("b3_group_depth", g["depth"] == max(0, (spec.pool_size - 1).bit_length()))
                final_group.update({"root": g["root"], "depth": group_depth(spec.pool_size),
                                    "leanimt_depth": g["depth"], "size": g["size"]})

            # ---- workflow in schedule order -------------------------------------
            sender_of = {a.slot: a.asset_sender for a in actors}
            eth_allowance: Dict[int, int] = {}
            root_verified = False
            for ev in schedule.events:
                a = actors[ev.slot]
                acct = accounts[ev.slot]
                if ev.phase == "deliver":
                    at(ev.time)
                    ok_tx(chain.send(sender_of[ev.slot], label=f"deliver/{ev.slot}",
                                     phase="workflow", to=env.token,
                                     data=_token_transfer_data(acct, cfg.transfer_amount),
                                     gas=cfg.gas_limit("erc20_transfer")), f"deliver/{ev.slot}")
                elif ev.phase == "fund":
                    at(ev.time)
                    if spec.baseline_id == "B0":
                        v = cfg.b0_eth_allowance
                        eth_allowance[ev.slot] = v
                        ok_tx(chain.send(sender_of[ev.slot], label=f"fund/{ev.slot}",
                                         phase="workflow", to=acct, value=v,
                                         gas=cfg.gas_limit("native_transfer")), f"fund/{ev.slot}")
                    elif spec.baseline_id == "B1":
                        v = prepared[ev.slot].required_prefund
                        eth_allowance[ev.slot] = v
                        ok_tx(chain.send(sender_of[ev.slot], label=f"fund/{ev.slot}",
                                         phase="workflow", to=acct, value=v,
                                         gas=cfg.gas_limit("native_transfer")), f"fund/{ev.slot}")
                    elif spec.baseline_id == "B2-Allowlist":
                        ok_tx(chain.send(keys.account("sponsor_operator"), label=f"fund/{ev.slot}",
                                         phase="workflow", to=env.allowlist_paymaster,
                                         data=abi.call(abi.SIG_PM_SET_SPONSORED,
                                                       ["address", "bool"], [acct, True]),
                                         gas=cfg.gas_limit("setup_call")), f"fund/{ev.slot}")
                    elif is_b3:
                        ok_tx(chain.send(
                            sender_of[ev.slot], label=f"fund/{ev.slot}", phase="workflow",
                            to=env.b3.registry, value=b3cfg.v_min + b3cfg.non_refundable_fee,
                            data=b3.announce_and_fund_calldata(
                                b3cfg.scheme_id, acct, b3.ephemeral_public_key(a.ephemeral),
                                bytes.fromhex(b3cfg.raw["protocol"]["announcement_metadata_hex"][2:])),
                            gas=b3cfg.userop("announce_and_fund_gas_limit")), f"fund/{ev.slot}")
                elif ev.phase == "issue":
                    label = new_label(ev.slot, "bootstrap")
                    at(ev.time)
                    op = estimate(label, bootstrap_builder(a))
                    at(ev.time)
                    submit(op, label)
                    insertion.append(ev.slot)
                elif ev.phase == "prepare":
                    if is_b3 and not root_verified:
                        check("b3_all_issuances_before_first_spend_preparation",
                              len(insertion) == spec.pool_size, len(insertion))
                        verify_final_root()
                        root_verified = True
                    label = new_label(ev.slot, "application")
                    t0 = time.perf_counter()
                    prepared[ev.slot] = estimate(label, app_builder(a, label))
                    prepared_hash[ev.slot] = label
                    wallclock["prepare_ms"][label] = (time.perf_counter() - t0) * 1000
                elif ev.phase == "act":
                    at(ev.time)
                    if spec.baseline_id == "B0":
                        ok_tx(chain.send(a.recipient, label=f"act/{ev.slot}", phase="workflow",
                                         to=env.token,
                                         data=_token_transfer_data(keys.address("destination"),
                                                                   cfg.transfer_amount),
                                         gas=cfg.gas_limit("b0_action")), f"act/{ev.slot}")
                    else:
                        if is_b3:
                            # The root must still be the one every proof was made against.
                            now_root = b3.view_uint(chain, env.b3.credit_paymaster,
                                                    b3.SIG_CPM_MERKLE_ROOT)
                            check(f"b3_root_unchanged_before_spend/{prepared_hash[ev.slot]}",
                                  now_root == final_group["root"])
                        submit(prepared[ev.slot], prepared_hash[ev.slot])
            workflow_end = chain.block_number()

            # ---- end-of-run checks (role-labelled, private) ----------------------
            dest = keys.address("destination")
            data = abi.call(abi.SIG_ERC20_BALANCE_OF, ["address"], [dest])
            check("destination_received_all", int(chain.eth_call(env.token, data), 16)
                  == spec.pool_size * cfg.transfer_amount)
            for slot, acct in accounts.items():
                d = abi.call(abi.SIG_ERC20_BALANCE_OF, ["address"], [acct])
                if int(chain.eth_call(env.token, d), 16) != 0:
                    raise PilotRunFailure(f"account of slot {slot} kept tokens")
            if is_b3:
                nullifiers = []
                for u in userops:
                    if op_labels[u["label"]]["stage"] == "application":
                        pmd = bytes.fromhex(u["packed"]["paymasterAndData"][2:])
                        nullifiers.append(b3.decode_proof(pmd[52:52 + b3.PROOF_BYTE_LENGTH])["nullifier"])
                check("b3_nullifiers_distinct", len(set(nullifiers)) == spec.pool_size)
                check("b3_nullifiers_spent", all(b3.view_uint(
                    chain, env.b3.credit_paymaster, b3.SIG_CPM_NULLIFIER_SPENT, ("uint256",), (n,))
                    for n in nullifiers))
                check("b3_root_unchanged_after_all_spends", b3.view_uint(
                    chain, env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT) == final_group["root"])
            nets = []
            for st in chain.sent:
                if tx_labels.get(st.hash, "").startswith("op-"):
                    ev_ = [abi.decode_log(l) for l in st.receipt["logs"]]
                    uoe = next(d for d in ev_ if d and d["event"] == "UserOperationEvent")
                    nets.append(uoe["actual_gas_cost"] - st.fee)
            if nets:
                check("bundler_net_within_tolerance",
                      min(nets) >= -BUNDLER_NET_TOLERANCE_GAS * cfg.max_fee,
                      {"min_net_wei": min(nets), "max_net_wei": max(nets)})

            deposit_before_tx: Dict[str, Dict[str, str]] = {}
            for st in chain.sent:
                for log in st.receipt["logs"]:
                    d = abi.decode_log(log)
                    if d and d["event"] == "Deposited":
                        blk = int(st.receipt["blockNumber"], 16) - 1
                        deposit_before_tx.setdefault(st.hash, {})[d["account"]] = str(
                            ep_deposit(chain, env.entrypoint, d["account"], blk))

            contracts = env.contracts()
            chain_dump = {
                "dump_version": DUMP_VERSION,
                "baseline_id": spec.baseline_id,
                "workload_id": pilot.workload_id,
                "evaluation_profile": profile.as_dict(),
                "seed_commitment_sha256": commit_to_value(
                    f"d1-dump/{spec.baseline_id}/{spec.scenario_id}/{spec.pool_size}", spec.seed),
                "config": cfg.raw,
                "b3_config": b3cfg.raw,
                "pilot_config_sha256": hashlib.sha256(json.dumps(
                    pilot.raw, sort_keys=True).encode()).hexdigest(),
                "environment": {
                    "anvil_version": anvil.version,
                    "anvil_args": anvil.args[:2] + ["<port>"] + anvil.args[3:],
                    "hardfork": ANVIL_HARDFORK, "chain_id": cfg.chain_id,
                    "coinbase": keys.address("block_producer"),
                    "python_dependencies": _python_deps(),
                    "evm_snapshots_taken": chain.snapshots_taken,
                },
                "contracts": contracts,
                "paymaster_used": PAYMASTER_OF.get(spec.baseline_id),
                "signature_paymaster_verifying_signer": keys.address("sponsor_signer"),
                "artifacts": {
                    **{n: {"deployed_bytecode_sha256": x.deployed_bytecode_sha256,
                           "bytecode_sha256": hashlib.sha256(x.bytecode).hexdigest()}
                       for n, x in arts.items()},
                    **{n: {"deployed_bytecode_sha256": x.deployed_bytecode_sha256,
                           "runtime_size_bytes": x.runtime_size,
                           "link_placeholders_zeroed": bool(x.link_references)}
                       for n, x in b3_arts.items()}},
                "entrypoint_provenance": {
                    "version": ENTRYPOINT_VERSION, "source_repo": ENTRYPOINT_SOURCE_REPO,
                    "source_commit": ENTRYPOINT_SOURCE_COMMIT,
                    "vendored_tree": "baselines/b3_privgas_v1/lib/account-abstraction/contracts",
                    "vendored_tree_digest": dependency_tree_digest(
                        root / "baselines/b3_privgas_v1/lib/account-abstraction/contracts"),
                },
                "b3_provenance": _b3_provenance(root),
                "bundler": ({"bundler_id": BUNDLER_ID, "simulation_method": SIMULATION_METHOD,
                             "pvg_mode": "calibrated_overhead",
                             "pre_verification_gas_method": "calibrated_overhead_v1",
                             "calibration_artifact_sha256": pvg_sha,
                             "environment_fingerprint": fingerprint,
                             "clock": "simulated (schedule chain time)"} if aa else None),
                # Per-operation pricing records are keyed by private labels: kept private.
                "pvg_records": {},
                "blocks": {"setup_end": setup_end, "workflow_end": workflow_end},
                "transactions": [st.as_dict() for st in chain.sent],
                "userops": userops,
                "state": {"entrypoint_deposit_before_tx": deposit_before_tx},
            }
        finally:
            if prover_ctx is not None:
                wallclock["proofs"] = list(prover.log)
                prover_ctx.__exit__(None, None, None)

    private = {
        "note": "SECRET. Actor/slot assignment, schedule, operation labels and checks of one "
                "D1 pilot run. Never an attacker input.",
        "spec": {"baseline_id": spec.baseline_id, "scenario_id": spec.scenario_id,
                 "pool_size": spec.pool_size, "replicate": spec.replicate},
        "roles": {**keys.addresses(), "destination": keys.address("destination"),
                  "token_treasury": treasury.address},
        "actors": [{"slot": a.slot, "actor_handle": a.actor_handle,
                    "wallet_address": a.wallet.address, "wallet_handle": a.wallet_handle,
                    "asset_sender_address": a.asset_sender.address,
                    "asset_sender_handle": a.asset_sender_handle,
                    "recipient_key_address": a.recipient.address,
                    "recipient_account": accounts[a.slot],
                    "stealth_handle": a.stealth_handle(spec.baseline_id),
                    "credit_handle": a.credit_handle, "issuance_handle": a.issuance_handle,
                    "commitment": str(commitments[a.slot]) if is_b3 else None,
                    "eth_allowance": str(eth_allowance.get(a.slot, 0))}
                   for a in actors],
        "schedule": schedule.as_private_dict(),
        "op_labels": op_labels,
        "tx_labels": tx_labels,
        "pvg_records": pvg_records,
        "b3": ({"insertion_order": insertion,
                "final_root": str(final_group.get("root")),
                "proof_merkle_tree_depth": final_group.get("depth"),
                "leanimt_depth": final_group.get("leanimt_depth"),
                "bootstrap_call_gas_limit": pilot.bootstrap_call_gas_limit,
                "circuit": f"semaphore-{final_group.get('depth')}"} if is_b3 else None),
        "wallclock": wallclock,
        "checks": checks,
    }
    return PilotRunResult(spec=spec, chain_dump=chain_dump,
                          bundler_log=bundler.log if bundler else [], private=private,
                          checks=checks)
