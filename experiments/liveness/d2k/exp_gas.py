"""Question B experiments: why does CreditPool.deposit gas grow, and what follows from it?

``decomp``    Sections 16-19. The frozen `CreditPool.deposit` (G0) measured insertion by
              insertion against G1 (LeanIMT only), G2 (root mirror only), G3 (B3
              surrounding logic without tree work), G4 (external-call floor) and G5 (one
              PoseidonT3 delegatecall), with Poseidon call counts and storage diffs.
``envelope``  Sections 20 and 23. Whether a Bootstrap can succeed under the FROZEN
              callGasLimit, the frozen sponsorship budget and the configured gas-price
              cap at each tree size; the minimal sufficient limit; and the maximum feasible
              gas price, measured against the analytic envelope.
``grant``     Section 21. Controlled failed Bootstraps on the FROZEN B3 deployment with
              full before/after state, then the identical logical Bootstrap with enough gas.
``detect``    Section 22. What the experimental bundler can and cannot see before
              submitting an operation whose callGasLimit is too low.

Every measured frame is a CALL sub-frame, so G0..G5 are on the same footing: G0 is the
`deposit` frame inside a real sponsored Bootstrap UserOperation (exactly as the frozen D2
pilot measured it) and G1..G5 are frames inside a `BenchRunner.run` call. No intrinsic-gas
or calldata accounting enters any comparison.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ...workloads.w1 import abi, b3
from ...workloads.w1.keys import faucet
from ...workloads.w1.userop import ep_deposit, ep_nonce
from ..d2 import exp_b as d2_exp_b
from ..d2.harness import D2Chain, HarnessInvariantViolation
from . import mitigation
from .harness import D2KChain

Log = Callable[[str], None]
GWEI = 10 ** 9

SIG_RUN = "run(address,bytes)"


# --- benchmark deployment ---------------------------------------------------------------


class Benches:
    """Every G-series contract, deployed once on the decomposition chain."""

    def __init__(self, ctx: D2KChain, ks: Sequence[int], runners: int) -> None:
        self.ctx = ctx
        dep = mitigation._Deployer(ctx.chain, ctx.keys.account("deployer"),
                                   ctx.cfg.gas_limit("deployment"))
        a, b3a = ctx.d2k_arts, ctx.b3arts
        poseidon = ctx.frozen_b3.poseidon_t3
        self.runners = [dep.deploy(f"BenchRunner_{i}", a["BenchRunner"], [], [])
                        for i in range(runners)]
        self.leanimt = dep.deploy("LeanIMTBench", a["LeanIMTBench"], [], [],
                                  libraries={"PoseidonT3": poseidon})
        self.noop = dep.deploy("NoopBench", a["NoopBench"], [], [])
        self.poseidon_bench = dep.deploy("PoseidonCallBench", a["PoseidonCallBench"], [], [],
                                         libraries={"PoseidonT3": poseidon})
        # G2 targets: one pusher per acceptance component (the mirror only accepts one caller)
        self.pushers: Dict[str, str] = {}
        self.mirrors: Dict[str, str] = {}
        for variant in ["frozen", "minimal"] + [f"K{k}" for k in ks]:
            mirror_addr, pusher_addr = dep.next_addresses(2)
            if variant == "frozen":
                m = dep.deploy("G2_CreditPaymaster", b3a["CreditPaymaster"],
                               ["address", "address", "address"],
                               [ctx.env.entrypoint, pusher_addr, ctx.frozen_b3.semaphore_verifier])
            elif variant == "minimal":
                m = dep.deploy("G2_MinimalRootMirror", a["MinimalRootMirror"], ["address"],
                               [pusher_addr])
            else:
                m = dep.deploy(f"G2_HistoryCreditPaymaster_{variant}", a["HistoryCreditPaymaster"],
                               ["address", "address", "address", "uint256"],
                               [ctx.env.entrypoint, pusher_addr,
                                ctx.frozen_b3.semaphore_verifier, int(variant[1:])])
            p = dep.deploy(f"G2_RootMirrorPusher_{variant}", a["RootMirrorPusher"], ["address"],
                           [mirror_addr])
            if (m, p) != (mirror_addr, pusher_addr):
                raise HarnessInvariantViolation("G2 benchmark address drift")
            self.mirrors[variant], self.pushers[variant] = m, p
        # G3: two PoolSurroundBench instances (a = surrounding only, b = + leaf bookkeeping),
        # each with its own mirror, both accepting eligibility from the deployer EOA.
        self.surround: Dict[str, str] = {}
        for mode in ("a", "b"):
            mirror_addr, bench_addr = dep.next_addresses(2)
            m = dep.deploy(f"G3_CreditPaymaster_{mode}", b3a["CreditPaymaster"],
                           ["address", "address", "address"],
                           [ctx.env.entrypoint, bench_addr, ctx.frozen_b3.semaphore_verifier])
            s = dep.deploy(f"G3_PoolSurroundBench_{mode}", a["PoolSurroundBench"],
                           ["address", "address"],
                           [mirror_addr, ctx.keys.address("deployer")])
            if (m, s) != (mirror_addr, bench_addr):
                raise HarnessInvariantViolation("G3 benchmark address drift")
            self.surround[mode] = s
        self.costs = dep.costs
        # G3 eligibility: each BenchRunner may deposit once per surround instance.
        for r in self.runners:
            for s in self.surround.values():
                ctx.chain.send(ctx.keys.account("deployer"), label="d2k_bench_g3_eligible",
                               phase="setup", to=s,
                               data=abi.call(mitigation.SIG_MIRROR_ELIGIBLE, ["address"], [r]),
                               gas=ctx.cfg.gas_limit("setup_call"))

    def call(self, runner_index: int, target: str, data: bytes, label: str) -> Tuple[str, int]:
        """``BenchRunner.run(target, data)``; returns (tx hash, transaction gas used).

        Sent by the anvil faucet: the benchmarks measure a contract's frame gas, not any
        W1/B3 actor's cost, so no research role pays for them.
        """
        st = self.ctx.chain.send(faucet(), label=label,
                                 phase="workflow", to=self.runners[runner_index],
                                 data=abi.call(SIG_RUN, ["address", "bytes"], [target, data]),
                                 gas=self.ctx.cfg.gas_limit("deployment"))
        if int(st.receipt["status"], 16) != 1:
            raise HarnessInvariantViolation(f"benchmark call {label} reverted")
        return st.hash, int(st.receipt["gasUsed"], 16)


def _frame_gas(ctx: D2KChain, tx_hash: str, to: str, selector_hex: Optional[str] = None
               ) -> Dict[str, Any]:
    """Gas of the first frame that calls ``to`` (optionally with ``selector_hex``), plus the
    PoseidonT3 delegatecall count inside it and the callee's storage diff."""
    target = to.lower()
    poseidon = ctx.frozen_b3.poseidon_t3.lower()
    out: Dict[str, Any] = {"frame_gas_used": None, "poseidon_calls": 0,
                           "slots_written": None, "slots_new_nonzero": None,
                           "slots_cleared": None}
    try:
        tr = ctx.chain.rpc.call("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    except Exception:
        return out
    found = {"hit": False}

    def walk(fr: Dict[str, Any], inside: bool) -> None:
        t = (fr.get("to") or "").lower()
        inp = fr.get("input") or ""
        hit = (t == target and (selector_hex is None or inp.startswith(selector_hex)))
        if hit and not found["hit"]:
            found["hit"] = True
            out["frame_gas_used"] = int(fr["gasUsed"], 16)
            inside = True
        if inside and t == poseidon:
            out["poseidon_calls"] += 1
        for c in fr.get("calls") or []:
            walk(c, inside)

    if isinstance(tr, dict):
        walk(tr, False)
    try:
        diff = ctx.chain.rpc.call("debug_traceTransaction", [
            tx_hash, {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}}])
        pre = (diff.get("pre", {}).get(target) or {}).get("storage", {}) or {}
        post = (diff.get("post", {}).get(target) or {}).get("storage", {}) or {}
        out["slots_written"] = len(post)
        out["slots_new_nonzero"] = sum(
            1 for k, v in post.items() if int(v, 16) != 0 and int(pre.get(k, "0x0"), 16) == 0)
        out["slots_cleared"] = sum(1 for k, v in post.items() if int(v, 16) == 0)
    except Exception:
        pass
    return out


