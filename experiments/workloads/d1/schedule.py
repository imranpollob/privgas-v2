"""Seeded event schedules for the D1 multi-actor pilot.

A schedule is a list of events ``(time, phase, slot)`` executed in time order.
``slot`` is the PRIVATE actor generation index; the schedule is written only to
``data/private``. Public observers see the resulting block order and block
timestamps, nothing else.

Phases (``PHASES``), per baseline:

====================  =====================================================  ============
phase                 what happens                                           baselines
====================  =====================================================  ============
``setup``             faucet ETH + treasury W1T to the actor's asset sender  all
``deliver``           asset sender -> ``W1Token.transfer(account, amount)``   all
``prepare``           OFF CHAIN: the wallet builds and signs the application all AA
                      operation (B3: generates the Semaphore proof)
``fund``              B0/B1: ETH to the recipient; B2-Allowlist:             not B2-Sig
                      ``setSponsored``; B3: ``announceAndFund``; B4: the
                      issuer funder's ``announceAndFund`` for the ISSUER
``issue``             B3/B4: Bootstrap operation (CreditPool deposit; B4:     B3, B4
                      sent by the issuer account)
``act``               the W1 application action                               all
====================  =====================================================  ============

Ordering constraints that every schedule satisfies (asserted):
deliver_k < act_k; fund_k < act_k; fund_k < issue_k (B3); for B1 prepare_k <
fund_k (the prefund depends on the prepared operation); for B3 every issue
precedes every prepare and every act (all Spend proofs use the SAME final root:
the clean single-root schedule; spends never change the root).

S0-clean-shuffled
    every phase has its own independent uniformly random permutation and its
    own independent exponential gaps; phases are sequential, separated by
    ``phase_gap``. Nothing is a function of the slot or of another phase.

B4-CrossAccount uses exactly B3's phases, streams and constraints (so B3 and B4 at
one (seed, pool size, scenario) have IDENTICAL schedules: a paired comparison).
Its only addition is ``orders["setup_issuer"]``, the order in which the faucet
funds the issuer funders during setup, drawn from its own stream in both
scenarios (never the arrival order): the issuer side and the spender side of an
actor are joined by nothing in the scheduler except the private slot.

S1b-issuance-redemption-timing-only
    ONLY issuance and redemption timing are correlated, with exactly S1's model
    (issuance k at arrival A_k with exponential inter-arrivals; action at
    A_k + common offset + U(-jitter, +jitter)), so action order follows issuance
    order up to local swaps. Every other order is its own independent
    permutation with its own exponential gaps, in sequential phases before the
    issuances: asset-sender setup, issuer-funder setup (B4), asset delivery,
    admission (announceAndFund); proof preparation is an independent order after
    the last issuance. Account creation is not separable: the issuer account is
    deployed by its Bootstrap (issuance timing) and the B4 spender account by its
    Spend (redemption timing).

S1-correlated-timing
    one random arrival order drives every phase (a natural "each user arrives,
    is paid, bootstraps, and later spends" pattern), with actions after a common
    offset plus bounded jitter -- so action order follows issuance order up to
    local swaps. Used to measure how much timing alone degrades R2.

Randomness: a SHA-256 counter-mode stream per (seed, pool size, scenario,
component); permutations sort by 64-bit stream keys and exponential gaps use
the inverse CDF, so schedules do not depend on the Python ``random`` module.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

SCENARIOS = ("S0-clean-shuffled", "S1-correlated-timing", "S1b-issuance-redemption-timing-only")
S1B = "S1b-issuance-redemption-timing-only"
#: S1b: the only intended correlation. Every other pair of orders must be independent
#: (checked per run by ``s1b_unintended_exposure`` and per batch by the evaluation gate).
S1B_INTENDED_PAIR = ("issue", "act")
PHASES = ("setup", "deliver", "prepare", "fund", "issue", "act")
ONCHAIN_PHASES = ("deliver", "fund", "issue", "act")
B3 = "B3-PrivGas-v1"
B4 = "B4-CrossAccount"
CREDIT = (B3, B4)


def phases_for(baseline_id: str) -> Tuple[str, ...]:
    if baseline_id == "B0":
        return ("setup", "deliver", "fund", "act")
    if baseline_id == "B2-Signature":
        return ("setup", "deliver", "prepare", "act")
    if baseline_id in ("B1", "B2-Allowlist"):
        return ("setup", "deliver", "prepare", "fund", "act")
    if baseline_id in CREDIT:
        return ("setup", "deliver", "fund", "issue", "prepare", "act")
    raise ValueError(f"no D1 pilot schedule for baseline {baseline_id!r}")


class Stream:
    """Deterministic SHA-256 counter-mode stream."""

    def __init__(self, *key: Any) -> None:
        self._key = "/".join(str(k) for k in ("privgas-v2/d1/schedule/v1", *key))
        self._n = 0

    def u64(self) -> int:
        d = hashlib.sha256(f"{self._key}/{self._n}".encode()).digest()
        self._n += 1
        return int.from_bytes(d[:8], "big")

    def uniform(self) -> float:
        """Uniform on (0, 1)."""
        return (self.u64() + 0.5) / 2 ** 64

    def exponential(self, mean: float) -> float:
        return -mean * math.log(self.uniform())

    def permutation(self, n: int) -> List[int]:
        keys = [(self.u64(), i) for i in range(n)]
        return [i for _, i in sorted(keys)]


@dataclass(frozen=True)
class Event:
    time: int
    phase: str
    slot: int


@dataclass
class Schedule:
    scenario_id: str
    baseline_id: str
    pool_size: int
    #: phase -> slots in the order that phase executes them (PRIVATE)
    orders: Dict[str, List[int]]
    events: List[Event]
    #: private per-event delays, for the record
    delays: Dict[str, Any] = field(default_factory=dict)

    def times(self, phase: str) -> Dict[int, int]:
        return {e.slot: e.time for e in self.events if e.phase == phase}

    def as_private_dict(self) -> Dict[str, Any]:
        return {"scenario_id": self.scenario_id, "baseline_id": self.baseline_id,
                "pool_size": self.pool_size, "orders": self.orders,
                "events": [[e.time, e.phase, e.slot] for e in self.events],
                "delays": self.delays}


def make_schedule(seed: int, pool_size: int, scenario_id: str, baseline_id: str,
                  params: Mapping[str, Any], start_time: int) -> Schedule:
    """``start_time``: chain time at which the workflow (after setup) begins."""
    if scenario_id not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario_id!r}")
    if scenario_id == S1B and baseline_id not in CREDIT:
        raise ValueError("S1b correlates credit issuance with redemption; it is defined only for "
                         "the credit baselines")
    phases = phases_for(baseline_id)
    n = pool_size
    gap = int(params["phase_gap"])

    def stream(component: str) -> Stream:
        # Deliberately independent of the baseline: matched baselines at one
        # (seed, pool size, scenario) share every order they have in common.
        return Stream(seed, pool_size, scenario_id, component)

    orders: Dict[str, List[int]] = {}
    events: List[Event] = []
    delays: Dict[str, Any] = {}

    if scenario_id == "S0-clean-shuffled":
        mean = float(params[scenario_id]["mean_gap"])
        for p in phases:
            orders[p] = stream(f"order/{p}").permutation(n)
        t = float(start_time)
        g = stream("gaps")
        for p in phases:
            if p == "setup":
                continue  # setup runs at fixed block intervals before start_time
            gaps = []
            for slot in orders[p]:
                d = g.exponential(mean)
                gaps.append(d)
                t += d
                events.append(Event(int(round(t)), p, slot))
            delays[p] = gaps
            t += gap
    elif scenario_id == S1B:
        p1 = params[scenario_id]
        mean = float(p1["mean_gap"])
        for p in phases:
            if p not in ("issue", "act"):
                orders[p] = stream(f"order/{p}").permutation(n)
        t = float(start_time)
        g = stream("gaps")
        for p in ("deliver", "fund"):
            if p not in phases:
                continue
            for slot in orders[p]:
                t += g.exponential(mean)
                events.append(Event(int(round(t)), p, slot))
            t += gap
        order = stream("order/arrival").permutation(n)
        orders["issue"] = list(order)
        a = stream("arrivals")
        arrivals: Dict[int, float] = {}
        for slot in order:
            t += a.exponential(float(p1["mean_interarrival"]))
            arrivals[slot] = t
            events.append(Event(int(round(t)), "issue", slot))
        action_offset = (arrivals[order[-1]] - arrivals[order[0]]) + gap
        j = stream("jitter")
        jitter = float(p1["action_jitter"])
        acts = {}
        for slot in order:
            acts[slot] = arrivals[slot] + action_offset + (2 * j.uniform() - 1) * jitter
            events.append(Event(int(round(acts[slot])), "act", slot))
        orders["act"] = sorted(order, key=lambda s: (acts[s], order.index(s)))
        delays = {"arrivals": {str(s): arrivals[s] for s in order},
                  "action_times": {str(s): acts[s] for s in order},
                  "action_offset": action_offset}
        if "prepare" in phases:
            anchor = max(arrivals.values()) + 1
            for slot in orders["prepare"]:
                events.append(Event(int(round(anchor)), "prepare", slot))
    else:
        p1 = params[scenario_id]
        order = stream("order/arrival").permutation(n)
        for p in phases:
            orders[p] = list(order)
        g = stream("arrivals")
        arrivals: Dict[int, float] = {}
        t = float(start_time)
        for slot in order:
            t += g.exponential(float(p1["mean_interarrival"]))
            arrivals[slot] = t
        offsets = {"deliver": 0.0, "fund": float(p1["funding_after_arrival"]),
                   "issue": float(p1["issuance_after_arrival"])}
        for p in ("deliver", "fund", "issue"):
            if p in phases:
                for slot in order:
                    events.append(Event(int(round(arrivals[slot] + offsets[p])), p, slot))
        last_pre_action = max(e.time for e in events)
        action_offset = (last_pre_action - arrivals[order[0]]) + gap
        j = stream("jitter")
        jitter = float(p1["action_jitter"])
        acts = {}
        for slot in order:
            acts[slot] = arrivals[slot] + action_offset + (2 * j.uniform() - 1) * jitter
            events.append(Event(int(round(acts[slot])), "act", slot))
        orders["act"] = sorted(order, key=lambda s: (acts[s], order.index(s)))
        delays = {"arrivals": {str(s): arrivals[s] for s in order},
                  "action_times": {str(s): acts[s] for s in order},
                  "action_offset": action_offset}
        if "prepare" in phases:
            # Off chain; B1 prepares before funding, B3 after the last issuance.
            if baseline_id == "B1" or baseline_id == "B2-Allowlist":
                t_prep = min(e.time for e in events if e.phase == "fund") - 1
            elif baseline_id in CREDIT:
                t_prep = max(e.time for e in events if e.phase == "issue") + 1
            else:
                t_prep = min(e.time for e in events if e.phase == "act") - 1
            for slot in order:
                events.append(Event(t_prep, "prepare", slot))

    if scenario_id == "S0-clean-shuffled" and "prepare" in phases:
        # Re-time S0 preparation so it respects the dependencies above while
        # keeping its own independent order.
        events = [e for e in events if e.phase != "prepare"]
        if baseline_id in ("B1", "B2-Allowlist"):
            anchor = min(e.time for e in events if e.phase == "fund") - 1
        elif baseline_id in CREDIT:
            anchor = max(e.time for e in events if e.phase == "issue") + 1
        else:
            anchor = min(e.time for e in events if e.phase == "act") - 1
        for slot in orders["prepare"]:
            events.append(Event(anchor, "prepare", slot))

    if baseline_id == B4:
        # Setup only (not an event): the faucet's issuer-funder transfers, in an order of
        # their own. Drawn last so every order B4 shares with B3 is untouched.
        orders["setup_issuer"] = stream("order/setup_issuer").permutation(n)

    events = _serialize(events, orders)
    sched = Schedule(scenario_id=scenario_id, baseline_id=baseline_id, pool_size=n,
                     orders=orders, events=events, delays=delays)
    check_constraints(sched)
    return sched


def _serialize(events: List[Event], orders: Mapping[str, List[int]]) -> List[Event]:
    """Total order by (time, phase precedence, phase order); on-chain events get
    strictly increasing integer timestamps (one transaction per block)."""
    precedence = {p: i for i, p in enumerate(PHASES)}
    rank = {p: {s: i for i, s in enumerate(o)} for p, o in orders.items()}
    ordered = sorted(events, key=lambda e: (e.time, precedence[e.phase],
                                            rank[e.phase][e.slot]))
    out: List[Event] = []
    last = None
    for e in ordered:
        t = e.time
        if e.phase in ONCHAIN_PHASES:
            if last is not None and t <= last:
                t = last + 1
            last = t
        out.append(Event(t, e.phase, e.slot))
    return out


def check_constraints(s: Schedule) -> None:
    pos = {(e.phase, e.slot): i for i, e in enumerate(s.events)}
    phases = phases_for(s.baseline_id)
    for slot in range(s.pool_size):
        for p in phases:
            if p != "setup" and (p, slot) not in pos:
                raise AssertionError(f"slot {slot} has no {p} event")
        if pos[("deliver", slot)] > pos[("act", slot)]:
            raise AssertionError("delivery after action")
        if "fund" in phases and pos[("fund", slot)] > pos[("act", slot)]:
            raise AssertionError("funding after action")
        if "prepare" in phases and pos[("prepare", slot)] > pos[("act", slot)]:
            raise AssertionError("preparation after action")
        if s.baseline_id in ("B1", "B2-Allowlist") and pos[("prepare", slot)] > pos[("fund", slot)]:
            raise AssertionError("B1/B2-Allowlist preparation after funding")
        if s.baseline_id in CREDIT and pos[("fund", slot)] > pos[("issue", slot)]:
            raise AssertionError("B3 issuance before admission")
    if s.baseline_id == B4 and sorted(s.orders.get("setup_issuer", [])) != list(range(s.pool_size)):
        raise AssertionError("B4 issuer-funder setup order is not a permutation of the actors")
    if s.baseline_id in CREDIT:
        last_issue = max(i for i, e in enumerate(s.events) if e.phase == "issue")
        first_after = min(i for i, e in enumerate(s.events) if e.phase in ("prepare", "act"))
        if first_after < last_issue:
            raise AssertionError("B3 spend preparation/action before the last issuance "
                                 "(would break the single-final-root schedule)")
    chain_times = [e.time for e in s.events if e.phase in ONCHAIN_PHASES]
    if any(b <= a for a, b in zip(chain_times, chain_times[1:])):
        raise AssertionError("on-chain timestamps are not strictly increasing")


def s1b_unintended_exposure(s: Schedule) -> Dict[str, float]:
    """Per-run S1b gate: for every pair of public orders other than issuance ~ redemption,
    the fraction of actors at the same rank in both (rank-match recovery of the hidden
    pairing). A value of 1.0 (identical orders) is a deterministic exposure."""
    o = observed_orders(s)
    for k in ("setup", "setup_issuer"):
        if k in s.orders:
            o[k] = list(s.orders[k])
    names = [p for p in ("setup", "setup_issuer", "deliver", "fund", "issue", "prepare", "act")
             if p in o]
    out = {}
    for i, p in enumerate(names):
        for q in names[i + 1:]:
            if (p, q) == S1B_INTENDED_PAIR:
                continue
            out[f"{p}~{q}"] = sum(x == y for x, y in zip(o[p], o[q])) / s.pool_size
    return out


def observed_orders(s: Schedule) -> Dict[str, List[int]]:
    """Execution order per phase as it will appear on chain (slots, PRIVATE)."""
    out: Dict[str, List[int]] = {}
    for e in s.events:
        out.setdefault(e.phase, []).append(e.slot)
    return out


def spearman(a: Sequence[int], b: Sequence[int]) -> float:
    """Spearman rank correlation of two permutations of the same slots."""
    n = len(a)
    if n < 2:
        return 0.0
    ra = {s: i for i, s in enumerate(a)}
    rb = {s: i for i, s in enumerate(b)}
    d2 = sum((ra[s] - rb[s]) ** 2 for s in ra)
    return 1 - 6 * d2 / (n * (n * n - 1))
