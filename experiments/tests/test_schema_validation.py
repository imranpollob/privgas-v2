"""Schema validation: what is accepted, and exactly why things are rejected.

Covers acceptance items A-H and K-M of the Prompt 3 test list.
"""

from __future__ import annotations

import unittest

from experiments.recorder import validate_record
from experiments.recorder.errors import PrivateDataLeak, RecordValidationError
from experiments.tests import fixtures as F


class RejectionTestCase(unittest.TestCase):
    def assertRejected(self, stream, record, code=None, exc=RecordValidationError):
        with self.assertRaises(exc) as ctx:
            validate_record(stream, record)
        if code is not None:
            self.assertEqual(ctx.exception.code, code,
                             f"expected rejection code {code!r}, got "
                             f"{ctx.exception.code!r}: {ctx.exception}")
        return ctx.exception


# --- A, B, C: valid records ------------------------------------------------


class TestValidRecords(RejectionTestCase):
    def test_a_valid_ground_truth_record(self):
        validate_record("ground_truth", F.ground_truth())

    def test_b_valid_public_event(self):
        validate_record("public_events", F.public_event())

    def test_c_valid_bundler_private_record(self):
        validate_record("bundler_private", F.bundler_private())

    def test_ground_truth_for_a_credit_baseline(self):
        validate_record("ground_truth", F.ground_truth("B3"))


# --- D, E: hidden data in public streams -----------------------------------


class TestPrivateDataInPublicStreams(RejectionTestCase):
    def test_d_public_event_with_actor_id_is_rejected(self):
        row = F.public_event(actor_id="actor_7c1e")
        self.assertRejected("public_events", row,
                            code="private_field_in_public_stream",
                            exc=PrivateDataLeak)

    def test_d_hidden_actor_id_nested_inside_an_object_is_rejected(self):
        """The scan is recursive: burying the key does not hide it."""
        row = F.public_event(baseline_id="B3")
        row["proof_metadata"] = {
            "scheme": "groth16", "verifier_address": None,
            "public_signal_count": 4, "proof_byte_length": 256,
            "tree_depth": 20, "actor_id": "actor_7c1e",
        }
        self.assertRejected("public_events", row,
                            code="private_field_in_public_stream",
                            exc=PrivateDataLeak)

    def test_e_public_event_with_relation_label_is_rejected(self):
        for field in ("payer_to_operation_label",
                      "issuance_to_redemption_label",
                      "stealth_to_actor_label"):
            with self.subTest(field=field):
                row = F.public_event(**{field: F.label("R1")})
                self.assertRejected("public_events", row,
                                    code="private_field_in_public_stream",
                                    exc=PrivateDataLeak)

    def test_e_seed_is_rejected_in_public_output(self):
        """The seed is the answer key in compressed form."""
        self.assertRejected("public_events", F.public_event(seed=42),
                            code="private_field_in_public_stream",
                            exc=PrivateDataLeak)

    def test_bundler_private_is_also_protected(self):
        row = F.bundler_private(actor_id="actor_7c1e")
        self.assertRejected("bundler_private", row,
                            code="private_field_in_public_stream",
                            exc=PrivateDataLeak)

    def test_unknown_field_is_rejected_even_when_not_on_the_denylist(self):
        """The denylist is defence in depth on top of a strict allow-list."""
        self.assertRejected("public_events",
                            F.public_event(secret_actor_handle="actor_7c1e"),
                            code="unknown_field")


# --- F, G, H: malformed values ---------------------------------------------


