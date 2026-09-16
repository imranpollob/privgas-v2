"""Question A experiments: can bounded root history cheaply remove the D2-A race?

Every function takes the merged D2K config and the seed list and returns a dict that may
contain ``attempts`` (engine records, ``records.FIELD_TIERS``), ``arrivals`` and anything
else (written to ``results/d2-killcondition/<batch>/raw/<exp>.json``).

Experiments
-----------
``boundary``    Section 13. Deterministic simulation -> inclusion race with EXACTLY
                0, 1, 2, 3, 4 or 8 intervening root updates, for K in {1, 2, 4, 8} and the
                frozen control, all against the SAME intervening Bootstraps.
``security``    Section 6. The security invariants, with real Groth16 proofs verified on
                chain by the frozen SemaphoreVerifier.
``stochastic``  Sections 9/10. lambda x T matrix per K, paired by common random numbers.
``retry``       Section 10. Retries / proofs / simulations / time to success per K.
``bundle``      Section 14. Bundle sizes sharing one root, 0..K+1 intervening updates.
``overhead``    Section 11. The mitigation's own cost, on DEDICATED deployments only.

Chain reuse follows the pilot: one fan-out chain per (experiment, seed[, pool size]), the
tree built with real Bootstraps, spenders funded with the W1 asset, contenders announced
and their Bootstrap ops priced, then a snapshot; every trial runs from that snapshot and
is reverted afterwards.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ...workloads.w1 import abi, b3
from ..d2.engine import VALID_PROOF_INCLUDED
from ..d2.exp_a import stream_seed
from ..d2.harness import HarnessInvariantViolation
from . import mitigation
from .engine import (ArrivalProcess, ContenderPool, HistoryTrial, Segments, SpenderState,
                     TrialSpec, annotate, check_model_agreement)
from .harness import D2KChain

Log = Callable[[str], None]


# --- chain setup -----------------------------------------------------------------------


def _fanout_chain(seed: int, cfg: Dict[str, Any], n: int, spenders_per_variant: int,
                  honest_capacity: int, distinct_per_variant: bool = False
                  ) -> Tuple[D2KChain, Dict[str, List], ContenderPool]:
    """One fan-out chain: a pool of ``n`` real members and the spenders' Spend operations.

    ``distinct_per_variant = False`` (the default) lets the SAME pool members serve every
    variant, which is correct whenever each variant is exercised in its own
    snapshot-reverted round: the member's EntryPoint nonce, token balance and nullifier
    state are restored between variants, so every variant's operation is built from the
    same account at the same nonce and only the credit Paymaster differs.

    ``distinct_per_variant = True`` gives every variant its own members. It is REQUIRED
    when several variants submit inside one round (the deterministic boundary experiment),
    because two operations from one account at one nonce cannot both be included -- the
    second would fail with the EntryPoint's nonce error rather than with the protocol
    behaviour under test.
    """
    ks = [int(k) for k in cfg["d2k"]["k_values"]]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    ctx = D2KChain(seed, cfg, shape="fanout", ks=ks).__enter__()
    try:
        variants = ctx.d2k.variants()
        need = spenders_per_variant * (len(variants) if distinct_per_variant else 1)
        if need > n:
            raise ValueError(f"pool of {n} cannot supply {need} spenders")
        ctx.build_pool(n, limit)
        ctx.assert_mirrors_agree()
        states: Dict[str, List] = {}
        for vi, v in enumerate(variants):
            base = vi * spenders_per_variant if distinct_per_variant else 0
            per = []
            for j in range(spenders_per_variant):
                p = ctx.participant("member", base + j)
                ctx.give_tokens(p)
                per.append((p, *ctx.spend_op_for(p, v)))
            states[v] = per
        honest = ContenderPool(ctx, "contender", honest_capacity, limit)
    except BaseException:
        ctx.__exit__(None, None, None)
        raise
    return ctx, states, honest


def _capacity_of(ctx: D2KChain, variant: str) -> int:
    return 1 if variant == "frozen" else int(variant[1:])


# --- Section 13: deterministic retention boundary --------------------------------------


def run_boundary(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2k"]["boundary"]
    ks = [int(k) for k in cfg["d2k"]["deterministic_k_values"]]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    n = int(c["pool_size"])
    rows: List[Dict[str, Any]] = []
    for seed in seeds:
        ctx, states, _ = _fanout_chain(seed, cfg, n, 1, int(c["contender_capacity"]),
                                       distinct_per_variant=True)
        try:
            variants = ["frozen"] + [f"K{k}" for k in ks]
            for d in c["intervening_root_updates"]:
                snap = ctx.snapshot()
                try:
                    rows += _boundary_round(ctx, seed, int(d), variants, states, limit)
                finally:
                    ctx.revert(snap)
            log(f"  boundary seed {seed}: "
                + ", ".join(f"d={r['intervening_root_updates']}/{r['variant']}:"
                            f"{'OK' if r['included'] else 'FAIL'}" for r in rows[-len(variants):]))
        finally:
            ctx.__exit__(None, None, None)
    return {"rows": rows}


def _boundary_round(ctx: D2KChain, seed: int, d: int, variants: List[str], states,
                    limit: int) -> List[Dict[str, Any]]:
    """Prove + simulate every variant against R, then execute exactly ``d`` unrelated
    Bootstraps, then submit every unchanged operation."""
    R = ctx.root()
    prepared = []
    for v in variants:
        p, op, h = states[v][0]
        pr = ctx.prove_for(p, h)
        if pr.root != R:
            raise HarnessInvariantViolation("boundary: proof root != observed root")
        op2 = ctx.with_proof(op, h, pr)
        sim = ctx.bundler.simulate([op2])
        prepared.append((v, p, op2, pr, sim))
    roots_after = []
    for i in range(d):
        out = ctx.bootstrap_now(ctx.participant("contender", i), limit)
        if not out["root_changed"]:
            raise HarnessInvariantViolation(f"boundary: intervening Bootstrap {i} did not insert")
        roots_after.append(out["root_after"])
    ctx.assert_mirrors_agree()
    out_rows = []
    for v, p, op2, pr, sim in prepared:
        k = _capacity_of(ctx, v)
        accepted_view = ctx.accepts_root(v, pr.root)
        age = ctx.root_age(v, pr.root)
        credit0 = ctx.pm_deposit_variant(v)
        bundler0 = ctx.eth_balance("bundler")
        nonce0 = ctx.ep_nonce_of(p)
        res = ctx.bundler.submit([op2], label="d2k_boundary")
        ev = res.userop_events[0] if res.userop_events else None
        included = bool(res.status == 1 and ev and ev["success"])
        if not included and (res.revert is None or res.revert.inner_error != "RootMismatch"):
            raise HarnessInvariantViolation(
                f"boundary: {v} failed for a non-protocol reason "
                f"({res.revert.reason if res.revert else 'unknown'}); the experiment would "
                "not be measuring root acceptance")
        out_rows.append({
            "seed": seed, "variant": v, "history_capacity": k,
            "intervening_root_updates": d, "pool_size": ctx.tree_size() - d,
            "proof_root": str(pr.root), "root_at_inclusion": str(ctx.root()),
            "simulation_accepted": sim.accepted, "simulation_inner_error": sim.inner_error,
            "view_accepts_proof_root": accepted_view, "root_age_at_inclusion": age,
            "history_state": ctx.history_state(v),
            "included": included, "bundle_status": res.status,
            "bundle_gas_used": res.gas_used, "bundle_fee_wei": res.fee_wei,
            "beneficiary_compensation_wei": res.beneficiary_compensation_wei,
            "bundler_net_wei": res.beneficiary_compensation_wei - res.fee_wei,
            "bundler_eth_delta_wei": ctx.eth_balance("bundler") - bundler0,
            "sponsor_charge_wei": credit0 - ctx.pm_deposit_variant(v),
            "actual_gas_used": ev["actual_gas_used"] if ev else None,
            "onchain_revert_reason": res.revert.reason if res.revert else None,
            "onchain_revert_inner_error": res.revert.inner_error if res.revert else None,
            "onchain_revert_proof_root": (str(res.revert.inner_args[0]) if res.revert
                                          and res.revert.inner_args else None),
            "onchain_revert_stored_root": (str(res.revert.inner_args[1]) if res.revert
                                           and res.revert.inner_args else None),
            "trace_revert_inner_error": (res.trace_revert or {}).get("inner_error"),
            "nonce_advanced": ctx.ep_nonce_of(p) - nonce0,
            "nullifier_spent": ctx.nullifier_spent_for(v, pr),
            # the analytical retention rule for this K, decided before submission
            "predicted_valid": d < k,
            "prediction_matches_outcome": (d < k) == included,
        })
    return out_rows


# --- Section 6: security invariants -----------------------------------------------------


def run_security(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2k"]["security"]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    n = int(c["pool_size"])
    k = int(c["capacity_under_test"])
    variant = f"K{k}"
    rows: List[Dict[str, Any]] = []
    for seed in seeds:
        ctx, states, _ = _fanout_chain(seed, cfg, n, 2, int(c["contender_capacity"]))
        try:
            for case in ("current_root_accepted", "retained_historical_root_accepted",
                         "root_older_than_window_rejected", "fabricated_root_rejected",
                         "future_unknown_root_rejected", "wrong_message_rejected",
                         "wrong_scope_rejected", "invalid_groth16_rejected",
                         "nullifier_reuse_rejected", "same_credit_twice_rejected",
                         "k1_matches_frozen"):
                snap = ctx.snapshot()
                try:
                    rows.append(_security_case(ctx, seed, case, variant, k, states, limit))
                finally:
                    ctx.revert(snap)
        finally:
            ctx.__exit__(None, None, None)
        log(f"  security seed {seed}: "
            + ", ".join(f"{r['case']}={'pass' if r['expectation_met'] else 'FAIL'}"
                        for r in rows[-11:]))
    return {"rows": rows}


def _spend_outcome(ctx: D2KChain, op, label: str) -> Dict[str, Any]:
    sim = ctx.bundler.simulate([op])
    out = {"simulation_accepted": sim.accepted, "simulation_reason": sim.reason,
           "simulation_inner_error": sim.inner_error}
    if not sim.accepted:
        out.update({"included": False, "submitted": False})
        return out
    res = ctx.bundler.submit([op], label=label)
    ev = res.userop_events[0] if res.userop_events else None
    out.update({"submitted": True, "included": bool(res.status == 1 and ev and ev["success"]),
                "bundle_status": res.status,
                "onchain_revert_inner_error": res.revert.inner_error if res.revert else None,
                "actual_gas_used": ev["actual_gas_used"] if ev else None})
    return out


def _security_case(ctx: D2KChain, seed: int, case: str, variant: str, k: int, states,
                   limit: int) -> Dict[str, Any]:
    p, op, h = states[variant][0]
    r: Dict[str, Any] = {"seed": seed, "case": case, "variant": variant, "history_capacity": k}

    def deposits(count: int, start: int = 0) -> None:
        for i in range(count):
            if not ctx.bootstrap_now(ctx.participant("contender", start + i), limit)["root_changed"]:
                raise HarnessInvariantViolation("security: intervening Bootstrap did not insert")

    if case == "current_root_accepted":
        pr = ctx.prove_for(p, h)
        r.update(_spend_outcome(ctx, ctx.with_proof(op, h, pr), "d2k_sec"))
        r["expected_included"] = True

    elif case == "retained_historical_root_accepted":
        pr = ctx.prove_for(p, h)
        deposits(k - 1)
        r["root_age"] = ctx.root_age(variant, pr.root)
        r.update(_spend_outcome(ctx, ctx.with_proof(op, h, pr), "d2k_sec"))
        r["expected_included"] = True

    elif case == "root_older_than_window_rejected":
        pr = ctx.prove_for(p, h)
        deposits(k)
        r["root_age"] = ctx.root_age(variant, pr.root)
        r["view_accepts"] = ctx.accepts_root(variant, pr.root)
        r.update(_spend_outcome(ctx, ctx.with_proof(op, h, pr), "d2k_sec"))
        r["expected_included"] = False
        r["expected_error"] = "RootMismatch"

    elif case == "fabricated_root_rejected":
        pr = ctx.prove_for(p, h)
        fake = dict(pr.proof)
        fake["merkleTreeRoot"] = str((int(pr.proof["merkleTreeRoot"]) + 1) % (1 << 254))
        r["view_accepts"] = ctx.accepts_root(variant, int(fake["merkleTreeRoot"]))
        r.update(_spend_outcome(ctx, ctx.with_proof(
            op, h, _replace_proof(pr, fake)), "d2k_sec"))
        r["expected_included"] = False
        r["expected_error"] = "RootMismatch"

    elif case == "future_unknown_root_rejected":
        # A real, well-formed proof against the tree the NEXT deposit will create: the root
        # is legitimate but has not been mirrored yet.
        nxt = ctx.participant("contender", 0)
        future_members = list(ctx.members) + [nxt.commitment]
        pr = ctx.prove_against(p, h, future_members)
        r["view_accepts"] = ctx.accepts_root(variant, pr.root)
        r.update(_spend_outcome(ctx, ctx.with_proof(op, h, pr), "d2k_sec"))
        r["expected_included"] = False
        r["expected_error"] = "RootMismatch"

    elif case == "wrong_message_rejected":
        other = hex((int(h, 16) ^ 1) % (1 << 256))
        pr = ctx.prove_against(p, other, list(ctx.members))
        r.update(_spend_outcome(ctx, ctx.with_proof(op, h, pr), "d2k_sec"))
        r["expected_included"] = False
        r["expected_error"] = "WrongMessage"

    elif case == "wrong_scope_rejected":
        pr = ctx.prove_against(p, h, list(ctx.members),
                               scope=(ctx.env.b3.credit_scope + 1) % (1 << 254))
        r.update(_spend_outcome(ctx, ctx.with_proof(op, h, pr), "d2k_sec"))
        r["expected_included"] = False
        r["expected_error"] = "WrongScope"

    elif case == "invalid_groth16_rejected":
        pr = ctx.prove_for(p, h)
        bad = dict(pr.proof)
        pts = [str(x) for x in pr.proof["points"]]
        pts[0] = str((int(pts[0]) + 1) % (1 << 254))
        bad["points"] = pts
        r.update(_spend_outcome(ctx, ctx.with_proof(op, h, _replace_proof(pr, bad)), "d2k_sec"))
        r["expected_included"] = False
        r["expected_error"] = "InvalidProof"

    elif case in ("nullifier_reuse_rejected", "same_credit_twice_rejected"):
        # First spend succeeds. The second uses the SAME credit: a different operation
        # (second spender slot is the same participant's next nonce) and, for
        # `same_credit_twice_rejected`, a different RETAINED root -- which must not help.
        pr = ctx.prove_for(p, h)
        first = _spend_outcome(ctx, ctx.with_proof(op, h, pr), "d2k_sec")
        r["first_spend"] = first
        r["nullifier_after_first"] = ctx.nullifier_spent_for(variant, pr)
        if case == "same_credit_twice_rejected":
            deposits(1)
        ctx.give_tokens(p)
        op2, h2 = ctx.spend_op_for(p, variant)
        pr2 = ctx.prove_against(p, h2, list(ctx.members))
        r["second_proof_root_retained"] = ctx.accepts_root(variant, pr2.root)
        r["same_nullifier"] = (str(pr2.proof["nullifier"]) == str(pr.proof["nullifier"]))
        r.update(_spend_outcome(ctx, ctx.with_proof(op2, h2, pr2), "d2k_sec"))
        r["expected_included"] = False
        r["expected_error"] = "NullifierSpent"

    elif case == "k1_matches_frozen":
        # For every root state, K=1 and the frozen contract must agree on acceptance,
        # both in their views and in a real on-chain Spend.
        views = []
        pr = ctx.prove_for(p, h)
        for d in range(0, 3):
            if d:
                deposits(1, start=d - 1)
            views.append({"intervening": d,
                          "frozen_accepts": ctx.accepts_root("frozen", pr.root),
                          "k1_accepts": ctx.accepts_root("K1", pr.root),
                          "frozen_root": str(ctx.variant_root("frozen")),
                          "k1_root": str(ctx.variant_root("K1"))})
        r["views"] = views
        r["expectation_met"] = all(v["frozen_accepts"] == v["k1_accepts"]
                                   and v["frozen_root"] == v["k1_root"] for v in views)
        return r
    else:  # pragma: no cover
        raise ValueError(case)

    ok = r["included"] == r["expected_included"]
    if not r["expected_included"]:
        observed = r.get("simulation_inner_error") or r.get("onchain_revert_inner_error")
        r["observed_error"] = observed
        ok = ok and observed == r["expected_error"]
    r["expectation_met"] = bool(ok)
    return r


def _replace_proof(pr, proof_dict):
    from ..d2.harness import ProofRecord
    return ProofRecord(proof_dict, pr.root, pr.depth, pr.group_size, pr.prove_ms,
                       pr.verify_off_chain_ms, True)


# --- Sections 9/10: stochastic contention ----------------------------------------------


def _segments(cfg: Dict[str, Any], T: float) -> Segments:
    fr = {k: v for k, v in cfg["d2a"]["segment_fractions"].items() if not k.startswith("_")}
    return Segments.split(T, fr)


def _run_history_trial(ctx: D2KChain, spec: TrialSpec, states, honest: ContenderPool,
                       lam: float, stream: int, variant: str, cohort: int = 1) -> HistoryTrial:
    snap = ctx.snapshot()
    honest.reset()
    try:
        sp = [SpenderState(p, op, h) for p, op, h in states[variant][:cohort]]
        tr = HistoryTrial(ctx, spec, sp, ArrivalProcess(lam, stream), honest,
                          capacity=_capacity_of(ctx, variant), variant=variant)
        tr.run(0.0)
        for s in sp:
            advanced = ctx.ep_nonce_of(s.participant) == s.base_op.nonce + 1
            if advanced != (s.success_time is not None):
                raise HarnessInvariantViolation("sender nonce does not match the recorded outcome")
        return tr
    finally:
        ctx.revert(snap)


def _arrivals(tr: HistoryTrial, extra: Dict[str, Any]) -> List[Dict[str, Any]]:
    keep = ("kind", "participant", "virtual_time", "sim_accepted", "sim_reason", "included",
            "execution_success", "root_changed", "root_before", "root_after",
            "tree_size_before", "tree_size_after", "tx_hash", "gas_used", "block_number",
            "bundler_fee_wei", "beneficiary_compensation_wei", "actual_gas_used",
            "actual_gas_cost", "sponsor_bootstrap_charge_wei", "rpc_calls")
    return [{**{k: v for k, v in a.items() if k in keep},
             "experiment": tr.spec.experiment, "trial_id": tr.spec.trial_id,
             "variant": tr.variant, "history_capacity": tr.capacity, **extra}
            for a in tr.arrival_records]


def _summary(tr: HistoryTrial, extra: Dict[str, Any]) -> Dict[str, Any]:
    recs = tr.records
    return {"trial_id": tr.spec.trial_id, "experiment": tr.spec.experiment,
            "variant": tr.variant, "history_capacity": tr.capacity, **extra,
            "attempts": len(recs),
            "successes": sum(r["outcome_class"] == VALID_PROOF_INCLUDED for r in recs),
            "simulations": tr.simulations, "arrivals_executed": len(tr.arrival_records),
            "root_changes": sum(a["root_changed"] for a in tr.arrival_records),
            "capacity_exceeded": tr.capacity_exceeded,
            "inconsistent": sum(1 for r in recs if r.get("consistent") is False),
            "model_mismatch": sum(1 for r in recs
                                  if r.get("prediction_matches_outcome") is False)}


def run_stochastic(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2k"]["stochastic"]
    n = int(c["pool_size"])
    attempts, arrivals, trials = [], [], []
    for seed in seeds:
        ctx, states, honest = _fanout_chain(seed, cfg, n, 1, int(c["contender_capacity"]))
        t_chain = time.time()
        try:
            for variant in ctx.d2k.variants():
                for lam in c["lambdas"]:
                    for T in c["windows"]:
                        for i in range(int(c["trials_per_seed"])):
                            tid = f"stochastic/s{seed}/{variant}/l{lam}/T{T}/t{i}"
                            spec = TrialSpec("stochastic", tid, seed, n, float(lam),
                                             _segments(cfg, float(T)), "P0", 1,
                                             meta={"window": T})
                            # common random numbers: the stream does NOT depend on the variant
                            tr = _run_history_trial(
                                ctx, spec, states, honest, float(lam),
                                stream_seed("d2k-stochastic", seed, n, lam, T, i), variant)
                            recs = annotate(tr, {"deployment_shape": "fanout"})
                            check_model_agreement(recs)
                            attempts += recs
                            arrivals += _arrivals(tr, {"deployment_shape": "fanout"})
                            trials.append(_summary(tr, {"seed": seed, "n": n, "lambda": lam,
                                                        "T": T}))
            log(f"  stochastic seed {seed}: {time.time() - t_chain:.0f}s, "
                f"proofs {ctx.proofs_generated}, attempts {len(attempts)}")
        finally:
            ctx.__exit__(None, None, None)
    return {"attempts": attempts, "arrivals": arrivals, "trials": trials}


def run_retry(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2k"]["retry"]
    n = int(c["pool_size"])
    attempts, arrivals, trials = [], [], []
    # Three seeds: each retry trial runs a whole 10-attempt client loop per variant, and the
    # per-K comparison is paired within a seed, so seeds buy less here than trials do.
    for seed in list(seeds)[:3]:
        ctx, states, honest = _fanout_chain(seed, cfg, n, 1, int(c["contender_capacity"]))
        t_chain = time.time()
        try:
            for variant in ctx.d2k.variants():
                for lam in c["lambdas"]:
                    for T in c["windows"]:
                        for i in range(int(c["trials_per_seed"])):
                            tid = f"retry/s{seed}/{variant}/l{lam}/T{T}/t{i}"
                            spec = TrialSpec("retry", tid, seed, n, float(lam),
                                             _segments(cfg, float(T)), "P0",
                                             int(c["max_attempts"]), meta={"window": T})
                            t0 = time.perf_counter()
                            tr = _run_history_trial(
                                ctx, spec, states, honest, float(lam),
                                stream_seed("d2k-retry", seed, n, lam, T, i), variant)
                            recs = annotate(tr, {"deployment_shape": "fanout"})
                            check_model_agreement(recs)
                            attempts += recs
                            arrivals += _arrivals(tr, {"deployment_shape": "fanout"})
                            s = _summary(tr, {"seed": seed, "n": n, "lambda": lam, "T": T})
                            s["harness_wall_ms"] = (time.perf_counter() - t0) * 1000
                            s["proofs_generated"] = sum(sp.proofs_generated for sp in tr.spenders)
                            trials.append(s)
            log(f"  retry seed {seed}: {time.time() - t_chain:.0f}s, proofs {ctx.proofs_generated}")
        finally:
            ctx.__exit__(None, None, None)
    return {"attempts": attempts, "arrivals": arrivals, "trials": trials}


# --- Section 14: bundle behaviour -------------------------------------------------------


def run_bundle(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    c = cfg["d2k"]["bundle"]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    n = int(c["pool_size"])
    ks = [int(k) for k in c["k_values"]]
    kmax = max(c["bundle_sizes"])
    rows: List[Dict[str, Any]] = []
    for seed in seeds:
        ctx, states, _ = _fanout_chain(seed, cfg, n, kmax, int(c["contender_capacity"]))
        try:
            for variant in ["frozen"] + [f"K{k}" for k in ks]:
                cap = _capacity_of(ctx, variant)
                for bsize in c["bundle_sizes"]:
                    # the informative points: none, one, just inside, exactly at, and just
                    # past the retention boundary
                    for d in sorted({0, 1, max(0, cap - 1), cap, cap + 1}):
                        snap = ctx.snapshot()
                        try:
                            rows.append(_bundle_case(ctx, seed, variant, cap, bsize, d,
                                                     states, limit, "shared_root"))
                        finally:
                            ctx.revert(snap)
                    if bsize > 1:
                        snap = ctx.snapshot()
                        try:
                            rows.append(_bundle_case(ctx, seed, variant, cap, bsize, cap,
                                                     states, limit, "one_stale_rest_fresh"))
                        finally:
                            ctx.revert(snap)
            log(f"  bundle seed {seed}: {len(rows)} rows")
        finally:
            ctx.__exit__(None, None, None)
    return {"rows": rows}


def _bundle_case(ctx: D2KChain, seed: int, variant: str, cap: int, bsize: int, d: int,
                 states, limit: int, mode: str) -> Dict[str, Any]:
    R = ctx.root()
    ops = []
    proofs = []
    for p, op, h in states[variant][:bsize]:
        pr = ctx.prove_for(p, h)
        proofs.append(pr)
        ops.append(ctx.with_proof(op, h, pr))
    sim = ctx.bundler.simulate(ops)
    for i in range(d):
        if not ctx.bootstrap_now(ctx.participant("contender", i), limit)["root_changed"]:
            raise HarnessInvariantViolation("bundle: intervening Bootstrap did not insert")
    if mode == "one_stale_rest_fresh":
        # op 0 keeps the now-evicted proof; ops 1.. re-prove against the current tree
        fresh = [ops[0]]
        for p, op, h in states[variant][1:bsize]:
            fresh.append(ctx.with_proof(op, h, ctx.prove_for(p, h)))
        ops = fresh
    credit0 = ctx.pm_deposit_variant(variant)
    bundler0 = ctx.eth_balance("bundler")
    res = ctx.bundler.submit(ops, label="d2k_bundle")
    included = sum(1 for e in res.userop_events if e["success"])
    return {"seed": seed, "variant": variant, "history_capacity": cap, "mode": mode,
            "bundle_size": bsize, "intervening_root_updates": d,
            "proof_root": str(R), "root_at_inclusion": str(ctx.root()),
            "bundle_simulation_accepted": sim.accepted,
            "bundle_simulation_inner_error": sim.inner_error,
            "bundle_status": res.status, "included_ops": included, "ops": len(ops),
            "all_included": included == len(ops),
            "bundle_gas_used": res.gas_used,
            "bundler_net_wei": res.beneficiary_compensation_wei - res.fee_wei,
            "bundler_eth_delta_wei": ctx.eth_balance("bundler") - bundler0,
            "sponsor_charge_wei": credit0 - ctx.pm_deposit_variant(variant),
            "onchain_revert_inner_error": res.revert.inner_error if res.revert else None,
            "onchain_revert_op_index": res.revert.op_index if res.revert else None,
            "predicted_all_included": (d < cap) if mode == "shared_root" else False,
            }


# --- Section 11: the mitigation's own cost ----------------------------------------------


def run_overhead(cfg: Dict[str, Any], seeds: Sequence[int], log: Log = print) -> Dict[str, Any]:
    """DEDICATED deployments only: one frozen CreditPool -> one Paymaster, as B3 deploys."""
    c = cfg["d2k"]["overhead"]
    ks = [int(k) for k in cfg["d2k"]["k_values"]]
    limit = int(cfg["d2a"]["bootstrap_call_gas_limit"])
    deploy_rows, update_rows, validate_rows = [], [], []
    # Deterministic gas: two seeds are enough to show seed-independence, and each seed costs
    # one dedicated chain per variant.
    for seed in list(seeds)[:2]:
        for variant, hk in [("frozen", None)] + [(f"K{k}", k) for k in ks]:
            with D2KChain(seed, cfg, shape="dedicated", history_k=hk) as ctx:
                cap = 1 if hk is None else hk
                deploy_rows += [{"seed": seed, "variant": variant, "history_capacity": cap,
                                 **vars(dc)} for dc in ctx.d2k.costs]
                update_rows += _update_overhead(ctx, seed, variant, cap, c, limit)
                validate_rows += _validation_overhead(ctx, seed, variant, cap, c, limit)
            log(f"  overhead seed {seed} {variant}: done")
    return {"deployment": deploy_rows, "root_update": update_rows, "spend_validation": validate_rows}


def _update_overhead(ctx: D2KChain, seed: int, variant: str, cap: int, c: Dict[str, Any],
                     limit: int) -> List[Dict[str, Any]]:
    """Root-update cost as the tree grows: the whole deposit, its mirror sub-frame, and the
    Paymaster's own storage writes."""
    sizes = sorted(int(s) for s in c["tree_sizes"])
    rows = []
    for s in range(max(sizes) + 1):
        p = ctx.participant("member", s)
        ctx.announce(p)
        out = ctx.bootstrap_now(p, limit)
        if not out["root_changed"]:
            raise HarnessInvariantViolation(f"overhead: insertion failed at size {s}")
        if s not in sizes:
            continue
        tr = _trace_mirror(ctx, out["tx_hash"])
        rows.append({"seed": seed, "variant": variant, "history_capacity": cap,
                     "tree_size_before": s, "tree_size_after": s + 1,
                     "deposit_frame_gas_used": tr["deposit_frame_gas_used"],
                     "mirror_root_frame_gas_used": tr["mirror_root_frame_gas_used"],
                     "poseidon_calls": tr["poseidon_calls"],
                     "paymaster_slots_written": tr["paymaster_slots_written"],
                     "paymaster_slots_new_nonzero": tr["paymaster_slots_new_nonzero"],
                     "paymaster_slots_cleared": tr["paymaster_slots_cleared"],
                     "paymaster_nonzero_slots_after": tr["paymaster_nonzero_slots_after"],
                     "history_length": (mitigation.history_length(ctx.chain, ctx.d2k.mirror_target)
                                        if variant != "frozen" else 1),
                     "bootstrap_actual_gas_used": out.get("actual_gas_used"),
                     "bootstrap_sponsor_charge_wei": out.get("actual_gas_cost")})
    return rows


