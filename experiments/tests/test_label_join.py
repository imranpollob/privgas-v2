"""Item J: labels join with predictions only through the evaluation path.

The full two-process workflow is exercised: a subprocess that can read only
attacker-visible data writes frozen predictions, then this process (which has
loaded ``experiments.labels`` and therefore cannot import
``experiments.attacker_view``) verifies the freeze and joins the labels.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from experiments.labels import (
    FrozenPredictionsError,
    accounts_by_actor,
    join_for_evaluation,
    load_ground_truth,
)
from experiments.recorder import paths as paths_mod
from experiments.recorder.examples.generate import RUNS, generate_one

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_ID, RUN_ID = RUNS["B2-Allowlist"]


class LabelJoinTestCase(unittest.TestCase):
    """Each test works in an isolated copy of a generated B2 example run."""

    _env_report = None

    @classmethod
    def setUpClass(cls):
        # scripts/env-report.sh shells out to every tool it knows about, which
        # is slow; the snapshot is identical for every run here, so take it
        # once.
        from experiments.recorder.provenance import environment_report
        cls._env_report = environment_report(REPO_ROOT)

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="privgas-labeljoin-")
        self.root = Path(self._tmp)
        # The recorder needs the repository's own tooling to build provenance,
        # so the sandbox mirrors just enough of the repo to be a valid root.
        (self.root / "docs").mkdir()
        (self.root / "scripts").mkdir()
        # A real (empty) repository, so provenance exercises the honest
        # "no commits yet" path rather than a stubbed one.
        subprocess.run(["git", "init", "-q"], cwd=str(self.root), check=True)
        shutil.copy(REPO_ROOT / "scripts" / "env-report.sh",
                    self.root / "scripts" / "env-report.sh")
        generate_one("B2-Allowlist", self.root, env_report=self._env_report)
        self.rp = paths_mod.run_paths(EXPERIMENT_ID, RUN_ID, self.root)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _freeze_from_attacker_process(self, attack_id="rule-equality",
                                      relation="R3", feature_set="T+G"):
        """Run prediction + freezing in a process that cannot see labels."""
        code = f"""
            import json
            from pathlib import Path
            import experiments.attacker_view as av
            from experiments._boundary import BoundaryViolation

            try:
                import experiments.labels
            except BoundaryViolation:
                pass
            else:
                raise SystemExit("attack process could import labels")

            root = Path({str(self.root)!r})
            run = av.load_run({EXPERIMENT_ID!r}, {RUN_ID!r}, "A2", root)

            # A deliberately naive placeholder "attack": every included
            # UserOperation is guessed to belong to one arbitrary candidate.
            # This is scaffolding for the join, not an attack.
            preds = [
                {{"subject_ref": row["userop_hash"], "prediction": "actor_7c1e",
                  "score": 0.5}}
                for row in run.public_events
                if row["userop_hash"] and row["outcome"] == "success"
                and row["event_type"] == "user_operation_event"
            ]
            m = av.freeze_predictions(
                experiment_id={EXPERIMENT_ID!r}, run_id={RUN_ID!r},
                attack_id={attack_id!r}, relation={relation!r},
                observer_tier="A2", predictions=preds,
                feature_set={feature_set!r}, root=root)
            print(json.dumps(m))
        """
        proc = subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                              cwd=str(REPO_ROOT), capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout.strip().splitlines()[-1])

    # --- the sanctioned path ------------------------------------------------

    def test_j_predictions_are_frozen_then_joined(self):
        manifest = self._freeze_from_attacker_process()
        self.assertEqual(manifest["relation"], "R3")
        self.assertEqual(manifest["feature_set"], "T+G")
        self.assertGreater(manifest["prediction_count"], 0)

        join = join_for_evaluation(
            experiment_id=EXPERIMENT_ID, run_id=RUN_ID,
            attack_id="rule-equality", relation="R3", root=self.root)

        self.assertEqual(join.feature_set, "T+G")
        self.assertEqual(join.observer_tier, "A2")
        self.assertEqual(len(join.rows), manifest["prediction_count"])
        self.assertTrue(any(r.label is not None for r in join.rows))
        for row in join.rows:
            if row.label is not None:
                self.assertEqual(row.label["relation"], "R3")

    def test_j_join_refuses_when_predictions_were_never_frozen(self):
        with self.assertRaises(FrozenPredictionsError):
            join_for_evaluation(experiment_id=EXPERIMENT_ID, run_id=RUN_ID,
                                attack_id="never-ran", relation="R3",
                                root=self.root)

    def test_j_join_refuses_predictions_edited_after_freezing(self):
        """Look at the answers, edit the guesses, re-score -- leaves evidence."""
        self._freeze_from_attacker_process()
        pred_path = (self.rp.predictions_dir / "rule-equality" / "R3"
                     / "predictions.jsonl")
        rows = [json.loads(l) for l in
                pred_path.read_text().splitlines() if l.strip()]
        rows[0]["prediction"] = "actor_edited_after_the_fact"
        pred_path.write_text(
            "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":"))
                      for r in rows) + "\n")

        with self.assertRaises(FrozenPredictionsError) as ctx:
            join_for_evaluation(experiment_id=EXPERIMENT_ID, run_id=RUN_ID,
                                attack_id="rule-equality", relation="R3",
                                root=self.root)
        self.assertIn("has changed since it was frozen", str(ctx.exception))

    def test_j_join_refuses_a_relation_mismatch(self):
        self._freeze_from_attacker_process(relation="R3")
        with self.assertRaises(FrozenPredictionsError):
            join_for_evaluation(experiment_id=EXPERIMENT_ID, run_id=RUN_ID,
                                attack_id="rule-equality", relation="R1",
                                root=self.root)

    def test_j_frozen_predictions_are_never_overwritten(self):
        self._freeze_from_attacker_process()
        code = f"""
            from pathlib import Path
            import experiments.attacker_view as av
            try:
                av.freeze_predictions(
                    experiment_id={EXPERIMENT_ID!r}, run_id={RUN_ID!r},
                    attack_id="rule-equality", relation="R3",
                    observer_tier="A2",
                    predictions=[{{"subject_ref": "x", "prediction": "y"}}],
                    feature_set="T", root=Path({str(self.root)!r}))
            except FileExistsError as exc:
                print("BLOCKED:", exc)
            else:
                raise SystemExit("a frozen predictions file was overwritten")
        """
        proc = subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                              cwd=str(REPO_ROOT), capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("BLOCKED:", proc.stdout)

    # --- unpredicted / unlabelled bookkeeping -------------------------------

    def test_join_reports_labelled_subjects_the_attack_skipped(self):
        """Dropping unpredicted subjects would inflate precision."""
        self._freeze_from_attacker_process(relation="R1")
        join = join_for_evaluation(
            experiment_id=EXPERIMENT_ID, run_id=RUN_ID,
            attack_id="rule-equality", relation="R1", root=self.root)
        self.assertIsInstance(join.unpredicted_subject_refs, tuple)
        self.assertIsInstance(join.unlabelled_subject_refs, tuple)

    # --- research rules encoded in the loader --------------------------------

    def test_one_actor_may_hold_several_accounts(self):
        """Rule: multiple addresses are not multiple people.

        The B2 example deliberately gives one actor two stealth accounts.
        """
        gt = load_ground_truth(EXPERIMENT_ID, RUN_ID, self.root)
        mapping = accounts_by_actor(gt)
        self.assertEqual(len(mapping), 1,
                         "the B2 fixture has exactly one actor")
        (accounts,) = mapping.values()
        stealth = {row["stealth_account_id"] for row in gt.rows}
        self.assertEqual(len(stealth), 2,
                         "the B2 fixture has two stealth accounts")
        self.assertTrue(stealth <= accounts)

    def test_labels_are_requested_one_relation_at_a_time(self):
        gt = load_ground_truth(EXPERIMENT_ID, RUN_ID, self.root)
        self.assertTrue(gt.labels_for("R1"))
        self.assertTrue(gt.labels_for("R3"))
        # B2 has no credit lifecycle, so R2 is not_applicable and yields none.
        self.assertEqual(gt.labels_for("R2"), {})

    def test_seed_is_available_only_from_the_private_manifest(self):
        gt = load_ground_truth(EXPERIMENT_ID, RUN_ID, self.root)
        self.assertEqual(gt.seed, 424242)
        public = json.loads(
            self.rp.public_manifest_path.read_text(encoding="utf-8"))
        self.assertIsNone(public["seed"])
        self.assertEqual(len(public["seed_commitment_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
