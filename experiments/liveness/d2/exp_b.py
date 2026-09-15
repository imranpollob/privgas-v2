"""D2-B: CreditPool.deposit / Bootstrap gas growth, the frozen call-gas limit, and fee caps.

Kept separate from root contention (D2-A). Three measurements per seed:

1. ``growth``: grow the tree one real Bootstrap at a time with an EXPERIMENTAL high
   ``callGasLimit`` (never reported as the frozen baseline). Before each insertion at tree
   size s, inside a snapshot that is then reverted:
     a. the same participant's Bootstrap with the FROZEN ``callGasLimit`` from
        b3-eval-config.json (outcome, failure class, gas), and
     b. the minimal ``callGasLimit`` with which the Bootstrap inserts (binary search over
        real inclusions),
   then the real insertion with the high limit, traced: ``CreditPool.deposit`` frame gas
   (callTracer), PoseidonT3 hash calls, new CreditPool storage slots (prestateTracer diff).
2. ``natural``: a fresh chain where every issuer uses the frozen limit, in sequence, with no
   high-limit help: where the first failure occurs and what it leaves behind (sponsored
   grant consumed, no deposit, tree stuck).
3. ``fee_envelope``: for selected tree sizes and a grid of maxFeePerGas, simulate the
   Bootstrap (frozen / minimal-required / high limit) and, at one pool size, a real-proof
   Spend, against the frozen Paymaster caps; plus the analytical p_max = cap / gas limits.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ...workloads.w1 import abi, b3
from ...workloads.w1.prover import group_depth
from .harness import D2Chain, HarnessInvariantViolation

GWEI = 10 ** 9


def _trace_deposit(ctx: D2Chain, tx_hash: str) -> Dict[str, Any]:
    pool = ctx.env.b3.credit_pool.lower()
    poseidon = ctx.env.b3.poseidon_t3.lower()
    out: Dict[str, Any] = {"deposit_frame_gas_used": None, "poseidon_calls": 0,
                           "mirror_root_frame_gas_used": None, "trace_available": False}
    try:
        tr = ctx.chain.rpc.call("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    except Exception:
        return out

    def walk(fr: Dict[str, Any]) -> None:
        to = (fr.get("to") or "").lower()
        inp = fr.get("input") or ""
        if to == pool and inp.startswith("0x" + abi.selector(b3.SIG_POOL_DEPOSIT).hex()):
            out["deposit_frame_gas_used"] = int(fr["gasUsed"], 16)
            out["trace_available"] = True
        if to == poseidon:
            out["poseidon_calls"] += 1
        if to == ctx.env.b3.credit_paymaster.lower() and inp.startswith(
                "0x" + abi.selector("mirrorRoot(uint256)").hex()):
            out["mirror_root_frame_gas_used"] = int(fr["gasUsed"], 16)
        for c in fr.get("calls") or []:
            walk(c)

    if isinstance(tr, dict) and "calls" in tr:
        walk(tr)
    try:
        diff = ctx.chain.rpc.call("debug_traceTransaction", [
            tx_hash, {"tracer": "prestateTracer", "tracerConfig": {"diffMode": True}}])
        pre = (diff.get("pre", {}).get(pool) or {}).get("storage", {}) or {}
        post = (diff.get("post", {}).get(pool) or {}).get("storage", {}) or {}
        new_slots = [k for k, v in post.items() if int(v, 16) != 0 and int(pre.get(k, "0x0"), 16) == 0]
        changed = [k for k, v in post.items() if k in pre and int(pre[k], 16) != 0]
        out.update({"pool_storage_slots_new_nonzero": len(new_slots),
                    "pool_storage_slots_modified_nonzero": len(changed),
                    "pool_storage_slots_written": len(post)})
    except Exception:
        pass
    return out


def _attempt_bootstrap(ctx: D2Chain, p, limit: int, max_fee: Optional[int] = None) -> Dict[str, Any]:
    """Simulate and (if accepted) include ``p``'s Bootstrap with ``limit``. Records the frozen
    Paymaster's verdict, execution success and gas, without appending to members."""
    op = ctx.bootstrap_op(p, limit, max_fee)
    before_root, size = ctx.root(), ctx.tree_size()
    dep0 = ctx.pm_deposit("bootstrap")
    sim = ctx.bundler.simulate([op])
    r: Dict[str, Any] = {"call_gas_limit": limit, "max_fee_per_gas": op.max_fee_per_gas,
                         "required_prefund_wei": op.required_prefund,
                         "pre_verification_gas": op.pre_verification_gas,
                         "verification_gas_limit": op.verification_gas_limit,
                         "paymaster_verification_gas_limit": op.paymaster_verification_gas_limit,
                         "tree_size_before": size, "sim_accepted": sim.accepted,
                         "sim_reason": sim.reason, "sim_inner_error": sim.inner_error}
    if not sim.accepted:
        r["failure_class"] = ("PAYMASTER_VALIDATION_" + (sim.inner_error or "SIG_VALIDATION_FAILED")
                              if sim.reason and sim.reason.startswith("AA3") else
                              f"VALIDATION_{sim.reason}")
        return r
    res = ctx.bundler.submit([op], label="d2b_bootstrap")
    ev = res.userop_events[0] if res.userop_events else None
    rr = [l for l in ctx.chain.sent[-1].receipt["logs"]
          if l["topics"] and l["topics"][0] == abi.T_USEROP_REVERT_REASON]
    after_root = ctx.root()
    r.update({"included": res.status == 1, "tx_hash": res.tx_hash, "bundle_gas_used": res.gas_used,
              "execution_success": bool(ev and ev["success"]),
              "actual_gas_used": ev["actual_gas_used"] if ev else None,
              "actual_gas_cost_wei": ev["actual_gas_cost"] if ev else None,
              "paymaster_charge_wei": dep0 - ctx.pm_deposit("bootstrap"),
              "bundler_fee_wei": res.fee_wei,
              "beneficiary_compensation_wei": res.beneficiary_compensation_wei,
              "root_changed": after_root != before_root, "root_after": str(after_root),
              "tree_size_after": ctx.tree_size(), "revert_reason_logged": bool(rr),
              "grant_consumed": bool(b3.view_uint(ctx.chain, ctx.env.b3.bootstrap_paymaster,
                                                  b3.SIG_BPM_IS_USED, ("address",), (p.account,))),
              "has_deposited": bool(b3.view_uint(ctx.chain, ctx.env.b3.credit_pool,
                                                 b3.SIG_POOL_HAS_DEPOSITED, ("address",), (p.account,)))})
    if ev and not ev["success"]:
        inner = _execution_revert(ctx, res.tx_hash)
        r["failure_class"] = "EXECUTION_REVERT_" + inner
    elif res.status != 1:
        r["failure_class"] = "BUNDLE_REVERT"
    else:
        r["failure_class"] = None
    return r


