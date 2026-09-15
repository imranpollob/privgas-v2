"""Static tests of the D2 pilot (no chain): configuration, record tiers, arrival process,
segments, statistics, and the frozen-B3 guard."""

from __future__ import annotations

import json
import math
import subprocess
import unittest
from pathlib import Path

import numpy as np

from experiments.liveness.d2.__main__ import load_d2_config
from experiments.liveness.d2.analysis import cloglog_fit, wilson
from experiments.liveness.d2.engine import (ArrivalProcess, OUTCOME_CLASSES, POLICIES, SEGMENT_NAMES,
                                            Segments, STALE_CLASSES)
from experiments.liveness.d2.records import (ARRIVAL_FIELD_TIERS, FIELD_TIERS, TIERS, UnclassifiedField,
                                             check_classified, project)
from experiments.workloads.w1 import b3

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = load_d2_config(REPO_ROOT)
        self.frozen = b3.load_b3_config(REPO_ROOT).userop("bootstrap_call_gas_limit")

    def test_experimental_limits_are_never_the_frozen_value(self):
        self.assertEqual(self.frozen, 160000, "b3-eval-config.json frozen Bootstrap limit changed")
        self.assertNotEqual(self.cfg["d2a"]["bootstrap_call_gas_limit"], self.frozen)
        self.assertNotEqual(self.cfg["d2b"]["high_call_gas_limit"], self.frozen)
        self.assertEqual(self.cfg["d2b"]["frozen_call_gas_limit_for_reference"], self.frozen)

    def test_experimental_limits_respect_frozen_bootstrap_cap_at_w1_fee(self):
        # (verification 300k + call + PVG (< 60k) + paymaster verification 60k) * 2 gwei <= 0.005 ETH
        for limit in (self.cfg["d2a"]["bootstrap_call_gas_limit"], self.cfg["d2b"]["high_call_gas_limit"]):
            self.assertLessEqual((300_000 + limit + 60_000 + 60_000) * 2 * 10 ** 9, 5 * 10 ** 15)

    def test_pilot_matrix_matches_prompt(self):
        s = self.cfg["d2a"]["stochastic"]
        self.assertEqual(s["pool_sizes"], [8, 16, 32])
        self.assertEqual(s["lambdas"], [0, 0.25, 0.5, 1, 2])
        self.assertEqual(s["windows"], [0.25, 0.5, 1, 2, 5])
        self.assertGreaterEqual(len(self.cfg["seeds"]), 5)
        self.assertEqual(self.cfg["d2a"]["policy_retry"]["policies"], list(POLICIES))

    def test_largest_d2a_tree_has_pinned_circuit(self):
        pin = json.loads((REPO_ROOT / "experiments/workloads/w1/prover/artifacts-pin.json").read_text())
        a = self.cfg["d2a"]
        worst = max(max(a["stochastic"]["pool_sizes"]) + a["stochastic"]["contender_capacity"],
                    a["policy_retry"]["pool_size"] + a["policy_retry"]["contender_capacity"],
                    a["measured_latency_retry"]["pool_size"] + a["measured_latency_retry"]["contender_capacity"],
                    max(a["proof_latency"]["pool_sizes"]))
        self.assertIn(str(max(1, (worst - 1).bit_length())), pin["artifacts"])


class TestRecords(unittest.TestCase):
    def test_every_field_has_a_known_tier(self):
        self.assertTrue(set(FIELD_TIERS.values()) <= set(TIERS))
        self.assertTrue(set(ARRIVAL_FIELD_TIERS.values()) <= set(TIERS))

    def test_unclassified_field_is_refused(self):
        with self.assertRaises(UnclassifiedField):
            check_classified({"outcome_class": "x", "mystery": 1})

    def test_public_view_has_no_client_private_or_bundler_fields(self):
        rec = {k: 1 for k in FIELD_TIERS}
        a0 = project(rec, ["A0"])
        for k in ("proof_generation_ms", "t0", "proof_root", "retry_number", "prior_attempt_id",
                  "simulation_result", "t3", "dropped_at"):
            self.assertNotIn(k, a0)
        self.assertIn("bundle_tx_hash", a0)
        a2 = project(rec, ["A0", "A2"])
        self.assertNotIn("proof_generation_ms", a2)
        self.assertIn("simulation_result", a2)


