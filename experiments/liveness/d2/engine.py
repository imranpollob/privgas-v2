"""The D2-A Spend state machine on a deterministic virtual clock.

Stages of one attempt (virtual seconds; ``Segments`` sets the controlled durations)::

    t0  root observed (witness = on-chain insertion order at t0)        client
    t1  proof generation begins            (t1 = t0)                    client
    t2  proof generation completes         (t0 + T_prove)               client
    t3  UserOperation received by bundler  (t2 + T_submit)              bundler (A2)
    t4  simulation begins                  (t3 + T_sim)                 bundler (A2)
    t5  simulation result                  (t4; eth_call is ~ms of wall time, recorded)
    t6  bundle constructed / queued        (t5)                         bundler (A2)
    t7  bundle transaction submitted       (t5 + T_queue)               bundler (A2)
    t8  on-chain validation                (t7 + T_chain)               chain (A0)
    t9  execution / inclusion or failure   (t8; same transaction)       chain (A0)

Root-changing Bootstraps ("arrivals") are REAL frozen-B3 Bootstraps executed on the chain
at their virtual time: every arrival with time <= a checkpoint is mined before the
checkpoint's chain action (simulation at t4, P1 re-simulation at t7, bundle broadcast at
t8 -- arrivals in (t7, t8) are mined in earlier blocks than the bundle; that ordering is a
modelling assumption, recorded). The witness is fixed at t0, so an arrival during proving
already makes the proof stale.

Bundler policies (experimental bundler behaviour, NOT protocol defenses):

* ``P0`` simulate once at t4, submit at t7.
* ``P1`` additionally re-simulate immediately before submission (state at t7).
* ``P2`` re-simulate after every observed root-changing transaction in (t5, t7]; the op is
  dropped at the first rejecting re-simulation (the client learns at that time).

A client learns of a failure when it is observed (t5 simulation rejection, the P1/P2
re-simulation time, or t8 for an on-chain failure) and, if retrying, starts the next
attempt then: fetch the latest root and members, re-prove, rebuild, re-sign (the
userOpHash excludes the proof, so the signature is unchanged -- checked), resubmit.
Every attempt is a separate record; nothing is discarded.

Classification (``outcome_class``) is computed from the ROOT TIMELINE and cross-checked
against the OBSERVED failure (``failure_observation``); a disagreement sets
``consistent = False`` (a D2 stop condition).
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .harness import D2Chain, HarnessInvariantViolation, Participant

POLICIES = ("P0", "P1", "P2")

VALID_PROOF_INCLUDED = "VALID_PROOF_INCLUDED"
STALE_BEFORE_SUBMISSION = "STALE_BEFORE_SUBMISSION"
STALE_BEFORE_SIMULATION = "STALE_BEFORE_SIMULATION"
VALID_AT_SIM_STALE_BEFORE_INCLUSION = "VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION"
OTHER_VALIDATION_FAILURE = "OTHER_VALIDATION_FAILURE"
EXECUTION_FAILURE = "EXECUTION_FAILURE"
PROOF_GENERATION_FAILURE = "PROOF_GENERATION_FAILURE"
BUNDLER_REJECTION_OTHER = "BUNDLER_REJECTION_OTHER"
HARNESS_CAPACITY_EXCEEDED = "HARNESS_CAPACITY_EXCEEDED"
OUTCOME_CLASSES = (VALID_PROOF_INCLUDED, STALE_BEFORE_SUBMISSION, STALE_BEFORE_SIMULATION,
                   VALID_AT_SIM_STALE_BEFORE_INCLUSION, OTHER_VALIDATION_FAILURE, EXECUTION_FAILURE,
                   PROOF_GENERATION_FAILURE, BUNDLER_REJECTION_OTHER, HARNESS_CAPACITY_EXCEEDED)
STALE_CLASSES = (STALE_BEFORE_SUBMISSION, STALE_BEFORE_SIMULATION, VALID_AT_SIM_STALE_BEFORE_INCLUSION)

OBS_NONE = "none"
OBS_SIM_ROOT = "SIMULATION_ROOT_MISMATCH"
OBS_RESIM_ROOT = "RESIMULATION_ROOT_MISMATCH"
OBS_ONCHAIN_ROOT = "ONCHAIN_ROOT_MISMATCH"
OBS_SIM_OTHER = "SIMULATION_OTHER"
OBS_ONCHAIN_OTHER = "ONCHAIN_OTHER_VALIDATION"
OBS_EXEC_REVERT = "EXECUTION_REVERT"

SEGMENT_NAMES = ("prove", "submit", "sim", "queue", "chain")


@dataclass(frozen=True)
class Segments:
    """Controlled virtual durations (seconds). ``prove=None`` = use the real measured proof
    generation time of that attempt's proof."""

    prove: Optional[float]
    submit: float
    sim: float
    queue: float
    chain: float

    @classmethod
    def split(cls, total: float, fractions: Dict[str, float]) -> "Segments":
        s = sum(fractions[k] for k in SEGMENT_NAMES)
        return cls(**{k: total * fractions[k] / s for k in SEGMENT_NAMES})

    def total(self, prove_s: float = 0.0) -> float:
        return (self.prove if self.prove is not None else prove_s) + self.submit + self.sim \
            + self.queue + self.chain


