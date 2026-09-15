"""Static tests of the D1 attack/evaluation framework (no chain, no recorded data)."""

from __future__ import annotations

import math
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

import numpy as np

from experiments.privacy.d1 import metrics, models, registry, rules, splits

REPO_ROOT = Path(__file__).resolve().parents[4]


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", textwrap.dedent(code)], cwd=str(REPO_ROOT),
                          capture_output=True, text=True)


class TestRegistry(unittest.TestCase):
    def test_every_row_kind_and_varying_field_is_classified(self):
        for rk in registry.ROW_KINDS:
            for f in registry.VARYING_FIELDS:
                c = registry.FIELD_REGISTRY[(rk, f)]
                self.assertIn(c.family, registry.FAMILIES)
                if c.alt_family is not None:
                    self.assertIn(c.alt_family, registry.FAMILIES)
                    self.assertTrue(c.ambiguity, f"{rk}.{f}: alternative without ambiguity note")

    def test_feature_sources_are_registered_and_subfamilies_known(self):
        for ft in registry.FEATURES:
            self.assertIn(ft.subfamily, registry.SUBFAMILIES)
            for rk, f in ft.sources:
                if rk != "AUX":
                    self.assertIn((rk, f), registry.FIELD_REGISTRY)
            self.assertTrue(ft.families("primary") or all(rk == "AUX" for rk, _ in ft.sources))

    def test_no_raw_identifier_fields_are_numeric_features(self):
        """Addresses and hashes enter only through equality / relation features."""
        ident = {"sender", "target", "subject_account", "paymaster", "transaction_hash",
                 "userop_hash", "commitment", "nullifier", "merkle_root", "factory"}
        for ft in registry.FEATURES:
            if ft.subfamily in ("gas", "timing"):
                continue
            used = {f for _, f in ft.sources}
            self.assertTrue(ft.subfamily in ("eq", "pm", "structure") or not (used & ident))

    def test_primary_family_decisions(self):
        fam = registry.field_family
        self.assertEqual(fam("erc20_in_op", "sender"), "T")
        self.assertEqual(fam("uoe@app", "sender"), "AA")
        self.assertEqual(fam("uoe@app", "paymaster"), "G")
        self.assertEqual(fam("uoe@app", "pre_verification_gas"), "G")
        self.assertEqual(fam("uoe@bootstrap", "sender"), "G")
        self.assertEqual(fam("uoe@bootstrap", "sender", "field_kind"), "AA")
        self.assertEqual(fam("pool_redeem_log", "sender"), "G")
        self.assertEqual(fam("announce_log", "subject_account", "field_kind"), "T")

    def test_selection_respects_families_and_ablations(self):
        t_only = registry.select("R2", "B3-PrivGas-v1", ("T",))
        self.assertEqual(t_only, [])  # R2 candidates have no T-only attributes
        full = registry.select("R2", "B3-PrivGas-v1", ("T", "AA", "G"))
        no_eq = registry.select("R2", "B3-PrivGas-v1", ("T", "AA", "G"), drop_subfamilies=("eq",))
        self.assertTrue(all(f.subfamily != "eq" for f in no_eq))
        self.assertLess(len(no_eq), len(full))
        for f in registry.select("R3", "B1", ("G",)):
            self.assertEqual(f.families(), frozenset({"G"}))

    def test_generated_doc_is_in_sync(self):
        doc = (REPO_ROOT / registry.DOC_PATH).read_text()
        body = doc[doc.index(registry.BEGIN) + len(registry.BEGIN):doc.index(registry.END)]
        self.assertEqual(body.strip(), registry.render().strip(),
                         "run: python3 -m experiments.privacy.d1.registry --write")

    def test_rules_declare_consistent_feature_sets(self):
        # attacker_view claims a process side, so its regex is checked in a subprocess
        r = _run("""
            from experiments.attacker_view.predictions import RE_FEATURE_SET
            from experiments.privacy.d1 import rules
            bad = [x.rule_id for x in rules.RULES
                   if not RE_FEATURE_SET.match(x.feature_set) or x.observer_tier != "A0"]
            print("BAD", bad)
        """)
        self.assertIn("BAD []", r.stdout, r.stderr)