class TestMalformedValues(RejectionTestCase):
    def test_f_malformed_experiment_id(self):
        for bad in ("Privacy/D1", "privacy//d1", "/privacy", "privacy/d1/",
                    "priv acy", "", "a" * 200):
            with self.subTest(bad=bad):
                self.assertRejected("public_events",
                                    F.public_event(experiment_id=bad))

    def test_f_missing_experiment_id(self):
        row = F.public_event()
        del row["experiment_id"]
        self.assertRejected("public_events", row, code="missing_field")

    def test_g_malformed_address(self):
        for bad in ("0x123", "57ea1a0000000000000000000000000000000001",
                    "0xZZea1a0000000000000000000000000000000001", 12345):
            with self.subTest(bad=bad):
                self.assertRejected("public_events", F.public_event(sender=bad),
                                    code="malformed_address")

    def test_g_malformed_hash(self):
        self.assertRejected("public_events",
                            F.public_event(transaction_hash="0xdeadbeef"),
                            code="malformed_hash")

    def test_h_unsupported_schema_version(self):
        # 1.0.0-3.0.0 are superseded versions: their rows are not readable by
        # 4.0.0 code (docs/experiment-schema.md Sec. 9).
        for bad in ("0.9", "1.0", "1.0.0", "2.0.0", "3.0.0", "5.0.0", "", None, 1.0):
            with self.subTest(bad=bad):
                self.assertRejected("public_events",
                                    F.public_event(schema_version=bad),
                                    code="unsupported_schema_version")

    def test_incompatible_chain_id_representation(self):
        self.assertRejected("public_events", F.public_event(chain_id="31337"),
                            code="incompatible_chain_id")
        self.assertRejected("public_events", F.public_event(chain_id=0),
                            code="out_of_range")

    def test_invalid_timestamp_format(self):
        for bad in ("2026-03-01 12:20:00", "2026-03-01T12:20:00+00:00",
                    "2026-13-01T12:20:00Z", "not a time"):
            with self.subTest(bad=bad):
                self.assertRejected(
                    "public_events",
                    F.public_event(block_timestamp_utc=bad),
                    code="invalid_timestamp")

    def test_fractional_second_timestamps_are_accepted(self):
        """Regression: RE_ISO_UTC allows 1-6 fractional digits, and real
        bundler timestamps use them; the calendar check must agree."""
        for good in ("2026-03-01T12:20:00.5Z", "2026-03-01T12:20:00.123456Z"):
            with self.subTest(good=good):
                validate_record("public_events",
                                F.public_event(block_timestamp_utc=good))
        self.assertRejected("public_events",
                            F.public_event(block_timestamp_utc="2026-02-30T12:20:00.1Z"),
                            code="invalid_timestamp")

    def test_uint256_values_must_be_decimal_strings(self):
        self.assertRejected("public_events",
                            F.public_event(asset_amount=1000),
                            code="numeric_representation")
        self.assertRejected("public_events",
                            F.public_event(asset_amount="0x64"),
                            code="malformed_uint256")

    def test_row_declaring_the_wrong_stream_is_rejected(self):
        self.assertRejected("public_events",
                            F.public_event(stream="ground_truth"),
                            code="wrong_stream")

    def test_unknown_stream_name(self):
        self.assertRejected("mempool", F.public_event(), code="unknown_stream")


# --- K, L: baseline capability rules ---------------------------------------


