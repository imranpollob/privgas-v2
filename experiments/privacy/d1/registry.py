"""Canonical D1 feature registry: every public observation -> T, AA or G.

NEUTRAL module (no data access; importable from the attack and the evaluation
side). The human-readable version is generated into
``docs/d1-feature-registry.md`` (``python3 -m experiments.privacy.d1.registry
--write``); a test fails if the two drift.

Families (docs/research-plan.md Sec. 6; Prompt 4 Sec. 3)
-------------------------------------------------------
T   application / stealth-workflow trace: exists independently of how gas is paid.
AA  account-abstraction trace: caused by ERC-4337 smart-account execution, not
    specifically by the gas mechanism.
G   gas-mechanism trace: caused specifically by how gas is funded or sponsored
    (B0/B1 sender ETH funding; B2 Paymaster funding and authorization; B3
    admission, Bootstrap, CreditPool, root, nullifier, proof).

Families are assigned by CAUSAL ORIGIN, never by attack usefulness. Two
decision rules, applied in order:

1. **Row origin.** A row belongs to the transaction / UserOperation that emitted
   it. Operations and transactions that exist only because of the gas mechanism
   (sender ETH-allowance transfers, Paymaster deposits, ``setSponsored``,
   ``announceAndFund``, the whole B3 Bootstrap operation) are G-origin: every row
   they emit is G.
2. **Counterfactual value** (for the rows of the W1 application operation, which
   mixes all three): a field is G if its value would change when ONLY the gas
   mechanism is swapped among the matched baselines B1 / B2-Signature / B3 (same
   actor, account, call); AA if it exists and keeps its value for every AA
   baseline; T if it is the application call's own content.

Values co-emitted in one transaction (block number, timestamp, transaction
index) are available through every row of that transaction; each feature reads
them from the rows of its own declared family.

Genuinely ambiguous cases are NOT silently resolved: they carry an
``ambiguity`` note, and the ``field_kind`` ALTERNATIVE CONVENTION reassigns
them. Analyses sensitive to them are run under both conventions:

* ``primary``    -- rules 1 and 2 as stated.
* ``field_kind`` -- AA-shaped fields keep family AA even inside a G-origin
  operation (Bootstrap sender, nonce, initCode/deployment, account gas limits,
  bundle metadata), and the B3 stealth announcement is T (the underlying stealth
  workflow) rather than G.

Auxiliary attacker knowledge (``AUX``): the R3 established-wallet directory. It
is not an on-chain observation; every model may use it.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

FAMILIES = ("T", "AA", "G")
CONVENTIONS = ("primary", "field_kind")
SUBFAMILIES = ("eq", "timing", "gas", "pm", "structure")

#: Subfamily meaning (used for ablations).
SUBFAMILY_DOC = {
    "eq": "address / equality relations (same account, direct value edge)",
    "timing": "block order, timestamps, delays, ranks, intervening events",
    "gas": "gas limits, preVerificationGas, gas used, fee amounts",
    "pm": "Paymaster / proof metadata (roots, commitments, nullifiers, proof fields)",
    "structure": "candidate-level structure (fan-out of a funding wallet)",
}

# --------------------------------------------------------------------------------------
# Row kinds (content-derived from public_events; experiments/privacy/d1/attack/extract.py)
# --------------------------------------------------------------------------------------

ROW_KINDS: Dict[str, str] = {
    "deploy": "eoa_transaction / contract_creation (setup; identical in every baseline)",
    "mint": "asset_transfer emitted by the token constructor (setup)",
    "eth_tx": "native_transfer / native_value_only, transaction level",
    "vmin_forward": "native_transfer / native_value_only emitted by AnnouncementRegistry (B3)",
    "fee_burn": "native_transfer / fee_burn (B3)",
    "pm_deposit_tx": "paymaster_event / paymaster_deposit (Paymaster funding transaction)",
    "pm_deposit_log": "entrypoint_deposit following a Paymaster funding transaction",
    "prefund_deposit_log": "entrypoint_deposit inside a bundle (B1 account prefund)",
    "erc20_tx": "asset_transfer / erc20_transfer, transaction level",
    "erc20_in_op": "asset_transfer inside a bundle (the application call's transfer)",
    "allowlist_tx": "paymaster_event / paymaster_policy (B2-Allowlist setSponsored)",
    "announce_tx": "eoa_transaction / stealth_announce_and_fund (B3 admission)",
    "announce_log": "stealth_announcement (B3 MockAnnouncer AnnounceCalled)",
    "eligibility_log": "sponsorship_eligibility (B3 EligibilityMirrored)",
    "bundle_tx@app": "eoa_transaction / entrypoint_handle_ops carrying the application op",
    "bundle_tx@bootstrap": "eoa_transaction / entrypoint_handle_ops carrying a B3 Bootstrap op",
    "deploy_log@app": "account_deployment inside the application op (B1/B2)",
    "deploy_log@bootstrap": "account_deployment inside a B3 Bootstrap op",
    "uoe@app": "user_operation_event of the application op",
    "uoe@bootstrap": "user_operation_event of a B3 Bootstrap op",
    "bootstrap_sponsored_log": "paymaster_event / paymaster_sponsorship (B3 BootstrapSponsored)",
    "root_update_log": "privacy_pool_event / pool_root_update (B3 RootMirrored)",
    "pool_deposit_log": "privacy_pool_event / pool_deposit (B3 CreditPool Deposited)",
    "pool_redeem_log": "privacy_pool_event / pool_redeem (B3 CreditSpent + proof)",
}

#: Envelope / constant fields: identical for every row of a run or pure bookkeeping;
#: never features. (record_id, seq, ... are recorder identities.)
CONTEXT_FIELDS = ("schema_version", "stream", "experiment_id", "run_id", "record_id", "seq",
                  "baseline_id", "workload_id", "scenario_id", "software_revision",
                  "data_origin", "recorded_at_utc", "observer_tier", "chain_id",
                  "entrypoint_version", "amount_bucket", "asset_token_id", "asset_type",
                  "event_type", "calldata_class", "trace_phase", "block_hash", "pool_id")

VARYING_FIELDS = (
    "block_number", "block_timestamp_utc", "transaction_index", "log_index",
    "transaction_hash", "userop_hash", "entrypoint_address", "factory", "sender", "paymaster",
    "target", "subject_account", "bundler_beneficiary", "method_selector", "nonce",
    "asset_contract", "asset_amount", "max_fee_per_gas", "max_priority_fee_per_gas",
    "verification_gas_limit", "call_gas_limit", "pre_verification_gas",
    "paymaster_verification_gas_limit", "paymaster_post_op_gas_limit", "actual_gas_used",
    "actual_gas_cost", "effective_gas_price", "success", "revert_reason_class", "outcome",
    "commitment", "merkle_root", "nullifier", "proof_metadata")

TIMING_FIELDS = ("block_number", "block_timestamp_utc", "transaction_index", "log_index",
                 "transaction_hash", "outcome", "success", "revert_reason_class")
AA_SHAPED = ("userop_hash", "entrypoint_address", "factory", "sender", "target",
             "bundler_beneficiary", "method_selector", "nonce", "max_fee_per_gas",
             "max_priority_fee_per_gas", "verification_gas_limit", "call_gas_limit",
             "effective_gas_price") + TIMING_FIELDS
PAYMASTER_FIELDS = ("paymaster", "paymaster_verification_gas_limit",
                    "paymaster_post_op_gas_limit")


@dataclass(frozen=True)
class FieldClass:
    row_kind: str
    field: str
    family: str
    rationale: str
    ambiguity: Optional[str] = None
    alt_family: Optional[str] = None  # family under the field_kind convention

    def family_under(self, convention: str) -> str:
        if convention == "field_kind" and self.alt_family is not None:
            return self.alt_family
        return self.family


def _build() -> Dict[Tuple[str, str], FieldClass]:
    out: List[FieldClass] = []
    V = VARYING_FIELDS

    out += [FieldClass("deploy", f, "T",
                       "setup deployment; identical for every baseline and actor. Family of the "
                       "deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and "
                       "B3 contracts -> G. Recorded as T for the row (not actor-specific; no "
                       "attack feature reads it).",
                       "the row's family depends on WHICH contract is deployed; no feature uses it")
            for f in V]
    out += [FieldClass("mint", f, "T", "token supply minted to the treasury (setup)") for f in V]
    out += [FieldClass(
        "eth_tx", f, "G",
        "a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge "
        "(sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1.",
        "setup faucet transfers share this row kind; they fund the asset senders' own "
        "application transactions (T-like environment). Features only use eth_tx rows whose "
        "recipient is an operation's gas payer.") for f in V]
    out += [FieldClass("vmin_forward", f, "G",
                       "B3 admission: AnnouncementRegistry forwards vMin to the announced account "
                       "(Sybil-resistance deposit; pays no gas)") for f in V]
    out += [FieldClass("fee_burn", f, "G", "B3 admission: non-refundable fee burned") for f in V]
    out += [FieldClass("pm_deposit_tx", f, "G", "Paymaster funding by the sponsor wallet")
            for f in V]
    out += [FieldClass("pm_deposit_log", f, "G", "Paymaster EntryPoint deposit event") for f in V]
    out += [FieldClass("prefund_deposit_log", f, "G",
                       "B1 account prefund credited to the EntryPoint deposit (sender-funded gas)")
            for f in V]
    out += [FieldClass("erc20_tx", f, "T",
                       "ERC-20 transfer transaction: asset delivery (sender -> recipient), token "
                       "distribution to asset senders (setup), and the B0 application action. "
                       "Its fee fields are paid by the plain transaction sender in every "
                       "baseline (asset sender; B0 recipient EOA).",
                       "B0 action: gas used/cost of the recipient EOA's own transaction is both "
                       "application execution and the B0 gas payment; kept T (no G counterpart "
                       "field exists in B0)" if f in ("actual_gas_used", "actual_gas_cost",
                                                      "effective_gas_price") else None)
            for f in V]
    out += [FieldClass("erc20_in_op", f, "T",
                       "the W1 application call's token transfer (account -> destination), "
                       "byte-identical in B1/B2/B3") for f in V]
    out += [FieldClass("allowlist_tx", f, "G", "B2-Allowlist public sponsor authorization")
            for f in V]
    ann = ("W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the "
           "pilot is B3's, carried by the sponsorship admission call. Under the counterfactual "
           "rule it is G; conceptually a stealth announcement belongs to the stealth workflow "
           "(T). field_kind convention: T.")
    out += [FieldClass("announce_tx", f, "G",
                       "B3 announceAndFund: admission value (vMin + fee) and announcement in one "
                       "transaction",
                       ann if f in ("sender", "subject_account") + TIMING_FIELDS else None,
                       "T" if f in ("sender", "subject_account") + TIMING_FIELDS else None)
            for f in V]
    out += [FieldClass("announce_log", f, "G", "B3 MockAnnouncer AnnounceCalled log", ann, "T")
            for f in V]
    out += [FieldClass("eligibility_log", f, "G", "B3 eligibility mirrored into the Paymasters")
            for f in V]

    # --- bundles, deployment, UserOperationEvent -----------------------------------
    boot_amb = ("an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only "
                "for sponsorship). Row origin -> G; field_kind convention -> AA.")
    for rk_app, rk_boot, fields in (
            ("bundle_tx@app", "bundle_tx@bootstrap", V),
            ("deploy_log@app", "deploy_log@bootstrap", V),
            ("uoe@app", "uoe@bootstrap", V)):
        for f in fields:
            # application op: rule 2 (counterfactual among B1 / B2-Signature / B3)
            if f in PAYMASTER_FIELDS:
                fam, why, amb = "G", "Paymaster address / Paymaster gas limits", None
            elif f == "pre_verification_gas":
                fam, why = "G", ("counterfactual: follows paymasterAndData length "
                                 "(B1 42,813 / B2-Signature 44,733 / B3 48,837 in W1)")
                amb = "a generic UserOperation field whose VALUE is set by the gas mechanism"
            elif f in ("actual_gas_used", "actual_gas_cost"):
                fam, why = "G", ("counterfactual: includes Paymaster validation (ecrecover / "
                                 "Groth16) and PVG, so it differs by mechanism")
                amb = ("also contains application execution (T) and account validation (AA); "
                       "not separable from public data")
            elif f == "nonce" and rk_app == "uoe@app":
                fam, why = "G", ("counterfactual: the B3 Spend uses nonce 1 because the "
                                 "Bootstrap consumed nonce 0 (B1/B2 and the B4-CrossAccount "
                                 "Spend: nonce 0)")
                amb = "AA-shaped field whose value is set by the gas mechanism"
            elif f == "factory" and rk_app in ("uoe@app", "deploy_log@app"):
                fam, why = "G", ("counterfactual: B1/B2 and B4-CrossAccount deploy the account in "
                                 "the application op, B3 in the Bootstrap op")
                amb = "account deployment is AA; its placement is caused by the gas mechanism"
            elif f in ("target", "asset_contract", "asset_amount") and rk_app == "uoe@app":
                fam, why, amb = "T", "the application call target (token)", None
            else:
                fam, why, amb = "AA", "ERC-4337 execution metadata, same for every AA baseline", None
            alt = ("AA" if f in ("nonce", "factory") and fam == "G" else None)
            out.append(FieldClass(rk_app, f, fam, why, amb, alt))
            # bootstrap op: rule 1 (G origin)
            b_alt = None
            if f in AA_SHAPED:
                b_alt = "AA"
            out.append(FieldClass(rk_boot, f, "G",
                                  "field of the B3 Bootstrap operation (exists only for "
                                  "sponsorship)", boot_amb if b_alt else None, b_alt))

    out += [FieldClass("bootstrap_sponsored_log", f, "G", "BootstrapPaymaster log naming the account")
            for f in V]
    out += [FieldClass("root_update_log", f, "G", "CreditPaymaster RootMirrored") for f in V]
    out += [FieldClass("pool_deposit_log", f, "G", "CreditPool Deposited: commitment, root, depositor")
            for f in V]
    out += [FieldClass("pool_redeem_log", f, "G",
                       "CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata")
            for f in V]
    reg = {(c.row_kind, c.field): c for c in out}
    assert len(reg) == len(out), "duplicate registry entries"
    return reg


FIELD_REGISTRY: Dict[Tuple[str, str], FieldClass] = _build()


def field_family(row_kind: str, field: str, convention: str = "primary") -> str:
    if row_kind == "AUX":
        return "AUX"
    return FIELD_REGISTRY[(row_kind, field)].family_under(convention)


# --------------------------------------------------------------------------------------
# Derived attack features
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Feature:
    name: str
    relation: str
    subfamily: str
    sources: Tuple[Tuple[str, str], ...]   # (row_kind, field); ("AUX", ...) for auxiliary
    description: str
    baselines: Tuple[str, ...] = ("B0", "B1", "B2-Signature", "B2-Allowlist", "B3-PrivGas-v1",
                                  "B4-CrossAccount")

    def families(self, convention: str = "primary") -> FrozenSet[str]:
        fams = {field_family(rk, f, convention) for rk, f in self.sources}
        fams.discard("AUX")
        return frozenset(fams)

    def label(self, convention: str = "primary") -> str:
        return "+".join(f for f in FAMILIES if f in self.families(convention)) or "AUX"


B0B1 = ("B0", "B1")
AA_B = ("B1", "B2-Signature", "B2-Allowlist", "B3-PrivGas-v1", "B4-CrossAccount")
B3_ = ("B3-PrivGas-v1",)
#: Baselines running the frozen credit contracts. B4-CrossAccount reuses every B3 R2
#: feature unchanged (docs/d1-b4-results.md); none was added for it.
CREDIT_ = ("B3-PrivGas-v1", "B4-CrossAccount")

FEATURES: Tuple[Feature, ...] = (
    # ---------------- R1: economic funder <-> operation (B0, B1 only) ----------------
    Feature("r1_token_edge", "R1", "eq",
            (("erc20_tx", "sender"), ("erc20_tx", "subject_account")),
            "candidate sent W1 tokens directly to the EOA that sends the B0 action transaction",
            ("B0",)),
    Feature("r1_token_edge_op", "R1", "eq",
            (("erc20_tx", "sender"), ("erc20_tx", "subject_account"), ("erc20_in_op", "sender")),
            "candidate sent W1 tokens directly to the account whose application transfer the "
            "op made", ("B1",)),
    Feature("r1_token_edge_aa", "R1", "eq",
            (("erc20_tx", "sender"), ("erc20_tx", "subject_account"), ("uoe@app", "sender")),
            "candidate sent W1 tokens to the UserOperation sender", ("B1",)),
    Feature("r1_eth_edge_t", "R1", "eq",
            (("eth_tx", "sender"), ("eth_tx", "target"), ("erc20_tx", "sender")),
            "candidate sent ETH directly to the account that performs the application transfer "
            "(B0: action tx sender)", ("B0",)),
    Feature("r1_eth_edge_t_op", "R1", "eq",
            (("eth_tx", "sender"), ("eth_tx", "target"), ("erc20_in_op", "sender")),
            "candidate sent ETH directly to the account whose application transfer the op made",
            ("B1",)),
    Feature("r1_eth_edge_aa", "R1", "eq",
            (("eth_tx", "sender"), ("eth_tx", "target"), ("uoe@app", "sender")),
            "candidate sent ETH directly to the UserOperation sender", ("B1",)),
    Feature("r1_eth_edge_g", "R1", "eq",
            (("eth_tx", "sender"), ("eth_tx", "target"), ("prefund_deposit_log", "subject_account")),
            "candidate sent ETH to the account credited by the op's prefund Deposited event",
            ("B1",)),
    Feature("r1_eth_amount_matches_prefund", "R1", "gas",
            (("eth_tx", "asset_amount"), ("uoe@app", "pre_verification_gas"),
             ("uoe@app", "verification_gas_limit"), ("uoe@app", "call_gas_limit"),
             ("uoe@app", "max_fee_per_gas")),
            "candidate's ETH transfer amount equals the op's required prefund "
            "(verificationGasLimit + callGasLimit + PVG) * maxFeePerGas", ("B1",)),
    Feature("r1_eth_fanout", "R1", "structure", (("eth_tx", "sender"), ("eth_tx", "target")),
            "log(1 + number of distinct ETH recipients of the candidate) (faucet-like fan-out)",
            B0B1),
    Feature("r1_funding_rank_gap_t", "R1", "timing",
            (("eth_tx", "block_number"), ("erc20_tx", "block_number")),
            "|rank of the candidate's ETH transfer - rank of the B0 action| / (N-1)", ("B0",)),
    Feature("r1_funding_rank_gap_op", "R1", "timing",
            (("eth_tx", "block_number"), ("erc20_in_op", "block_number")),
            "|rank of the candidate's ETH transfer - rank of the application op| / (N-1)", ("B1",)),
    Feature("r1_token_rank_gap", "R1", "timing",
            (("erc20_tx", "block_number"), ("erc20_tx", "block_number")),
            "|rank of the candidate's token transfer - rank of the B0 action| / (N-1)", ("B0",)),
    Feature("r1_token_rank_gap_op", "R1", "timing",
            (("erc20_tx", "block_number"), ("erc20_in_op", "block_number")),
            "|rank of the candidate's token transfer - rank of the application op| / (N-1)",
            ("B1",)),

    # ---------------- R2: issuance <-> redemption (B3, B4-CrossAccount) ---------------------------
    Feature("r2_eq_g_account", "R2", "eq",
            (("pool_redeem_log", "sender"), ("pool_deposit_log", "sender")),
            "CreditSpent(nullifier, sender) names the same account as the issuance's "
            "CreditPool depositor", CREDIT_),
    Feature("r2_eq_aa_sender", "R2", "eq",
            (("uoe@app", "sender"), ("uoe@bootstrap", "sender")),
            "Spend UserOperation.sender == Bootstrap UserOperation.sender", CREDIT_),
    Feature("r2_eq_t_account", "R2", "eq",
            (("erc20_in_op", "sender"), ("pool_deposit_log", "sender")),
            "the account whose application transfer the Spend made == the issuance's depositor",
            CREDIT_),
    Feature("r2_eq_deploy", "R2", "eq",
            (("uoe@app", "sender"), ("deploy_log@bootstrap", "sender")),
            "Spend sender == account deployed by the issuance operation", CREDIT_),
    Feature("r2_rank_gap_g", "R2", "timing",
            (("pool_redeem_log", "block_number"), ("pool_deposit_log", "block_number")),
            "|rank of the redemption among redemptions - rank of the issuance among issuances| "
            "/ (N-1)  (insertion-order / FIFO signal)", CREDIT_),
    Feature("r2_rank_gap_aa", "R2", "timing",
            (("uoe@app", "block_number"), ("uoe@bootstrap", "block_number")),
            "same rank gap read from the UserOperationEvent rows", CREDIT_),
    Feature("r2_dt_offset_g", "R2", "timing",
            (("pool_redeem_log", "block_timestamp_utc"), ("pool_deposit_log", "block_timestamp_utc")),
            "|(t_redeem - t_issue) - (median t_redeem - median t_issue)| / (run span), an "
            "unsupervised common-delay window", CREDIT_),
    Feature("r2_latest_issuance_g", "R2", "timing",
            (("pool_redeem_log", "block_number"), ("pool_deposit_log", "block_number")),
            "candidate is the most recent issuance before the redemption (nearest prior)", CREDIT_),
    Feature("r2_intervening_g", "R2", "timing",
            (("pool_redeem_log", "block_number"), ("pool_deposit_log", "block_number")),
            "number of issuances between the candidate and the redemption / N (root age proxy)",
            CREDIT_),
    Feature("r2_root_match", "R2", "pm",
            (("pool_redeem_log", "merkle_root"), ("pool_deposit_log", "merkle_root")),
            "the redemption proved against the root emitted by the candidate's deposit", CREDIT_),
    Feature("r2_bits_agree", "R2", "pm",
            (("pool_redeem_log", "nullifier"), ("pool_deposit_log", "commitment")),
            "fraction of equal bits in the low 64 bits of nullifier and commitment "
            "(cryptographic negative control)", CREDIT_),
    Feature("r2_gas_rank_gap", "R2", "gas",
            (("uoe@app", "actual_gas_used"), ("uoe@bootstrap", "actual_gas_used")),
            "|rank of Spend gas used - rank of Bootstrap gas used| / (N-1)", CREDIT_),
    Feature("r2_pvg_gap", "R2", "gas",
            (("uoe@app", "pre_verification_gas"), ("uoe@bootstrap", "pre_verification_gas")),
            "|z(Spend PVG) - z(Bootstrap PVG)| (within-run z-scores)", CREDIT_),
    Feature("r2_cand_gas_z", "R2", "gas", (("uoe@bootstrap", "actual_gas_used"),),
            "within-run z-score of the Bootstrap op's gas used (insertion-position dependent)",
            CREDIT_),
    Feature("r2_cand_pvg_z", "R2", "gas", (("uoe@bootstrap", "pre_verification_gas"),),
            "within-run z-score of the Bootstrap op's PVG (calldata zero bytes)", CREDIT_),
    Feature("r2_delivery_rank_gap_tg", "R2", "timing",
            (("erc20_tx", "block_number"), ("erc20_tx", "subject_account"),
             ("pool_deposit_log", "sender"), ("erc20_in_op", "block_number")),
            "|rank of token delivery to the candidate's depositor - rank of the Spend's "
            "application transfer| / (N-1)", CREDIT_),

    # ---------------- R3: stealth account <-> established wallet (negative control) --------
    Feature("r3_dir_vs_action_rank_t", "R3", "timing",
            (("AUX", "directory_position"), ("erc20_in_op", "block_number")),
            "|directory position of the wallet - rank of the application transfer| / (N-1)",
            AA_B),
    Feature("r3_dir_vs_action_rank_b0", "R3", "timing",
            (("AUX", "directory_position"), ("erc20_tx", "block_number")),
            "|directory position - rank of the B0 action| / (N-1)", ("B0",)),
    Feature("r3_dir_vs_delivery_rank", "R3", "timing",
            (("AUX", "directory_position"), ("erc20_tx", "block_number"),
             ("erc20_tx", "subject_account"), ("erc20_in_op", "sender")),
            "|directory position - rank of the token delivery to the account| / (N-1)"),
    Feature("r3_dir_vs_op_rank_aa", "R3", "timing",
            (("AUX", "directory_position"), ("uoe@app", "block_number")),
            "|directory position - rank of the UserOperation| / (N-1)", AA_B),
    Feature("r3_dir_vs_funding_rank_b0", "R3", "timing",
            (("AUX", "directory_position"), ("eth_tx", "block_number"), ("eth_tx", "target"),
             ("erc20_tx", "sender")),
            "|directory position - rank of the ETH funding of the action's sender| / (N-1)",
            ("B0",)),
    Feature("r3_dir_vs_funding_rank_g", "R3", "timing",
            (("AUX", "directory_position"), ("eth_tx", "block_number"), ("eth_tx", "target"),
             ("prefund_deposit_log", "subject_account")),
            "|directory position - rank of the ETH funding of the prefunded account| / (N-1)",
            ("B1",)),
    Feature("r3_dir_vs_allowlist_rank", "R3", "timing",
            (("AUX", "directory_position"), ("allowlist_tx", "block_number"),
             ("allowlist_tx", "subject_account"), ("uoe@app", "sender")),
            "|directory position - rank of setSponsored(op sender)| / (N-1)", ("B2-Allowlist",)),
    Feature("r3_dir_vs_issuance_rank_g", "R3", "timing",
            (("AUX", "directory_position"), ("pool_deposit_log", "block_number"),
             ("pool_deposit_log", "sender"), ("pool_redeem_log", "sender")),
            "|directory position - rank of the spender's issuance| / (N-1). B3 only: it is "
            "defined through spender == depositor, which does not exist in B4-CrossAccount", B3_),
    Feature("r3_addr_hamming_t", "R3", "eq",
            (("AUX", "wallet_address"), ("erc20_tx", "sender"), ("erc20_in_op", "sender")),
            "normalised Hamming distance between the bits of the account that makes the "
            "application transfer and the wallet address"),
    Feature("r3_addr_prefix_t", "R3", "eq",
            (("AUX", "wallet_address"), ("erc20_tx", "sender"), ("erc20_in_op", "sender")),
            "shared leading hex nibbles of that account and the wallet address / 40"),
    Feature("r3_gas_rank_vs_dir_g", "R3", "gas",
            (("AUX", "directory_position"), ("uoe@app", "actual_gas_used")),
            "|rank of the op's gas used - directory position| / (N-1)", AA_B),
    Feature("r3_pvg_rank_vs_dir_g", "R3", "gas",
            (("AUX", "directory_position"), ("uoe@app", "pre_verification_gas")),
            "|rank of the op's PVG - directory position| / (N-1)", AA_B),
)

FEATURES_BY_NAME = {f.name: f for f in FEATURES}


def features_for(relation: str, baseline_id: str) -> List[Feature]:
    return [f for f in FEATURES if f.relation == relation and baseline_id in f.baselines]


def select(relation: str, baseline_id: str, families: Iterable[str],
           convention: str = "primary", drop_subfamilies: Iterable[str] = (),
           drop_family: Iterable[str] = ()) -> List[Feature]:
    """Features whose every family is allowed, minus ablated subfamilies / families."""
    allowed = set(families)
    drop_sub = set(drop_subfamilies)
    drop_fam = set(drop_family)
    out = []
    for f in features_for(relation, baseline_id):
        fams = f.families(convention)
        if not fams <= allowed or f.subfamily in drop_sub or fams & drop_fam:
            continue
        out.append(f)
    return out


# --------------------------------------------------------------------------------------
# Documentation
# --------------------------------------------------------------------------------------

DOC_PATH = Path("docs") / "d1-feature-registry.md"
BEGIN, END = "<!-- BEGIN GENERATED: d1-registry -->", "<!-- END GENERATED: d1-registry -->"


def render() -> str:
    lines = ["### Row kinds", "", "| Row kind | Public rows |", "|---|---|"]
    lines += [f"| `{k}` | {v} |" for k, v in ROW_KINDS.items()]
    lines += ["", "### Field registry (every varying public field of every row kind)", "",
              "Context fields never used as features: " + ", ".join(f"`{f}`" for f in CONTEXT_FIELDS)
              + ".", "",
              "| Row kind | Field | Family (primary) | field_kind alt. | Rationale | Ambiguity |",
              "|---|---|---|---|---|---|"]
    for (rk, f), c in FIELD_REGISTRY.items():
        lines.append(f"| `{rk}` | `{f}` | {c.family} | {c.alt_family or ''} | {c.rationale} | "
                     f"{c.ambiguity or ''} |")
    lines += ["", "### Derived attack features", "",
              "| Feature | Relation | Subfamily | Families (primary) | Families (field_kind) | "
              "Baselines | Sources | Description |", "|---|---|---|---|---|---|---|---|"]
    for ft in FEATURES:
        src = ", ".join(f"`{rk}.{fl}`" for rk, fl in ft.sources)
        lines.append(f"| `{ft.name}` | {ft.relation} | {ft.subfamily} | {ft.label('primary')} | "
                     f"{ft.label('field_kind')} | {', '.join(ft.baselines)} | {src} | "
                     f"{ft.description} |")
    return "\n".join(lines) + "\n"


def write_doc(root: Path) -> bool:
    path = root / DOC_PATH
    text = path.read_text(encoding="utf-8")
    start, end = text.index(BEGIN) + len(BEGIN), text.index(END)
    new = text[:start] + "\n\n" + render() + "\n" + text[end:]
    changed = new != text
    path.write_text(new, encoding="utf-8")
    return changed


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    from ...recorder.provenance import repo_root
    if args.write:
        print("updated" if write_doc(repo_root()) else "unchanged", DOC_PATH)
    else:
        sys.stdout.write(render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