class TestEngineParts(unittest.TestCase):
    def test_segments_split_and_total(self):
        s = Segments.split(2.0, {"prove": 0.3, "submit": 0.05, "sim": 0.05, "queue": 0.3, "chain": 0.3})
        self.assertAlmostEqual(s.total(), 2.0)
        self.assertEqual(SEGMENT_NAMES, ("prove", "submit", "sim", "queue", "chain"))

    def test_arrival_process_is_deterministic_and_poisson(self):
        a, b = ArrivalProcess(1.5, 42), ArrivalProcess(1.5, 42)
        self.assertEqual([x.time for x in a.due(10)], [x.time for x in b.due(10)])
        counts = [len(ArrivalProcess(1.5, s).due(2.0)) for s in range(4000)]
        self.assertAlmostEqual(np.mean(counts), 3.0, delta=0.12)
        self.assertAlmostEqual(np.mean([c == 0 for c in counts]), math.exp(-3.0), delta=0.02)

    def test_zero_rate_has_no_arrivals_and_inserted_arrivals_are_due(self):
        a = ArrivalProcess(0.0, 1)
        self.assertEqual(a.due(1e9), [])
        a.insert(1.0, "adversary")
        self.assertEqual(a.due(0.5), [])
        self.assertEqual([x.kind for x in a.due(1.0)], ["adversary"])
        a.insert(2.0, "adversary")
        self.assertEqual(a.due(2.0, strict=True), [])

    def test_pop_next_leaves_later_arrivals_pending(self):
        """P2 must not apply arrivals later than the drop time: a retry restarts earlier in
        virtual time, and a chain state ahead of that clock was the cause of the 37
        inconsistent P2 records of batch 20260915T223607Z (fixed 2026-09-15)."""
        a = ArrivalProcess(0.0, 1)
        for t in (0.5, 0.7, 1.2):
            a.insert(t, "honest")
        first = a.pop_next(2.0)
        self.assertEqual(first.time, 0.5)
        self.assertEqual([x.time for x in a.pending], [0.7, 1.2])
        self.assertIsNone(ArrivalProcess(0.0, 1).pop_next(5.0))

    def test_outcome_taxonomy(self):
        self.assertTrue(set(STALE_CLASSES) < set(OUTCOME_CLASSES))
        self.assertIn("VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION", OUTCOME_CLASSES)


class TestStatistics(unittest.TestCase):
    def test_wilson(self):
        lo, hi = wilson(0, 40)
        self.assertEqual(lo, 0.0)
        self.assertLess(hi, 0.1)
        self.assertEqual(wilson(0, 0), (None, None))

    def test_cloglog_recovers_poisson_baseline_on_synthetic_data(self):
        rng = np.random.default_rng(0)
        cells = []
        for n in (8, 16, 32):
            for lam in (0.25, 0.5, 1, 2):
                for T in (0.25, 0.5, 1, 2, 5):
                    m = 400
                    k = int(rng.binomial(m, 1 - math.exp(-lam * T)))
                    cells.append({"n": n, "lambda": lam, "T": T, "lambdaT": lam * T, "stale": k, "trials": m})
        fit = cloglog_fit(cells)
        self.assertAlmostEqual(fit["b1"], 1.0, delta=0.05)
        self.assertAlmostEqual(fit["b0"], 0.0, delta=0.1)
        self.assertGreater(fit["p_pool_size"], 0.001)


class TestFrozenB3Guard(unittest.TestCase):
    def test_submodule_at_pinned_commit_and_clean(self):
        sub = REPO_ROOT / "baselines" / "b3_privgas_v1"
        head = subprocess.run(["git", "-C", str(sub), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(head, b3.B3_SOURCE_COMMIT)
        dirty = subprocess.run(["git", "-C", str(sub), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True).stdout.strip()
        self.assertEqual(dirty, "")

    def test_d2_code_does_not_write_into_baselines(self):
        src = "\n".join(p.read_text() for p in (REPO_ROOT / "experiments/liveness/d2").glob("*.py"))
        self.assertNotIn("baselines/b3_privgas_v1/src", src)


if __name__ == "__main__":
    unittest.main()