# --- arrivals -----------------------------------------------------------------------------------


@dataclass
class Arrival:
    time: float
    kind: str                   # "honest" | "adversary"
    executed: bool = False
    result: Optional[Dict[str, Any]] = None


class ArrivalProcess:
    """Root-changing Bootstrap arrivals: a lazily extended homogeneous Poisson process
    (rate ``lam`` per virtual second, seeded) plus explicitly inserted arrivals."""

    def __init__(self, lam: float, rng_seed: int, start: float = 0.0) -> None:
        self.lam = lam
        self.rng = np.random.default_rng(rng_seed)
        self._next_poisson = start + (self.rng.exponential(1.0 / lam) if lam > 0 else math.inf)
        self.pending: List[Arrival] = []
        self.history: List[Arrival] = []

    def insert(self, t: float, kind: str) -> None:
        self.pending.append(Arrival(t, kind))
        self.pending.sort(key=lambda a: a.time)

    def pop_next(self, t: float, strict: bool = False) -> Optional[Arrival]:
        """Pop only the EARLIEST arrival with time <= t (< t if strict), or None.

        P2 uses this: it reacts to one root-changing transaction at a time and stops when
        every pending operation has been dropped, so arrivals later than the drop time stay
        pending and are executed by the next attempt at their own virtual time. Popping a
        whole window at once would apply them to the chain before a retry that restarts
        earlier in virtual time."""
        due = self.due(t, strict)
        if not due:
            return None
        first, rest = due[0], due[1:]
        self.pending.extend(rest)
        self.pending.sort(key=lambda a: a.time)
        return first

    def due(self, t: float, strict: bool = False) -> List[Arrival]:
        """Pop every arrival with time <= t (< t if strict), in time order."""
        while self._next_poisson <= t:
            self.pending.append(Arrival(self._next_poisson, "honest"))
            self._next_poisson += self.rng.exponential(1.0 / self.lam)
        self.pending.sort(key=lambda a: a.time)
        out = [a for a in self.pending if (a.time < t if strict else a.time <= t)]
        self.pending = [a for a in self.pending if a not in out]
        return out


class ContenderPool:
    """Pre-announced issuers whose Bootstraps are the arrivals. Announcing happens in the
    chain's setup (before the trial snapshot); a trial needing more issuers than prepared
    fails as HARNESS_CAPACITY_EXCEEDED rather than being truncated."""

    def __init__(self, ctx: D2Chain, role: str, capacity: int, call_gas_limit: int) -> None:
        self.ctx, self.role, self.capacity, self.call_gas_limit = ctx, role, capacity, call_gas_limit
        self.used = 0
        for i in range(capacity):
            p = ctx.participant(role, i)
            ctx.announce(p)
            ctx.bootstrap_op(p, call_gas_limit)

    def reset(self) -> None:
        self.used = 0

    def execute(self, arrival: Arrival) -> Dict[str, Any]:
        if self.used >= self.capacity:
            raise CapacityExceeded(f"{self.role} capacity {self.capacity} exceeded")
        p = self.ctx.participant(self.role, self.used)
        self.used += 1
        calls = self.ctx.chain.rpc.calls
        dep_before = self.ctx.pm_deposit("bootstrap")
        out = self.ctx.bootstrap_now(p, self.call_gas_limit)
        out["sponsor_bootstrap_charge_wei"] = dep_before - self.ctx.pm_deposit("bootstrap")
        out["rpc_calls"] = self.ctx.chain.rpc.calls - calls
        out["virtual_time"] = arrival.time
        out["kind"] = arrival.kind
        arrival.executed, arrival.result = True, out
        return out