def _trace_mirror(ctx: D2KChain, tx_hash: str) -> Dict[str, Any]:
    pool = ctx.d2k.credit_pool.lower()
    target = ctx.d2k.mirror_target.lower()
    poseidon = ctx.frozen_b3.poseidon_t3.lower()
    out: Dict[str, Any] = {"deposit_frame_gas_used": None, "mirror_root_frame_gas_used": None,
                           "poseidon_calls": 0, "paymaster_slots_written": None,
                           "paymaster_slots_new_nonzero": None, "paymaster_slots_cleared": None,
                           "paymaster_nonzero_slots_after": None}
    try:
        tr = ctx.chain.rpc.call("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    except Exception:
        return out

    def walk(fr: Dict[str, Any]) -> None:
        to = (fr.get("to") or "").lower()
        inp = fr.get("input") or ""
        if to == pool and inp.startswith("0x" + abi.selector(b3.SIG_POOL_DEPOSIT).hex()):
            out["deposit_frame_gas_used"] = int(fr["gasUsed"], 16)
        if to == poseidon:
            out["poseidon_calls"] += 1
        if to == target and inp.startswith(mitigation.SELECTOR_MIRROR_ROOT):
            out["mirror_root_frame_gas_used"] = int(fr["gasUsed"], 16)
        for c in fr.get("calls") or []:
            walk(c)

    if isinstance(tr, dict):
        walk(tr)
    try:
        diff = ctx.chain.rpc.call("debug_traceTransaction", [
            tx_hash, {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}}])
        pre = (diff.get("pre", {}).get(target) or {}).get("storage", {}) or {}
        post = (diff.get("post", {}).get(target) or {}).get("storage", {}) or {}
        out["paymaster_slots_written"] = len(post)
        out["paymaster_slots_new_nonzero"] = sum(
            1 for k, v in post.items() if int(v, 16) != 0 and int(pre.get(k, "0x0"), 16) == 0)
        out["paymaster_slots_cleared"] = sum(1 for k, v in post.items() if int(v, 16) == 0)
    except Exception:
        pass
    return out


