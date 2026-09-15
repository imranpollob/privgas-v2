"""D2-A experiments: root contention on the frozen B3 specimen.

Every function takes the D2 config and the seed list and returns a dict that may contain
``attempts`` (engine records, FIELD_TIERS), ``arrivals`` (ARRIVAL_FIELD_TIERS) and
anything else (written to ``results/.../raw/<exp>.json``).

Chain reuse: one chain per (experiment, seed, pool size) is set up, the initial tree is
built with real Bootstraps, spenders get the W1 asset, contenders are announced and their
Bootstrap ops priced, then a snapshot is taken; every trial runs from that snapshot and
is reverted afterwards. The Poisson streams are seeded per (experiment, seed, N, lambda,
T, policy-independent trial index): the same trial index sees the same arrival times under
P0 / P1 / P2 (common random numbers, paired comparison).

Proof reuse: identical proof inputs (identity, member list, userOpHash, depth) reuse the
first real proof of that input within one chain (``proof_cache_hit``); the attempt's
``proof_generation_ms`` is that real proof's measured time. Virtual time uses the
controlled segment, except in ``measured`` (real proof time drives the clock).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Sequence

from .engine import (ArrivalProcess, ContenderPool, Segments, SpenderState, Trial, TrialSpec,
                     VALID_PROOF_INCLUDED)
from .harness import D2Chain, HarnessInvariantViolation

Log = Callable[[str], None]


def stream_seed(*parts: Any) -> int:
    return int.from_bytes(hashlib.sha256("/".join(map(str, ("privgas-v2/d2/stream/v1",) + parts))
                                        .encode()).digest()[:8], "big")


def _chain(seed: int, cfg: Dict[str, Any], n: int, spenders: int, honest_capacity: int,
           adversary_capacity: int = 0):
    a = cfg["d2a"]
    limit = int(a["bootstrap_call_gas_limit"])
    ctx = D2Chain(seed, cfg).__enter__()
    try:
        ctx.build_pool(n, limit)
        states = []
        for i in range(spenders):
            p = ctx.participant("member", i)
            ctx.give_tokens(p)
            op, h = ctx.spend_op(p)
            states.append((p, op, h))
        honest = ContenderPool(ctx, "contender", honest_capacity, limit)
        adv = ContenderPool(ctx, "adversary", adversary_capacity, limit) if adversary_capacity else None
    except BaseException:
        ctx.__exit__(None, None, None)
        raise
    return ctx, states, honest, adv


def _run_trial(ctx: D2Chain, spec: TrialSpec, states, honest: ContenderPool,
               adv: Optional[ContenderPool], lam: float, stream: int, cohort: int = 1) -> Trial:
    snap = ctx.snapshot()
    honest.reset()
    if adv:
        adv.reset()
    try:
        sp = [SpenderState(p, op, h) for p, op, h in states[:cohort]]
        tr = Trial(ctx, spec, sp, ArrivalProcess(lam, stream), honest, adv)
        tr.run(0.0)
        for s in sp:
            # an included Spend consumes the sender's nonce; a failed attempt never does
            advanced = ctx.ep_nonce_of(s.participant) == s.base_op.nonce + 1
            if advanced != (s.success_time is not None):
                raise HarnessInvariantViolation("sender nonce does not match the recorded outcome")
        return tr
    finally:
        ctx.revert(snap)


def _arrivals(tr: Trial) -> List[Dict[str, Any]]:
    out = []
    for a in tr.arrival_records:
        row = {k: v for k, v in a.items() if k in (
            "kind", "participant", "virtual_time", "sim_accepted", "sim_reason", "included",
            "execution_success", "root_changed", "root_before", "root_after", "tree_size_before",
            "tree_size_after", "tx_hash", "gas_used", "block_number", "bundler_fee_wei",
            "beneficiary_compensation_wei", "actual_gas_used", "actual_gas_cost",
            "sponsor_bootstrap_charge_wei", "rpc_calls")}
        row.update({"experiment": tr.spec.experiment, "trial_id": tr.spec.trial_id})
        out.append(row)
    return out


def _trial_summary(tr: Trial, extra: Dict[str, Any]) -> Dict[str, Any]:
    recs = tr.records
    return {"trial_id": tr.spec.trial_id, "experiment": tr.spec.experiment, **extra,
            "attempts": len(recs), "successes": sum(r["outcome_class"] == VALID_PROOF_INCLUDED for r in recs),
            "simulations": tr.simulations,
            "arrivals_executed": len(tr.arrival_records),
            "root_changes": sum(a["root_changed"] for a in tr.arrival_records),
            "capacity_exceeded": tr.capacity_exceeded,
            "inconsistent": sum(1 for r in recs if r.get("consistent") is False)}


# --- Experiment 1: zero-contention control ------------------------------------------------


def run_control(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2a"]["control"]
    attempts, trials, wall = [], [], []
    for seed in seeds:
        for n in c["pool_sizes"]:
            k = int(c["trials_per_seed"])
            ctx, states, honest, _ = _chain(seed, cfg, n, k, 0)
            try:
                for i in range(k):
                    spec = TrialSpec("control", f"control/s{seed}/n{n}/t{i}", seed, n, 0.0,
                                     Segments(0.0, 0.0, 0.0, 0.0, 0.0), "P0", 1)
                    snap = ctx.snapshot()
                    try:
                        s = SpenderState(*states[i])
                        tr = Trial(ctx, spec, [s], ArrivalProcess(0.0, 0), honest)
                        t0 = time.perf_counter()
                        tr.run()
                        wall.append((time.perf_counter() - t0) * 1000)
                        attempts += tr.records
                        trials.append(_trial_summary(tr, {"n": n, "seed": seed}))
                    finally:
                        ctx.revert(snap)
            finally:
                ctx.__exit__(None, None, None)
            log(f"  control seed {seed} n {n}: {sum(t['successes'] for t in trials if t['n']==n and t['seed']==seed)}/{k}")
    return {"attempts": attempts, "trials": trials}


# --- Experiment 2 / 14: deterministic simulation -> inclusion race -----------------------


def run_race(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    rows = []
    for seed in seeds:
        for n in cfg["d2a"]["race"]["pool_sizes"]:
            ctx, states, honest, _ = _chain(seed, cfg, n, 1, 2)
            try:
                p, op, h = states[0]
                for variant in ("race_P0", "inverse_control", "race_P1_resimulation", "race_then_reprove"):
                    snap = ctx.snapshot()
                    try:
                        rows.append(_race_variant(ctx, seed, n, variant, p, op, h, limit))
                    finally:
                        ctx.revert(snap)
            finally:
                ctx.__exit__(None, None, None)
            log(f"  race seed {seed} n {n}: " + ", ".join(
                f"{r['variant']}={r['outcome']}" for r in rows[-4:]))
    return {"rows": rows}


def _race_variant(ctx: D2Chain, seed: int, n: int, variant: str, p, op, h, limit: int) -> Dict[str, Any]:
    r: Dict[str, Any] = {"seed": seed, "n": n, "variant": variant}
    R = ctx.root()
    r["root_R"] = str(R)
    pr = ctx.prove_for(p, h, use_cache=False)
    r.update({"proof_root": str(pr.root), "proof_root_equals_R": pr.root == R,
              "prove_ms": pr.prove_ms, "verify_off_chain_ms": pr.verify_off_chain_ms,
              "proof_depth": pr.depth})
    op2 = ctx.with_proof(op, h, pr)
    sim = ctx.bundler.simulate([op2])
    r.update({"simulation_accepted": sim.accepted, "simulation_reason": sim.reason,
              "simulation_inner_error": sim.inner_error, "root_at_simulation": str(ctx.root())})
    if not sim.accepted:
        r["outcome"] = "REJECTED_AT_SIMULATION"
        return r
    if variant != "inverse_control":
        b = ctx.bootstrap_now(ctx.participant("contender", 0), limit)
        r.update({"intervening_bootstrap_root_changed": b["root_changed"],
                  "root_after_bootstrap": b["root_after"],
                  "intervening_bootstrap_sponsor_charge_wei": b.get("actual_gas_cost")})
    if variant == "race_P1_resimulation":
        sim2 = ctx.bundler.simulate([op2])
        r.update({"resimulation_accepted": sim2.accepted, "resimulation_reason": sim2.reason,
                  "resimulation_inner_error": sim2.inner_error,
                  "resimulation_stored_root": str(sim2.inner_args[1]) if sim2.inner_args else None})
        if not sim2.accepted:
            r["outcome"] = "DROPPED_AT_RESIMULATION"
            r["bundler_gas_lost_wei"] = 0
            return r
    bundler0, credit0 = ctx.eth_balance("bundler"), ctx.pm_deposit("credit")
    nonce0 = ctx.ep_nonce_of(p)
    from ...workloads.w1.userop import ep_deposit
    sender_eth0 = ctx.chain.balance(p.account, ctx.chain.block_number())
    sender_dep0 = ep_deposit(ctx.chain, ctx.env.entrypoint, p.account, ctx.chain.block_number())
    res = ctx.bundler.submit([op2], label="d2_race")
    r.update({"sender_eth_delta_wei": ctx.chain.balance(p.account, ctx.chain.block_number()) - sender_eth0,
              "sender_entrypoint_deposit_delta_wei": ep_deposit(
                  ctx.chain, ctx.env.entrypoint, p.account, ctx.chain.block_number()) - sender_dep0})
    r.update({"bundle_status": res.status, "bundle_gas_used": res.gas_used,
              "bundle_fee_wei": res.fee_wei,
              "beneficiary_compensation_wei": res.beneficiary_compensation_wei,
              "bundler_eth_delta_wei": ctx.eth_balance("bundler") - bundler0,
              "bundler_net_wei": res.beneficiary_compensation_wei - res.fee_wei,
              "credit_paymaster_deposit_delta_wei": ctx.pm_deposit("credit") - credit0,
              "sender_nonce_before": nonce0, "sender_nonce_after": ctx.ep_nonce_of(p),
              "nullifier_spent": ctx.nullifier_spent(pr),
              "userop_events": len(res.userop_events),
              "userop_success": res.userop_events[0]["success"] if res.userop_events else None,
              "onchain_revert_error": res.revert.error if res.revert else None,
              "onchain_revert_reason": res.revert.reason if res.revert else None,
              "onchain_revert_inner_error": res.revert.inner_error if res.revert else None,
              "onchain_revert_proof_root": str(res.revert.inner_args[0]) if res.revert and res.revert.inner_args else None,
              "onchain_revert_stored_root": str(res.revert.inner_args[1]) if res.revert and res.revert.inner_args else None,
              "trace_revert": res.trace_revert, "root_at_inclusion": str(ctx.root())})
    ok = res.status == 1 and res.userop_events and res.userop_events[0]["success"]
    r["outcome"] = "INCLUDED" if ok else ("ONCHAIN_" + (res.revert.inner_error or res.revert.reason or "REVERT")
                                          if res.revert else "ONCHAIN_REVERT")
    if variant == "race_then_reprove" and not ok:
        pr2 = ctx.prove_for(p, h, use_cache=False)
        op3 = ctx.with_proof(op, h, pr2)
        r.update({"reprove_signature_unchanged": op3.signature == op.signature,
                  "reprove_userop_hash_unchanged": True, "reprove_ms": pr2.prove_ms})
        sim3 = ctx.bundler.simulate([op3])
        res3 = ctx.bundler.submit([op3], label="d2_race_retry") if sim3.accepted else None
        r["retry_outcome"] = ("INCLUDED" if res3 and res3.status == 1 and res3.userop_events
                              and res3.userop_events[0]["success"] else "FAILED")
        r["retry_sponsor_charge_wei"] = res3.userop_events[0]["actual_gas_cost"] if res3 and res3.userop_events else None
    return r


# --- Experiment 19: bundle size and mixed bundles -----------------------------------------


def run_bundle(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    b = cfg["d2a"]["bundle_size"]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    rows = []
    for seed in seeds:
        kmax = max(b["bundle_sizes"])
        ctx, states, honest, _ = _chain(seed, cfg, int(b["pool_size"]), kmax, 2)
        try:
            for k in b["bundle_sizes"]:
                for variant in ("same_root_no_bootstrap", "bootstrap_between_sim_and_inclusion",
                                "one_stale_rest_fresh"):
                    if variant == "one_stale_rest_fresh" and k == 1:
                        continue
                    snap = ctx.snapshot()
                    try:
                        rows.append(_bundle_variant(ctx, seed, k, variant, states, limit))
                    finally:
                        ctx.revert(snap)
            for variant in ("[Bootstrap, Spend(R)]", "[Spend(R), Bootstrap]",
                            "[Bootstrap, Spend(R')]", "[Spend(R'), Bootstrap]"):
                snap = ctx.snapshot()
                try:
                    rows.append(_mixed_variant(ctx, seed, variant, states[0], limit))
                finally:
                    ctx.revert(snap)
        finally:
            ctx.__exit__(None, None, None)
        log(f"  bundle seed {seed}: " + "; ".join(f"{r['variant']}/k{r.get('k')}: {r['included_ops']}/{r['ops']}"
                                                  for r in rows[-14:]))
    return {"rows": rows}


def _submit_rows(ctx: D2Chain, ops, label: str) -> Dict[str, Any]:
    bundler0, credit0 = ctx.eth_balance("bundler"), ctx.pm_deposit("credit")
    res = ctx.bundler.submit(ops, label=label)
    return {"bundle_status": res.status, "bundle_gas_used": res.gas_used,
            "bundle_fee_wei": res.fee_wei, "beneficiary_compensation_wei": res.beneficiary_compensation_wei,
            "bundler_net_wei": res.beneficiary_compensation_wei - res.fee_wei,
            "credit_paymaster_deposit_delta_wei": ctx.pm_deposit("credit") - credit0,
            "userop_events": [{"success": e["success"], "actual_gas_cost": e["actual_gas_cost"],
                               "paymaster": e["paymaster"]} for e in res.userop_events],
            "included_ops": sum(1 for e in res.userop_events if e["success"]),
            "onchain_revert_reason": res.revert.reason if res.revert else None,
            "onchain_revert_inner_error": res.revert.inner_error if res.revert else None,
            "onchain_revert_op_index": res.revert.op_index if res.revert else None}


def _bundle_variant(ctx: D2Chain, seed: int, k: int, variant: str, states, limit: int) -> Dict[str, Any]:
    ops = []
    stale_ops = []
    for p, op, h in states[:k]:
        pr = ctx.prove_for(p, h)
        ops.append(ctx.with_proof(op, h, pr))
    r: Dict[str, Any] = {"seed": seed, "k": k, "variant": variant, "ops": k}
    sim = ctx.bundler.simulate(ops)
    r.update({"bundle_simulation_accepted": sim.accepted, "bundle_simulation_inner_error": sim.inner_error})
    if variant == "bootstrap_between_sim_and_inclusion":
        ctx.bootstrap_now(ctx.participant("contender", 0), limit)
    if variant == "one_stale_rest_fresh":
        # op 0 keeps its proof against R; a Bootstrap changes the root; ops 1..k-1 re-prove
        ctx.bootstrap_now(ctx.participant("contender", 0), limit)
        fresh = [ops[0]]
        for p, op, h in states[1:k]:
            fresh.append(ctx.with_proof(op, h, ctx.prove_for(p, h)))
        ops = fresh
        sim_fresh = ctx.bundler.simulate(ops[1:])
        r["fresh_subset_simulation_accepted"] = sim_fresh.accepted
    r.update(_submit_rows(ctx, ops, "d2_bundle"))
    r["root_at_inclusion"] = str(ctx.root())
    return r


def _mixed_variant(ctx: D2Chain, seed: int, variant: str, state, limit: int) -> Dict[str, Any]:
    p, op, h = state
    c = ctx.participant("contender", 0)
    R = ctx.root()
    boot = ctx.bootstrap_op(c, limit)
    if "R'" in variant:
        members_after = list(ctx.members) + [c.commitment]
        pr = ctx.prove_for(p, h, members=members_after)
    else:
        pr = ctx.prove_for(p, h)
    spend = ctx.with_proof(op, h, pr)
    ops = [boot, spend] if variant.startswith("[Bootstrap") else [spend, boot]
    r: Dict[str, Any] = {"seed": seed, "variant": variant, "k": None, "ops": 2,
                         "spend_proof_root": str(pr.root), "root_before": str(R)}
    sim = ctx.bundler.simulate(ops)
    r.update({"bundle_simulation_accepted": sim.accepted, "bundle_simulation_reason": sim.reason,
              "bundle_simulation_inner_error": sim.inner_error,
              "bundle_simulation_op_index": sim.op_index})
    r.update(_submit_rows(ctx, ops, "d2_mixed"))
    r["root_after"] = str(ctx.root())
    r["spend_included"] = any(e["success"] and e["paymaster"] and e["paymaster"].lower()
                              == ctx.env.b3.credit_paymaster.lower() for e in r["userop_events"])
    r["bootstrap_included"] = any(e["success"] and e["paymaster"] and e["paymaster"].lower()
                                  == ctx.env.b3.bootstrap_paymaster.lower() for e in r["userop_events"])
    return r


# --- Experiment 13: real proof-generation latency -----------------------------------------


def run_latency(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2a"]["proof_latency"]
    rows = []
    seed = seeds[0]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    for n in c["pool_sizes"]:
        with D2Chain(seed, cfg) as ctx:
            ctx.build_pool(n, limit)
            p = ctx.participant("member", 0)
            ctx.give_tokens(p)
            op, h = ctx.spend_op(p)
            total = int(c["samples"]) + int(c["warmup"])
            for i in range(total):
                # distinct messages: a fresh proof every time (no cache)
                msg = hex((int(h, 16) + i) % (1 << 256))
                pr = ctx.prove_for(p, msg, use_cache=False)
                rows.append({"n": n, "depth": pr.depth, "sample": i, "warmup": i < int(c["warmup"]),
                             "prove_ms": pr.prove_ms, "verify_off_chain_ms": pr.verify_off_chain_ms,
                             "seed": seed})
            # one of them is also verified on chain (real SemaphoreVerifier): the op's own hash
            pr = ctx.prove_for(p, h, use_cache=False)
            sim = ctx.bundler.simulate([ctx.with_proof(op, h, pr)])
            rows.append({"n": n, "depth": pr.depth, "sample": total, "warmup": False,
                         "prove_ms": pr.prove_ms, "verify_off_chain_ms": pr.verify_off_chain_ms,
                         "seed": seed, "onchain_simulation_accepted": sim.accepted})
        log(f"  latency n {n}: done")
    return {"rows": rows}


# --- Experiments 3 / 15 / 16: stochastic contention, policies, retries ------------------


def _segments(cfg: Dict[str, Any], T: float) -> Segments:
    fr = {k: v for k, v in cfg["d2a"]["segment_fractions"].items() if not k.startswith("_")}
    return Segments.split(T, fr)


def run_stochastic(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2a"]["stochastic"]
    attempts, arrivals, trials = [], [], []
    for seed in seeds:
        for n in c["pool_sizes"]:
            ctx, states, honest, _ = _chain(seed, cfg, n, 1, int(c["contender_capacity"]))
            t_chain = time.time()
            try:
                for lam in c["lambdas"]:
                    for T in c["windows"]:
                        for i in range(int(c["trials_per_seed"])):
                            tid = f"stochastic/s{seed}/n{n}/l{lam}/T{T}/t{i}"
                            spec = TrialSpec("stochastic", tid, seed, n, float(lam), _segments(cfg, T),
                                             "P0", 1, meta={"window": T})
                            tr = _run_trial(ctx, spec, states, honest, None, float(lam),
                                            stream_seed("stochastic", seed, n, lam, T, i))
                            attempts += tr.records
                            arrivals += _arrivals(tr)
                            trials.append(_trial_summary(tr, {"seed": seed, "n": n, "lambda": lam, "T": T}))
            finally:
                ctx.__exit__(None, None, None)
            log(f"  stochastic seed {seed} n {n}: {time.time() - t_chain:.0f}s, proofs {ctx.proofs_generated}")
    return {"attempts": attempts, "arrivals": arrivals, "trials": trials}


def run_policy(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2a"]["policy_retry"]
    attempts, arrivals, trials = [], [], []
    n = int(c["pool_size"])
    for seed in seeds:
        ctx, states, honest, _ = _chain(seed, cfg, n, 1, int(c["contender_capacity"]))
        t_chain = time.time()
        try:
            for lam in c["lambdas"]:
                for T in c["windows"]:
                    for i in range(int(c["trials_per_seed"])):
                        for pol in c["policies"]:
                            tid = f"policy/s{seed}/l{lam}/T{T}/t{i}/{pol}"
                            spec = TrialSpec("policy", tid, seed, n, float(lam), _segments(cfg, T), pol,
                                             int(c["max_attempts"]), meta={"window": T})
                            t0 = time.perf_counter()
                            calls0 = ctx.chain.rpc.calls
                            tr = _run_trial(ctx, spec, states, honest, None, float(lam),
                                            stream_seed("policy", seed, n, lam, T, i))
                            attempts += tr.records
                            arrivals += _arrivals(tr)
                            summ = _trial_summary(tr, {"seed": seed, "n": n, "lambda": lam, "T": T,
                                                       "policy": pol})
                            summ["harness_wall_ms"] = (time.perf_counter() - t0) * 1000
                            summ["rpc_calls_total"] = ctx.chain.rpc.calls - calls0
                            summ["rpc_calls_arrivals"] = sum(a["rpc_calls"] for a in tr.arrival_records)
                            summ["bundler_simulation_wall_ms"] = sum(
                                r.get("simulation_wall_ms") or 0 for r in tr.records)
                            trials.append(summ)
        finally:
            ctx.__exit__(None, None, None)
        log(f"  policy seed {seed}: {time.time() - t_chain:.0f}s, real proofs {ctx.proofs_generated}")
    return {"attempts": attempts, "arrivals": arrivals, "trials": trials}


def run_segments(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    """Experiment 12: one segment long (``dominant_segment``), all others ``base_segment``."""
    c = cfg["d2a"]["segment_dominance"]
    attempts, arrivals, trials = [], [], []
    n = int(c["pool_size"])
    names = ("prove", "submit", "sim", "queue", "chain")
    for seed in seeds:
        ctx, states, honest, _ = _chain(seed, cfg, n, 1, int(c["contender_capacity"]))
        try:
            for dom in names:
                seg = Segments(**{k: (float(c["dominant_segment"]) if k == dom else float(c["base_segment"]))
                                  for k in names})
                for i in range(int(c["trials_per_seed"])):
                    for pol in c["policies"]:
                        tid = f"segments/s{seed}/{dom}/t{i}/{pol}"
                        spec = TrialSpec("segments", tid, seed, n, float(c["lambda"]), seg, pol, 1,
                                         meta={"segment_profile": dom})
                        tr = _run_trial(ctx, spec, states, honest, None, float(c["lambda"]),
                                        stream_seed("segments", seed, dom, i))
                        attempts += tr.records
                        arrivals += _arrivals(tr)
                        trials.append(_trial_summary(tr, {"seed": seed, "segment_profile": dom,
                                                          "policy": pol}))
        finally:
            ctx.__exit__(None, None, None)
        log(f"  segments seed {seed} done")
    return {"attempts": attempts, "arrivals": arrivals, "trials": trials}


def run_measured(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    """Retry loop where the proof segment is the real measured proof time (no proof cache
    can shorten the clock: a cache hit charges the cached proof's measured time)."""
    c = cfg["d2a"]["measured_latency_retry"]
    attempts, arrivals, trials = [], [], []
    n = int(c["pool_size"])
    for seed in seeds:
        ctx, states, honest, _ = _chain(seed, cfg, n, 1, int(c["contender_capacity"]))
        try:
            for lam in c["lambdas"]:
                for bi in c["block_intervals"]:
                    seg = Segments(None, float(c["submit"]), float(c["sim"]), float(c["queue"]), float(bi))
                    for i in range(int(c["trials_per_seed"])):
                        for pol in c["policies"]:
                            tid = f"measured/s{seed}/l{lam}/b{bi}/t{i}/{pol}"
                            spec = TrialSpec("measured", tid, seed, n, float(lam), seg, pol,
                                             int(c["max_attempts"]), meta={"block_interval": bi})
                            tr = _run_trial(ctx, spec, states, honest, None, float(lam),
                                            stream_seed("measured", seed, lam, bi, i))
                            attempts += tr.records
                            arrivals += _arrivals(tr)
                            trials.append(_trial_summary(tr, {"seed": seed, "lambda": lam,
                                                              "block_interval": bi, "policy": pol}))
        finally:
            ctx.__exit__(None, None, None)
        log(f"  measured seed {seed} done")
    return {"attempts": attempts, "arrivals": arrivals, "trials": trials}


# --- Experiment 18: concurrent spenders ---------------------------------------------------


def run_concurrency(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2a"]["concurrency"]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    n = int(c["pool_size"])
    mmax = max(c["cohort_sizes"])
    rows, attempts, arrivals, trials = [], [], [], []
    for seed in seeds:
        ctx, states, honest, _ = _chain(seed, cfg, n, mmax, int(c["contender_capacity"]))
        try:
            for m in c["cohort_sizes"]:
                for variant in ("no_bootstrap", "one_bootstrap_between_sim_and_inclusion"):
                    snap = ctx.snapshot()
                    try:
                        ops = []
                        for p, op, h in states[:m]:
                            ops.append(ctx.with_proof(op, h, ctx.prove_for(p, h)))
                        sims = [ctx.bundler.simulate([o]).accepted for o in ops]
                        if variant != "no_bootstrap":
                            ctx.bootstrap_now(ctx.participant("contender", 0), limit)
                        b0 = ctx.eth_balance("bundler")
                        res = [ctx.bundler.submit([o], label="d2_conc") for o in ops]
                        rows.append({"seed": seed, "m": m, "variant": variant,
                                     "simulations_accepted": sum(sims),
                                     "included": sum(1 for x in res if x.status == 1 and x.userop_events
                                                     and x.userop_events[0]["success"]),
                                     "onchain_root_mismatch": sum(1 for x in res if x.revert and
                                                                  x.revert.inner_error == "RootMismatch"),
                                     "bundler_eth_delta_wei": ctx.eth_balance("bundler") - b0,
                                     "bundler_net_wei": sum(x.beneficiary_compensation_wei - x.fee_wei for x in res),
                                     "failed_gas": sum(x.gas_used for x in res if x.status != 1)})
                    finally:
                        ctx.revert(snap)
                for lam in c["stochastic_lambdas"]:
                    for i in range(int(c["trials_per_seed"])):
                        for pol in c["policies"]:
                            tid = f"concurrency/s{seed}/m{m}/l{lam}/t{i}/{pol}"
                            spec = TrialSpec("concurrency", tid, seed, n, float(lam),
                                             _segments(cfg, float(c["stochastic_window"])), pol,
                                             int(c["max_attempts"]),
                                             meta={"window": float(c["stochastic_window"])})
                            tr = _run_trial(ctx, spec, states, honest, None, float(lam),
                                            stream_seed("concurrency", seed, m, lam, i), cohort=m)
                            attempts += tr.records
                            arrivals += _arrivals(tr)
                            trials.append(_trial_summary(tr, {"seed": seed, "m": m, "lambda": lam,
                                                              "policy": pol}))
        finally:
            ctx.__exit__(None, None, None)
        log(f"  concurrency seed {seed} done")
    return {"rows": rows, "attempts": attempts, "arrivals": arrivals, "trials": trials}


# --- Experiment 25: A2 adversarial schedule -----------------------------------------------


def run_adversary(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    """Observer: the bundler's A2 view (simulation acceptance). The adversary is the bundler
    operator or a party it feeds; it has no other visibility. No honest arrivals (lambda 0),
    so every root change is adversarial. Budget = adversarial deposits per victim trial."""
    c = cfg["d2a"]["adversary"]
    n = int(c["pool_size"])
    attempts, arrivals, trials = [], [], []
    mmax = max(c["cohort_sizes"])
    for seed in seeds:
        ctx, states, honest, adv = _chain(seed, cfg, n, mmax, 1, int(c["capacity"]))
        try:
            for m in c["cohort_sizes"]:
                for budget in c["budgets"]:
                    for pol in c["policies"]:
                        tid = f"adversary/s{seed}/m{m}/k{budget}/{pol}"
                        spec = TrialSpec("adversary", tid, seed, n, 0.0,
                                         _segments(cfg, float(c["window"])), pol, int(c["max_attempts"]),
                                         adversary_budget=int(budget), adversary_delay=float(c["delay"]),
                                         meta={"adversary_budget": int(budget), "window": float(c["window"])})
                        tr = _run_trial(ctx, spec, states, honest, adv, 0.0, 0, cohort=m)
                        attempts += tr.records
                        arrivals += _arrivals(tr)
                        trials.append(_trial_summary(tr, {"seed": seed, "m": m, "budget": budget,
                                                          "policy": pol,
                                                          "adversary_deposits": tr.adversary_used}))
        finally:
            ctx.__exit__(None, None, None)
        log(f"  adversary seed {seed} done")
    return {"attempts": attempts, "arrivals": arrivals, "trials": trials}