class CapacityExceeded(RuntimeError):
    pass


# --- engine ---------------------------------------------------------------------------------


@dataclass
class SpenderState:
    participant: Participant
    base_op: Any
    userop_hash: str
    done: bool = False
    attempts: int = 0
    success_time: Optional[float] = None
    prior_attempt_id: Optional[str] = None
    proofs_generated: int = 0


@dataclass
class TrialSpec:
    experiment: str
    trial_id: str
    seed: int
    n_initial: int
    lam: float
    segments: Segments
    policy: str
    max_attempts: int
    bundle_mode: str = "separate"          # "separate" single-op bundles | "joint" one bundle
    adversary_budget: int = 0              # A2 adversary: deposits right after a sim acceptance
    adversary_delay: float = 0.05
    meta: Dict[str, Any] = field(default_factory=dict)


class Trial:
    """Runs one cohort of spenders (M >= 1, sharing one timeline) to success or exhaustion."""

    def __init__(self, ctx: D2Chain, spec: TrialSpec, spenders: Sequence[SpenderState],
                 arrivals: ArrivalProcess, honest: ContenderPool,
                 adversary: Optional[ContenderPool] = None) -> None:
        if spec.policy not in POLICIES:
            raise ValueError(spec.policy)
        self.ctx, self.spec, self.spenders, self.arrivals = ctx, spec, list(spenders), arrivals
        self.honest, self.adversary = honest, adversary
        self.records: List[Dict[str, Any]] = []
        self.arrival_records: List[Dict[str, Any]] = []
        self.adversary_used = 0
        self.simulations = 0
        self.capacity_exceeded = False

    # -- arrivals --
    def _apply(self, t: float, strict: bool = False) -> List[Dict[str, Any]]:
        outs = []
        for a in self.arrivals.due(t, strict):
            pool = self.adversary if a.kind == "adversary" else self.honest
            out = pool.execute(a)
            self.arrival_records.append(out)
            outs.append(out)
        return outs

    def _root_changes_between(self, lo: float, hi: float, strict_hi: bool = False) -> List[float]:
        return [a["virtual_time"] for a in self.arrival_records if a["root_changed"]
                and lo < a["virtual_time"] and (a["virtual_time"] < hi if strict_hi
                                                else a["virtual_time"] <= hi)]

    # -- main --
    def run(self, start: float = 0.0) -> None:
        t = start
        try:
            while True:
                active = [s for s in self.spenders if not s.done
                          and s.attempts < self.spec.max_attempts]
                if not active:
                    return
                t = self._attempt(active, t)
        except CapacityExceeded as e:
            self.capacity_exceeded = True
            for s in self.spenders:
                if not s.done:
                    self.records.append(self._capacity_record(s, t, str(e)))

    def _capacity_record(self, s: SpenderState, t: float, msg: str) -> Dict[str, Any]:
        r = self._base_record(s, s.attempts + 1)
        r.update({"outcome_class": HARNESS_CAPACITY_EXCEEDED, "failure_observation": OBS_NONE,
                  "failure_stage": "harness", "t0": t, "consistent": True, "detail": msg,
                  "terminal": True})
        return r

    def _base_record(self, s: SpenderState, n: int) -> Dict[str, Any]:
        sp = self.spec
        return {"experiment": sp.experiment, "trial_id": sp.trial_id, "seed": sp.seed,
                "n_initial": sp.n_initial, "lambda": sp.lam,
                "T_total": sp.segments.total() if sp.segments.prove is not None else None,
                "segments": asdict(sp.segments), "policy": sp.policy,
                "bundle_mode": sp.bundle_mode, "cohort_size": len(self.spenders),
                "spender": f"{s.participant.role}/{s.participant.index}",
                "attempt_id": f"{sp.trial_id}/{s.participant.index}/a{n}", "retry_number": n - 1,
                "prior_attempt_id": s.prior_attempt_id, **sp.meta}

    def _attempt(self, cohort: List[SpenderState], t: float) -> float:
        ctx, seg, pol = self.ctx, self.spec.segments, self.spec.policy
        self._apply(t)
        t0 = t
        st0 = ctx.state_point()
        recs: Dict[int, Dict[str, Any]] = {}
        proofs = {}
        prove_s = 0.0
        for s in cohort:
            s.attempts += 1
            r = self._base_record(s, s.attempts)
            r.update({"t0": t0, "t1": t0, "root_observed": st0["root"],
                      "tree_size_observed": st0["tree_size"], "block_at_t0": st0["block_number"],
                      "block_timestamp_at_t0": st0["block_timestamp"],
                      "reproved": s.attempts > 1})
            calls = ctx.chain.rpc.calls
            wall = time.perf_counter()
            try:
                pr = ctx.prove_for(s.participant, s.userop_hash)
            except HarnessInvariantViolation:
                raise
            except Exception as e:  # prover failure is an outcome, not a crash
                r.update({"outcome_class": PROOF_GENERATION_FAILURE, "failure_observation": OBS_NONE,
                          "failure_stage": "proof_generation", "detail": str(e)[:300],
                          "consistent": True, "terminal": True})
                s.done = True
                self.records.append(r)
                continue
            if not pr.cache_hit:
                s.proofs_generated += 1
            op = ctx.with_proof(s.base_op, s.userop_hash, pr)
            # the account signature covers userOpHash, which excludes the proof: re-signing a
            # retry yields the identical signature (checked, not assumed)
            if op.signature != s.base_op.signature:
                raise HarnessInvariantViolation("re-signing changed the account signature")
            r.update({"proof_root": str(pr.root), "proof_tree_size": pr.group_size,
                      "proof_depth": pr.depth, "proof_generation_ms": pr.prove_ms,
                      "proof_verify_off_chain_ms": pr.verify_off_chain_ms,
                      "local_verification_ok": True, "proof_cache_hit": pr.cache_hit,
                      "client_wall_ms": (time.perf_counter() - wall) * 1000,
                      "proof_root_equals_observed_root": str(pr.root) == st0["root"]})
            if str(pr.root) != st0["root"]:
                raise HarnessInvariantViolation("STOP: proof root differs from the recorded root")
            prove_s = max(prove_s, seg.prove if seg.prove is not None else pr.prove_ms / 1000)
            proofs[id(s)] = (op, r, calls)
            recs[id(s)] = r
        cohort = [s for s in cohort if id(s) in proofs]
        if not cohort:
            return t0
        t2 = t0 + prove_s
        self._apply(t2)
        st2 = ctx.state_point()
        t3 = t2 + seg.submit
        self._apply(t3)
        st3 = ctx.state_point()
        t4 = t3 + seg.sim
        self._apply(t4)
        st4 = ctx.state_point()
        accepted: List[SpenderState] = []
        for s in cohort:
            op, r, _ = proofs[id(s)]
            sim = ctx.bundler.simulate([op])
            self.simulations += 1
            r.update({"t2": t2, "root_at_proof_complete": st2["root"], "t3": t3,
                      "root_at_submission": st3["root"], "tree_size_at_submission": st3["tree_size"],
                      "t4": t4, "t5": t4, "root_at_simulation": st4["root"],
                      "block_at_simulation": st4["block_number"],
                      "simulation_result": "accepted" if sim.accepted else "rejected",
                      "simulation_reason": sim.reason, "simulation_inner_error": sim.inner_error,
                      "simulation_wall_ms": sim.wall_ms, "simulations": 1})
            if sim.accepted:
                accepted.append(s)
                continue
            first = self._root_changes_between(t0, t4)
            root_obs = sim.inner_error == "RootMismatch"
            if root_obs:
                cls = (STALE_BEFORE_SUBMISSION if first and first[0] <= t3
                       else STALE_BEFORE_SIMULATION if first else None)
                stored_ok = sim.inner_args and str(sim.inner_args[1]) == st4["root"]
                r.update({"outcome_class": cls or OTHER_VALIDATION_FAILURE,
                          "failure_observation": OBS_SIM_ROOT, "failure_stage": "simulation",
                          "consistent": bool(first) and bool(stored_ok)})
            else:
                r.update({"outcome_class": BUNDLER_REJECTION_OTHER if sim.error not in (
                    "FailedOp", "FailedOpWithRevert") else OTHER_VALIDATION_FAILURE,
                          "failure_observation": OBS_SIM_OTHER, "failure_stage": "simulation",
                          "consistent": not first})
            self._close(s, r, t4, first, recs)
        if not accepted:
            return t4
        t5 = t4
        # A2 adversary: observes the simulation acceptance and immediately deposits.
        if self.adversary is not None and self.adversary_used < self.spec.adversary_budget:
            self.arrivals.insert(t5 + self.spec.adversary_delay, "adversary")
            self.adversary_used += 1
        t7 = t5 + seg.queue
        for s in accepted:
            proofs[id(s)][1].update({"t6": t5, "t7": t7})
        dropped_at: Dict[int, float] = {}
        resims: Dict[int, List[str]] = {id(s): [] for s in accepted}
        if pol == "P0":
            self._apply(t7)
        elif pol == "P1":
            self._apply(t7)
            for s in accepted:
                op, r, _ = proofs[id(s)]
                sim = ctx.bundler.simulate([op])
                self.simulations += 1
                r["simulations"] += 1
                resims[id(s)].append("accepted" if sim.accepted else (sim.inner_error or sim.reason))
                if not sim.accepted:
                    dropped_at[id(s)] = t7
                    self._fail_resim(s, r, sim, t0, t5, t7, recs)
        else:  # P2
            while len(dropped_at) < len(accepted):
                a = self.arrivals.pop_next(t7)
                if a is None:
                    break
                pool = self.adversary if a.kind == "adversary" else self.honest
                out = pool.execute(a)
                self.arrival_records.append(out)
                if not out["root_changed"]:
                    continue
                for s in accepted:
                    if id(s) in dropped_at:
                        continue
                    op, r, _ = proofs[id(s)]
                    sim = ctx.bundler.simulate([op])
                    self.simulations += 1
                    r["simulations"] += 1
                    resims[id(s)].append("accepted" if sim.accepted else (sim.inner_error or sim.reason))
                    if not sim.accepted:
                        dropped_at[id(s)] = a.time
                        self._fail_resim(s, r, sim, t0, t5, a.time, recs)
        for s in accepted:
            proofs[id(s)][1]["resimulation_results"] = resims[id(s)]
        survivors = [s for s in accepted if id(s) not in dropped_at]
        next_t = max([t4] + list(dropped_at.values()))
        if not survivors:
            return next_t
        st7 = ctx.state_point()
        t8 = t7 + seg.chain
        self._apply(t8, strict=True)
        st8 = ctx.state_point()
        groups = ([[s] for s in survivors] if self.spec.bundle_mode == "separate" else [survivors])
        for g in groups:
            ops = [proofs[id(s)][0] for s in g]
            credit_before = ctx.pm_deposit("credit")
            res = ctx.bundler.submit(ops, label="d2_spend")
            credit_charge = credit_before - ctx.pm_deposit("credit")
            ev_by_hash = {e["userop_hash"]: e for e in res.userop_events}
            for s in g:
                op, r, _ = proofs[id(s)]
                ev = ev_by_hash.get(s.userop_hash)
                r.update({"t7": t7, "root_at_bundle_submission": st7["root"], "t8": t8, "t9": t8,
                          "root_at_inclusion": st8["root"], "block_at_inclusion": res.block_number,
                          "block_timestamp_at_inclusion": res.block_timestamp,
                          "bundle_tx_hash": res.tx_hash, "bundle_size": len(g),
                          "onchain_status": res.status, "bundle_gas_used": res.gas_used,
                          "bundle_fee_wei": res.fee_wei // len(g),
                          "beneficiary_compensation_wei": res.beneficiary_compensation_wei // len(g),
                          "bundle_fee_wei_total": res.fee_wei,
                          "bundle_compensation_wei_total": res.beneficiary_compensation_wei,
                          "sponsor_credit_charge_wei": (ev["actual_gas_cost"] if ev else 0),
                          "sponsor_credit_charge_bundle_wei": credit_charge,
                          "userop_success": ev["success"] if ev else None,
                          "actual_gas_used": ev["actual_gas_used"] if ev else None,
                          "submission_wall_ms": res.wall_ms})
                first = self._root_changes_between(t0, t8, strict_hi=True)
                if res.status == 1 and ev and ev["success"]:
                    r.update({"outcome_class": VALID_PROOF_INCLUDED, "failure_observation": OBS_NONE,
                              "failure_stage": None, "consistent": not first})
                    s.done = True
                    s.success_time = t8
                    r["terminal"] = True
                    r["time_to_success"] = t8
                    self.records.append(r)
                    continue
                if res.status == 1 and ev and not ev["success"]:
                    r.update({"outcome_class": EXECUTION_FAILURE, "failure_observation": OBS_EXEC_REVERT,
                              "failure_stage": "execution", "consistent": True})
                    s.done = True
                    r["terminal"] = True
                    self.records.append(r)
                    continue
                rv = res.revert
                r.update({"onchain_revert_reason": rv.reason if rv else None,
                          "onchain_revert_inner_error": rv.inner_error if rv else None,
                          "onchain_revert_op_index": rv.op_index if rv else None,
                          "trace_revert_inner_error": (res.trace_revert or {}).get("inner_error"),
                          "bundler_loss_wei": res.fee_wei - res.beneficiary_compensation_wei})
                bundle_root_fail = rv is not None and rv.inner_error == "RootMismatch"
                if bundle_root_fail:
                    stale_self = str(r["proof_root"]) != st8["root"]
                    r.update({"outcome_class": (VALID_AT_SIM_STALE_BEFORE_INCLUSION if stale_self
                                                else OTHER_VALIDATION_FAILURE),
                              "failure_observation": OBS_ONCHAIN_ROOT, "failure_stage": "onchain",
                              "failed_by_other_op_in_bundle": not stale_self,
                              "consistent": (bool(first) and first[0] > t4) if stale_self else True})
                else:
                    r.update({"outcome_class": OTHER_VALIDATION_FAILURE,
                              "failure_observation": OBS_ONCHAIN_OTHER, "failure_stage": "onchain",
                              "consistent": not first})
                self._close(s, r, t8, first, recs)
            next_t = max(next_t, t8)
        return next_t

    def _fail_resim(self, s: SpenderState, r: Dict[str, Any], sim, t0: float, t5: float,
                    at: float, recs) -> None:
        first = self._root_changes_between(t0, at)
        root_obs = sim.inner_error == "RootMismatch"
        r.update({"outcome_class": VALID_AT_SIM_STALE_BEFORE_INCLUSION if root_obs
                  else OTHER_VALIDATION_FAILURE,
                  "failure_observation": OBS_RESIM_ROOT if root_obs else OBS_SIM_OTHER,
                  "failure_stage": "resimulation", "dropped_at": at,
                  "consistent": (bool(first) and first[0] > t5) if root_obs else not first})
        self._close(s, r, at, first, recs)

    def _close(self, s: SpenderState, r: Dict[str, Any], t_fail: float, first: List[float],
               recs) -> None:
        onset = None
        if first:
            tau = first[0]
            for name, lo_key, hi_key in (("prove", "t0", "t2"), ("submit", "t2", "t3"),
                                         ("sim", "t3", "t4"), ("queue", "t5", "t7"),
                                         ("chain", "t7", "t8")):
                lo, hi = r.get(lo_key), r.get(hi_key)
                if lo is not None and hi is not None and lo < tau <= hi:
                    onset = name
                    break
            else:
                onset = "queue" if r.get("t5") is not None and tau > r["t5"] else "unknown"
        r.update({"stale_onset_segment": onset, "root_change_count": len(first),
                  "failure_observed_at": t_fail})
        terminal_other = r["outcome_class"] not in STALE_CLASSES
        exhausted = s.attempts >= self.spec.max_attempts
        r["terminal"] = terminal_other or exhausted
        if terminal_other:
            s.done = True
        s.prior_attempt_id = r["attempt_id"]
        self.records.append(r)