def _validation_overhead(ctx: D2KChain, seed: int, variant: str, cap: int, c: Dict[str, Any],
                         limit: int) -> List[Dict[str, Any]]:
    """Paymaster validation cost of a real, included Spend with a real proof.

    Run after ``_update_overhead``, so the tree is at ``max(tree_sizes) + 1`` -- the same
    size, the same members and therefore the same proof depth for every variant, because
    the member commitments are seed-derived and the insertion order is fixed.
    """
    n = int(c["spend_pool_size"])
    while ctx.tree_size() < n:
        s = ctx.tree_size()
        p = ctx.participant("member", s)
        ctx.announce(p)
        if not ctx.bootstrap_now(p, limit)["root_changed"]:
            raise HarnessInvariantViolation("overhead: spend-pool growth failed")
    n = ctx.tree_size()
    rows = []
    for rep in range(int(c["spend_repeats"])):
        p = ctx.participant("member", rep)
        ctx.give_tokens(p)
        op, h = ctx.spend_op_for(p, variant)
        pr = ctx.prove_for(p, h)
        op2 = ctx.with_proof(op, h, pr)
        dep0 = ctx.pm_deposit_variant(variant)
        res = ctx.bundler.submit([op2], label="d2k_overhead_spend")
        ev = res.userop_events[0] if res.userop_events else None
        if not (res.status == 1 and ev and ev["success"]):
            raise HarnessInvariantViolation(f"overhead: Spend not included for {variant}")
        tr = _trace_validation(ctx, res.tx_hash, variant)
        rows.append({"seed": seed, "variant": variant, "history_capacity": cap, "rep": rep,
                     "pool_size": n, "proof_depth": pr.depth,
                     "validate_frame_gas_used": tr["validate_frame_gas_used"],
                     "verify_proof_frame_gas_used": tr["verify_proof_frame_gas_used"],
                     "paymaster_slots_written": tr["paymaster_slots_written"],
                     "actual_gas_used": ev["actual_gas_used"],
                     "paymaster_charge_wei": dep0 - ctx.pm_deposit_variant(variant),
                     "bundle_gas_used": res.gas_used,
                     "history_length": (mitigation.history_length(ctx.chain,
                                                                  ctx.d2k.mirror_target)
                                        if variant != "frozen" else 1)})
    return rows