class TestBaselineCapabilities(RejectionTestCase):
    def test_k_b0_record_needs_no_useroperation_fields(self):
        """B0 validates with every ERC-4337 field null."""
        row = F.public_event(baseline_id="B0")
        self.assertIsNone(row["userop_hash"])
        self.assertIsNone(row["max_fee_per_gas"])
        validate_record("public_events", row)

    def test_k_b0_record_with_a_useroperation_is_rejected(self):
        """A fabricated UserOperation would make B0 look like an AA baseline."""
        row = F.public_event(baseline_id="B0", userop_hash=F.HASH_B)
        self.assertRejected("public_events", row,
                            code="baseline_capability_violation")

    def test_k_b0_produces_no_bundler_observations(self):
        row = F.bundler_private(baseline_id="B0")
        self.assertRejected("bundler_private", row,
                            code="baseline_capability_violation")

    def test_l_b1_records_erc4337_fields_with_a_null_paymaster(self):
        row = F.erc4337_public_event("B1")
        validate_record("public_events", row)
        self.assertIsNone(row["paymaster"])
        self.assertEqual(row["entrypoint_version"], "0.9.0")
        self.assertEqual(row["call_gas_limit"], "120000")

    def test_l_b1_with_a_paymaster_is_rejected(self):
        row = F.erc4337_public_event("B1", paymaster=F.PAYMASTER)
        self.assertRejected("public_events", row,
                            code="baseline_capability_violation")

    def test_l_b2_records_a_public_paymaster(self):
        row = F.erc4337_public_event("B2-Allowlist")
        validate_record("public_events", row)
        self.assertEqual(row["paymaster"], F.PAYMASTER)
        self.assertEqual(row["paymaster_post_op_gas_limit"], "40000")

    def test_b2_publishes_no_privacy_artifacts(self):
        row = F.erc4337_public_event("B2-Allowlist", commitment=F.HASH_C)
        self.assertRejected("public_events", row,
                            code="baseline_capability_violation")

    def test_unknown_baseline_id(self):
        self.assertRejected("public_events", F.public_event(baseline_id="B9"),
                            code="unknown_baseline")

    def test_the_pooled_b2_id_no_longer_exists(self):
        """Schema 3.0.0: B2-Allowlist and B2-Signature must not collapse."""
        self.assertRejected("public_events", F.public_event(baseline_id="B2"),
                            code="unknown_baseline")
        for b in ("B2-Allowlist", "B2-Signature"):
            with self.subTest(baseline=b):
                validate_record("public_events", F.erc4337_public_event(b))

    def test_r1_economic_funder_and_immediate_payer_are_separate_fields(self):
        for b, kind in (("B0", "eoa_balance"), ("B1", "smart_account_entrypoint_deposit"),
                        ("B2-Signature", "paymaster_entrypoint_deposit")):
            with self.subTest(baseline=b):
                row = F.ground_truth(b)
                validate_record("ground_truth", row)
                self.assertEqual(row["immediate_gas_payer_kind"], kind)
                self.assertNotIn("funding_wallet_id", row)

    def test_immediate_payer_kind_must_match_the_baseline_mechanism(self):
        self.assertRejected("ground_truth",
                            F.ground_truth("B2-Allowlist", immediate_gas_payer_kind="eoa_balance"),
                            code="baseline_capability_violation")

    def test_paymaster_contract_cannot_be_the_economic_funder(self):
        row = F.ground_truth("B2-Signature")
        row["public_anchors"]["economic_funding_address"] = row["public_anchors"][
            "immediate_gas_payer_address"]
        self.assertRejected("ground_truth", row, code="payer_conflation")

    def test_pre_4_funding_fields_are_rejected(self):
        row = F.ground_truth("B1")
        row["funding_wallet_id"] = row.pop("economic_funding_source_id")
        self.assertRejected("ground_truth", row)
        self.assertRejected("public_events", F.public_event(funding_wallet_id="funder_x"),
                            exc=Exception)

    def test_trace_phase_is_content_derived(self):
        validate_record("public_events", F.public_event(
            event_type="native_transfer", calldata_class="native_value_only",
            asset_type="native", asset_contract=None, method_selector=None))
        self.assertRejected("public_events", F.public_event(trace_phase="funding"),
                            code="trace_phase_inconsistent")
        self.assertRejected("public_events", F.public_event(trace_phase="sponsor_link"),
                            code="not_in_enum")

    def test_warm_workload_only_for_account_abstraction_baselines(self):
        self.assertRejected("public_events",
                            F.public_event(baseline_id="B0", workload_id="W1-warm"),
                            code="baseline_capability_violation")
        validate_record("public_events",
                        F.erc4337_public_event("B1", workload_id="W1-warm"))

    def test_unsplit_w1_workload_is_rejected(self):
        self.assertRejected("public_events", F.public_event(workload_id="W1"),
                            code="not_in_enum")


# --- M: null / not_applicable semantics ------------------------------------


