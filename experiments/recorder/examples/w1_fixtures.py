"""Canonical workload W1 as synthetic observations for B0, B1 and B2.

W1 (docs/research-plan.md Sec. 4): a sender transfers an ERC-20 token to a fresh
stealth-controlled account; that account then transfers the token to a fixed
destination. The three baselines perform the *same* application action and
differ only in account type and gas mechanism:

    B0  fresh EOA, sender also supplies ETH for the later transfer
    B1  ERC-4337 smart account, sender supplies native balance, no Paymaster
    B2  same smart account and same action, gas sponsored by an ordinary,
        fully observable Paymaster (and therefore no ETH top-up)

Scenario structure, chosen to exercise the rules the schema exists to
protect:

* Each run has two scenarios, so a candidate set is never of size one.
* Under B2 both scenarios belong to **one** actor holding **two** stealth
  accounts. That is the case rule "multiple addresses are not multiple
  people" refers to: an analysis that counts accounts would see two
  participants where there is one.
* B2's second scenario includes a rejected UserOperation followed by a fee
  replacement. The rejection is recorded, not dropped.

Every address and hash below is fabricated fixture data on chain id 31337.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..adapters.base import (
    BundlerObservation,
    GroundTruth,
    Observation,
    RelationLabel,
    UserOpObservation,
)

CHAIN_ID = 31337
ENTRYPOINT = "0x0000000071727De22E5E9d8BAf0edAc6f37da032"
ENTRYPOINT_VERSION = "0.9.0"
TOKEN = "0x5fbdb2315678afecb367f032d93f642f64180aa3"
DESTINATION = "0xdddddddddddddddddddddddddddddddddddddddd"
FACTORY = "0xfaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PAYMASTER = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
BENEFICIARY = "0xbeee000000000000000000000000000000000001"

ASSET_SENDER_A = "0xaaaa000000000000000000000000000000000001"
ASSET_SENDER_B = "0xaaaa000000000000000000000000000000000002"
STEALTH_A = "0x57ea1a0000000000000000000000000000000001"
STEALTH_B = "0x57ea1b0000000000000000000000000000000002"
ESTABLISHED_A = "0xeeee000000000000000000000000000000000001"
ESTABLISHED_B = "0xeeee000000000000000000000000000000000002"

SELECTOR_ERC20_TRANSFER = "0xa9059cbb"
SELECTOR_ACCOUNT_EXECUTE = "0xb61d27f6"

TOKEN_AMOUNT = 1_000_000_000_000_000_000  # 1 token, 18 decimals
ETH_TOPUP = 3_000_000_000_000_000  # 0.003 ETH gas allowance for B0/B1


def _h(prefix: str, n: int) -> str:
    """Deterministic fixture 32-byte hash."""
    body = f"{prefix}{n:04d}"
    return "0x" + (body.encode().hex() + "0" * 64)[:64]


def _ts(minute: int, second: int = 0) -> str:
    return f"2026-03-01T12:{minute:02d}:{second:02d}Z"


class _Scenario:
    """One (actor, stealth account, asset sender) triple for one baseline."""

    def __init__(self, tag: str, idx: int, *, actor: str, stealth_addr: str,
                 sender_addr: str, established_addr: str,
                 stealth_handle: str, actor_handle: str,
                 established_handle: str, funder_handle: str,
                 sender_handle: str) -> None:
        self.tag = tag
        self.idx = idx
        self.actor = actor
        self.stealth_addr = stealth_addr
        self.sender_addr = sender_addr
        self.established_addr = established_addr
        self.stealth_handle = stealth_handle
        self.actor_handle = actor_handle
        self.established_handle = established_handle
        self.funder_handle = funder_handle
        self.sender_handle = sender_handle


def _scenarios(baseline_id: str) -> List[_Scenario]:
    # Under B2 both scenarios belong to one actor holding two stealth
    # accounts -- see the module docstring.
    actor_b = "actor_7c1e" if baseline_id == "B2" else "actor_9d42"
    established_b = ("wallet_7c1e_main" if baseline_id == "B2"
                     else "wallet_9d42_main")
    funder_b = "funder_sponsor" if baseline_id == "B2" else "funder_9d42"
    funder_a = "funder_sponsor" if baseline_id == "B2" else "funder_7c1e"
    return [
        _Scenario("scn-a", 0, actor="A", stealth_addr=STEALTH_A,
                  sender_addr=ASSET_SENDER_A, established_addr=ESTABLISHED_A,
                  stealth_handle="stealth_a1", actor_handle="actor_7c1e",
                  established_handle="wallet_7c1e_main",
                  funder_handle=funder_a, sender_handle="sender_7c1e"),
        _Scenario("scn-b", 1, actor="B", stealth_addr=STEALTH_B,
                  sender_addr=ASSET_SENDER_B, established_addr=ESTABLISHED_B,
                  stealth_handle="stealth_b1", actor_handle=actor_b,
                  established_handle=established_b,
                  funder_handle=funder_b, sender_handle="sender_9d42"),
    ]


def _userop(scn: _Scenario, *, with_paymaster: bool, seq: int,
            max_fee: int = 2_000_000_000) -> UserOpObservation:
    return UserOpObservation(
        userop_hash=_h(f"uo{scn.tag}", seq),
        entrypoint_address=ENTRYPOINT,
        entrypoint_version=ENTRYPOINT_VERSION,
        max_fee_per_gas=max_fee,
        max_priority_fee_per_gas=1_000_000_000,
        verification_gas_limit=150_000,
        call_gas_limit=120_000,
        pre_verification_gas=50_000,
        factory=FACTORY,
        paymaster_verification_gas_limit=80_000 if with_paymaster else None,
        paymaster_post_op_gas_limit=40_000 if with_paymaster else None,
    )


def build(baseline_id: str) -> Tuple[List[Observation], List[BundlerObservation],
                                     List[GroundTruth]]:
    """Return (public observations, bundler observations, ground truth)."""
    if baseline_id == "B0":
        return _build_b0()
    if baseline_id == "B1":
        return _build_b1()
    if baseline_id == "B2":
        return _build_b2()
    raise ValueError(
        f"no W1 fixture for {baseline_id!r}; fixtures exist for B0, B1 and B2 "
        "only (Prompt 3 Sec. 18)")


def _asset_arrival(scn: _Scenario, block: int, minute: int,
                   tx_seq: int) -> Observation:
    """The sender's ERC-20 transfer into the fresh stealth account."""
    return Observation(
        event_type="asset_transfer", outcome="success", asset_type="erc20",
        scenario_id=scn.tag, observer_tier="A0",
        block_number=block, block_hash=_h("blk", block),
        block_timestamp_utc=_ts(minute), transaction_index=0, log_index=0,
        transaction_hash=_h(f"tx{scn.tag}", tx_seq),
        sender=scn.sender_addr, target=TOKEN,
        method_selector=SELECTOR_ERC20_TRANSFER,
        calldata_class="erc20_transfer", nonce=11,
        asset_contract=TOKEN, asset_amount=TOKEN_AMOUNT,
        actual_gas_used=51_000, actual_gas_cost=102_000_000_000_000,
        effective_gas_price=2_000_000_000, success=True,
    )