SIG_VALIDATE = ("validatePaymasterUserOp((address,uint256,bytes,bytes,bytes32,uint256,"
                "bytes32,bytes,bytes),bytes32,uint256)")


def _trace_validation(ctx: D2KChain, tx_hash: str, variant: str) -> Dict[str, Any]:
    pm = ctx.d2k.paymaster_for(variant).lower()
    verifier = ctx.frozen_b3.semaphore_verifier.lower()
    out: Dict[str, Any] = {"validate_frame_gas_used": None, "verify_proof_frame_gas_used": None,
                           "paymaster_slots_written": None}
    sel = "0x" + abi.selector(SIG_VALIDATE).hex()
    try:
        tr = ctx.chain.rpc.call("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    except Exception:
        return out

    def walk(fr: Dict[str, Any]) -> None:
        to = (fr.get("to") or "").lower()
        inp = fr.get("input") or ""
        if to == pm and inp.startswith(sel):
            out["validate_frame_gas_used"] = int(fr["gasUsed"], 16)
        if to == verifier:
            out["verify_proof_frame_gas_used"] = int(fr["gasUsed"], 16)
        for c in fr.get("calls") or []:
            walk(c)

    if isinstance(tr, dict):
        walk(tr)
    try:
        diff = ctx.chain.rpc.call("debug_traceTransaction", [
            tx_hash, {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}}])
        out["paymaster_slots_written"] = len((diff.get("post", {}).get(pm) or {})
                                             .get("storage", {}) or {})
    except Exception:
        pass
    return out
