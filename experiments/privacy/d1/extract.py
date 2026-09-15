"""Public trace -> entities -> per-relation candidate sets and pair features.

NEUTRAL and PURE: every function takes rows already loaded by the attacker-side
reader (``experiments.attacker_view``) and returns plain data. Nothing here opens
a file, and nothing here can see ground truth. Every value used is read from
the row kind and field declared by the feature in ``registry.FEATURES``.

Subjects and candidate sets (constructed from public data and public workload
knowledge only):

R1 (B0, B1)  subject = application action (B0 action tx hash / B1 userop hash);
             candidates = every distinct sender of a plain ETH transfer in the run
             (the faucet included). Not constructed for B2/B3: every sponsored
             operation there has one public candidate economic funder (see
             ``r1_structure``), so no classification is run.
R2 (B3, B4-CrossAccount)  subject = Spend userop hash; candidates = every Bootstrap
             userop hash. B4-CrossAccount uses the identical extractor and features.
R3 (all)     subject = application action; candidates = the auxiliary
             established-wallet directory (auxiliary attacker knowledge).

The destination address of the W1 application transfer is public workload
configuration (``run_manifest.public.json`` components).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import registry

B3 = "B3-PrivGas-v1"
B4 = "B4-CrossAccount"
CREDIT = (B3, B4)


def _ts(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


def _int(x: Any) -> Optional[int]:
    return None if x is None else int(x)


def classify_rows(rows: Sequence[Mapping[str, Any]]) -> List[str]:
    """Row kind for every public_events row (content only)."""
    by_tx: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by_tx[r["transaction_hash"]].append(r)
    tx_kind: Dict[str, str] = {}
    for h, rs in by_tx.items():
        classes = {r.get("calldata_class") for r in rs}
        if "entrypoint_handle_ops" in classes:
            tx_kind[h] = "bundle@bootstrap" if "pool_deposit" in classes else "bundle@app"
        elif "contract_creation" in classes:
            tx_kind[h] = "creation"
        elif "paymaster_deposit" in classes:
            tx_kind[h] = "pm_deposit"
        else:
            tx_kind[h] = "plain"
    kinds = []
    for r in rows:
        tk = tx_kind[r["transaction_hash"]]
        et, cc = r["event_type"], r.get("calldata_class")
        ctx = tk.split("@")[1] if "@" in tk else None
        if cc == "contract_creation":
            k = "deploy"
        elif et == "asset_transfer" and tk == "creation":
            k = "mint"
        elif et == "native_transfer" and cc == "fee_burn":
            k = "fee_burn"
        elif et == "native_transfer" and r.get("log_index") is None:
            k = "eth_tx"
        elif et == "native_transfer":
            k = "vmin_forward"
        elif cc == "paymaster_deposit":
            k = "pm_deposit_tx"
        elif et == "entrypoint_deposit":
            k = "prefund_deposit_log" if ctx else "pm_deposit_log"
        elif et == "asset_transfer":
            k = "erc20_in_op" if ctx else "erc20_tx"
        elif cc == "paymaster_policy":
            k = "allowlist_tx"
        elif cc == "stealth_announce_and_fund":
            k = "announce_tx"
        elif et == "stealth_announcement":
            k = "announce_log"
        elif et == "sponsorship_eligibility":
            k = "eligibility_log"
        elif cc == "entrypoint_handle_ops":
            k = f"bundle_tx@{ctx}"
        elif et == "account_deployment":
            k = f"deploy_log@{ctx}"
        elif et == "user_operation_event":
            k = f"uoe@{ctx}"
        elif cc == "paymaster_sponsorship":
            k = "bootstrap_sponsored_log"
        elif cc == "pool_root_update":
            k = "root_update_log"
        elif cc == "pool_deposit":
            k = "pool_deposit_log"
        elif cc == "pool_redeem":
            k = "pool_redeem_log"
        else:
            raise ValueError(f"unclassified public row {r['record_id']}: {et}/{cc}")
        if k not in registry.ROW_KINDS:  # pragma: no cover
            raise ValueError(k)
        kinds.append(k)
    return kinds


@dataclass
class RunTrace:
    experiment_id: str
    run_id: str
    baseline_id: str
    pool_size: int
    destination: str
    rows: List[Dict[str, Any]]
    kinds: List[str]
    wallet_directory: List[str]

    def of(self, kind: str) -> List[Dict[str, Any]]:
        return [r for r, k in zip(self.rows, self.kinds) if k == kind]

    def in_tx(self, tx: str, kind: str) -> List[Dict[str, Any]]:
        return [r for r, k in zip(self.rows, self.kinds)
                if k == kind and r["transaction_hash"] == tx]


def make_trace(experiment_id: str, run_id: str, baseline_id: str, pool_size: int,
               manifest: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
               wallet_directory: Sequence[str]) -> RunTrace:
    rows = [dict(r) for r in rows]
    return RunTrace(experiment_id, run_id, baseline_id, pool_size,
                    manifest["components"]["destination"].lower(), rows, classify_rows(rows),
                    [w.lower() for w in wallet_directory])


# --------------------------------------------------------------------------------------
# entities
# --------------------------------------------------------------------------------------

@dataclass
class AppOp:
    ref: str
    tx: str
    account_t: str               # sender of the application transfer (T)
    block_t: int
    account_aa: Optional[str] = None
    block_aa: Optional[int] = None
    account_g: Optional[str] = None      # B1 prefund subject / B3 CreditSpent sender
    block_g: Optional[int] = None
    ts_g: Optional[float] = None
    gas_used: Optional[int] = None
    pvg: Optional[int] = None
    vgl: Optional[int] = None
    cgl: Optional[int] = None
    max_fee: Optional[int] = None
    paymaster: Optional[str] = None
    nullifier: Optional[str] = None
    root: Optional[str] = None


@dataclass
class Issuance:
    ref: str
    tx: str
    depositor_g: str
    block_g: int
    ts_g: float
    commitment: str
    root: str
    sender_uoe: str
    block_uoe: int
    deployed: Optional[str]
    gas_used: int
    pvg: int


def app_ops(t: RunTrace) -> List[AppOp]:
    out: List[AppOp] = []
    if t.baseline_id == "B0":
        for r in t.of("erc20_tx"):
            if (r.get("subject_account") or "") == t.destination:
                out.append(AppOp(ref=r["transaction_hash"], tx=r["transaction_hash"],
                                 account_t=r["sender"], block_t=r["block_number"]))
        return sorted(out, key=lambda o: o.block_t)
    for u in t.of("uoe@app"):
        tx = u["transaction_hash"]
        (xfer,) = t.in_tx(tx, "erc20_in_op")
        op = AppOp(ref=u["userop_hash"], tx=tx, account_t=xfer["sender"], block_t=xfer["block_number"],
                   account_aa=u["sender"], block_aa=u["block_number"],
                   gas_used=_int(u["actual_gas_used"]), pvg=_int(u["pre_verification_gas"]),
                   vgl=_int(u["verification_gas_limit"]), cgl=_int(u["call_gas_limit"]),
                   max_fee=_int(u["max_fee_per_gas"]), paymaster=u.get("paymaster"))
        pre = t.in_tx(tx, "prefund_deposit_log")
        red = t.in_tx(tx, "pool_redeem_log")
        if pre:
            op.account_g, op.block_g = pre[0]["subject_account"], pre[0]["block_number"]
            op.ts_g = _ts(pre[0]["block_timestamp_utc"])
        if red:
            op.account_g, op.block_g = red[0]["sender"], red[0]["block_number"]
            op.ts_g = _ts(red[0]["block_timestamp_utc"])
            op.nullifier, op.root = red[0]["nullifier"], red[0]["merkle_root"]
        out.append(op)
    return sorted(out, key=lambda o: o.block_t)


def issuances(t: RunTrace) -> List[Issuance]:
    out = []
    for u in t.of("uoe@bootstrap"):
        tx = u["transaction_hash"]
        (dep,) = t.in_tx(tx, "pool_deposit_log")
        deploy = t.in_tx(tx, "deploy_log@bootstrap")
        out.append(Issuance(
            ref=u["userop_hash"], tx=tx, depositor_g=dep["sender"], block_g=dep["block_number"],
            ts_g=_ts(dep["block_timestamp_utc"]), commitment=dep["commitment"],
            root=dep["merkle_root"], sender_uoe=u["sender"], block_uoe=u["block_number"],
            deployed=deploy[0]["sender"] if deploy else None,
            gas_used=int(u["actual_gas_used"]), pvg=int(u["pre_verification_gas"])))
    return sorted(out, key=lambda i: i.block_g)


def _ranks(values: Mapping[str, float]) -> Dict[str, float]:
    """Average ranks (0-based) normalised to [0, 1]."""
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    out: Dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and items[j + 1][1] == items[i][1]:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            out[items[k][0]] = avg / (n - 1) if n > 1 else 0.0
        i = j + 1
    return out


def _z(values: Mapping[str, float]) -> Dict[str, float]:
    vs = list(values.values())
    mu = statistics.fmean(vs)
    sd = statistics.pstdev(vs)
    return {k: (v - mu) / sd if sd > 0 else 0.0 for k, v in values.items()}


# --------------------------------------------------------------------------------------
# pair features
# --------------------------------------------------------------------------------------

@dataclass
class SubjectCandidates:
    subject_ref: str
    candidates: List[str]
    features: Dict[str, List[float]]     # feature name -> value per candidate


def r1_features(t: RunTrace) -> List[SubjectCandidates]:
    if t.baseline_id not in ("B0", "B1"):
        return []
    ops = app_ops(t)
    eth = t.of("eth_tx")
    candidates = sorted({r["sender"] for r in eth})
    eth_by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in eth:
        eth_by[r["sender"]].append(r)
    tok_by: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in t.of("erc20_tx"):
        tok_by[r["sender"]].append(r)
    last_eth = {c: max(r["block_number"] for r in eth_by[c]) for c in candidates}
    last_tok = {c: max((r["block_number"] for r in tok_by.get(c, [])), default=-1)
                for c in candidates}
    eth_rank = _ranks(last_eth)
    tok_rank = _ranks(last_tok)
    op_rank_t = _ranks({o.ref: o.block_t for o in ops})
    out = []
    for o in ops:
        f: Dict[str, List[float]] = defaultdict(list)
        for c in candidates:
            eth_targets = {r["target"] for r in eth_by[c]}
            tok_targets = {r.get("subject_account") for r in tok_by.get(c, [])}
            f["r1_eth_fanout"].append(math.log1p(len(eth_targets)))
            if t.baseline_id == "B0":
                f["r1_token_edge"].append(float(o.account_t in tok_targets))
                f["r1_eth_edge_t"].append(float(o.account_t in eth_targets))
                f["r1_funding_rank_gap_t"].append(abs(eth_rank[c] - op_rank_t[o.ref]))
                f["r1_token_rank_gap"].append(abs(tok_rank[c] - op_rank_t[o.ref]))
            else:
                prefund = (o.vgl + o.cgl + o.pvg) * o.max_fee
                f["r1_token_edge_op"].append(float(o.account_t in tok_targets))
                f["r1_token_edge_aa"].append(float(o.account_aa in tok_targets))
                f["r1_eth_edge_t_op"].append(float(o.account_t in eth_targets))
                f["r1_eth_edge_aa"].append(float(o.account_aa in eth_targets))
                f["r1_eth_edge_g"].append(float(o.account_g in eth_targets))
                f["r1_eth_amount_matches_prefund"].append(
                    float(any(int(r["asset_amount"]) == prefund for r in eth_by[c])))
                f["r1_funding_rank_gap_op"].append(abs(eth_rank[c] - op_rank_t[o.ref]))
                f["r1_token_rank_gap_op"].append(abs(tok_rank[c] - op_rank_t[o.ref]))
        out.append(SubjectCandidates(o.ref, list(candidates), dict(f)))
    return out


def _bits_agree(a_hex: str, b_hex: str) -> float:
    a, b = int(a_hex, 16) & (2 ** 64 - 1), int(b_hex, 16) & (2 ** 64 - 1)
    return (64 - bin(a ^ b).count("1")) / 64


def r2_features(t: RunTrace) -> List[SubjectCandidates]:
    if t.baseline_id not in CREDIT:
        return []
    ops = app_ops(t)
    iss = issuances(t)
    n = len(iss)
    cand = [i.ref for i in iss]
    rank_iss_g = _ranks({i.ref: i.block_g for i in iss})
    rank_iss_aa = _ranks({i.ref: i.block_uoe for i in iss})
    rank_red_g = _ranks({o.ref: o.block_g for o in ops})
    rank_red_aa = _ranks({o.ref: o.block_aa for o in ops})
    rank_app_t = _ranks({o.ref: o.block_t for o in ops})
    gas_rank_iss = _ranks({i.ref: i.gas_used for i in iss})
    gas_rank_op = _ranks({o.ref: o.gas_used for o in ops})
    pvg_z_iss = _z({i.ref: i.pvg for i in iss})
    pvg_z_op = _z({o.ref: o.pvg for o in ops})
    gas_z_iss = _z({i.ref: i.gas_used for i in iss})
    med_offset = statistics.median([o.ts_g for o in ops]) - statistics.median([i.ts_g for i in iss])
    all_ts = [o.ts_g for o in ops] + [i.ts_g for i in iss]
    span = max(all_ts) - min(all_ts) or 1.0
    deliveries = {r.get("subject_account"): r["block_number"] for r in t.of("erc20_tx")}
    dep_delivery = {i.ref: deliveries.get(i.depositor_g) for i in iss}
    delivery_rank = _ranks({k: v for k, v in dep_delivery.items() if v is not None})
    out = []
    for o in ops:
        f: Dict[str, List[float]] = defaultdict(list)
        prior = [i for i in iss if i.block_g < o.block_g]
        latest = max(prior, key=lambda i: i.block_g).ref if prior else None
        for i in iss:
            f["r2_eq_g_account"].append(float(o.account_g == i.depositor_g))
            f["r2_eq_aa_sender"].append(float(o.account_aa == i.sender_uoe))
            f["r2_eq_t_account"].append(float(o.account_t == i.depositor_g))
            f["r2_eq_deploy"].append(float(i.deployed is not None and o.account_aa == i.deployed))
            f["r2_rank_gap_g"].append(abs(rank_red_g[o.ref] - rank_iss_g[i.ref]))
            f["r2_rank_gap_aa"].append(abs(rank_red_aa[o.ref] - rank_iss_aa[i.ref]))
            f["r2_dt_offset_g"].append(abs((o.ts_g - i.ts_g) - med_offset) / span)
            f["r2_latest_issuance_g"].append(float(i.ref == latest))
            f["r2_intervening_g"].append(
                sum(1 for j in iss if i.block_g < j.block_g < o.block_g) / n)
            f["r2_root_match"].append(float(o.root == i.root))
            f["r2_bits_agree"].append(_bits_agree(o.nullifier, i.commitment))
            f["r2_gas_rank_gap"].append(abs(gas_rank_op[o.ref] - gas_rank_iss[i.ref]))
            f["r2_pvg_gap"].append(abs(pvg_z_op[o.ref] - pvg_z_iss[i.ref]))
            f["r2_cand_gas_z"].append(gas_z_iss[i.ref])
            f["r2_cand_pvg_z"].append(pvg_z_iss[i.ref])
            f["r2_delivery_rank_gap_tg"].append(
                abs(delivery_rank[i.ref] - rank_app_t[o.ref]) if i.ref in delivery_rank else 1.0)
        out.append(SubjectCandidates(o.ref, list(cand), dict(f)))
    return out


def _hamming(a: str, b: str) -> float:
    return bin(int(a, 16) ^ int(b, 16)).count("1") / 160


def _prefix(a: str, b: str) -> float:
    a, b = a[2:], b[2:]
    k = 0
    while k < 40 and a[k] == b[k]:
        k += 1
    return k / 40


def r3_features(t: RunTrace) -> List[SubjectCandidates]:
    ops = app_ops(t)
    directory = list(t.wallet_directory)
    n = len(directory)
    pos = {w: (i / (n - 1) if n > 1 else 0.0) for i, w in enumerate(directory)}
    rank_t = _ranks({o.ref: o.block_t for o in ops})
    deliveries = {r.get("subject_account"): r["block_number"] for r in t.of("erc20_tx")}
    rank_del = _ranks({o.ref: deliveries[o.account_t] for o in ops})
    b = t.baseline_id
    rank_aa = _ranks({o.ref: o.block_aa for o in ops}) if b != "B0" else {}
    rank_gas = _ranks({o.ref: o.gas_used for o in ops}) if b != "B0" else {}
    rank_pvg = _ranks({o.ref: o.pvg for o in ops}) if b != "B0" else {}
    rank_fund: Dict[str, float] = {}
    if b in ("B0", "B1"):
        fund = {r["target"]: r["block_number"] for r in t.of("eth_tx")}
        key = (lambda o: o.account_t) if b == "B0" else (lambda o: o.account_g)
        rank_fund = _ranks({o.ref: fund[key(o)] for o in ops})
    rank_allow: Dict[str, float] = {}
    if b == "B2-Allowlist":
        allow = {r["subject_account"]: r["block_number"] for r in t.of("allowlist_tx")}
        rank_allow = _ranks({o.ref: allow[o.account_aa] for o in ops})
    rank_iss: Dict[str, float] = {}
    if b == B3:
        dep = {i.depositor_g: i.block_g for i in issuances(t)}
        rank_iss = _ranks({o.ref: dep[o.account_g] for o in ops})
    out = []
    for o in ops:
        f: Dict[str, List[float]] = defaultdict(list)
        for w in directory:
            p = pos[w]
            if b == "B0":
                f["r3_dir_vs_action_rank_b0"].append(abs(p - rank_t[o.ref]))
                f["r3_dir_vs_funding_rank_b0"].append(abs(p - rank_fund[o.ref]))
            else:
                f["r3_dir_vs_action_rank_t"].append(abs(p - rank_t[o.ref]))
                f["r3_dir_vs_op_rank_aa"].append(abs(p - rank_aa[o.ref]))
                f["r3_gas_rank_vs_dir_g"].append(abs(p - rank_gas[o.ref]))
                f["r3_pvg_rank_vs_dir_g"].append(abs(p - rank_pvg[o.ref]))
            if b == "B1":
                f["r3_dir_vs_funding_rank_g"].append(abs(p - rank_fund[o.ref]))
            if b == "B2-Allowlist":
                f["r3_dir_vs_allowlist_rank"].append(abs(p - rank_allow[o.ref]))
            if b == B3:
                f["r3_dir_vs_issuance_rank_g"].append(abs(p - rank_iss[o.ref]))
            f["r3_dir_vs_delivery_rank"].append(abs(p - rank_del[o.ref]))
            f["r3_addr_hamming_t"].append(_hamming(o.account_t, w))
            f["r3_addr_prefix_t"].append(_prefix(o.account_t, w))
        out.append(SubjectCandidates(o.ref, directory, dict(f)))
    return out


RELATION_EXTRACTORS = {"R1": r1_features, "R2": r2_features, "R3": r3_features}


def features(t: RunTrace, relation: str) -> List[SubjectCandidates]:
    out = RELATION_EXTRACTORS[relation](t)
    declared = {f.name for f in registry.features_for(relation, t.baseline_id)}
    for sc in out:
        extra = set(sc.features) - declared
        missing = declared - set(sc.features)
        if extra or missing:
            raise AssertionError(f"{relation}/{t.baseline_id}: features not matching the "
                                 f"registry: extra {sorted(extra)}, missing {sorted(missing)}")
    return out


# --------------------------------------------------------------------------------------
# R1 structure (all baselines; no classification where the candidate set is 1)
# --------------------------------------------------------------------------------------

def r1_structure(t: RunTrace) -> Dict[str, Any]:
    ops = app_ops(t)
    b = t.baseline_id
    pm_depositors: Dict[str, set] = defaultdict(set)
    for r in t.of("pm_deposit_tx"):
        pm = (r.get("subject_account") or r.get("target")).lower()
        pm_depositors[pm].add(r["sender"])
    eth = t.of("eth_tx")
    funders_of: Dict[str, set] = defaultdict(set)
    for r in eth:
        funders_of[r["target"]].add(r["sender"])
    if b == "B0":
        kind, payer = "eoa_balance", lambda o: o.account_t
    elif b == "B1":
        kind, payer = "smart_account_entrypoint_deposit", lambda o: o.account_aa
    else:
        kind, payer = "paymaster_entrypoint_deposit", lambda o: o.paymaster
    eth_senders = sorted({r["sender"] for r in eth})
    per_op = []
    for o in ops:
        p = payer(o)
        if kind == "paymaster_entrypoint_deposit":
            candidates = sorted(pm_depositors.get(p.lower(), set()))
            edge = []
        else:
            # Any wallet that sent plain ETH in the run is a plausible one-hop funder;
            # the account-specific edge (a transfer INTO the payer) is reported separately.
            candidates = eth_senders
            edge = sorted(funders_of.get(p, set()))
        per_op.append({"immediate_payer": p, "candidates": candidates, "edge": edge})
    cand_sets = [tuple(x["candidates"]) for x in per_op]
    shared = max((cand_sets.count(c) for c in set(cand_sets)), default=0)
    edge_owner = defaultdict(int)
    for x in per_op:
        for e in x["edge"]:
            edge_owner[e] += 1
    extra_bootstrap = None
    if b in CREDIT:
        boot_pm = {u.get("paymaster") for u in t.of("uoe@bootstrap")}
        extra_bootstrap = {"bootstrap_paymasters": len([p for p in boot_pm if p]),
                           "bootstrap_paymaster_depositors": len(
                               set().union(*(pm_depositors.get(p, set()) for p in boot_pm if p)))}
    sizes = sorted({len(x["candidates"]) for x in per_op})
    authorization = None
    if b == "B2-Allowlist":
        allow = t.of("allowlist_tx")
        auth_edges = sum(any(r["subject_account"] == o.account_aa and r["block_number"] < o.block_aa
                             for r in allow) for o in ops)
        depositors = set().union(*pm_depositors.values()) if pm_depositors else set()
        authorization = {"ops_with_prior_public_allowlist_edge": auth_edges,
                         "allowlist_sender_is_a_paymaster_depositor": all(
                             r["sender"] in depositors for r in allow)}
    return {
        "baseline_id": b, "pool_size": t.pool_size, "operations": len(ops),
        "immediate_gas_payer_kind": kind,
        "distinct_immediate_payers": len({x["immediate_payer"] for x in per_op}),
        "public_candidate_economic_funders_per_op": sizes,
        "ops_with_direct_account_specific_funding_edge": sum(bool(x["edge"]) for x in per_op),
        "ops_whose_edge_names_exactly_one_funder": sum(len(x["edge"]) == 1 for x in per_op),
        "max_ops_per_edge_funder": max(edge_owner.values(), default=0),
        # Sponsored: many ops draw on one publicly funded Paymaster deposit. Sender-funded:
        # shared only if one wallet funded several operations' payers.
        "funding_relation_shared_across_ops": (shared > 1 if kind == "paymaster_entrypoint_deposit"
                                               else max(edge_owner.values(), default=0) > 1),
        "max_ops_sharing_one_candidate_set": shared,
        "r1_classification_run": min(sizes, default=0) >= 2,
        "b3_bootstrap": extra_bootstrap,
        "b2_allowlist_authorization": authorization,
    }
