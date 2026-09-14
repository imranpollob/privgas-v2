"""End-to-end recorder behaviour and the B0/B1/B2 integration (Prompt 3 Sec. 18).

Each test generates the synthetic example run for a baseline into an isolated
sandbox and checks the properties the baseline is supposed to have. These runs
are fixtures -- what is under test is the recorder's behaviour per baseline,
not a measurement. Real B0/B1/B2 runs are tested end to end against anvil in
experiments/workloads/w1/tests/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from experiments.recorder import RecorderError, validate_record
from experiments.recorder import paths as paths_mod
from experiments.recorder.examples.generate import RUNS, generate_one
from experiments.recorder.provenance import environment_report, software_revision
from experiments.recorder.writers import ExperimentRecorder, new_run_id

REPO_ROOT = Path(__file__).resolve().parents[2]


class SandboxTestCase(unittest.TestCase):
    _env_report = None

    @classmethod
    def setUpClass(cls):
        cls._env_report = environment_report(REPO_ROOT)

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="privgas-recorder-")
        self.root = Path(self._tmp)
        (self.root / "docs").mkdir()
        (self.root / "scripts").mkdir()
        shutil.copy(REPO_ROOT / "scripts" / "env-report.sh",
                    self.root / "scripts" / "env-report.sh")
        subprocess.run(["git", "init", "-q"], cwd=str(self.root), check=True)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def generate(self, baseline_id):
        result = generate_one(baseline_id, self.root,
                              env_report=self._env_report)
        experiment_id, run_id = RUNS[baseline_id]
        return result, paths_mod.run_paths(experiment_id, run_id, self.root)

    @staticmethod
    def read_jsonl(path):
        return [json.loads(line) for line in
                path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestB0Integration(SandboxTestCase):
    def test_b0_run_has_no_useroperation_no_paymaster_no_bundler(self):
        result, rp = self.generate("B0")
        rows = self.read_jsonl(rp.public_events_path)
        self.assertTrue(rows)

        for row in rows:
            validate_record("public_events", row)
            self.assertEqual(row["baseline_id"], "B0")
            self.assertIsNone(row["userop_hash"], "B0 has no UserOperation")
            self.assertIsNone(row["entrypoint_address"])
            self.assertIsNone(row["entrypoint_version"])
            self.assertIsNone(row["paymaster"], "B0 has no Paymaster")
            self.assertIsNone(row["max_fee_per_gas"])
            self.assertIsNone(row["call_gas_limit"])
            self.assertEqual(row["observer_tier"], "A0")

        self.assertIsNone(result["bundler_private_path"])
        self.assertFalse(rp.bundler_private_path.exists(),
                         "B0 must not produce a bundler stream file at all")
        self.assertFalse(rp.a2_dir.exists(),
                         "B0 must not even leave an empty A2 directory, which "
                         "would read as 'we looked and saw nothing'")

    def test_b0_recorder_refuses_a_bundler_row(self):
        experiment_id, _ = RUNS["B0"]
        rec = ExperimentRecorder(
            experiment_id=experiment_id, run_id=new_run_id(synthetic=True),
            baseline_id="B0", workload_id="W1", seed=1, chain_id=31337,
            components={}, data_origin="synthetic_fixture",
            revision=software_revision(self.root),
            paths=paths_mod.run_paths(experiment_id, new_run_id(
                synthetic=True, suffix="x"), self.root))
        with rec:
            with self.assertRaises(RecorderError):
                rec.record_bundler_private({})

    def test_b0_public_manifest_records_no_entrypoint(self):
        _, rp = self.generate("B0")
        manifest = json.loads(rp.public_manifest_path.read_text())
        self.assertIsNone(manifest["components"]["entrypoint"])
        self.assertIsNone(manifest["components"]["paymaster"])
        self.assertIsNone(manifest["streams"]["bundler_private"])


class TestB1Integration(SandboxTestCase):
    def test_b1_records_erc4337_fields_with_a_null_paymaster(self):
        _, rp = self.generate("B1")
        rows = self.read_jsonl(rp.public_events_path)
        ops = [r for r in rows if r["event_type"] == "user_operation_event"]
        self.assertTrue(ops)
        for row in ops:
            validate_record("public_events", row)
            self.assertIsNotNone(row["userop_hash"])
            self.assertEqual(row["entrypoint_version"], "0.9.0")
            self.assertIsNotNone(row["max_fee_per_gas"])
            self.assertIsNotNone(row["verification_gas_limit"])
            self.assertIsNotNone(row["pre_verification_gas"])
            self.assertIsNone(row["paymaster"],
                              "B1 has no Paymaster: null by construction")
            self.assertIsNone(row["paymaster_verification_gas_limit"])
            # Schema 2.0.0: a mined UserOperation is recoverable from chain
            # data alone, so its row is A0 (1.0.0 fixtures said A1).
            self.assertEqual(row["observer_tier"], "A0")

    def test_b1_bundler_data_is_in_its_own_directory(self):
        _, rp = self.generate("B1")
        self.assertTrue(rp.bundler_private_path.exists())
        self.assertEqual(rp.bundler_private_path.parent.name, "observer_a2")
        self.assertEqual(rp.public_events_path.parent.name, "observer_a0a1")
        self.assertNotEqual(rp.bundler_private_path.parent,
                            rp.public_events_path.parent)

        for row in self.read_jsonl(rp.bundler_private_path):
            validate_record("bundler_private", row)
            self.assertEqual(row["observer_tier"], "A2")
        for row in self.read_jsonl(rp.public_events_path):
            self.assertIn(row["observer_tier"], ("A0", "A1"))


class TestB2Integration(SandboxTestCase):
    def test_b2_matches_b1_application_semantics(self):
        """Same account code, target, selector, asset and amount as B1."""
        _, rp1 = self.generate("B1")
        _, rp2 = self.generate("B2")

        def action(rp):
            rows = self.read_jsonl(rp.public_events_path)
            ops = [r for r in rows if r["event_type"] == "user_operation_event"
                   and r["outcome"] == "success"]
            return ops[0]

        def transfer(rp):
            rows = self.read_jsonl(rp.public_events_path)
            return [r for r in rows if r["event_type"] == "asset_transfer"][-1]

        a1, a2 = action(rp1), action(rp2)
        for field in ("target", "method_selector", "calldata_class",
                      "entrypoint_address", "entrypoint_version", "factory"):
            self.assertEqual(a1[field], a2[field],
                             f"{field} must match between B1 and B2")

        t1, t2 = transfer(rp1), transfer(rp2)
        for field in ("asset_type", "asset_contract", "asset_amount",
                      "method_selector"):
            self.assertEqual(t1[field], t2[field],
                             f"{field} must match between B1 and B2")

        m1 = json.loads(rp1.public_manifest_path.read_text())
        m2 = json.loads(rp2.public_manifest_path.read_text())
        self.assertEqual(m1["components"]["asset"], m2["components"]["asset"])
        self.assertEqual(m1["components"]["destination"],
                         m2["components"]["destination"])
        self.assertEqual(m1["chain_id"], m2["chain_id"])

    def test_b2_paymaster_information_is_public(self):
        _, rp = self.generate("B2")
        rows = self.read_jsonl(rp.public_events_path)
        ops = [r for r in rows if r["event_type"] == "user_operation_event"]
        self.assertTrue(ops)
        for row in ops:
            self.assertIsNotNone(row["paymaster"])
            self.assertIsNotNone(row["paymaster_verification_gas_limit"])
        manifest = json.loads(rp.public_manifest_path.read_text())
        self.assertIsNotNone(manifest["components"]["paymaster"]["address"])

    def test_b2_bundler_information_stays_separate_from_public(self):
        _, rp = self.generate("B2")
        public_text = rp.public_events_path.read_text()
        for field in ("receive_timestamp_utc", "simulation_result",
                      "rejection_category", "replacement_lineage",
                      "bundler_id"):
            self.assertNotIn(field, public_text,
                             f"{field} is A2 data and must not be in the "
                             "A0/A1 stream")

    def test_b2_records_a_rejected_operation_rather_than_dropping_it(self):
        _, rp = self.generate("B2")
        bundler_rows = self.read_jsonl(rp.bundler_private_path)
        rejected = [r for r in bundler_rows
                    if r["simulation_result"] == "rejected"]
        self.assertTrue(rejected, "the rejected attempt must be recorded")
        self.assertEqual(rejected[0]["rejection_category"],
                         "paymaster_validation_revert")
        self.assertIsNone(rejected[0]["inclusion_timestamp_utc"])
        self.assertIsNone(rejected[0]["submitted_bundle_transaction_hash"])

        retried = [r for r in bundler_rows
                   if r["userop_hash"] == rejected[0]["userop_hash"]
                   and r["simulation_result"] == "accepted"]
        self.assertEqual([r["submission_attempt"] for r in retried], [2])

    def test_b2_privately_rejected_operation_is_not_public(self):
        """Schema 2.0.0 correction: an operation submitted to a private bundler
        and never included was seen by no A0/A1 observer, so it has no public
        row (1.0.0 fixtures recorded a public 'not_included' row for it)."""
        _, rp = self.generate("B2")
        public = self.read_jsonl(rp.public_events_path)
        self.assertEqual([r for r in public if r["outcome"] == "not_included"], [])

    def test_b2_mined_bundle_hash_is_public(self):
        _, rp = self.generate("B2")
        public_hashes = {r["transaction_hash"]
                         for r in self.read_jsonl(rp.public_events_path)}
        for row in self.read_jsonl(rp.bundler_private_path):
            if row["submitted_bundle_transaction_hash"]:
                self.assertIn(row["submitted_bundle_transaction_hash"], public_hashes)


class TestRecorderProperties(SandboxTestCase):
    def test_regeneration_is_byte_identical(self):
        """Public records can be regenerated deterministically."""
        _, rp = self.generate("B1")
        first = rp.public_events_path.read_bytes()
        first_bundler = rp.bundler_private_path.read_bytes()
        self.generate("B1")
        self.assertEqual(first, rp.public_events_path.read_bytes())
        self.assertEqual(first_bundler, rp.bundler_private_path.read_bytes())

    def test_stream_files_are_never_appended_to_across_runs(self):
        _, rp = self.generate("B1")
        with self.assertRaises(RecorderError):
            generate_one("B1", self.root, overwrite=False,
                         env_report=self._env_report)

    def test_observations_cannot_overwrite_the_envelope(self):
        experiment_id, _ = RUNS["B1"]
        run_id = new_run_id(synthetic=True, suffix="env")
        rec = ExperimentRecorder(
            experiment_id=experiment_id, run_id=run_id, baseline_id="B1",
            workload_id="W1", seed=1, chain_id=31337, components={},
            data_origin="synthetic_fixture",
            revision=software_revision(self.root),
            paths=paths_mod.run_paths(experiment_id, run_id, self.root))
        with rec:
            with self.assertRaises(RecorderError) as ctx:
                rec.record_public_event({"baseline_id": "B0"})
            self.assertIn("envelope", str(ctx.exception))

    def test_provenance_is_honest_about_an_uncommitted_worktree(self):
        rev = software_revision(self.root)
        self.assertEqual(rev["kind"], "git_worktree")
        self.assertIsNone(rev["git_commit"],
                          "a repository with no commits must not be given one")
        self.assertEqual(len(rev["worktree_id"]), 64)

    def test_every_row_carries_experiment_id_and_software_revision(self):
        for baseline_id in ("B0", "B1", "B2"):
            with self.subTest(baseline=baseline_id):
                _, rp = self.generate(baseline_id)
                paths = [rp.public_events_path, rp.ground_truth_path]
                if rp.bundler_private_path.exists():
                    paths.append(rp.bundler_private_path)
                for path in paths:
                    for row in self.read_jsonl(path):
                        self.assertTrue(row["experiment_id"])
                        self.assertTrue(row["schema_version"])
                        self.assertTrue(row["software_revision"]["describe"])
                        self.assertEqual(row["data_origin"],
                                         "synthetic_fixture")

    def test_ground_truth_lands_only_under_data_private(self):
        for baseline_id in ("B0", "B1", "B2"):
            with self.subTest(baseline=baseline_id):
                _, rp = self.generate(baseline_id)
                self.assertIn("data/private",
                              str(rp.ground_truth_path.relative_to(self.root)))
                self.assertTrue(rp.ground_truth_path.exists())
                public_files = list(rp.public_run_dir.rglob("*.jsonl"))
                self.assertTrue(public_files)
                for f in public_files:
                    self.assertNotIn("ground_truth", f.name)


if __name__ == "__main__":
    unittest.main()