# --- Sections 16-19: the decomposition ---------------------------------------------------


def run_decomp(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    d = cfg["d2b_decomposition"]
    ks = [int(k) for k in cfg["d2k"]["k_values"]]
    max_size = int(d["max_tree_size"])
    record = set(int(x) - 1 for x in d["record_sizes"])       # insertion index -> size after
    check = set(int(x) for x in d["bootstrap_check_sizes"])
    g2_dense = 40
    rows: List[Dict[str, Any]] = []
    floor: Dict[str, Any] = {}
    deploy_rows: List[Dict[str, Any]] = []
    frozen_limit_rows: List[Dict[str, Any]] = []
    checks: Dict[str, Any] = {}
    for seed in d["seeds"]:
        with D2KChain(seed, cfg, shape="dedicated", history_k=None,
                      registry_eoa_role="deployer") as ctx:
            benches = Benches(ctx, ks, runners=int(d.get("g3_samples", 8)))
            deploy_rows += [{"seed": seed, **asdict(c)} for c in benches.costs]
            floor = _floor_measurements(ctx, benches, int(d["poseidon_samples"]))
            frozen_limit = ctx.b3cfg.userop("bootstrap_call_gas_limit")
            high = int(d["frozen_envelope"]["high_call_gas_limit"])
            started = time.time()
            for s in range(max_size):
                p = ctx.participant("member", s)
                ctx.grant_eligibility(p)
                if ctx.tree_size() != s:
                    raise HarnessInvariantViolation(f"tree size {ctx.tree_size()} != {s}")
                row: Dict[str, Any] = {
                    "seed": seed, "tree_size_before": s, "tree_size_after": s + 1,
                    "leanimt_depth_after": s.bit_length(),
                    "insertion_index_bits": bin(s).count("1")}
                # --- frozen-limit feasibility (Section 20), inside a reverted snapshot
                if s in check or s in record:
                    snap = ctx.snapshot()
                    try:
                        fr = d2_exp_b._attempt_bootstrap(ctx, p, frozen_limit)
                        frozen_limit_rows.append({"seed": seed, "tree_size_before": s, **fr})
                    finally:
                        ctx.revert(snap)
                        p.bootstrap_ops.pop((frozen_limit, ctx.cfg.max_fee), None)
                # --- G0: the real frozen Bootstrap UserOperation
                out = ctx.bootstrap_now(p, high)
                if not out["root_changed"]:
                    raise HarnessInvariantViolation(f"G0 insertion failed at size {s}: {out}")
                g0 = _frame_gas(ctx, out["tx_hash"], ctx.d2k.credit_pool,
                                "0x" + abi.selector(b3.SIG_POOL_DEPOSIT).hex())
                mirror = _frame_gas(ctx, out["tx_hash"], ctx.d2k.mirror_target,
                                    mitigation.SELECTOR_MIRROR_ROOT)
                row.update({"g0_deposit_frame_gas": g0["frame_gas_used"],
                            "g0_poseidon_calls": g0["poseidon_calls"],
                            "g0_pool_slots_written": g0["slots_written"],
                            "g0_pool_slots_new_nonzero": g0["slots_new_nonzero"],
                            "g0_mirror_frame_gas": mirror["frame_gas_used"],
                            "g0_bootstrap_actual_gas_used": out.get("actual_gas_used"),
                            "g0_bootstrap_sponsor_charge_wei": out.get("actual_gas_cost"),
                            "g0_bundle_gas_used": out.get("gas_used"),
                            "root_after": out["root_after"]})
                # --- G1: the same leaf into the LeanIMT-only benchmark
                h1, tx1 = benches.call(0, benches.leanimt,
                                       abi.call(mitigation.SIG_BENCH_INSERT, ["uint256"],
                                                [p.commitment]), "d2k_g1_insert")
                g1 = _frame_gas(ctx, h1, benches.leanimt,
                                "0x" + abi.selector(mitigation.SIG_BENCH_INSERT).hex())
                row.update({"g1_insert_frame_gas": g1["frame_gas_used"],
                            "g1_poseidon_calls": g1["poseidon_calls"],
                            "g1_slots_written": g1["slots_written"],
                            "g1_slots_new_nonzero": g1["slots_new_nonzero"],
                            "g1_tx_gas_used": tx1})
                # --- G2: publishing the same root, no Merkle work
                if s < g2_dense or s in record:
                    for variant in ["frozen", "minimal"] + [f"K{k}" for k in ks]:
                        h2, _ = benches.call(0, benches.pushers[variant],
                                             abi.call(mitigation.SIG_BENCH_PUSH, ["uint256"],
                                                      [int(out["root_after"])]), "d2k_g2_push")
                        g2 = _frame_gas(ctx, h2, benches.mirrors[variant],
                                        mitigation.SELECTOR_MIRROR_ROOT)
                        row[f"g2_{variant}_mirror_frame_gas"] = g2["frame_gas_used"]
                        row[f"g2_{variant}_slots_written"] = g2["slots_written"]
                        row[f"g2_{variant}_slots_new_nonzero"] = g2["slots_new_nonzero"]
                        row[f"g2_{variant}_slots_cleared"] = g2["slots_cleared"]
                # --- G3: B3 surrounding logic without tree work (constant; a few samples)
                if s < len(benches.runners):
                    for mode, sig in (("a", mitigation.SIG_SURROUND_DEPOSIT),
                                      ("b", mitigation.SIG_SURROUND_DEPOSIT_BOOK)):
                        h3, _ = benches.call(s, benches.surround[mode],
                                             abi.call(sig, ["uint256"], [p.commitment]),
                                             f"d2k_g3{mode}")
                        g3 = _frame_gas(ctx, h3, benches.surround[mode],
                                        "0x" + abi.selector(sig).hex())
                        row[f"g3{mode}_frame_gas"] = g3["frame_gas_used"]
                        row[f"g3{mode}_slots_written"] = g3["slots_written"]
                rows.append(row)
                if s in (0, 1, 3, 7, 15, 31, 63, 127, 255):
                    log(f"  decomp seed {seed} size {s}: G0 {row['g0_deposit_frame_gas']} "
                        f"G1 {row['g1_insert_frame_gas']} poseidon {row['g0_poseidon_calls']} "
                        f"({time.time() - started:.0f}s)")
            g = ctx.prover.group_root(ctx.members)
            checks[str(seed)] = {
                "final_tree_size": ctx.tree_size(),
                "offchain_group_root_matches": g["root"] == ctx.root() == ctx.pool_root(),
                "leanimt_bench_root_matches_pool": (
                    b3.view_uint(ctx.chain, benches.leanimt, "currentRoot()") == ctx.pool_root()),
                "leanimt_bench_size": b3.view_uint(ctx.chain, benches.leanimt, "treeSize()"),
                "frozen_call_gas_limit": ctx.b3cfg.userop("bootstrap_call_gas_limit"),
                "contracts": {**ctx.d2k.contracts(), "PoseidonT3": ctx.frozen_b3.poseidon_t3,
                              "LeanIMTBench": benches.leanimt}}
            log(f"  decomp seed {seed}: checks {checks[str(seed)]['offchain_group_root_matches']}, "
                f"{checks[str(seed)]['leanimt_bench_root_matches_pool']}")
    return {"rows": rows, "floor": floor, "deployment": deploy_rows,
            "frozen_limit": frozen_limit_rows, "checks": checks}


def _floor_measurements(ctx: D2KChain, benches: Benches, samples: int) -> Dict[str, Any]:
    """G4 (call floor) and G5 (one PoseidonT3 delegatecall), both as CALL sub-frames."""
    noop, hash_once, store_only = [], [], []
    for i in range(samples):
        h, _ = benches.call(0, benches.noop,
                            abi.call(mitigation.SIG_BENCH_NOOP, ["uint256"], [i + 1]),
                            "d2k_g4_noop")
        noop.append(_frame_gas(ctx, h, benches.noop)["frame_gas_used"])
        h, _ = benches.call(0, benches.poseidon_bench,
                            abi.call(mitigation.SIG_BENCH_HASH_ONCE, ["uint256", "uint256"],
                                     [i + 1, i + 2]), "d2k_g5_hash")
        fr = _frame_gas(ctx, h, benches.poseidon_bench,
                        "0x" + abi.selector(mitigation.SIG_BENCH_HASH_ONCE).hex())
        hash_once.append(fr["frame_gas_used"])
        h, _ = benches.call(0, benches.poseidon_bench,
                            abi.call(mitigation.SIG_BENCH_STORE_ONLY, ["uint256", "uint256"],
                                     [i + 1, i + 2]), "d2k_g5_store")
        store_only.append(_frame_gas(ctx, h, benches.poseidon_bench,
                                     "0x" + abi.selector(mitigation.SIG_BENCH_STORE_ONLY).hex()
                                     )["frame_gas_used"])
    warm_hash = [a - b for a, b in zip(hash_once[1:], store_only[1:])]
    return {"g4_noop_frame_gas": noop, "g5_hash_once_frame_gas": hash_once,
            "g5_store_only_frame_gas": store_only,
            "g5_poseidon_hash_gas_warm": warm_hash,
            "g5_poseidon_hash_gas_first": (hash_once[0] - store_only[0]) if hash_once else None}


# --- Sections 20 and 23: frozen-parameter feasibility and the fee envelope ----------------


def run_envelope(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    """Frozen callGasLimit feasibility, minimal sufficient limit, and the gas-price envelope.

    Uses the ordinary frozen deployment through the frozen D2 pilot's own measurement
    helpers (``exp_b._attempt_bootstrap``, ``exp_b._min_required_limit``), so the frozen
    numbers are produced by the same code that produced the pilot's.
    """
    e = cfg["d2b_decomposition"]["frozen_envelope"]
    sizes = sorted(int(s) for s in e["sizes"])
    fees = [int(g) * GWEI for g in e["fee_grid_gwei"]]
    search = e["required_limit_search"]
    high = int(e["high_call_gas_limit"])
    limit_rows, fee_rows = [], []
    for seed in cfg["d2b_decomposition"]["seeds"][:1]:
        with D2KChain(seed, cfg, shape="dedicated", history_k=None,
                      registry_eoa_role="deployer") as ctx:
            frozen = ctx.b3cfg.userop("bootstrap_call_gas_limit")
            for s in range(max(sizes) + 1):
                p = ctx.participant("member", s)
                ctx.grant_eligibility(p)
                if s in sizes:
                    snap = ctx.snapshot()
                    try:
                        at_frozen = d2_exp_b._attempt_bootstrap(ctx, p, frozen)
                    finally:
                        ctx.revert(snap)
                        p.bootstrap_ops.pop((frozen, ctx.cfg.max_fee), None)
                    req, at_req = d2_exp_b._min_required_limit(
                        ctx, p, int(search["low"]), int(search["high"]), int(search["tolerance"]))
                    limit_rows.append({
                        "seed": seed, "tree_size_before": s,
                        "frozen_call_gas_limit": frozen,
                        "frozen_included": at_frozen.get("included"),
                        "frozen_execution_success": at_frozen.get("execution_success"),
                        "frozen_root_changed": at_frozen.get("root_changed"),
                        "frozen_failure_class": at_frozen.get("failure_class"),
                        "frozen_grant_consumed": at_frozen.get("grant_consumed"),
                        "frozen_paymaster_charge_wei": at_frozen.get("paymaster_charge_wei"),
                        "min_required_call_gas_limit": req,
                        "frozen_limit_margin_gas": (frozen - req) if req else None,
                        "minreq_actual_gas_used": (at_req or {}).get("actual_gas_used"),
                        "minreq_required_prefund_wei": (at_req or {}).get("required_prefund_wei")})
                    for lname, limit in (("frozen", frozen), ("min_required", req),
                                         ("high", high)):
                        if limit is None:
                            continue
                        for fee in fees:
                            op = ctx.bootstrap_op(p, limit, fee)
                            sim = ctx.bundler.simulate([op])
                            fee_rows.append({
                                "seed": seed, "tree_size_before": s, "limit_kind": lname,
                                "call_gas_limit": limit, "max_fee_gwei": fee / GWEI,
                                "required_prefund_wei": op.required_prefund,
                                "gas_limits_sum": op.required_prefund // fee,
                                "sim_accepted": sim.accepted, "sim_reason": sim.reason,
                                "sim_inner_error": sim.inner_error})
                if s == max(sizes):
                    break
                if not ctx.bootstrap_now(p, high)["root_changed"]:
                    raise HarnessInvariantViolation(f"envelope: growth failed at size {s}")
            log(f"  envelope seed {seed}: {len(limit_rows)} sizes, {len(fee_rows)} fee points")
    return {"limits": limit_rows, "fees": fee_rows}


# --- Section 21: failure atomicity and grant consumption ---------------------------------


def _grant_state(ctx: D2Chain, p, label: str) -> Dict[str, Any]:
    ep = ctx.env.entrypoint
    blk = ctx.chain.block_number()
    return {
        "when": label,
        "bootstrap_paymaster_is_eligible": bool(b3.view_uint(
            ctx.chain, ctx.env.b3.bootstrap_paymaster, b3.SIG_BPM_IS_ELIGIBLE,
            ("address",), (p.account,))),
        "bootstrap_paymaster_is_used": bool(b3.view_uint(
            ctx.chain, ctx.env.b3.bootstrap_paymaster, b3.SIG_BPM_IS_USED,
            ("address",), (p.account,))),
        "credit_pool_is_eligible": bool(b3.view_uint(
            ctx.chain, ctx.env.b3.credit_pool, "isEligible(address)", ("address",), (p.account,))),
        "credit_pool_has_deposited": bool(b3.view_uint(
            ctx.chain, ctx.env.b3.credit_pool, b3.SIG_POOL_HAS_DEPOSITED,
            ("address",), (p.account,))),
        "bootstrap_paymaster_deposit_wei": ep_deposit(
            ctx.chain, ep, ctx.env.b3.bootstrap_paymaster, blk),
        "account_entrypoint_nonce": ep_nonce(ctx.chain, ep, p.account, ctx.cfg.nonce_key),
        "account_eth_wei": ctx.chain.balance(p.account, blk),
        "account_code_size": len(bytes.fromhex(ctx.chain.code(p.account, blk)[2:])),
        "credit_pool_tree_size": ctx.tree_size(),
        "credit_pool_root": str(ctx.pool_root()),
        "credit_paymaster_mirrored_root": str(ctx.root()),
    }


def run_grant(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    """Frozen B3, unmodified: a Bootstrap that VALIDATES but whose execution runs out of gas.

    The tree is first grown by one insertion so that the frozen callGasLimit is genuinely
    insufficient (it covers only tree size 0), using the pilot's experimental high limit for
    the growth step only; the measured attempts always use the starved limits.
    """
    g = cfg["d2b_decomposition"]["grant"]
    rows: List[Dict[str, Any]] = []
    for seed in seeds:
        with D2Chain(seed, cfg) as ctx:
            high = int(g["sufficient_call_gas_limit"])
            # one real insertion so the frozen limit no longer suffices
            seed_p = ctx.participant("member", 0)
            ctx.announce(seed_p)
            if not ctx.bootstrap_now(seed_p, high)["root_changed"]:
                raise HarnessInvariantViolation("grant: seeding insertion failed")
            for i, starved in enumerate(g["starved_call_gas_limits"]):
                p = ctx.participant("grant", i)
                ctx.announce(p)
                before = _grant_state(ctx, p, "before_failed_attempt")
                sponsor0 = ctx.pm_deposit("bootstrap")
                attempt = d2_exp_b._attempt_bootstrap(ctx, p, int(starved))
                after = _grant_state(ctx, p, "after_failed_attempt")
                sponsor_loss = sponsor0 - ctx.pm_deposit("bootstrap")
                # The IDENTICAL logical Bootstrap, now with enough gas. The failed attempt
                # consumed the account's EntryPoint nonce and deployed the account, so the
                # retry must be rebuilt at the live nonce with no initCode -- otherwise the
                # experiment would only be measuring `AA25 invalid account nonce`, which is
                # a property of the first attempt having been INCLUDED, not of the grant.
                p.bootstrap_ops[(high, ctx.cfg.max_fee)] = _live_bootstrap_op(ctx, p, high)
                retry = d2_exp_b._attempt_bootstrap(ctx, p, high)
                after_retry = _grant_state(ctx, p, "after_retry_with_sufficient_gas")
                # can the account still deposit by paying for itself? (the frozen comment
                # in BootstrapPaymaster claims it can)
                self_funded = _self_funded_deposit(ctx, p)
                rows.append({
                    "seed": seed, "attempt_index": i, "starved_call_gas_limit": int(starved),
                    "sufficient_call_gas_limit": high,
                    "failed_attempt": attempt, "retry_attempt": retry,
                    "sponsor_loss_on_failure_wei": sponsor_loss,
                    "state_before": before, "state_after_failure": after,
                    "state_after_retry": after_retry,
                    "self_funded_deposit": self_funded,
                    "grant_permanently_consumed": bool(
                        after["bootstrap_paymaster_is_used"]
                        and not after["credit_pool_has_deposited"]
                        and not retry.get("root_changed")),
                    "commitment_inserted_by_failed_attempt": after["credit_pool_tree_size"]
                    > before["credit_pool_tree_size"],
                    "nonce_advanced_by_failed_attempt": after["account_entrypoint_nonce"]
                    - before["account_entrypoint_nonce"],
                })
                log(f"  grant seed {seed} limit {starved}: "
                    f"failed={attempt.get('failure_class')} "
                    f"grant_used={after['bootstrap_paymaster_is_used']} "
                    f"retry_inserted={retry.get('root_changed')}")
    return {"rows": rows}


def _live_bootstrap_op(ctx: D2Chain, p, call_gas_limit: int, paymaster: bool = True):
    """``D2Chain.bootstrap_op`` at the account's LIVE EntryPoint nonce.

    The frozen helper always builds nonce 0 with initCode, which is right for a first
    attempt but wrong for anything after one has been included. ``paymaster=False`` builds
    the same operation with NO paymaster, so the account pays from its own ETH through the
    EntryPoint's ``missingAccountFunds`` path (SimpleAccount's `_payPrefund`).
    """
    from ...workloads.w1.userop import UserOp, init_code, sign_userop
    nonce = ep_nonce(ctx.chain, ctx.env.entrypoint, p.account, ctx.cfg.nonce_key)
    deployed = len(ctx.chain.code(p.account, ctx.chain.block_number())) > 2
    call_data = b3.bootstrap_call_data(ctx.env.b3.credit_pool, p.commitment)

    def build(pvg: int) -> UserOp:
        op = UserOp(
            sender=p.account, nonce=nonce,
            init_code=b"" if deployed else init_code(ctx.env.factory, p.owner.address,
                                                     ctx.cfg.account_salt),
            call_data=call_data, verification_gas_limit=ctx.cfg.verification_gas_limit,
            call_gas_limit=call_gas_limit, pre_verification_gas=pvg,
            max_priority_fee_per_gas=min(ctx.cfg.max_priority_fee, ctx.cfg.max_fee),
            max_fee_per_gas=ctx.cfg.max_fee,
            paymaster=ctx.env.b3.bootstrap_paymaster if paymaster else None,
            paymaster_verification_gas_limit=(
                ctx.b3cfg.userop("bootstrap_paymaster_verification_gas_limit")
                if paymaster else 0),
            paymaster_post_op_gas_limit=(ctx.b3cfg.userop("paymaster_post_op_gas_limit")
                                         if paymaster else 0))
        sign_userop(ctx.chain, ctx.env.entrypoint, op, p.owner)
        return op

    build.call_data = call_data  # type: ignore[attr-defined]
    return ctx._estimate(build)


def _self_funded_deposit(ctx: D2Chain, p) -> Dict[str, Any]:
    """After the grant is gone, can the credit still be created without a sponsor?

    Two paths are measured, because they need very different things from the recipient:

    ``userop``  an UNSPONSORED UserOperation from the same account. The EntryPoint takes
                the prefund from the account itself (SimpleAccount's ``_payPrefund``
                forwards it from the account's own balance), so this needs only the vMin
                ETH the AnnouncementRegistry already forwarded -- no other funded address.
    ``direct``  an ordinary transaction from the account's owner EOA. This needs an
                EXTERNALLY FUNDED EOA, which is the gas-funding problem B3 exists to
                solve, so it is recorded but is not an answer on its own. The owner is
                funded from the faucet for this measurement.
    """
    blk = ctx.chain.block_number()
    code = ctx.chain.code(p.account, blk)
    out: Dict[str, Any] = {"account_deployed": len(code) > 2,
                           "account_eth_wei": ctx.chain.balance(p.account, blk),
                           "account_entrypoint_deposit_wei": ep_deposit(
                               ctx.chain, ctx.env.entrypoint, p.account, blk)}
    size0 = ctx.tree_size()
    # (1) unsponsored UserOperation, paid from the account's own ETH
    try:
        op = _live_bootstrap_op(ctx, p, 1_500_000, paymaster=False)
        sim = ctx.bundler.simulate([op])
        out["userop_simulation_accepted"] = sim.accepted
        out["userop_simulation_reason"] = sim.reason
        if sim.accepted:
            res = ctx.bundler.submit([op], label="d2k_self_funded_userop")
            ev = res.userop_events[0] if res.userop_events else None
            out.update({"userop_included": bool(res.status == 1 and ev and ev["success"]),
                        "userop_actual_gas_cost_wei": ev["actual_gas_cost"] if ev else None,
                        "userop_account_eth_after_wei": ctx.chain.balance(
                            p.account, ctx.chain.block_number()),
                        "userop_tree_size_after": ctx.tree_size()})
        else:
            out["userop_included"] = False
    except Exception as exc:
        out["userop_error"] = str(exc)[:200]
        out["userop_included"] = False
    out["result"] = "USEROP_INCLUDED" if out.get("userop_included") else "USEROP_FAILED"
    if out.get("userop_included"):
        out["credit_recoverable_without_external_funding"] = True
        out["tree_size_after"] = ctx.tree_size()
        return out
    out["credit_recoverable_without_external_funding"] = False
    # (2) direct owner-EOA transaction (needs an externally funded EOA)
    if not out["account_deployed"]:
        out["direct_result"] = "ACCOUNT_NOT_DEPLOYED"
        return out
    ctx.chain.send(faucet(), label="d2k_fund_self_funded_owner", phase="setup",
                   to=p.owner.address, value=10 ** 18,
                   gas=ctx.cfg.gas_limit("native_transfer"))
    data = abi.call(abi.SIG_ACCOUNT_EXECUTE, ["address", "uint256", "bytes"],
                    [ctx.env.b3.credit_pool,
                     0, abi.call(b3.SIG_POOL_DEPOSIT, ["uint256"], [p.commitment])])
    try:
        st = ctx.chain.send(p.owner, label="d2k_self_funded_direct", phase="workflow",
                            to=p.account, data=data, gas=2_000_000)
        out["direct_result"] = "INCLUDED" if int(st.receipt["status"], 16) == 1 else "REVERTED"
    except Exception as exc:
        out["direct_result"] = f"REJECTED: {str(exc)[:200]}"
    out["tree_size_after"] = ctx.tree_size()
    out["inserted"] = ctx.tree_size() > size0
    return out


# --- Section 22: what a bundler can detect before inclusion ------------------------------


def run_detect(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    """Validation-only simulation vs execution-aware estimation vs actual inclusion."""
    g = cfg["d2b_decomposition"]["grant"]
    rows: List[Dict[str, Any]] = []
    for seed in seeds[:2]:
        with D2Chain(seed, cfg) as ctx:
            high = int(g["sufficient_call_gas_limit"])
            frozen = ctx.b3cfg.userop("bootstrap_call_gas_limit")
            p0 = ctx.participant("member", 0)
            ctx.announce(p0)
            ctx.bootstrap_now(p0, high)
            for i, limit in enumerate(list(g["starved_call_gas_limits"]) + [high]):
                p = ctx.participant("detect", i)
                ctx.announce(p)
                op = ctx.bootstrap_op(p, int(limit))
                calldata = _handle_ops(ctx, [op])
                row: Dict[str, Any] = {"seed": seed, "call_gas_limit": int(limit),
                                       "is_frozen_limit": int(limit) == frozen}
                # (1) validation-only: the bundler's own eth_call handleOps
                sim = ctx.bundler.simulate([op])
                row.update({"handleops_eth_call_accepted": sim.accepted,
                            "handleops_eth_call_reason": sim.reason,
                            "handleops_eth_call_inner_error": sim.inner_error})
                # (2) execution-aware: trace the same call and look for an OOG sub-frame
                row.update(_trace_call_probe(ctx, calldata))
                # (3) execution-aware: estimate the account call directly
                row.update(_estimate_probe(ctx, p))
                # (4) what actually happens on chain
                size_before = ctx.tree_size()
                res = ctx.bundler.submit([op], label="d2k_detect")
                ev = res.userop_events[0] if res.userop_events else None
                row.update({"onchain_bundle_status": res.status,
                            "onchain_userop_success": bool(ev and ev["success"]),
                            "onchain_actual_gas_used": ev["actual_gas_used"] if ev else None,
                            "onchain_root_changed": ctx.tree_size() > size_before,
                            "grant_consumed": bool(b3.view_uint(
                                ctx.chain, ctx.env.b3.bootstrap_paymaster, b3.SIG_BPM_IS_USED,
                                ("address",), (p.account,)))})
                rows.append(row)
                log(f"  detect seed {seed} limit {limit}: sim_ok={sim.accepted} "
                    f"trace_oog={row.get('trace_call_execution_out_of_gas')} "
                    f"onchain_ok={row['onchain_userop_success']}")
    return {"rows": rows}


def _handle_ops(ctx: D2Chain, ops) -> bytes:
    from ...workloads.w1.userop import handle_ops_calldata
    return handle_ops_calldata(list(ops), ctx.bundler.beneficiary)


def _trace_call_probe(ctx: D2Chain, calldata: bytes) -> Dict[str, Any]:
    """``debug_traceCall`` of the identical ``handleOps`` call: does any frame run out of gas?"""
    out: Dict[str, Any] = {"trace_call_available": False,
                           "trace_call_execution_out_of_gas": None,
                           "trace_call_failing_frame_target": None,
                           "trace_call_userop_revert_log": None}
    try:
        tr = ctx.chain.rpc.call("debug_traceCall", [
            {"from": ctx.bundler.account.address, "to": ctx.env.entrypoint,
             "data": "0x" + calldata.hex(), "gas": hex(30_000_000)},
            "latest", {"tracer": "callTracer", "tracerConfig": {"withLog": True}}])
    except Exception as exc:
        out["trace_call_error"] = str(exc)[:200]
        return out
    out["trace_call_available"] = True
    found = {"oog": False, "target": None, "revert_log": False}

    def walk(fr: Dict[str, Any]) -> None:
        err = (fr.get("error") or "").lower()
        if "out of gas" in err or "outofgas" in err:
            found["oog"] = True
            found["target"] = fr.get("to")
        for lg in fr.get("logs") or []:
            if (lg.get("topics") or [None])[0] == abi.T_USEROP_REVERT_REASON:
                found["revert_log"] = True
        for c in fr.get("calls") or []:
            walk(c)

    if isinstance(tr, dict):
        walk(tr)
    out.update({"trace_call_execution_out_of_gas": found["oog"],
                "trace_call_failing_frame_target": found["target"],
                "trace_call_userop_revert_log": found["revert_log"]})
    return out


def _estimate_probe(ctx: D2Chain, p) -> Dict[str, Any]:
    """``eth_estimateGas`` of the account execution the operation asks the EntryPoint to make.

    The account is counterfactual, so the estimate is taken on the pool call itself from an
    eligible sender -- the closest execution-aware estimate available without deploying the
    account first. Recorded as the lower bound a bundler could compute, not as a claim that
    an ERC-4337 bundler's ``eth_estimateUserOperationGas`` would return exactly this.
    """
    out: Dict[str, Any] = {"estimate_gas_pool_deposit": None}
    data = abi.call(b3.SIG_POOL_DEPOSIT, ["uint256"], [p.commitment])
    try:
        res = ctx.chain.rpc.call("eth_estimateGas", [
            {"from": p.account, "to": ctx.env.b3.credit_pool, "data": "0x" + data.hex()},
            "latest"])
        out["estimate_gas_pool_deposit"] = int(res, 16)
    except Exception as exc:
        out["estimate_gas_error"] = str(exc)[:200]
    return out
