"""Canonical workload W1-cold as synthetic observations for B0, B1,
B2-Allowlist and B2-Signature.

Schema 3.0.0 revision: "B2" is split into B2-Allowlist (public on-chain
allowlist row before the operation) and B2-Signature (no allowlist row; the
sponsor's authorization travels inside paymasterAndData), and the workload is
W1-cold. B2-Signature's rejected attempt carries a wrong sponsor signature
(EntryPoint AA34), the rejection the real in-repo bundler produces for it.

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
* B2's second scenario includes a UserOperation rejected by the Paymaster
  (sent before the account was allowlisted) and then resubmitted. The
  rejection is recorded, not dropped.

Every address and hash below is fabricated fixture data on chain id 31337.

Schema 2.0.0 revision (2026-09-14). These fixtures were first written before
any real baseline existed. The first real B0/B1/B2 runs
(experiments/workloads/w1) showed several of their assumptions were wrong;
the fixtures now follow the real event structure, and each correction is
listed in docs/w1-baselines.md Sec. 14:

1. mined UserOperation rows are observer tier A0, not A1;
2. the A2 bundle field is the pre-inclusion association
   (submitted_bundle_transaction_hash + bundle_submission_timestamp_utc), not
   the mined hash;
3. B2's per-operation "paymaster_event" deposit-decrease row is removed:
   EntryPoint v0.9.0 emits no log when it debits or refunds a deposit;
4. B2's rejected operation has no public "not_included" row: it went to a
   private bundler with no public mempool, so no A0/A1 observer saw it;
5. B2's fee-too-low rejection + replacement is replaced by the rejection the
   real in-repo bundler actually produces (Paymaster validation revert), since
   that bundler implements no fee policy or replacement;
6. the bundle transaction row, the account_deployment row, B1's
   entrypoint_deposit row and B2's allowlist paymaster_event row -- all
   present on chain in real runs -- are added;
7. the EntryPoint placeholder is no longer the canonical v0.7 EntryPoint
   address mislabelled 0.9.0; all addresses are lowercase;
8. the B2 paymaster postOp gas limit is 0, as for the real ObservablePaymaster.
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
ENTRYPOINT = "0x0e90000000000000000000000000000000000009"
ENTRYPOINT_VERSION = "0.9.0"
TOKEN = "0x5fbdb2315678afecb367f032d93f642f64180aa3"
DESTINATION = "0xdddddddddddddddddddddddddddddddddddddddd"
FACTORY = "0xfaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
PAYMASTER = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
SIG_PAYMASTER = "0xb5160000000000000000000000000000000000b2"
BENEFICIARY = "0xbeee000000000000000000000000000000000001"
BUNDLER_EOA = "0xb0b0000000000000000000000000000000000001"
SPONSOR_OPERATOR = "0x5905000000000000000000000000000000000001"

ASSET_SENDER_A = "0xaaaa000000000000000000000000000000000001"
ASSET_SENDER_B = "0xaaaa000000000000000000000000000000000002"
STEALTH_A = "0x57ea1a0000000000000000000000000000000001"
STEALTH_B = "0x57ea1b0000000000000000000000000000000002"
ESTABLISHED_A = "0xeeee000000000000000000000000000000000001"
ESTABLISHED_B = "0xeeee000000000000000000000000000000000002"

SELECTOR_ERC20_TRANSFER = "0xa9059cbb"
SELECTOR_ACCOUNT_EXECUTE = "0xb61d27f6"
SELECTOR_HANDLE_OPS = "0x765e827f"
SELECTOR_SET_SPONSORED = "0xf935d0b0"

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
    sponsored = baseline_id.startswith("B2")
    actor_b = "actor_7c1e" if sponsored else "actor_9d42"
    established_b = ("wallet_7c1e_main" if sponsored
                     else "wallet_9d42_main")
    funder_b = "funder_sponsor" if sponsored else "funder_9d42"
    funder_a = "funder_sponsor" if sponsored else "funder_7c1e"
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
        paymaster_verification_gas_limit=60_000 if with_paymaster else None,
        paymaster_post_op_gas_limit=0 if with_paymaster else None,
    )


def build(baseline_id: str) -> Tuple[List[Observation], List[BundlerObservation],
                                     List[GroundTruth]]:
    """Return (public observations, bundler observations, ground truth)."""
    if baseline_id == "B0":
        return _build_b0()
    if baseline_id == "B1":
        return _build_b1()
    if baseline_id in ("B2-Allowlist", "B2-Signature"):
        return _build_b2(baseline_id)
    raise ValueError(
        f"no W1 fixture for {baseline_id!r}; fixtures exist for B0, B1, B2-Allowlist and B2-Signature "
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
               minute: int, uo: UserOpObservation,
               paymaster: str = PAYMASTER) -> List[Observation]:
    """The bundle transaction and its W1-relevant logs, in real log order.

    Mirrors experiments/workloads/w1/recording.py: bundle tx row, then
    AccountDeployed, (B1 only) the account's prefund Deposited, the ERC-20
    Transfer, and UserOperationEvent.
    """
    tx = _h(f"tx{scn.tag}", 4)
    common = dict(
        scenario_id=scn.tag, observer_tier="A0", block_number=block,
        block_hash=_h("blk", block), block_timestamp_utc=_ts(minute),
        transaction_index=0, transaction_hash=tx,
    )
    pm = paymaster if with_paymaster else None
    rows = [
        Observation(
            event_type="eoa_transaction", outcome="success", asset_type="none",
            sender=BUNDLER_EOA, target=ENTRYPOINT, bundler_beneficiary=BENEFICIARY,
            method_selector=SELECTOR_HANDLE_OPS,
            calldata_class="entrypoint_handle_ops", nonce=scn.idx,
            actual_gas_used=296_000, actual_gas_cost=592_000_000_000_000,
            effective_gas_price=2_000_000_000, success=True, **common,
        ),
        Observation(
            event_type="account_deployment", outcome="success", asset_type="none",
            log_index=3, sender=scn.stealth_addr, target=FACTORY, paymaster=pm,
            calldata_class="account_deploy", userop=uo, success=True, **common,
        ),
    ]
    if not with_paymaster:
        rows.append(Observation(
            event_type="entrypoint_deposit", outcome="success", asset_type="native",
            log_index=4, target=ENTRYPOINT, subject_account=scn.stealth_addr,
            asset_amount=1_060_000_000_000_000, success=True, **common,
        ))
    rows += [
        Observation(
            event_type="asset_transfer", outcome="success", asset_type="erc20",
            log_index=6 if not with_paymaster else 5, sender=scn.stealth_addr,
            target=TOKEN, method_selector=SELECTOR_ERC20_TRANSFER,
            calldata_class="erc20_transfer", asset_contract=TOKEN,
            asset_amount=TOKEN_AMOUNT, success=True, **common,
        ),
        Observation(
            event_type="user_operation_event", outcome="success",
            asset_type="none", log_index=7 if not with_paymaster else 6,
            sender=scn.stealth_addr, target=TOKEN, paymaster=pm,
            bundler_beneficiary=BENEFICIARY,
            method_selector=SELECTOR_ACCOUNT_EXECUTE,
            calldata_class="account_execute", nonce=0, userop=uo,
            actual_gas_used=282_000, actual_gas_cost=564_000_000_000_000,
            effective_gas_price=2_000_000_000, success=True, **common,
        ),
    ]
    return rows


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
            bundle_submission_timestamp_utc=_ts(19 + scn.idx, 12),
            submitted_bundle_transaction_hash=_h(f"tx{scn.tag}", 4),
            inclusion_timestamp_utc=_ts(20 + scn.idx, 2),
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


def _build_b2(baseline_id: str):
    allowlist = baseline_id == "B2-Allowlist"
    pm_addr = PAYMASTER if allowlist else SIG_PAYMASTER
    obs: List[Observation] = []
    bundler: List[BundlerObservation] = []
    gts: List[GroundTruth] = []
    for scn in _scenarios(baseline_id):
        base_block = 300 + scn.idx * 10
        # B2 receives the asset but no ETH: the Paymaster pays for gas.
        obs.append(_asset_arrival(scn, base_block, 10 + scn.idx, 1))
        uo = _userop(scn, with_paymaster=True, seq=1)

        attempt = 1
        if scn.idx == 1:
            # B2-Allowlist: submitted before the account was allowlisted
            # (AA33). B2-Signature: carried a wrong sponsor signature (AA34).
            # Recorded in the A2 stream only -- no public observer saw a
            # privately submitted operation.
            bundler.append(BundlerObservation(
                bundler_id="bundler-alpha", userop_hash=uo.userop_hash,
                sender=scn.stealth_addr, nonce=0, scenario_id=scn.tag,
                receive_timestamp_utc=_ts(15, 30),
                simulation_timestamp_utc=_ts(15, 31),
                simulation_result="rejected",
                rejection_category="paymaster_validation_revert",
                rejection_message_class="entrypoint_revert",
                replacement_lineage=[], rpc_endpoint_id="local-anvil",
            ))
            attempt = 2

        # The public allowlist entry: an ordinary allowlist Paymaster names
        # the sponsored account on chain before the operation. B2-Signature
        # has no such transaction.
        if allowlist:
            obs.append(Observation(
                event_type="paymaster_event", outcome="success", asset_type="none",
                scenario_id=scn.tag, observer_tier="A0",
                block_number=base_block + 1, block_hash=_h("blk", base_block + 1),
                block_timestamp_utc=_ts(16 + scn.idx), transaction_index=0,
                log_index=0, transaction_hash=_h(f"tx{scn.tag}", 2),
                sender=SPONSOR_OPERATOR, target=PAYMASTER, paymaster=PAYMASTER,
                subject_account=scn.stealth_addr,
                method_selector=SELECTOR_SET_SPONSORED,
                calldata_class="paymaster_policy", nonce=scn.idx + 1,
                actual_gas_used=47_900, actual_gas_cost=95_800_000_000_000,
                effective_gas_price=2_000_000_000, success=True,
            ))
        obs.extend(_aa_action(scn, with_paymaster=True, block=base_block + 2,
                              minute=20 + scn.idx, uo=uo, paymaster=pm_addr))
        bundler.append(BundlerObservation(
            bundler_id="bundler-alpha", userop_hash=uo.userop_hash,
            sender=scn.stealth_addr, nonce=0, scenario_id=scn.tag,
            submission_attempt=attempt,
            receive_timestamp_utc=_ts(19 + scn.idx, 10),
            simulation_timestamp_utc=_ts(19 + scn.idx, 11),
            simulation_result="accepted", replacement_lineage=[],
            bundle_submission_timestamp_utc=_ts(19 + scn.idx, 12),
            submitted_bundle_transaction_hash=_h(f"tx{scn.tag}", 4),
            inclusion_timestamp_utc=_ts(20 + scn.idx, 2),
            rpc_endpoint_id="local-anvil",
        ))
        gts.append(_ground_truth(
            scn, baseline_id, action_ref=uo.userop_hash,
            anchors={
                "stealth_account_address": scn.stealth_addr,
                "funding_address": pm_addr,
                "asset_sender_address": scn.sender_addr,
                "established_wallet_address": scn.established_addr,
                "transaction_hash": _h(f"tx{scn.tag}", 4),
                "userop_hash": uo.userop_hash,
                "public_event_record_ids": [],
            }))
    return obs, bundler, gts
