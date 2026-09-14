"""End-to-end tests of the REAL B0/B1/B2 baselines against a throwaway anvil.

Every transaction is locally signed and submitted raw; every failure below is
a failure the node or the EntryPoint actually produced. Skipped (not passed)
when anvil or forge is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from experiments.recorder.provenance import environment_report, software_revision
from experiments.workloads.w1 import abi
from experiments.workloads.w1.accounting import AccountingError, reconcile
from experiments.workloads.w1.artifacts import forge_build
from experiments.workloads.w1.config import load_config
from experiments.workloads.w1.recording import record_run
from experiments.workloads.w1.runner import Variation, run_baseline
from experiments.workloads.w1.userop import unpack

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = 20260914
TOOLS = all(shutil.which(t) for t in ("anvil", "forge"))


def workflow_txs(result):
    return [t for t in result.chain_dump["transactions"] if t["phase"] == "workflow"]


def by_label(result, label):
    hashes = [h for h, l in result.private["tx_labels"].items() if l == label]
    return next((t for t in workflow_txs(result) if t["tx"]["hash"] in hashes), None)


def state(result, kind, addr, which):
    blk = str(result.chain_dump["blocks"]["setup_end" if which == "start" else "workflow_end"])
    return result.chain_dump["state"][kind][addr][blk]


def bundle_op(result):
    tx = by_label(result, "w3_bundle")
    ops, _ = abi.decode_handle_ops(abi.data_bytes(tx["tx"]["input"]))
    return unpack(ops[0])


@unittest.skipUnless(TOOLS, "anvil and forge are required for live baseline tests")
class LiveW1TestCase(unittest.TestCase):
    runs = {}

    @classmethod
    def setUpClass(cls):
        if not cls.runs:
            forge_build(REPO_ROOT)
            for b in ("B0", "B1", "B2"):
                LiveW1TestCase.runs[b] = run_baseline(b, SEED, REPO_ROOT, build=False)
        cls.cfg = load_config(REPO_ROOT)

    def run_of(self, b):
        return self.runs[b]


class TestB0(LiveW1TestCase):
    def test_successful_w1(self):
        r = self.run_of("B0")
        self.assertIsNone(r.failure)
        costs = reconcile(r.chain_dump, r.private)
        self.assertTrue(all(c["ok"] for c in costs["checks"]))
        self.assertEqual([t["label"] for t in workflow_txs(r)],
                         ["w1_asset_delivery", "w2_eth_allowance", "w3_recipient_action"])
        dest = r.private["roles"]["destination"]
        self.assertEqual(int(state(r, "erc20_balance", dest, "end")), self.cfg.transfer_amount)
        self.assertEqual(r.chain_dump["userops"], [])
        self.assertEqual(r.bundler_log, [])

    def test_insufficient_eth_fails_at_the_node(self):
        r = run_baseline("B0", SEED, REPO_ROOT, build=False,
                         variation=Variation(eth_allowance_delta=-1))
        self.assertIsNotNone(r.failure)
        self.assertEqual(r.failure.step, "w3_recipient_action")
        self.assertIn("insufficient funds", r.failure.detail["node_error"].lower())
        self.assertIsNone(by_label(r, "w3_recipient_action"), "never mined")
        rec = r.private["roles"]["recipient_account"]
        self.assertEqual(int(state(r, "erc20_balance", rec, "end")), self.cfg.transfer_amount)
        self.assertEqual(int(state(r, "eth_balance", rec, "end")),
                         self.cfg.b0_eth_allowance - 1, "the allowance stays unspent")
        with self.assertRaises(AccountingError):
            reconcile(r.chain_dump, r.private)  # no completed action to account for

    def test_retained_eth_is_accounted(self):
        r = self.run_of("B0")
        s = reconcile(r.chain_dump, r.private)["summary"]
        fee = int(by_label(r, "w3_recipient_action")["receipt"]["gasUsed"], 16) * 2 * 10**9
        self.assertEqual(int(s["eth_transferred_directly_to_recipient"]), self.cfg.b0_eth_allowance)
        self.assertEqual(int(s["recipient_action_gas_charge"]), fee)
        self.assertEqual(int(s["unused_recipient_eth"]), self.cfg.b0_eth_allowance - fee)
        self.assertGreater(int(s["unused_recipient_eth"]), 0)

    def test_tampered_balances_do_not_reconcile(self):
        r = self.run_of("B0")
        dump = json.loads(json.dumps(r.chain_dump))
        rec = r.private["roles"]["recipient_account"]
        end = str(dump["blocks"]["workflow_end"])
        dump["state"]["eth_balance"][rec][end] = str(int(dump["state"]["eth_balance"][rec][end]) + 1)
        with self.assertRaises(AccountingError):
            reconcile(dump, r.private)


class TestB1(LiveW1TestCase):
    def test_successful_w1(self):
        r = self.run_of("B1")
        self.assertIsNone(r.failure)
        costs = reconcile(r.chain_dump, r.private)
        self.assertIsNone(costs["userop"]["paymaster"])
        self.assertEqual([t["label"] for t in workflow_txs(r)],
                         ["w1_asset_delivery", "w2_eth_allowance", "w3_bundle"])
        rec = r.private["roles"]["recipient_account"]
        self.assertEqual(state(r, "code_size", rec, "start"), 0)
        self.assertGreater(state(r, "code_size", rec, "end"), 0)
        self.assertEqual(bundle_op(r)["paymaster"], None)
        self.assertGreater(int(costs["summary"]["unused_recipient_eth"]), 0,
                           "unused prefund is credited to the account's EntryPoint deposit")

    def test_insufficient_native_funding_is_rejected_by_simulation(self):
        r = run_baseline("B1", SEED, REPO_ROOT, build=False,
                         variation=Variation(eth_allowance_delta=-1))
        self.assertEqual(r.failure.step, "w3_bundle")
        self.assertEqual(r.failure.detail["rejection_category"], "insufficient_prefund")
        self.assertTrue(r.failure.detail["reason"].startswith("AA21"))
        self.assertIsNone(by_label(r, "w3_bundle"), "no bundle was broadcast")
        rec = r.private["roles"]["recipient_account"]
        self.assertEqual(state(r, "code_size", rec, "end"), 0)

    def test_same_application_semantics_as_b2(self):
        o1, o2 = bundle_op(self.run_of("B1")), bundle_op(self.run_of("B2"))
        for field in ("sender", "nonce", "factory", "call_data", "verification_gas_limit",
                      "call_gas_limit", "pre_verification_gas", "max_fee_per_gas",
                      "max_priority_fee_per_gas"):
            self.assertEqual(o1[field], o2[field], field)
        self.assertIsNone(o1["paymaster"])
        self.assertIsNotNone(o2["paymaster"])


class TestB2(LiveW1TestCase):
    def test_successful_sponsored_w1_with_zero_native_eth(self):
        r = self.run_of("B2")
        self.assertIsNone(r.failure)
        costs = reconcile(r.chain_dump, r.private)
        rec = r.private["roles"]["recipient_account"]
        for which in ("start", "end"):
            self.assertEqual(state(r, "eth_balance", rec, which), "0")
            self.assertEqual(state(r, "entrypoint_deposit", rec, which), "0")
        self.assertEqual([t["label"] for t in workflow_txs(r)],
                         ["w1_asset_delivery", "w2_sponsor_allowlist", "w3_bundle"])
        self.assertEqual(costs["summary"]["eth_transferred_directly_to_recipient"], "0")

    def test_paymaster_deposit_decreases_by_the_userop_charge(self):
        r = self.run_of("B2")
        costs = reconcile(r.chain_dump, r.private)
        pm = r.chain_dump["contracts"]["ObservablePaymaster"]
        delta = (int(state(r, "entrypoint_deposit", pm, "end"))
                 - int(state(r, "entrypoint_deposit", pm, "start")))
        self.assertEqual(-delta, int(costs["userop"]["actual_gas_cost"]))
        self.assertGreater(-delta, 0)

    def test_unauthorized_operation_is_rejected(self):
        r = run_baseline("B2", SEED, REPO_ROOT, build=False,
                         variation=Variation(skip_sponsorship=True))
        self.assertEqual(r.failure.step, "w3_bundle")
        self.assertEqual(r.failure.detail["rejection_category"], "paymaster_validation_revert")
        self.assertTrue(r.failure.detail["reason"].startswith("AA33"))
        self.assertIsNone(by_label(r, "w3_bundle"))
        pm = r.chain_dump["contracts"]["ObservablePaymaster"]
        self.assertEqual(state(r, "entrypoint_deposit", pm, "start"),
                         state(r, "entrypoint_deposit", pm, "end"))

    def test_same_account_implementation_as_b1(self):
        r1, r2 = self.run_of("B1"), self.run_of("B2")
        self.assertEqual(r1.chain_dump["contracts"], r2.chain_dump["contracts"])
        a1, a2 = (r.private["roles"]["recipient_account"] for r in (r1, r2))
        self.assertEqual(a1, a2)
        self.assertEqual(state(r1, "code_sha256", a1, "end"), state(r2, "code_sha256", a2, "end"))
        impl = r1.chain_dump["contracts"]["SimpleAccount_implementation"]
        self.assertEqual(state(r1, "code_sha256", impl, "end"),
                         state(r2, "code_sha256", impl, "end"))
        self.assertEqual(r1.chain_dump["artifacts"]["SimpleAccount"],
                         r2.chain_dump["artifacts"]["SimpleAccount"])


class TestShared(LiveW1TestCase):
    def test_same_token_amount_destination_and_intended_action(self):
        b0, b1, b2 = (self.run_of(b) for b in ("B0", "B1", "B2"))
        token = b0.chain_dump["contracts"]["W1Token"]
        self.assertTrue(b0.chain_dump["contracts"] == b1.chain_dump["contracts"]
                        == b2.chain_dump["contracts"])
        dest = {r.private["roles"]["destination"] for r in (b0, b1, b2)}
        self.assertEqual(len(dest), 1)

        b0_call = abi.data_bytes(by_label(b0, "w3_recipient_action")["tx"]["input"])
        self.assertEqual(by_label(b0, "w3_recipient_action")["tx"]["to"].lower(), token.lower())
        for r in (b1, b2):
            target, value, inner = abi.decode_execute(bundle_op(r)["call_data"])
            self.assertEqual(target.lower(), token.lower())
            self.assertEqual(value, 0)
            self.assertEqual(inner, b0_call, "byte-identical ERC20.transfer call")
        to, amount = abi.decode_erc20_transfer(b0_call)
        self.assertEqual(to, dest.pop())
        self.assertEqual(amount, self.cfg.transfer_amount)

    def test_same_fee_policy_on_every_workflow_transaction(self):
        for b in ("B0", "B1", "B2"):
            for t in workflow_txs(self.run_of(b)):
                with self.subTest(baseline=b, tx=t["label"]):
                    self.assertEqual(int(t["receipt"]["effectiveGasPrice"], 16), 2 * 10**9)
                    self.assertEqual(int(t["block"]["baseFeePerGas"], 16), 10**9)

    def test_repeated_runs_are_deterministic_under_the_seed(self):
        again = run_baseline("B1", SEED, REPO_ROOT, build=False)
        first = self.run_of("B1")
        key = lambda r: [(t["tx"]["hash"], t["receipt"]["gasUsed"], t["receipt"]["logs"] and
                          [l["data"] for l in t["receipt"]["logs"]]) for t in workflow_txs(r)]
        self.assertEqual(key(first), key(again))
        self.assertEqual(first.chain_dump["userops"], again.chain_dump["userops"])
        self.assertEqual(reconcile(first.chain_dump, first.private)["summary"],
                         reconcile(again.chain_dump, again.private)["summary"])


class TestGasLimitPolicy(LiveW1TestCase):
    def test_configured_call_gas_limit_incurs_no_unused_gas_penalty(self):
        """EntryPoint v0.9.0 charges 10% of unused execution gas once the unused
        amount exceeds 40k. With the matched callGasLimit it must not apply:
        lowering the limit by 10k must leave actualGasUsed unchanged."""
        from experiments.workloads.w1 import config as config_mod
        original = config_mod.W1Config.call_gas_limit
        lowered = self.cfg.call_gas_limit - 10_000
        try:
            config_mod.W1Config.call_gas_limit = property(lambda s: lowered)
            for b in ("B1", "B2"):
                with self.subTest(baseline=b):
                    r = run_baseline(b, SEED, REPO_ROOT, build=False)
                    self.assertEqual(
                        reconcile(r.chain_dump, r.private)["userop"]["actual_gas_used"],
                        reconcile(self.run_of(b).chain_dump,
                                  self.run_of(b).private)["userop"]["actual_gas_used"])
        finally:
            config_mod.W1Config.call_gas_limit = original


class TestRecording(LiveW1TestCase):
    """Real runs through the existing recorder, in an isolated sandbox root."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = environment_report(REPO_ROOT)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="privgas-w1-"))
        (self.tmp / "docs").mkdir()
        (self.tmp / "scripts").mkdir()
        shutil.copy(REPO_ROOT / "scripts/env-report.sh", self.tmp / "scripts/env-report.sh")
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def record(self, result, run_id, root=None):
        return record_run(result.chain_dump, result.bundler_log, result.private, SEED,
                          run_id, root or self.tmp, clock=lambda: "2026-09-14T00:00:00Z",
                          env_report=self.env,
                          revision=software_revision(root or self.tmp))

    @staticmethod
    def rows(path):
        return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    def test_b0_measured_record_has_no_userop_paymaster_or_bundler(self):
        out = self.record(self.run_of("B0"), "20260914T000000Z-b0")
        rp = out["paths"]
        self.assertFalse(rp.a2_dir.exists(), "no observer_a2/ directory at all")
        for row in self.rows(rp.public_events_path):
            self.assertEqual(row["data_origin"], "measured")
            self.assertFalse(row["run_id"].startswith("synthetic-"))
            for f in ("userop_hash", "entrypoint_address", "max_fee_per_gas", "paymaster",
                      "bundler_beneficiary"):
                self.assertIsNone(row[f], f)
        manifest = json.loads(rp.public_manifest_path.read_text())
        self.assertIsNone(manifest["components"]["entrypoint"])
        self.assertIsNone(manifest["streams"]["bundler_private"])

    def test_b1_measured_record_has_erc4337_fields_and_separate_bundler_data(self):
        out = self.record(self.run_of("B1"), "20260914T000000Z-b1")
        rp = out["paths"]
        public = self.rows(rp.public_events_path)
        uo = [r for r in public if r["event_type"] == "user_operation_event"]
        self.assertEqual(len(uo), 1)
        for f in ("userop_hash", "entrypoint_address", "entrypoint_version", "factory",
                  "max_fee_per_gas", "max_priority_fee_per_gas", "verification_gas_limit",
                  "call_gas_limit", "pre_verification_gas", "bundler_beneficiary"):
            self.assertIsNotNone(uo[0][f], f)
        self.assertTrue(all(r["paymaster"] is None for r in public))
        self.assertTrue(all(r["observer_tier"] == "A0" for r in public))
        self.assertEqual(len(self.rows(rp.bundler_private_path)), 1)
        text = rp.public_events_path.read_text()
        for a2_field in ("receive_timestamp_utc", "simulation_result", "bundler_id",
                         "submitted_bundle_transaction_hash"):
            self.assertNotIn(a2_field, text)

    def test_b2_measured_record_has_public_paymaster_and_matches_b1_action(self):
        rp2 = self.record(self.run_of("B2"), "20260914T000000Z-b2")["paths"]
        rp1 = self.record(self.run_of("B1"), "20260914T000000Z-b1")["paths"]
        uo1 = next(r for r in self.rows(rp1.public_events_path)
                   if r["event_type"] == "user_operation_event")
        p2 = self.rows(rp2.public_events_path)
        uo2 = next(r for r in p2 if r["event_type"] == "user_operation_event")
        pm = self.run_of("B2").chain_dump["contracts"]["ObservablePaymaster"].lower()
        self.assertEqual(uo2["paymaster"], pm)
        self.assertIsNotNone(uo2["paymaster_verification_gas_limit"])
        for f in ("sender", "target", "method_selector", "calldata_class", "factory",
                  "entrypoint_address", "nonce", "call_gas_limit", "verification_gas_limit"):
            self.assertEqual(uo1[f], uo2[f], f)
        allow = [r for r in p2 if r["event_type"] == "paymaster_event"]
        self.assertEqual(allow[0]["subject_account"], uo2["sender"])
        self.assertEqual(len(self.rows(rp2.bundler_private_path)), 1)
        self.assertNotIn("simulation_result", rp2.public_events_path.read_text())

    def test_regeneration_from_raw_is_byte_identical(self):
        r = self.run_of("B2")
        other = Path(tempfile.mkdtemp(prefix="privgas-w1-b-"))
        try:
            (other / "docs").mkdir()
            (other / "scripts").mkdir()
            shutil.copy(REPO_ROOT / "scripts/env-report.sh", other / "scripts/env-report.sh")
            subprocess.run(["git", "init", "-q"], cwd=other, check=True)
            a = self.record(r, "20260914T000000Z-b2")["paths"]
            b = self.record(r, "20260914T000000Z-b2", root=other)["paths"]
            self.assertEqual(a.public_events_path.read_bytes(), b.public_events_path.read_bytes())
            self.assertEqual(a.bundler_private_path.read_bytes(),
                             b.bundler_private_path.read_bytes())
        finally:
            shutil.rmtree(other, ignore_errors=True)

    def test_rejected_b2_operation_is_recorded_in_a2_only(self):
        r = run_baseline("B2", SEED, REPO_ROOT, build=False,
                         variation=Variation(skip_sponsorship=True))
        rp = self.record(r, "20260914T000001Z-b2")["paths"]
        public = self.rows(rp.public_events_path)
        self.assertEqual([p["event_type"] for p in public], ["asset_transfer"])
        (row,) = self.rows(rp.bundler_private_path)
        self.assertEqual(row["simulation_result"], "rejected")
        self.assertEqual(row["rejection_category"], "paymaster_validation_revert")
        self.assertIsNone(row["submitted_bundle_transaction_hash"])

    def test_leakage_selfcheck_passes_on_measured_records(self):
        for b in ("B0", "B1", "B2"):
            self.record(self.run_of(b), f"20260914T000000Z-{b.lower()}")
        proc = subprocess.run(["python3", "-m", "experiments.labels", "--all-runs",
                               "--root", str(self.tmp)], cwd=REPO_ROOT,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