def _execution_revert(ctx: D2Chain, tx_hash: str) -> str:
    """Why the Bootstrap's execution frame failed (from the call trace)."""
    try:
        tr = ctx.chain.rpc.call("debug_traceTransaction", [tx_hash, {"tracer": "callTracer"}])
    except Exception:
        return "UNKNOWN"
    pool = ctx.env.b3.credit_pool.lower()
    found = {"err": None}

    def walk(fr):
        if (fr.get("to") or "").lower() == pool and fr.get("error"):
            found["err"] = fr["error"]
        for c in fr.get("calls") or []:
            walk(c)

    walk(tr)
    e = (found["err"] or "UNKNOWN").upper().replace(" ", "_")
    return "OUT_OF_GAS" if "OUT_OF_GAS" in e or "OUTOFGAS" in e else e


def _min_required_limit(ctx: D2Chain, p, low: int, high: int, tol: int):
    """Smallest callGasLimit (within ``tol``) whose Bootstrap inserts; every probe is a real
    inclusion inside a reverted snapshot. Returns (limit, outcome at that limit)."""
    last: Dict[int, Dict[str, Any]] = {}

    def ok(limit: int) -> bool:
        snap = ctx.snapshot()
        try:
            r = _attempt_bootstrap(ctx, p, limit)
            last[limit] = r
            return bool(r.get("root_changed"))
        finally:
            ctx.revert(snap)
            p.bootstrap_ops.pop((limit, ctx.cfg.max_fee), None)

    if not ok(high):
        return None, None
    lo, hi = low, high
    while hi - lo > tol:
        mid = (lo + hi) // 2
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi, last[hi]


def run_growth(seed: int, d2cfg: Dict[str, Any], root=None, log=print) -> Dict[str, Any]:
    b = d2cfg["d2b"]
    rows: List[Dict[str, Any]] = []
    frozen = None
    with D2Chain(seed, d2cfg, root) as ctx:
        frozen = ctx.b3cfg.userop("bootstrap_call_gas_limit")
        high = int(b["high_call_gas_limit"])
        search = b["required_limit_search"]
        started = time.time()
        for s in range(int(b["max_tree_size"])):
            p = ctx.participant("member", s)
            ctx.announce(p)
            if ctx.tree_size() != s:
                raise HarnessInvariantViolation(f"tree size {ctx.tree_size()} != {s}")
            snap = ctx.snapshot()
            try:
                orig = _attempt_bootstrap(ctx, p, frozen)
            finally:
                ctx.revert(snap)
            req, at_req = _min_required_limit(ctx, p, int(search["low"]), int(search["high"]),
                                              int(search["tolerance"]))
            real = _attempt_bootstrap(ctx, p, high)
            if not real.get("root_changed"):
                raise HarnessInvariantViolation(f"high-limit insertion failed at size {s}: {real}")
            ctx.members.append(p.commitment)
            tr = _trace_deposit(ctx, real["tx_hash"])
            rows.append({
                "seed": seed, "tree_size_before": s, "tree_size_after": s + 1,
                "leanimt_depth_after": max(0, s).bit_length() if s else 0,
                "semaphore_proof_depth_after": group_depth(s + 1),
                "high_call_gas_limit": high, "frozen_call_gas_limit": frozen,
                **{f"high_{k}": v for k, v in real.items() if k not in ("tx_hash",)},
                **tr,
                **{f"frozen_{k}": v for k, v in orig.items()},
                "min_required_call_gas_limit": req,
                **{f"minreq_{k}": v for k, v in (at_req or {}).items()
                   if k in ("actual_gas_used", "paymaster_charge_wei", "required_prefund_wei",
                            "bundle_gas_used", "pre_verification_gas")},
                "frozen_limit_margin_gas": (frozen - req) if req else None,
                "root": real["root_after"],
            })
            if s in (0, 1, 3, 7, 15, 31, 63, 127, 255):
                log(f"  d2b seed {seed} size {s}: deposit frame {tr['deposit_frame_gas_used']} "
                    f"req limit {req} frozen ok {orig.get('root_changed')} ({time.time() - started:.0f}s)")
        # tree check at the end (off-chain group vs both roots)
        g = ctx.prover.group_root(ctx.members)
        roots_ok = g["root"] == ctx.root() == ctx.pool_root()
        env = {"anvil_version": ctx.anvil_version, "contracts": ctx.env.contracts()}
    return {"rows": rows, "final_root_check": roots_ok, "frozen_call_gas_limit": frozen,
            "environment": env}


