"""Transparent deterministic and timing rules (Attack A, Attack B). NEUTRAL, pure.

A rule maps one run's public trace to, per subject, a candidate ``selected`` set
(the rule's answer; empty means "the rule does not fire", scored as a uniform
guess) and ``scores`` (a ranking used for top-k). No learning, no labels.
These are equality / ordering checks and are reported as such, not as machine
learning.

Every rule states the relation it attacks, the observer tier it needs, and the
feature families (registry) it reads.
"""

from __future__ import annotations

import hashlib
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Tuple

from . import extract

B3 = "B3-PrivGas-v1"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    relation: str
    baselines: Tuple[str, ...]
    observer_tier: str
    feature_set: str
    kind: str                 # "exact" | "timing" | "control"
    description: str
    fn: Callable[[extract.RunTrace], List[Dict[str, Any]]]


def _from_feature(relation: str, name: str, select_value: float = 1.0):
    def fn(t: extract.RunTrace) -> List[Dict[str, Any]]:
        out = []
        for sc in extract.features(t, relation):
            vals = sc.features[name]
            sel = [c for c, v in zip(sc.candidates, vals) if v == select_value]
            out.append({"subject_ref": sc.subject_ref, "candidates": sc.candidates,
                        "scores": [float(v == select_value) for v in vals], "selected": sel})
        return out
    return fn


def _uniform(relation: str):
    def fn(t: extract.RunTrace) -> List[Dict[str, Any]]:
        return [{"subject_ref": sc.subject_ref, "candidates": sc.candidates,
                 "scores": [0.0] * len(sc.candidates), "selected": []}
                for sc in extract.features(t, relation)]
    return fn


def _min_gap(relation: str, name: str):
    """Select the candidate(s) with the smallest value of a gap feature."""
    def fn(t: extract.RunTrace) -> List[Dict[str, Any]]:
        out = []
        for sc in extract.features(t, relation):
            vals = sc.features[name]
            m = min(vals)
            out.append({"subject_ref": sc.subject_ref, "candidates": sc.candidates,
                        "scores": [-v for v in vals],
                        "selected": [c for c, v in zip(sc.candidates, vals) if v == m]})
        return out
    return fn


def r2_nearest_prior(t: extract.RunTrace) -> List[Dict[str, Any]]:
    iss = {i.ref: i for i in extract.issuances(t)}
    out = []
    for o in extract.app_ops(t):
        cands = list(iss)
        prior = [c for c in cands if iss[c].ts_g <= o.ts_g]
        scores = [-(o.ts_g - iss[c].ts_g) if c in prior else -1e18 for c in cands]
        best = max(scores)
        out.append({"subject_ref": o.ref, "candidates": cands, "scores": scores,
                    "selected": [c for c, s in zip(cands, scores) if s == best and c in prior]})
    return out


def _r2_window(k: float):
    """Unsupervised common-delay window: centre = median(t_redeem) - median(t_issue);
    half-width = k * median gap between consecutive issuances (all public)."""
    def fn(t: extract.RunTrace) -> List[Dict[str, Any]]:
        iss = extract.issuances(t)
        ops = extract.app_ops(t)
        centre = statistics.median(o.ts_g for o in ops) - statistics.median(i.ts_g for i in iss)
        times = sorted(i.ts_g for i in iss)
        gaps = [b - a for a, b in zip(times, times[1:])] or [0.0]
        half = k * statistics.median(gaps)
        out = []
        for o in ops:
            cands = [i.ref for i in iss]
            dev = [abs((o.ts_g - i.ts_g) - centre) for i in iss]
            out.append({"subject_ref": o.ref, "candidates": cands,
                        "scores": [-d for d in dev],
                        "selected": [c for c, d in zip(cands, dev) if d <= half]})
        return out
    return fn


def r2_shuffled_fifo_control(t: extract.RunTrace) -> List[Dict[str, Any]]:
    """FIFO with the redemption order replaced by a fixed pseudo-random permutation
    (seeded by the public run id): a negative control that must be at chance."""
    iss = extract.issuances(t)
    ops = extract.app_ops(t)
    n = len(iss)
    key = hashlib.sha256(f"shuffled-fifo/{t.experiment_id}/{t.run_id}".encode()).digest()
    order = sorted(range(n), key=lambda i: hashlib.sha256(key + bytes([i])).digest())
    fake_rank = {o.ref: order[k] for k, o in enumerate(sorted(ops, key=lambda o: o.block_g))}
    iss_rank = {i.ref: k for k, i in enumerate(sorted(iss, key=lambda i: i.block_g))}
    out = []
    for o in ops:
        cands = [i.ref for i in iss]
        gaps = [abs(fake_rank[o.ref] - iss_rank[c]) for c in cands]
        m = min(gaps)
        out.append({"subject_ref": o.ref, "candidates": cands, "scores": [-g for g in gaps],
                    "selected": [c for c, g in zip(cands, gaps) if g == m]})
    return out


def r3_wallet_on_chain(t: extract.RunTrace) -> List[Dict[str, Any]]:
    """Select directory wallets that appear in ANY address field of ANY public row
    of the run (a wallet that transacted or was paid)."""
    seen = set()
    for r in t.rows:
        for f in ("sender", "target", "subject_account", "paymaster", "factory",
                  "bundler_beneficiary", "asset_contract", "entrypoint_address"):
            if r.get(f):
                seen.add(r[f])
    out = []
    for sc in extract.features(t, "R3"):
        sel = [w for w in sc.candidates if w in seen]
        out.append({"subject_ref": sc.subject_ref, "candidates": sc.candidates,
                    "scores": [float(w in seen) for w in sc.candidates], "selected": sel})
    return out