class TestModelAndMetrics(unittest.TestCase):
    def test_uniform_without_features(self):
        m = models.ConditionalLogit(feature_names=[]).fit([np.zeros((5, 0))], [2])
        p = m.predict_proba(np.zeros((5, 0)))
        s = metrics.subject_metrics(p, 2)
        self.assertAlmostEqual(s["ce_bits"], math.log2(5))
        self.assertAlmostEqual(s["top1"], 0.2)
        self.assertAlmostEqual(s["top3"], 0.6)

    def test_learns_a_real_signal_and_ignores_noise(self):
        rng = np.random.default_rng(0)
        groups, idx = [], []
        for _ in range(200):
            X = rng.normal(size=(8, 2))
            t = int(rng.integers(8))
            X[:, 0] = 0.0
            X[t, 0] = 1.0
            groups.append(X)
            idx.append(t)
        m = models.ConditionalLogit(l2=1.0, feature_names=["signal", "noise"]).fit(groups, idx)
        self.assertGreater(abs(m.coef_[0]), 5 * abs(m.coef_[1]))
        X = rng.normal(size=(8, 2)); X[:, 0] = 0; X[3, 0] = 1
        self.assertEqual(int(np.argmax(m.predict_proba(X))), 3)

    def test_vectorised_objective_matches_loop(self):
        rng = np.random.default_rng(1)
        groups = [rng.normal(size=(int(rng.integers(2, 9)), 3)) for _ in range(30)]
        idx = [int(rng.integers(len(g))) for g in groups]
        m = models.ConditionalLogit(l2=0.5, feature_names=["a", "b", "c"]).fit(groups, idx)
        # the fitted weights are a stationary point of the loop-computed objective
        Z = [(g - m.mean_) / m.scale_ for g in groups]
        grad = 0.5 * m.coef_
        for g, t in zip(Z, idx):
            s = g @ m.coef_
            p = np.exp(s - s.max()); p /= p.sum()
            grad -= g[t] - p @ g
        self.assertLess(float(np.abs(grad).max()), 1e-3)

    def test_tie_aware_topk_and_bootstrap(self):
        s = metrics.subject_metrics([0.5, 0.5, 0.0, 0.0], 1)
        self.assertAlmostEqual(s["top1"], 0.5)
        self.assertAlmostEqual(s["top3"], 1.0)
        ci = metrics.cluster_bootstrap({"a": [1, 1, 1], "b": [0, 0, 0]}, reps=200)
        self.assertAlmostEqual(ci["mean"], 0.5)
        self.assertLessEqual(ci["lo"], ci["hi"])


class TestSplits(unittest.TestCase):
    def manifest(self):
        runs = []
        for b, s in (("B1", "S0-clean-shuffled"), ("B3-PrivGas-v1", "S0-clean-shuffled"),
                     ("B3-PrivGas-v1", "S1-correlated-timing")):
            for n in (4, 8):
                for rep in ("r1", "r2", "r3"):
                    runs.append({"experiment_id": f"d1-pilot/{b.lower()}/{s[:2].lower()}/n{n:02d}",
                                 "run_id": f"20260915T000000Z-{rep}", "baseline_id": b,
                                 "scenario_id": s, "pool_size": n, "replicate": rep,
                                 "status": "recorded"})
        return {"batch": "x", "runs": runs}

    def test_folds_are_run_disjoint_and_replicate_or_size_held_out(self):
        body = splits.build_splits(self.manifest())
        runs = {(r["experiment_id"], r["run_id"]): r for r in self.manifest()["runs"]}
        for f in body["folds"]:
            tr = [runs[tuple(x)] for x in f["train_runs"]]
            te = [runs[tuple(x)] for x in f["test_runs"]]
            self.assertFalse({(r["experiment_id"], r["run_id"]) for r in tr}
                             & {(r["experiment_id"], r["run_id"]) for r in te})
            # actors are keyed by (seed = replicate, pool size): no shared (replicate, N)
            self.assertFalse({(r["replicate"], r["pool_size"]) for r in tr}
                             & {(r["replicate"], r["pool_size"]) for r in te}, f["fold_id"])
        kinds = {f["kind"] for f in body["folds"]}
        self.assertEqual(kinds, {"loro", "holdout", "transfer"})


class TestBoundary(unittest.TestCase):
    def test_attack_side_cannot_import_labels(self):
        r = _run("""
            import experiments.privacy.d1.attack  # noqa
            from experiments._boundary import BoundaryViolation
            try:
                import experiments.privacy.d1.evaluate  # noqa
            except BoundaryViolation:
                print("BLOCKED")
        """)
        self.assertIn("BLOCKED", r.stdout, r.stderr)

    def test_neutral_modules_import_neither_side(self):
        r = _run("""
            import sys
            import experiments.privacy.d1.registry, experiments.privacy.d1.extract
            import experiments.privacy.d1.rules, experiments.privacy.d1.models
            import experiments.privacy.d1.metrics, experiments.privacy.d1.splits
            assert "experiments.labels" not in sys.modules
            assert "experiments.attacker_view" not in sys.modules
            print("NEUTRAL")
        """)
        self.assertIn("NEUTRAL", r.stdout, r.stderr)


if __name__ == "__main__":
    unittest.main()