def _eth_topup(scn: _Scenario, block: int, minute: int,
               tx_seq: int) -> Observation:
    """Gas allowance the sender supplies. B0 and B1 only -- B2 is sponsored."""
    return Observation(
        event_type="native_transfer", outcome="success", asset_type="native",
        scenario_id=scn.tag, observer_tier="A0",
        block_number=block, block_hash=_h("blk", block),
        block_timestamp_utc=_ts(minute), transaction_index=1, log_index=None,
        transaction_hash=_h(f"tx{scn.tag}", tx_seq),
        sender=scn.sender_addr, target=scn.stealth_addr,
        calldata_class="native_value_only", nonce=12,
        asset_amount=ETH_TOPUP,
        actual_gas_used=21_000, actual_gas_cost=42_000_000_000_000,
        effective_gas_price=2_000_000_000, success=True,
    )


def _ground_truth(scn: _Scenario, baseline_id: str, action_ref: str,
                  anchors: Dict[str, Any]) -> GroundTruth:
    r2 = RelationLabel(relation="R2", status="not_applicable")
    return GroundTruth(
        scenario_id=scn.tag,
        subject_kind="operation",
        actor_id=scn.actor_handle,
        established_wallet_id=scn.established_handle,
        funding_wallet_id=scn.funder_handle,
        asset_sender_id=scn.sender_handle,
        stealth_account_id=scn.stealth_handle,
        credit_id=None,
        issuance_id=None,
        r1=RelationLabel("R1", "observed", subject_ref=action_ref,
                         true_value=scn.funder_handle,
                         candidate_set_id="w1-funders"),
        r2=r2,
        r3=RelationLabel("R3", "observed", subject_ref=action_ref,
                         true_value=scn.actor_handle,
                         candidate_set_id="w1-actors"),
        public_anchors=anchors,
    )