B0B1 = ("B0", "B1")
ALL = ("B0", "B1", "B2-Signature", "B2-Allowlist", B3)

RULES: Tuple[Rule, ...] = (
    # ---- R1 (sender-funded baselines only) ----
    Rule("rule.r1-uniform", "R1", B0B1, "A0", "none", "control",
         "uniform random guess over the public candidate funders", _uniform("R1")),
    Rule("rule.r1-direct-eth-edge-b0", "R1", ("B0",), "A0", "T+G", "exact",
         "the wallet that sent ETH directly to the EOA sending the action",
         _from_feature("R1", "r1_eth_edge_t")),
    Rule("rule.r1-direct-eth-edge-b1", "R1", ("B1",), "A0", "AA+G", "exact",
         "the wallet that sent ETH directly to the UserOperation sender",
         _from_feature("R1", "r1_eth_edge_aa")),
    Rule("rule.r1-direct-eth-edge-g-only", "R1", ("B1",), "A0", "G", "exact",
         "the wallet that sent ETH to the account named by the op's prefund Deposited event",
         _from_feature("R1", "r1_eth_edge_g")),
    Rule("rule.r1-direct-asset-edge-b0", "R1", ("B0",), "A0", "T", "exact",
         "the wallet that sent the W1 tokens to the EOA sending the action",
         _from_feature("R1", "r1_token_edge")),
    Rule("rule.r1-direct-asset-edge-b1", "R1", ("B1",), "A0", "T", "exact",
         "the wallet that sent the W1 tokens to the account whose transfer the op made",
         _from_feature("R1", "r1_token_edge_op")),
    Rule("rule.r1-prefund-amount-match", "R1", ("B1",), "A0", "AA+G", "exact",
         "the wallet whose ETH transfer amount equals the op's required prefund",
         _from_feature("R1", "r1_eth_amount_matches_prefund")),
    # ---- R2 (B3) ----
    Rule("rule.r2-uniform", "R2", (B3,), "A0", "none", "control",
         "uniform random guess over all issuances in the run", _uniform("R2")),
    Rule("rule.r2-bootstrap-sender-eq-spend-sender", "R2", (B3,), "A0", "AA+G", "exact",
         "Bootstrap UserOperation.sender == Spend UserOperation.sender",
         _from_feature("R2", "r2_eq_aa_sender")),
    Rule("rule.r2-creditspent-sender-eq-depositor", "R2", (B3,), "A0", "G", "exact",
         "CreditSpent(nullifier, sender).sender == CreditPool depositor of the issuance",
         _from_feature("R2", "r2_eq_g_account")),
    Rule("rule.r2-transfer-account-eq-depositor", "R2", (B3,), "A0", "T+G", "exact",
         "account of the Spend's application transfer == CreditPool depositor",
         _from_feature("R2", "r2_eq_t_account")),
    Rule("rule.r2-deployed-account-eq-spender", "R2", (B3,), "A0", "AA+G", "exact",
         "account deployed by the Bootstrap operation == Spend sender",
         _from_feature("R2", "r2_eq_deploy")),
    Rule("rule.r2-root-match", "R2", (B3,), "A0", "G", "exact",
         "the redemption's proof root equals the root emitted by the issuance's deposit",
         _from_feature("R2", "r2_root_match")),
    Rule("rule.r2-insertion-order-fifo", "R2", (B3,), "A0", "G", "timing",
         "k-th redemption <-> k-th issuance (minimum rank gap)", _min_gap("R2", "r2_rank_gap_g")),
    Rule("rule.r2-nearest-prior-issuance", "R2", (B3,), "A0", "G", "timing",
         "the most recent issuance before the redemption", r2_nearest_prior),
    Rule("rule.r2-window-k1", "R2", (B3,), "A0", "G", "timing",
         "issuances within 1 median issuance gap of the common delay", _r2_window(1.0)),
    Rule("rule.r2-window-k2", "R2", (B3,), "A0", "G", "timing",
         "issuances within 2 median issuance gaps of the common delay", _r2_window(2.0)),
    Rule("rule.r2-window-k4", "R2", (B3,), "A0", "G", "timing",
         "issuances within 4 median issuance gaps of the common delay", _r2_window(4.0)),
    Rule("rule.r2-shuffled-fifo-control", "R2", (B3,), "A0", "G", "control",
         "FIFO against a pseudo-randomly permuted redemption order (negative control)",
         r2_shuffled_fifo_control),
    # ---- R3 (negative control) ----
    Rule("rule.r3-uniform", "R3", ALL, "A0", "none", "control",
         "uniform random guess over the wallet directory", _uniform("R3")),
    Rule("rule.r3-wallet-appears-on-chain", "R3", ALL, "A0", "T+AA+G", "exact",
         "directory wallets that appear in any public row of the run", r3_wallet_on_chain),
    Rule("rule.r3-order-match-action", "R3", ALL, "A0", "T", "control",
         "wallet whose directory position is closest to the action's rank (harness-order "
         "leak check)",
         lambda t: _min_gap("R3", "r3_dir_vs_action_rank_b0" if t.baseline_id == "B0"
                            else "r3_dir_vs_action_rank_t")(t)),
)


def rules_for(relation: str, baseline_id: str) -> List[Rule]:
    return [r for r in RULES if r.relation == relation and baseline_id in r.baselines]
