"""The automated privacy-leakage self-check (Prompt 3 Sec. 19).

Checks that the scan actually fires. A self-check nobody has seen fail is
indistinguishable from a self-check that does nothing, so every finding kind
is provoked deliberately here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from experiments.labels import scan_public_output
from experiments.recorder import paths as paths_mod
from experiments.recorder.examples.generate import RUNS, generate_one
from experiments.recorder.privatekeys import FORBIDDEN_PRIVATE_KEYS
from experiments.recorder.provenance import environment_report

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ID, RUN_ID = RUNS["B2-Allowlist"]


class TestLeakageSelfCheck(unittest.TestCase):
    _env_report = None

    @classmethod
    def setUpClass(cls):
        cls._env_report = environment_report(REPO_ROOT)

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="privgas-selfcheck-")
        self.root = Path(self._tmp)
        (self.root / "docs").mkdir()
        (self.root / "scripts").mkdir()
        shutil.copy(REPO_ROOT / "scripts" / "env-report.sh",
                    self.root / "scripts" / "env-report.sh")
        subprocess.run(["git", "init", "-q"], cwd=str(self.root), check=True)
        generate_one("B2-Allowlist", self.root, env_report=self._env_report)
        self.rp = paths_mod.run_paths(EXPERIMENT_ID, RUN_ID, self.root)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _append_public_row(self, **extra):
        rows = [json.loads(l) for l in
                self.rp.public_events_path.read_text().splitlines() if l.strip()]
        row = dict(rows[-1])
        row.update(extra)
        with open(self.rp.public_events_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            fh.write("\n")

    # --- clean baseline ------------------------------------------------------

    def test_a_generated_run_passes_the_scan(self):
        findings, summary = scan_public_output(EXPERIMENT_ID, RUN_ID, self.root)
        self.assertEqual(findings, [], "\n".join(map(str, findings)))
        self.assertTrue(summary["key_scan"])
        self.assertTrue(summary["value_scan"])
        self.assertGreater(summary["files_scanned"], 0)
        self.assertIn("Defence in depth", summary["caveat"])

    def test_summary_reports_when_only_the_key_scan_ran(self):
        _, summary = scan_public_output(root=self.root)
        self.assertTrue(summary["key_scan"])
        self.assertFalse(summary["value_scan"])

    # --- key scan ------------------------------------------------------------

    def test_a_forbidden_key_written_past_the_validator_is_caught(self):
        """Simulates output produced by some future path that skipped validation."""
        self._append_public_row(actor_id="actor_7c1e")
        findings, _ = scan_public_output(EXPERIMENT_ID, RUN_ID, self.root)
        kinds = {f.kind for f in findings}
        self.assertIn("forbidden_key", kinds)

    def test_every_named_private_key_is_detected(self):
        for key in sorted(FORBIDDEN_PRIVATE_KEYS):
            with self.subTest(key=key):
                path = self.rp.public_run_dir / "stray.json"
                path.write_text(json.dumps({key: "x"}))
                findings, _ = scan_public_output(EXPERIMENT_ID, RUN_ID,
                                                 self.root)
                path.unlink()
                self.assertTrue(
                    any(f.kind == "forbidden_key" and key in f.detail
                        for f in findings),
                    f"{key} was not detected in public output")

    def test_public_manifest_seed_null_is_not_a_finding(self):
        """'seed': null is a deliberate statement that the value is withheld."""
        manifest = json.loads(self.rp.public_manifest_path.read_text())
        self.assertIsNone(manifest["seed"])
        findings, _ = scan_public_output(EXPERIMENT_ID, RUN_ID, self.root)
        self.assertEqual(findings, [])

    def test_a_seed_value_in_the_public_manifest_is_a_finding(self):
        manifest = json.loads(self.rp.public_manifest_path.read_text())
        manifest["seed"] = 424242
        self.rp.public_manifest_path.write_text(json.dumps(manifest))
        findings, _ = scan_public_output(EXPERIMENT_ID, RUN_ID, self.root)
        self.assertTrue(any("seed" in f.detail for f in findings))

    # --- value scan ----------------------------------------------------------

    def test_a_hidden_identifier_under_a_renamed_key_is_caught(self):
        """The failure mode the key scan alone cannot see."""
        self._append_public_row(pool_id="actor_7c1e")
        findings, _ = scan_public_output(EXPERIMENT_ID, RUN_ID, self.root)
        value_findings = [f for f in findings if f.kind == "hidden_value"]
        self.assertTrue(value_findings,
                        "a hidden identifier copied under an innocuous key was "
                        "not detected")
        self.assertIn("actor_7c1e", value_findings[0].detail)

    def test_a_label_answer_copied_into_public_output_is_caught(self):
        path = self.rp.public_run_dir / "derived_features.json"
        path.write_text(json.dumps({"cluster": "funder_sponsor"}))
        findings, _ = scan_public_output(EXPERIMENT_ID, RUN_ID, self.root)
        self.assertTrue(any(f.kind == "hidden_value" for f in findings))

    def test_public_anchor_addresses_are_not_flagged(self):
        """Anchors are public values recorded in the private stream by design."""
        findings, _ = scan_public_output(EXPERIMENT_ID, RUN_ID, self.root)
        self.assertEqual(findings, [])

    # --- CLI -----------------------------------------------------------------

    def test_cli_exits_nonzero_on_a_finding(self):
        self._append_public_row(actor_id="actor_7c1e")
        proc = subprocess.run(
            ["python3", "-m", "experiments.labels", "--all-runs",
             "--root", str(self.root)],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("forbidden_key", proc.stdout)

    def test_cli_exits_zero_on_a_clean_run(self):
        proc = subprocess.run(
            ["python3", "-m", "experiments.labels", "--all-runs",
             "--root", str(self.root)],
            cwd=str(REPO_ROOT), capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("0 finding(s)", proc.stdout)
        self.assertIn("not a privacy result", proc.stdout)


if __name__ == "__main__":
    unittest.main()