def _build_b0():
    obs: List[Observation] = []
    gts: List[GroundTruth] = []
    for scn in _scenarios("B0"):
        base_block = 100 + scn.idx * 10
        obs.append(_asset_arrival(scn, base_block, 10 + scn.idx, 1))
        obs.append(_eth_topup(scn, base_block, 10 + scn.idx, 2))
        action_tx = _h(f"tx{scn.tag}", 3)
        obs.append(Observation(
            event_type="asset_transfer", outcome="success", asset_type="erc20",
            scenario_id=scn.tag, observer_tier="A0",
            block_number=base_block + 2, block_hash=_h("blk", base_block + 2),
            block_timestamp_utc=_ts(20 + scn.idx), transaction_index=0,
            log_index=0, transaction_hash=action_tx,
            sender=scn.stealth_addr, target=TOKEN,
            method_selector=SELECTOR_ERC20_TRANSFER,
            calldata_class="erc20_transfer", nonce=0,
            asset_contract=TOKEN, asset_amount=TOKEN_AMOUNT,
            actual_gas_used=51_000, actual_gas_cost=102_000_000_000_000,
            effective_gas_price=2_000_000_000, success=True,
        ))
        gts.append(_ground_truth(
            scn, "B0", action_ref=action_tx,
            anchors={
                "stealth_account_address": scn.stealth_addr,
                "funding_address": scn.sender_addr,
                "asset_sender_address": scn.sender_addr,
                "established_wallet_address": scn.established_addr,
                "transaction_hash": action_tx,
                "userop_hash": None,
                "public_event_record_ids": [],
            }))
    # B0 has no bundler at all: no A2 observations exist to record.
    return obs, [], gts


def _aa_action(scn: _Scenario, *, with_paymaster: bool, block: int,
               minute: int, uo: UserOpObservation) -> List[Observation]:
    """The EntryPoint event plus the ERC-20 log from the same transaction."""
    tx = _h(f"tx{scn.tag}", 4)
    common = dict(
        scenario_id=scn.tag, block_number=block, block_hash=_h("blk", block),
        block_timestamp_utc=_ts(minute), transaction_index=0,
        transaction_hash=tx, sender=scn.stealth_addr,
    )
    return [
        Observation(
            event_type="user_operation_event", outcome="success",
            asset_type="none", observer_tier="A1", log_index=1,
            target=TOKEN, paymaster=PAYMASTER if with_paymaster else None,
            bundler_beneficiary=BENEFICIARY,
            method_selector=SELECTOR_ACCOUNT_EXECUTE,
            calldata_class="account_execute", nonce=0, userop=uo,
            actual_gas_used=268_000, actual_gas_cost=536_000_000_000_000,
            effective_gas_price=2_000_000_000, success=True, **common,
        ),
        Observation(
            event_type="asset_transfer", outcome="success", asset_type="erc20",
            observer_tier="A0", log_index=0, target=TOKEN,
            method_selector=SELECTOR_ERC20_TRANSFER,
            calldata_class="erc20_transfer",
            asset_contract=TOKEN, asset_amount=TOKEN_AMOUNT,
            success=True, **common,
        ),
    ]


def _build_b1():
    obs: List[Observation] = []
    bundler: List[BundlerObservation] = []
    gts: List[GroundTruth] = []
    for scn in _scenarios("B1"):
        base_block = 200 + scn.idx * 10
        obs.append(_asset_arrival(scn, base_block, 10 + scn.idx, 1))
        obs.append(_eth_topup(scn, base_block, 10 + scn.idx, 2))
        uo = _userop(scn, with_paymaster=False, seq=1)
        obs.extend(_aa_action(scn, with_paymaster=False, block=base_block + 2,
                              minute=20 + scn.idx, uo=uo))
        bundler.append(BundlerObservation(
            bundler_id="bundler-alpha", userop_hash=uo.userop_hash,
            sender=scn.stealth_addr, nonce=0, scenario_id=scn.tag,
            receive_timestamp_utc=_ts(19 + scn.idx, 10),
            simulation_timestamp_utc=_ts(19 + scn.idx, 11),
            simulation_result="accepted", replacement_lineage=[],
            inclusion_timestamp_utc=_ts(20 + scn.idx, 2),
            bundle_transaction_hash=_h(f"tx{scn.tag}", 4),
            rpc_endpoint_id="local-anvil",
        ))
        gts.append(_ground_truth(
            scn, "B1", action_ref=uo.userop_hash,
            anchors={
                "stealth_account_address": scn.stealth_addr,
                "funding_address": scn.sender_addr,
                "asset_sender_address": scn.sender_addr,
                "established_wallet_address": scn.established_addr,
                "transaction_hash": _h(f"tx{scn.tag}", 4),
                "userop_hash": uo.userop_hash,
                "public_event_record_ids": [],
            }))
    return obs, bundler, gts


