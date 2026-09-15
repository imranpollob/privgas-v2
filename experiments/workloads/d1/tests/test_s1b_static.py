"""Static tests of the S1b-issuance-redemption-timing-only scheduler (no chain).

The only intended correlation is issuance ~ redemption. Over many independent schedules,
every other pair of orders (including every order named by the experiment specification:
delivery / funding / setup vs issuance / redemption) must be independent of the slot and of
each other, and must recover the hidden pairing only at chance; the issuance -> redemption
timing model must equal S1's.
"""

from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from experiments.workloads.d1.config import (B4_CONFIG_RELPATH, S1B_CONFIG_RELPATH,
                                             experiment_id, load_pilot_config, parse_experiment_id)
from experiments.workloads.d1.schedule import (S1B, check_constraints, make_schedule,
                                               observed_orders, s1b_unintended_exposure, spearman)

REPO_ROOT = Path(__file__).resolve().parents[4]
B3, B4 = "B3-PrivGas-v1", "B4-CrossAccount"


class TestS1bConfig(unittest.TestCase):
    def test_only_variants_pool_sizes_and_the_new_schedule_entry_differ(self):
        b4 = json.loads((REPO_ROOT / B4_CONFIG_RELPATH).read_text())
        s1b = json.loads((REPO_ROOT / S1B_CONFIG_RELPATH).read_text())
        for k, v in b4.items():
            if k in ("_comment", "variants", "pool_sizes", "schedule"):
                continue
            self.assertEqual(s1b[k], v, k)
        self.assertEqual(set(s1b), set(b4))
        self.assertEqual(s1b["pool_sizes"], [8, 16, 32])
        for k, v in b4["schedule"].items():
            self.assertEqual(s1b["schedule"][k], v)
        p, p1 = s1b["schedule"][S1B], b4["schedule"]["S1-correlated-timing"]
        self.assertEqual((p["mean_interarrival"], p["action_jitter"]),
                         (p1["mean_interarrival"], p1["action_jitter"]))
        self.assertEqual(load_pilot_config(REPO_ROOT, S1B_CONFIG_RELPATH).variants(),
                         [(B3, S1B), (B4, S1B)])
        e = experiment_id(B4, S1B, 16)
        self.assertEqual(parse_experiment_id(e)["scenario_id"], S1B)


class TestS1bScheduler(unittest.TestCase):
    params = load_pilot_config(REPO_ROOT, S1B_CONFIG_RELPATH).raw["schedule"]
    SEEDS = range(400)

    def sched(self, seed, n, b=B4):
        return make_schedule(seed, n, S1B, b, self.params, start_time=1_800_000_000)

    def orders(self, s):
        o = observed_orders(s)
        o["setup"], o["setup_issuer"] = s.orders["setup"], s.orders["setup_issuer"]
        return o

    def test_matched_b3_b4_and_constraints(self):
        for n in (8, 16, 32):
            for seed in range(5):
                a, b = self.sched(seed, n, B3), self.sched(seed, n, B4)
                self.assertEqual(a.events, b.events)
                check_constraints(b)
                last_issue = max(i for i, e in enumerate(b.events) if e.phase == "issue")
                first_spend = min(i for i, e in enumerate(b.events) if e.phase in ("prepare", "act"))
                self.assertLess(last_issue, first_spend)
                self.assertTrue(all(v < 1.0 for v in s1b_unintended_exposure(b).values()))

    def test_issuance_redemption_is_the_intended_correlation(self):
        rhos = [spearman(*(lambda o: (o["issue"], o["act"]))(observed_orders(self.sched(s, 16))))
                for s in range(40)]
        self.assertGreater(sum(rhos) / len(rhos), 0.8)

    def test_issuance_to_redemption_delay_model_equals_s1(self):
        """act - issue = common offset + U(-jitter, jitter) in both scenarios: the spread of the
        per-actor delay around its run mean is bounded by the same jitter."""
        jitter = self.params[S1B]["action_jitter"]
        for seed in range(20):
            s = self.sched(seed, 16)
            iss, act = s.times("issue"), s.times("act")
            d = [act[k] - iss[k] for k in iss]
            self.assertLessEqual(max(d) - min(d), 2 * jitter + 40)  # +40: integer / serialization

    def test_every_unintended_pair_is_independent_and_at_chance(self):
        n = 16
        names = ("setup", "setup_issuer", "deliver", "fund", "issue", "prepare", "act")
        stats = {}
        for seed in self.SEEDS:
            o = self.orders(self.sched(seed, n))
            for i, p in enumerate(names):
                stats.setdefault(("slot", p), []).append(
                    spearman(list(range(n)), o[p]) * math.sqrt(n - 1))
                for q in names[i + 1:]:
                    st = stats.setdefault((p, q), [0.0, 0])
                    st[0] += spearman(o[p], o[q]) * math.sqrt(n - 1)
                    st[1] += sum(x == y for x, y in zip(o[p], o[q]))
        k = len(self.SEEDS)
        for key, st in stats.items():
            if key[0] == "slot":
                z = sum(st) / math.sqrt(k)
                self.assertLess(abs(z), 3.29, f"slot~{key[1]} z={z:.2f}")
                continue
            if key == ("issue", "act"):
                continue
            z_rho = st[0] / math.sqrt(k)
            z_match = (st[1] - k) / math.sqrt(k)
            self.assertLess(abs(z_rho), 3.29, f"{key} spearman z={z_rho:.2f}")
            self.assertLess(abs(z_match), 3.29, f"{key} rank-match z={z_match:.2f}")


if __name__ == "__main__":
    unittest.main()