def run_natural(seed: int, d2cfg: Dict[str, Any], root=None) -> Dict[str, Any]:
    """Every issuer uses the frozen Bootstrap callGasLimit; no high-limit help."""
    n = int(d2cfg["d2b"]["natural_sequence_attempts"])
    rows = []
    with D2Chain(seed, d2cfg, root) as ctx:
        frozen = ctx.b3cfg.userop("bootstrap_call_gas_limit")
        for i in range(n):
            p = ctx.participant("natural", i)
            ctx.announce(p)
            r = _attempt_bootstrap(ctx, p, frozen)
            r.update({"seed": seed, "attempt": i})
            rows.append(r)
    return {"rows": rows, "frozen_call_gas_limit": frozen}


def run_fee_envelope(seed: int, d2cfg: Dict[str, Any], growth_rows: List[Dict[str, Any]],
                     root=None) -> Dict[str, Any]:
    b = d2cfg["d2b"]
    sizes = sorted(int(x) for x in b["fee_grid_sizes"])
    fees = [int(g) * GWEI for g in b["fee_grid_gwei"]]
    req_by_size = {r["tree_size_before"]: r["min_required_call_gas_limit"] for r in growth_rows}
    out_boot, out_spend = [], []
    with D2Chain(seed, d2cfg, root) as ctx:
        frozen = ctx.b3cfg.userop("bootstrap_call_gas_limit")
        high = int(b["high_call_gas_limit"])
        for s in range(max(sizes) + 1):
            if s in sizes or s == max(sizes):
                p = ctx.participant("member", s)
                ctx.announce(p)
                limits = {"frozen": frozen, "high": high}
                if req_by_size.get(s):
                    limits["min_required"] = req_by_size[s]
                for lname, limit in limits.items():
                    for fee in fees:
                        op = ctx.bootstrap_op(p, limit, fee)
                        sim = ctx.bundler.simulate([op])
                        out_boot.append({"seed": seed, "tree_size_before": s, "limit_kind": lname,
                                         "call_gas_limit": limit, "max_fee_gwei": fee / GWEI,
                                         "required_prefund_wei": op.required_prefund,
                                         "gas_limits_sum": op.required_prefund // fee,
                                         "sim_accepted": sim.accepted, "sim_reason": sim.reason,
                                         "sim_inner_error": sim.inner_error})
            if s == max(sizes):
                break
            p = ctx.participant("member", s)
            ctx.announce(p)
            res = ctx.bootstrap_now(p, high)
            if not res["root_changed"]:
                raise HarnessInvariantViolation(f"fee-envelope pool growth failed at {s}")
        # Spend at one pool size (tree is currently max size; use a fresh chain for the
        # configured Spend pool size so the proof depth matches the pinned artifacts)
    with D2Chain(seed, d2cfg, root) as ctx:
        n = int(b["spend_fee_grid_pool_size"])
        ctx.build_pool(n, high)
        sp = ctx.participant("member", 0)
        ctx.give_tokens(sp)
        for fee in fees:
            op, h = ctx.spend_op(sp, fee)
            pr = ctx.prove_for(sp, h)
            op2 = ctx.with_proof(op, h, pr)
            sim = ctx.bundler.simulate([op2])
            out_spend.append({"seed": seed, "pool_size": n, "max_fee_gwei": fee / GWEI,
                              "required_prefund_wei": op2.required_prefund,
                              "gas_limits_sum": op2.required_prefund // fee,
                              "call_plus_verification_gas": op2.call_gas_limit + op2.verification_gas_limit,
                              "sim_accepted": sim.accepted, "sim_reason": sim.reason,
                              "sim_inner_error": sim.inner_error})
    return {"bootstrap": out_boot, "spend": out_spend}