class TestNullAndNotApplicableSemantics(RejectionTestCase):
    def test_m_every_schema_field_must_be_present_as_a_key(self):
        row = F.public_event()
        del row["paymaster"]
        self.assertRejected("public_events", row, code="missing_field")

    def test_m_null_and_not_applicable_are_not_interchangeable(self):
        """B0 has no credit system: the sentinel is required, null is wrong."""
        self.assertRejected("ground_truth",
                            F.ground_truth("B0", credit_id=None),
                            code="baseline_capability_violation")
        validate_record("ground_truth", F.ground_truth("B0"))

    def test_m_not_applicable_is_rejected_where_only_null_is_meaningful(self):
        self.assertRejected("public_events",
                            F.public_event(block_number="not_applicable"),
                            code="na_not_allowed")

    def test_m_null_rejected_on_a_non_nullable_field(self):
        self.assertRejected("public_events", F.public_event(asset_type=None),
                            code="null_not_allowed")

    def test_m_r2_is_not_applicable_for_a_baseline_without_credits(self):
        row = F.ground_truth("B0")
        self.assertEqual(row["issuance_to_redemption_label"]["status"],
                         "not_applicable")
        validate_record("ground_truth", row)

    def test_m_r2_not_applicable_is_rejected_for_a_credit_baseline(self):
        """B3 has a credit lifecycle: 'absent' means no link, not 'no concept'."""
        row = F.ground_truth("B3",
                             issuance_to_redemption_label=F.label(
                                 "R2", status="not_applicable"))
        self.assertRejected("ground_truth", row,
                            code="baseline_capability_violation")

    def test_m_absent_status_keeps_a_true_negative(self):
        row = F.ground_truth(
            "B0", payer_to_operation_label=F.label("R1", status="absent"))
        validate_record("ground_truth", row)
        self.assertIsNone(row["payer_to_operation_label"]["true_value"])
        self.assertIsNotNone(row["payer_to_operation_label"]["subject_ref"])

    def test_m_absent_status_may_not_carry_an_answer(self):
        bad = F.label("R1", status="absent")
        bad["true_value"] = "funder_7c1e"
        self.assertRejected("ground_truth",
                            F.ground_truth("B0", payer_to_operation_label=bad),
                            code="label_inconsistent")

    def test_m_empty_lineage_differs_from_unobserved_lineage(self):
        observed_none = F.bundler_private(replacement_lineage=[],
                                          replacement_count=0)
        validate_record("bundler_private", observed_none)
        not_observed = F.bundler_private(replacement_lineage=None,
                                         replacement_count=None)
        validate_record("bundler_private", not_observed)


# --- relation separation and consistency -----------------------------------


class TestRelationLabels(RejectionTestCase):
    def test_relations_cannot_be_swapped_between_fields(self):
        row = F.ground_truth("B0", stealth_to_actor_label=F.label("R1"))
        self.assertRejected("ground_truth", row, code="relation_mismatch")

    def test_hidden_identifiers_must_be_opaque(self):
        for bad in (F.ADDRESS, "0xdeadbeef", "0x00"):
            with self.subTest(bad=bad):
                self.assertRejected("ground_truth",
                                    F.ground_truth("B0", actor_id=bad),
                                    code="hidden_id_not_opaque")

    def test_hidden_identifier_may_not_equal_a_public_anchor(self):
        row = F.ground_truth("B0")
        row["public_anchors"]["stealth_account_address"] = F.ADDRESS
        row["stealth_account_id"] = "stealth_a1"
        validate_record("ground_truth", row)

    def test_observed_label_requires_an_answer(self):
        bad = F.label("R3")
        bad["true_value"] = None
        self.assertRejected("ground_truth",
                            F.ground_truth("B0", stealth_to_actor_label=bad),
                            code="label_inconsistent")


# --- outcome / asset consistency -------------------------------------------


