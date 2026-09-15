"""End-to-end tests of the REAL W1 baselines against a throwaway anvil.

Variants: B0 W1-cold, B1 W1-cold, B1 W1-warm, B2-Allowlist W1-cold,
B2-Signature W1-cold. Every transaction is locally signed and submitted raw;
every failure below is a failure the node or the EntryPoint actually produced.
Skipped (not passed) when anvil or forge is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from experiments.recorder.provenance import environment_report, software_revision
from experiments.recorder.version import SCHEMA_VERSION
from experiments.workloads.w1 import abi, calibration, compare, pvg
from experiments.workloads.w1.accounting import (
    SUBSIDY_TOLERANCE_GAS,
    AccountingError,
    reconcile,
)
from experiments.workloads.w1.artifacts import forge_build
from experiments.workloads.w1.config import EXPERIMENT_IDS, RUN_ID_SUFFIX, load_config
from experiments.workloads.w1.calibrate import run_calibration
from experiments.workloads.w1.recording import record_run
from experiments.workloads.w1.runner import Variation, run_baseline
from experiments.workloads.w1.userop import unpack

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = 20260914
TOOLS = all(shutil.which(t) for t in ("anvil", "forge"))
B1C, B1W = ("B1", "W1-cold"), ("B1", "W1-warm")
B2A, B2S = ("B2-Allowlist", "W1-cold"), ("B2-Signature", "W1-cold")
B0 = ("B0", "W1-cold")
AA = (B1C, B1W, B2A, B2S)


def txs(result, phase="workflow"):
    return [t for t in result.chain_dump["transactions"] if t["phase"] == phase]


def by_label(result, label):
    hashes = [h for h, l in result.private["tx_labels"].items() if l == label]
    return next((t for t in result.chain_dump["transactions"] if t["tx"]["hash"] in hashes),
                None)


def state(result, kind, addr, which):
    key = {"setup": "setup_end", "start": "warmup_end", "end": "workflow_end"}[which]
    return result.chain_dump["state"][kind][addr][str(result.chain_dump["blocks"][key])]


def bundle_op(result, label="w3_bundle"):
    tx = by_label(result, label)
    ops, _ = abi.decode_handle_ops(abi.data_bytes(tx["tx"]["input"]))
    return unpack(ops[0])


@unittest.skipUnless(TOOLS, "anvil and forge are required for live baseline tests")
class LiveW1TestCase(unittest.TestCase):
    runs = {}

    @classmethod
    def setUpClass(cls):
        if not LiveW1TestCase.runs:
            forge_build(REPO_ROOT)
            for b, w in EXPERIMENT_IDS:
                LiveW1TestCase.runs[(b, w)] = run_baseline(b, SEED, REPO_ROOT, build=False,
                                                           workload_id=w)
        cls.cfg = load_config(REPO_ROOT)

    def run_of(self, variant):
        return self.runs[variant]

    def costs(self, variant):
        r = self.run_of(variant)
        return reconcile(r.chain_dump, r.private)


class TestB0(LiveW1TestCase):
    def test_successful_w1(self):
        r = self.run_of(B0)
        self.assertIsNone(r.failure)
        self.assertTrue(all(c["ok"] for c in self.costs(B0)["checks"]))
        self.assertEqual([r.private["tx_labels"][t["tx"]["hash"]] for t in txs(r)],
                         ["w1_asset_delivery", "w2_eth_allowance", "w3_recipient_action"])
        self.assertEqual(r.chain_dump["userops"], [])
        self.assertEqual(r.bundler_log, [])

    def test_insufficient_eth_fails_at_the_node(self):
        r = run_baseline("B0", SEED, REPO_ROOT, build=False,
                         variation=Variation(eth_allowance_delta=-1))
        self.assertEqual(r.failure.step, "w3_recipient_action")
        self.assertIn("insufficient funds", r.failure.detail["node_error"].lower())
        rec = r.private["roles"]["recipient_account"]
        self.assertEqual(int(state(r, "erc20_balance", rec, "end")), self.cfg.transfer_amount)
        with self.assertRaises(AccountingError):
            reconcile(r.chain_dump, r.private)

    def test_retained_eth_is_accounted(self):
        s = self.costs(B0)["summary"]
        fee = int(by_label(self.run_of(B0), "w3_recipient_action")["receipt"]["gasUsed"], 16) * 2 * 10**9
        self.assertEqual(int(s["unused_recipient_eth"]), self.cfg.b0_eth_allowance - fee)
        self.assertGreater(int(s["unused_recipient_eth"]), 0)

    def test_tampered_balances_do_not_reconcile(self):
        r = self.run_of(B0)
        dump = json.loads(json.dumps(r.chain_dump))
        rec = r.private["roles"]["recipient_account"]
        end = str(dump["blocks"]["workflow_end"])
        dump["state"]["eth_balance"][rec][end] = str(int(dump["state"]["eth_balance"][rec][end]) + 1)
        with self.assertRaises(AccountingError):
            reconcile(dump, r.private)


class TestB1Cold(LiveW1TestCase):
    def test_successful_w1_with_deployment_in_the_measured_op(self):
        r = self.run_of(B1C)
        self.assertIsNone(r.failure)
        c = self.costs(B1C)
        self.assertIsNone(c["userop"]["paymaster"])
        self.assertTrue(c["summary"]["account_deployment_in_measured_action"])
        rec = r.private["roles"]["recipient_account"]
        self.assertEqual(state(r, "code_size", rec, "start"), 0)
        self.assertGreater(bundle_op(r)["init_code_length"], 0)

    def test_insufficient_native_funding_is_rejected_by_simulation(self):
        r = run_baseline("B1", SEED, REPO_ROOT, build=False,
                         variation=Variation(eth_allowance_delta=-1))
        self.assertEqual(r.failure.detail["rejection_category"], "insufficient_prefund")
        self.assertTrue(r.failure.detail["reason"].startswith("AA21"))
        self.assertIsNone(by_label(r, "w3_bundle"))


class TestB1Warm(LiveW1TestCase):
    def test_account_is_deployed_before_the_measured_action(self):
        r = self.run_of(B1W)
        self.assertIsNone(r.failure)
        rec = r.private["roles"]["recipient_account"]
        self.assertEqual(state(r, "code_size", rec, "setup"), 0)
        self.assertGreater(state(r, "code_size", rec, "start"), 0)
        self.assertEqual([r.private["tx_labels"][t["tx"]["hash"]] for t in txs(r, "warmup")],
                         ["warmup_eth_allowance", "warmup_deploy_bundle"])
        self.assertEqual(bundle_op(r)["init_code_length"], 0)
        self.assertEqual(bundle_op(r, "warmup_deploy_bundle")["call_data"], b"")

    def test_warmup_is_excluded_from_measured_cost(self):
        c = self.costs(B1W)
        workflow_fees = sum(int(t["fee"]) for t in c["transactions"])
        self.assertEqual(int(c["summary"]["total_eth_consumed_by_workflow"]), workflow_fees)
        self.assertGreater(int(c["summary"]["warmup_gas_used"]), 0)
        self.assertFalse(c["summary"]["account_deployment_in_measured_action"])
        self.assertTrue(all(t["phase"] == "workflow" for t in c["transactions"]))

    def test_warm_action_is_cheaper_than_cold_by_the_deployment_component(self):
        d = compare.derived({v: self.costs(v) for v in (B1C, B1W)})
        self.assertGreater(d["account_deployment_component_by_difference"]["userop_gas"], 100_000)

    def test_b0_has_no_warm_workload(self):
        with self.assertRaises(ValueError):
            run_baseline("B0", SEED, REPO_ROOT, build=False, workload_id="W1-warm")


class TestB2Allowlist(LiveW1TestCase):
    def test_sponsored_w1_with_zero_native_eth_and_public_allowlist_tx(self):
        r = self.run_of(B2A)
        self.assertIsNone(r.failure)
        c = self.costs(B2A)
        rec = r.private["roles"]["recipient_account"]
        for which in ("start", "end"):
            self.assertEqual(state(r, "eth_balance", rec, which), "0")
            self.assertEqual(state(r, "entrypoint_deposit", rec, which), "0")
        self.assertEqual([r.private["tx_labels"][t["tx"]["hash"]] for t in txs(r)],
                         ["w1_asset_delivery", "w2_sponsor_allowlist", "w3_bundle"])
        self.assertGreater(int(c["summary"]["sponsor_authorization_cost"]), 0)
        pm = r.chain_dump["contracts"]["ObservablePaymaster"]
        delta = int(state(r, "entrypoint_deposit", pm, "end")) - int(
            state(r, "entrypoint_deposit", pm, "start"))
        self.assertEqual(-delta, int(c["userop"]["actual_gas_cost"]))

    def test_unauthorized_operation_is_rejected(self):
        r = run_baseline("B2-Allowlist", SEED, REPO_ROOT, build=False,
                         variation=Variation(skip_sponsorship=True))
        self.assertEqual(r.failure.detail["rejection_category"], "paymaster_validation_revert")
        self.assertTrue(r.failure.detail["reason"].startswith("AA33"))


class TestB2Signature(LiveW1TestCase):
    def test_sponsored_w1_with_zero_native_eth_and_no_authorization_tx(self):
        r = self.run_of(B2S)
        self.assertIsNone(r.failure)
        c = self.costs(B2S)
        self.assertEqual([r.private["tx_labels"][t["tx"]["hash"]] for t in txs(r)], ["w1_asset_delivery", "w3_bundle"])
        operator = r.private["roles"]["sponsor_operator"]
        signer = r.private["roles"]["sponsor_signer"]
        for t in txs(r):
            self.assertNotEqual(t["tx"]["from"].lower(), operator.lower())
            self.assertNotEqual(t["tx"]["from"].lower(), signer.lower())
        self.assertEqual(c["summary"]["sponsor_authorization_cost"], "0")
        rec = r.private["roles"]["recipient_account"]
        self.assertEqual(state(r, "eth_balance", rec, "end"), "0")
        pm = r.chain_dump["contracts"]["SignatureVerifyingPaymaster"]
        self.assertEqual(int(c["userop"]["paymaster"], 16), int(pm, 16))
        delta = int(state(r, "entrypoint_deposit", pm, "end")) - int(
            state(r, "entrypoint_deposit", pm, "start"))
        self.assertEqual(-delta, int(c["userop"]["actual_gas_cost"]))
        self.assertTrue(bundle_op(r)["paymaster_signature_present"])

    def test_wrong_sponsor_signature_is_rejected(self):
        r = run_baseline("B2-Signature", SEED, REPO_ROOT, build=False,
                         variation=Variation(wrong_sponsor_signature=True))
        self.assertEqual(r.failure.step, "w3_bundle")
        self.assertEqual(r.failure.detail["rejection_category"], "paymaster_validation_revert")
        self.assertTrue(r.failure.detail["reason"].startswith("AA34"))
        pm = r.chain_dump["contracts"]["SignatureVerifyingPaymaster"]
        self.assertEqual(state(r, "entrypoint_deposit", pm, "start"),
                         state(r, "entrypoint_deposit", pm, "end"))


class TestPreVerificationGasCalibration(LiveW1TestCase):
    def test_bundler_is_not_systematically_subsidised(self):
        for v in AA:
            with self.subTest(variant=v):
                c = self.costs(v)
                net_gas = int(c["summary"]["bundler_net_gas"])
                self.assertGreaterEqual(net_gas, -SUBSIDY_TOLERANCE_GAS)
                self.assertLessEqual(abs(net_gas), SUBSIDY_TOLERANCE_GAS)
                self.assertEqual(int(c["summary"]["bundler_net"]), net_gas * 2 * 10**9)

    def test_calibration_decomposition_matches_the_mined_bundle(self):
        for v in AA:
            with self.subTest(variant=v):
                r = self.run_of(v)
                cal = r.chain_dump["pvg_records"]["w3_bundle"]
                mined = abi.data_bytes(by_label(r, "w3_bundle")["tx"]["input"])
                self.assertEqual(cal["final_calldata_gas"], pvg.calldata_gas(mined))
                self.assertEqual(bundle_op(r)["pre_verification_gas"], cal["pre_verification_gas"])
                self.assertEqual(cal["pre_verification_gas"],
                                 pvg.TX_BASE_GAS + cal["final_calldata_gas"]
                                 + cal["entrypoint_unmeasured_overhead"] + cal["surplus_gas"])

    def test_subsidy_assertion_detects_an_underpaying_bundle(self):
        r = self.run_of(B2S)
        dump = json.loads(json.dumps(r.chain_dump))
        bundle_hashes = [h for h, l in r.private["tx_labels"].items() if l == "w3_bundle"]
        tx = next(t for t in dump["transactions"] if t["tx"]["hash"] in bundle_hashes)
        # Pretend the bundle cost the ~17.8k gas the old fixed value under-covered.
        tx["receipt"]["gasUsed"] = hex(int(tx["receipt"]["gasUsed"], 16) + 17_813)
        with self.assertRaises(AccountingError) as ctx:
            reconcile(dump, r.private)
        self.assertIn("no systematic bundler subsidy", str(ctx.exception))

    def test_configured_call_gas_limit_incurs_no_unused_gas_penalty(self):
        from experiments.workloads.w1 import config as config_mod
        original = config_mod.W1Config.call_gas_limit
        lowered = self.cfg.call_gas_limit - 10_000

        def measured(u):
            return int(u["actual_gas_used"]) - int(u["pre_verification_gas"])

        try:
            config_mod.W1Config.call_gas_limit = property(lambda s: lowered)
            for v in (B1C, B2S):
                with self.subTest(variant=v):
                    low = run_baseline(v[0], SEED, REPO_ROOT, build=False, workload_id=v[1])
                    self.assertEqual(measured(reconcile(low.chain_dump, low.private)["userop"]),
                                     measured(self.costs(v)["userop"]))
        finally:
            config_mod.W1Config.call_gas_limit = original


class TestPreVerificationGasExperimentMode(LiveW1TestCase):
    """Experiment runs price PVG from the calibration artifact; they never
    execute (snapshot/revert) their own operation to rediscover O."""

    def test_no_exact_operation_dry_run_in_experiment_runs(self):
        artifact = calibration.load_artifact(REPO_ROOT)
        sha = calibration.artifact_sha256(artifact)
        for v, r in self.runs.items():
            with self.subTest(variant=v):
                self.assertEqual(r.chain_dump["environment"]["evm_snapshots_taken"], 0)
                events = {e["event"] for e in r.bundler_log}
                self.assertNotIn("pvg_calibration", events)
                if v[0] == "B0":
                    continue
                self.assertIn("pvg_estimate", events)
                self.assertEqual(r.chain_dump["bundler"]["pvg_mode"], "calibrated_overhead")
                for label, rec in r.chain_dump["pvg_records"].items():
                    self.assertEqual(rec["method"], "calibrated_overhead_v1")
                    self.assertEqual(rec["calibration_artifact_sha256"], sha)
                    self.assertEqual(
                        rec["entrypoint_unmeasured_overhead"],
                        artifact["entrypoint_unmeasured_overhead_by_shape"][rec["op_shape"]])

    def test_dry_run_mode_remains_available_and_agrees(self):
        diag = run_baseline("B2-Signature", SEED, REPO_ROOT, build=False, pvg_mode="dry_run")
        self.assertGreater(diag.chain_dump["environment"]["evm_snapshots_taken"], 0)
        measured = diag.chain_dump["pvg_records"]["w3_bundle"]["pre_verification_gas"]
        estimated = self.run_of(B2S).chain_dump["pvg_records"]["w3_bundle"]["pre_verification_gas"]
        self.assertLessEqual(abs(measured - estimated), 24)

    def test_changed_environment_requires_recalibration(self):
        original = calibration.environment_fingerprint

        def changed(*a, **k):
            return {**original(*a, **k), "bundle_size": 2}

        try:
            calibration.environment_fingerprint = changed
            with self.assertRaises(calibration.RecalibrationRequired) as ctx:
                run_baseline("B1", SEED, REPO_ROOT, build=False)
            self.assertIn("bundle_size", str(ctx.exception))
        finally:
            calibration.environment_fingerprint = original

    def test_calibration_is_reproducible_with_a_fresh_seed(self):
        fresh = run_calibration([910777], REPO_ROOT, build=False)
        artifact = calibration.load_artifact(REPO_ROOT)
        self.assertEqual(fresh["entrypoint_unmeasured_overhead_by_shape"],
                         artifact["entrypoint_unmeasured_overhead_by_shape"])
        self.assertEqual(fresh["environment_fingerprint"], artifact["environment_fingerprint"])


class TestR1PublicTrace(LiveW1TestCase):
    """The recorded public trace contains the funding evidence that exists.
    Uses private anchors only to locate it -- this is not inference."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = environment_report(REPO_ROOT)
        cls.tmp = TestRecording._sandbox()
        cls.traces = {}
        for v in EXPERIMENT_IDS:
            r = cls.runs[v]
            out = record_run(r.chain_dump, r.bundler_log, r.private, SEED,
                             f"20260914T000000Z-{RUN_ID_SUFFIX[v]}", cls.tmp,
                             clock=lambda: "2026-09-14T00:00:00Z", env_report=cls.env)
            cls.traces[v] = (out["rows"]["public_events"], out["rows"]["ground_truth"][0])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def find(rows, **want):
        return [r for r in rows if all(r[k] == v for k, v in want.items())]

    def test_every_mined_transaction_is_in_the_public_trace(self):
        for v in EXPERIMENT_IDS:
            with self.subTest(variant=v):
                rows, _ = self.traces[v]
                hashes = {t["tx"]["hash"] for t in self.run_of(v).chain_dump["transactions"]}
                self.assertEqual({r["transaction_hash"] for r in rows}, hashes)
                phases = {r["trace_phase"] for r in rows}
                self.assertTrue({"infrastructure", "funding", "application"} <= phases)

    def test_ground_truth_separates_economic_funder_immediate_payer_and_operation(self):
        expected = {B0: "eoa_balance", B1C: "smart_account_entrypoint_deposit",
                    B1W: "smart_account_entrypoint_deposit",
                    B2A: "paymaster_entrypoint_deposit", B2S: "paymaster_entrypoint_deposit"}
        for v in EXPERIMENT_IDS:
            with self.subTest(variant=v):
                rows, gt = self.traces[v]
                a = gt["public_anchors"]
                self.assertEqual(gt["immediate_gas_payer_kind"], expected[v])
                self.assertNotEqual(a["economic_funding_address"], a["immediate_gas_payer_address"])
                self.assertEqual(gt["payer_to_operation_label"]["true_value"],
                                 gt["economic_funding_source_id"])
                op_ref = gt["payer_to_operation_label"]["subject_ref"]
                self.assertTrue(self.find(rows, transaction_hash=op_ref) if v == B0
                                else self.find(rows, userop_hash=op_ref))
                if v[0].startswith("B2"):
                    pm = self.run_of(v).chain_dump["contracts"][
                        self.run_of(v).chain_dump["paymaster_used"]].lower()
                    self.assertEqual(a["immediate_gas_payer_address"], pm)
                    self.assertNotEqual(a["economic_funding_address"], pm)

    def _sponsor_funding_evidence(self, v):
        rows, gt = self.traces[v]
        a = gt["public_anchors"]
        pm = a["immediate_gas_payer_address"]
        deposit_tx = self.find(rows, event_type="paymaster_event", calldata_class="paymaster_deposit",
                               sender=a["economic_funding_address"], target=pm)
        self.assertEqual(len(deposit_tx), 1, "sponsor wallet -> Paymaster deposit()")
        self.assertTrue(self.find(rows, event_type="entrypoint_deposit", subject_account=pm,
                                  transaction_hash=deposit_tx[0]["transaction_hash"]))
        uo = self.find(rows, event_type="user_operation_event", paymaster=pm)
        self.assertEqual(len(uo), 1, "sponsored UserOperation names the Paymaster")
        self.assertEqual(uo[0]["sender"], a["stealth_account_address"])
        return rows, a, uo[0]

    def test_b0_trace_contains_the_eth_funding_edge(self):
        rows, gt = self.traces[B0]
        a = gt["public_anchors"]
        edge = self.find(rows, event_type="native_transfer", sender=a["economic_funding_address"],
                         target=a["immediate_gas_payer_address"])
        self.assertEqual(len(edge), 1)
        action = self.find(rows, transaction_hash=a["transaction_hash"])
        self.assertLess(edge[0]["seq"], action[0]["seq"])

    def test_b1_trace_contains_the_account_funding_and_deposit_path(self):
        for v in (B1C, B1W):
            with self.subTest(variant=v):
                rows, gt = self.traces[v]
                a = gt["public_anchors"]
                account = a["immediate_gas_payer_address"]
                self.assertEqual(account, a["stealth_account_address"])
                self.assertTrue(self.find(rows, event_type="native_transfer",
                                          sender=a["economic_funding_address"], target=account))
                self.assertTrue(self.find(rows, event_type="entrypoint_deposit",
                                          subject_account=account))
                self.assertTrue(self.find(rows, event_type="user_operation_event",
                                          sender=account, paymaster=None))

    def test_b2_allowlist_trace_contains_funding_authorization_and_operation(self):
        rows, a, uo = self._sponsor_funding_evidence(B2A)
        auth = self.find(rows, event_type="paymaster_event", calldata_class="paymaster_policy",
                         subject_account=a["stealth_account_address"])
        self.assertEqual(len(auth), 1, "setSponsored(account, true)")
        self.assertEqual(auth[0]["trace_phase"], "authorization")
        self.assertEqual(auth[0]["sender"], a["economic_funding_address"])
        self.assertLess(auth[0]["seq"], uo["seq"])

    def test_b2_signature_trace_contains_funding_and_operation_but_no_authorization_tx(self):
        rows, a, uo = self._sponsor_funding_evidence(B2S)
        self.assertEqual(self.find(rows, calldata_class="paymaster_policy"), [])
        self.assertEqual(self.find(rows, trace_phase="authorization"), [])

    def test_cost_window_is_private_and_excludes_setup(self):
        for v in (B0, B2S):
            with self.subTest(variant=v):
                rp = paths_run(self.tmp, v)
                window = json.loads((rp.private_run_dir / "w1_cost_window.json").read_text())
                in_window = [x for x in window["rows"] if x["in_measured_cost_window"]]
                self.assertLess(len(in_window), len(window["rows"]))
                self.assertNotIn("in_measured_cost_window", rp.public_events_path.read_text())