def _build_b2():
    obs: List[Observation] = []
    bundler: List[BundlerObservation] = []
    gts: List[GroundTruth] = []
    for scn in _scenarios("B2"):
        base_block = 300 + scn.idx * 10
        # B2 receives the asset but no ETH: the Paymaster pays for gas. That
        # missing top-up transaction is itself an observable difference from
        # B0/B1, which is exactly the kind of effect D1 measures.
        obs.append(_asset_arrival(scn, base_block, 10 + scn.idx, 1))

        if scn.idx == 1:
            # A rejected attempt, then a fee replacement. Kept, not discarded.
            rejected = _userop(scn, with_paymaster=True, seq=8,
                               max_fee=1_000_000_000)
            obs.append(Observation(
                event_type="user_operation_event", outcome="not_included",
                asset_type="none", scenario_id=scn.tag, observer_tier="A1",
                sender=scn.stealth_addr, target=TOKEN, paymaster=PAYMASTER,
                method_selector=SELECTOR_ACCOUNT_EXECUTE,
                calldata_class="account_execute", nonce=0, userop=rejected,
            ))
            bundler.append(BundlerObservation(
                bundler_id="bundler-alpha", userop_hash=rejected.userop_hash,
                sender=scn.stealth_addr, nonce=0, scenario_id=scn.tag,
                receive_timestamp_utc=_ts(18, 30),
                simulation_timestamp_utc=_ts(18, 31),
                simulation_result="rejected", rejection_category="fee_too_low",
                rejection_message_class="bundler_policy",
                replacement_lineage=[], rpc_endpoint_id="local-anvil",
            ))
            lineage = [rejected.userop_hash]
            attempt = 2
        else:
            lineage = []
            attempt = 1

        uo = _userop(scn, with_paymaster=True, seq=1)
        obs.extend(_aa_action(scn, with_paymaster=True, block=base_block + 2,
                              minute=20 + scn.idx, uo=uo))
        obs.append(Observation(
            event_type="paymaster_event", outcome="success", asset_type="native",
            scenario_id=scn.tag, observer_tier="A0",
            block_number=base_block + 2, block_hash=_h("blk", base_block + 2),
            block_timestamp_utc=_ts(20 + scn.idx), transaction_index=0,
            log_index=2, transaction_hash=_h(f"tx{scn.tag}", 4),
            sender=PAYMASTER, target=ENTRYPOINT, paymaster=PAYMASTER,
            calldata_class="paymaster_deposit",
            asset_amount=536_000_000_000_000, success=True,
        ))
        bundler.append(BundlerObservation(
            bundler_id="bundler-alpha", userop_hash=uo.userop_hash,
            sender=scn.stealth_addr, nonce=0, scenario_id=scn.tag,
            submission_attempt=attempt,
            receive_timestamp_utc=_ts(19 + scn.idx, 10),
            simulation_timestamp_utc=_ts(19 + scn.idx, 11),
            simulation_result="accepted", replacement_lineage=lineage,
            inclusion_timestamp_utc=_ts(20 + scn.idx, 2),
            bundle_transaction_hash=_h(f"tx{scn.tag}", 4),
            rpc_endpoint_id="local-anvil",
        ))
        gts.append(_ground_truth(
            scn, "B2", action_ref=uo.userop_hash,
            anchors={
                "stealth_account_address": scn.stealth_addr,
                "funding_address": PAYMASTER,
                "asset_sender_address": scn.sender_addr,
                "established_wallet_address": scn.established_addr,
                "transaction_hash": _h(f"tx{scn.tag}", 4),
                "userop_hash": uo.userop_hash,
                "public_event_record_ids": [],
            }))
    return obs, bundler, gts