class TestCrossFieldConsistency(RejectionTestCase):
    def test_not_included_operation_carries_no_inclusion_data(self):
        row = F.erc4337_public_event("B1", outcome="not_included")
        self.assertRejected("public_events", row, code="outcome_inconsistent")

    def test_not_included_operation_validates_when_truly_empty(self):
        row = F.erc4337_public_event(
            "B1", outcome="not_included", success=None, block_number=None,
            block_hash=None, block_timestamp_utc=None, transaction_index=None,
            log_index=None, transaction_hash=None, actual_gas_used=None,
            actual_gas_cost=None, effective_gas_price=None)
        validate_record("public_events", row)

    def test_failed_operations_are_recordable(self):
        """Rule: failed operations are data, not noise to be dropped."""
        row = F.erc4337_public_event(
            "B1", outcome="reverted", success=False,
            revert_reason_class="target_reverted")
        validate_record("public_events", row)

    def test_erc721_row_may_not_carry_an_amount(self):
        row = F.public_event(asset_type="erc721", asset_amount="1",
                             asset_token_id="7")
        self.assertRejected("public_events", row, code="asset_inconsistent")

    def test_rejected_simulation_requires_a_category(self):
        row = F.bundler_private(simulation_result="rejected",
                                rejection_category=None,
                                inclusion_timestamp_utc=None)
        self.assertRejected("bundler_private", row,
                            code="rejection_inconsistent")

    def test_rejected_operation_is_recorded_with_its_reason(self):
        row = F.bundler_private(
            simulation_result="rejected", rejection_category="stale_root",
            rejection_message_class="entrypoint_revert",
            inclusion_timestamp_utc=None, bundle_submission_timestamp_utc=None,
            submitted_bundle_transaction_hash=None)
        validate_record("bundler_private", row)

    def test_rejected_operation_cannot_carry_a_bundle_association(self):
        row = F.bundler_private(
            simulation_result="rejected",
            rejection_category="paymaster_validation_revert",
            rejection_message_class="entrypoint_revert",
            inclusion_timestamp_utc=None, bundle_submission_timestamp_utc=None)
        self.assertRejected("bundler_private", row,
                            code="rejection_inconsistent")

    def test_paymaster_validation_revert_is_its_own_category(self):
        row = F.bundler_private(
            simulation_result="rejected",
            rejection_category="paymaster_validation_revert",
            rejection_message_class="entrypoint_revert",
            inclusion_timestamp_utc=None, bundle_submission_timestamp_utc=None,
            submitted_bundle_transaction_hash=None)
        validate_record("bundler_private", row)

    def test_mined_bundle_hash_is_not_a_bundler_private_field(self):
        """Schema 2.0.0: the mined hash is public; only the pre-inclusion
        association is A2."""
        row = F.bundler_private()
        row["bundle_transaction_hash"] = row.pop(
            "submitted_bundle_transaction_hash")
        self.assertRejected("bundler_private", row, code="unknown_field")

    def test_allowlist_event_records_its_subject_account(self):
        row = F.public_event(
            baseline_id="B2-Allowlist", event_type="paymaster_event",
            calldata_class="paymaster_policy", asset_type="none",
            asset_contract=None, asset_amount=None, method_selector="0xf935d0b0",
            target=F.PAYMASTER, paymaster=F.PAYMASTER, subject_account=F.ADDRESS)
        validate_record("public_events", row)

    def test_replacement_count_must_match_the_lineage(self):
        row = F.bundler_private(replacement_lineage=[F.HASH_C],
                                replacement_count=3)
        self.assertRejected("bundler_private", row,
                            code="replacement_inconsistent")

    def test_a2_tier_is_rejected_in_the_public_stream(self):
        self.assertRejected("public_events",
                            F.public_event(observer_tier="A2"),
                            code="not_in_enum")

    def test_synthetic_origin_requires_a_synthetic_run_id(self):
        row = F.public_event(run_id="20260301T120000Z",
                             record_id="20260301T120000Z/public_events/000000")
        self.assertRejected("public_events", row, code="origin_mismatch")


if __name__ == "__main__":
    unittest.main()