def paths_run(root, v):
    from experiments.recorder import paths as paths_mod
    return paths_mod.run_paths(EXPERIMENT_IDS[v], f"20260914T000000Z-{RUN_ID_SUFFIX[v]}", root)


class TestFairness(LiveW1TestCase):
    def test_all_fairness_checks_pass(self):
        runs = {v: {"chain_dump": r.chain_dump, "private": r.private}
                for v, r in self.runs.items()}
        failed = [c for c in compare.fairness_checks(runs) if not c["ok"]]
        self.assertEqual(failed, [])

    def test_byte_identical_application_call_across_all_baselines(self):
        b0_call = abi.data_bytes(by_label(self.run_of(B0), "w3_recipient_action")["tx"]["input"])
        token = self.run_of(B0).chain_dump["contracts"]["W1Token"].lower()
        for v in AA:
            with self.subTest(variant=v):
                target, value, inner = abi.decode_execute(bundle_op(self.run_of(v))["call_data"])
                self.assertEqual((target.lower(), value, inner), (token, 0, b0_call))

    def test_same_fee_policy_on_every_workflow_transaction(self):
        for v, r in self.runs.items():
            for t in txs(r) + txs(r, "warmup"):
                with self.subTest(variant=v, tx=t["tx"]["hash"]):
                    self.assertEqual(int(t["receipt"]["effectiveGasPrice"], 16), 2 * 10**9)
                    self.assertEqual(int(t["block"]["baseFeePerGas"], 16), 10**9)

    def test_repeated_runs_are_deterministic_under_the_seed(self):
        again = run_baseline("B2-Signature", SEED, REPO_ROOT, build=False)
        first = self.run_of(B2S)

        def key(r):
            return [(t["tx"]["hash"], t["receipt"]["gasUsed"]) for t in txs(r)]

        self.assertEqual(key(first), key(again))
        self.assertEqual(first.chain_dump["userops"], again.chain_dump["userops"])
        self.assertEqual(first.chain_dump["pvg_records"], again.chain_dump["pvg_records"])


class TestRecording(LiveW1TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = environment_report(REPO_ROOT)

    def setUp(self):
        self.tmp = self._sandbox()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _sandbox():
        tmp = Path(tempfile.mkdtemp(prefix="privgas-w1-"))
        (tmp / "docs").mkdir()
        (tmp / "scripts").mkdir()
        shutil.copy(REPO_ROOT / "scripts/env-report.sh", tmp / "scripts/env-report.sh")
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        return tmp

    def record(self, result, suffix, root=None):
        root = root or self.tmp
        return record_run(result.chain_dump, result.bundler_log, result.private, SEED,
                          f"20260914T000000Z-{suffix}", root,
                          clock=lambda: "2026-09-14T00:00:00Z", env_report=self.env,
                          revision=software_revision(root))

    @staticmethod
    def rows(path):
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_every_variant_records_measured_rows_with_its_own_ids(self):
        for v in EXPERIMENT_IDS:
            with self.subTest(variant=v):
                rp = self.record(self.run_of(v), RUN_ID_SUFFIX[v])["paths"]
                for row in self.rows(rp.public_events_path):
                    self.assertEqual(row["data_origin"], "measured")
                    self.assertEqual((row["baseline_id"], row["workload_id"]), v)
                    self.assertEqual(row["schema_version"], SCHEMA_VERSION)

    def test_b0_record_has_no_userop_paymaster_or_bundler(self):
        rp = self.record(self.run_of(B0), "b0cold")["paths"]
        self.assertFalse(rp.a2_dir.exists())
        for row in self.rows(rp.public_events_path):
            for f in ("userop_hash", "paymaster", "bundler_beneficiary"):
                self.assertIsNone(row[f])

    def test_b1_record_has_erc4337_fields_null_paymaster_and_separate_bundler_data(self):
        rp = self.record(self.run_of(B1C), "b1cold")["paths"]
        public = self.rows(rp.public_events_path)
        (uo,) = [r for r in public if r["event_type"] == "user_operation_event"]
        for f in ("userop_hash", "entrypoint_address", "factory", "max_fee_per_gas",
                  "pre_verification_gas"):
            self.assertIsNotNone(uo[f], f)
        self.assertTrue(all(r["paymaster"] is None for r in public))
        self.assertNotIn("simulation_result", rp.public_events_path.read_text())
        self.assertEqual(len(self.rows(rp.bundler_private_path)), 1)

    def test_b2_variants_are_recorded_distinctly(self):
        pa = self.rows(self.record(self.run_of(B2A), "b2allowcold")["paths"].public_events_path)
        ps = self.rows(self.record(self.run_of(B2S), "b2sigcold")["paths"].public_events_path)
        uo_a = next(r for r in pa if r["event_type"] == "user_operation_event")
        uo_s = next(r for r in ps if r["event_type"] == "user_operation_event")
        self.assertNotEqual(uo_a["paymaster"], uo_s["paymaster"])
        for f in ("sender", "target", "method_selector", "factory", "entrypoint_address",
                  "nonce", "call_gas_limit", "verification_gas_limit"):
            self.assertEqual(uo_a[f], uo_s[f], f)
        self.assertTrue([r for r in pa if r["calldata_class"] == "paymaster_policy"])
        self.assertEqual([r for r in ps if r["calldata_class"] == "paymaster_policy"], [])

    def test_warm_record_includes_warmup_rows_but_labels_the_ablation(self):
        out = self.record(self.run_of(B1W), "b1warm")
        rows = self.rows(out["paths"].public_events_path)
        uo = [r for r in rows if r["event_type"] == "user_operation_event"]
        self.assertEqual(len(uo), 2)
        self.assertIsNone(uo[0]["method_selector"], "warm-up op has empty callData")
        manifest = json.loads(out["paths"].public_manifest_path.read_text())
        self.assertIn("ablation", manifest["components"]["workload"]["role"])
        (gt,) = self.rows(out["paths"].ground_truth_path)
        self.assertEqual(gt["payer_to_operation_label"]["subject_ref"], uo[1]["userop_hash"])

    def test_regeneration_from_raw_is_byte_identical(self):
        other = self._sandbox()
        try:
            a = self.record(self.run_of(B2S), "b2sigcold")["paths"]
            b = self.record(self.run_of(B2S), "b2sigcold", root=other)["paths"]
            self.assertEqual(a.public_events_path.read_bytes(), b.public_events_path.read_bytes())
            self.assertEqual(a.bundler_private_path.read_bytes(),
                             b.bundler_private_path.read_bytes())
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_rejected_signature_operation_is_recorded_in_a2_only(self):
        r = run_baseline("B2-Signature", SEED, REPO_ROOT, build=False,
                         variation=Variation(wrong_sponsor_signature=True))
        rp = self.record(r, "b2sigbad")["paths"]
        public = self.rows(rp.public_events_path)
        # The full public trace (setup, asset delivery) is present, but nothing
        # about the privately rejected operation is.
        self.assertTrue([p for p in public if p["event_type"] == "asset_transfer"])
        self.assertEqual([p for p in public if p["event_type"] in
                          ("user_operation_event", "account_deployment")
                          or p["calldata_class"] == "entrypoint_handle_ops"], [])
        (row,) = self.rows(rp.bundler_private_path)
        self.assertEqual(row["rejection_category"], "paymaster_validation_revert")

    def test_leakage_selfcheck_passes_on_measured_records(self):
        for v in EXPERIMENT_IDS:
            self.record(self.run_of(v), RUN_ID_SUFFIX[v])
        proc = subprocess.run(["python3", "-m", "experiments.labels", "--all-runs",
                               "--root", str(self.tmp)], cwd=REPO_ROOT,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
