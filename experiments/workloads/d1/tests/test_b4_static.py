"""Static tests of the B4-CrossAccount ablation workload (no chain).

* the B4 config changes nothing it shares with the pilot config;
* issuer and spender identities are distinct, independent, and adding them left every
  pilot identity unchanged;
* the scheduler: B4 has exactly B3's schedule at one (seed, N, scenario) (paired), and in
  S0 the hidden issuer <-> spender permutation is NOT recoverable from any public order the
  scheduler produces (direct audit, docs/d1-b4-results.md Sec. 3).
"""

from __future__ import annotations

import hashlib
import json
import math
import unittest
from pathlib import Path

from experiments.workloads.d1.actors import KINDS, make_actors
from experiments.workloads.d1.config import (B4_CONFIG_RELPATH, CONFIG_RELPATH, experiment_id,
                                             load_pilot_config, parse_experiment_id)
from experiments.workloads.d1.schedule import (SCENARIOS, check_constraints, make_schedule,
                                               observed_orders, phases_for, spearman)

REPO_ROOT = Path(__file__).resolve().parents[4]
B3, B4 = "B3-PrivGas-v1", "B4-CrossAccount"
S0, S1 = SCENARIOS


class TestB4Config(unittest.TestCase):
    def test_every_shared_key_equals_the_pilot_config(self):
        pilot = json.loads((REPO_ROOT / CONFIG_RELPATH).read_text())
        b4 = json.loads((REPO_ROOT / B4_CONFIG_RELPATH).read_text())
        for k, v in pilot.items():
            if k in ("_comment", "variants"):
                continue
            self.assertEqual(b4[k], v, f"b4-config.json changed shared key {k!r}")
        self.assertEqual(set(b4) - set(pilot), {"b4"})
        self.assertEqual(load_pilot_config(REPO_ROOT, B4_CONFIG_RELPATH).variants(),
                         [(B3, S0), (B3, S1), (B4, S0), (B4, S1)])
        self.assertEqual(load_pilot_config(REPO_ROOT, B4_CONFIG_RELPATH).issuer_funder_eth,
                         int(pilot["actor_setup"]["asset_sender_eth"]))

    def test_experiment_id_roundtrip(self):
        for scen in SCENARIOS:
            e = experiment_id(B4, scen, 32)
            self.assertEqual(parse_experiment_id(e),
                             {"baseline_id": B4, "scenario_id": scen, "pool_size": 32})


class TestB4Identities(unittest.TestCase):
    def test_issuer_and_spender_keys_accounts_and_funders_are_distinct(self):
        for n in (4, 32):
            actors = make_actors(77, n)
            issuer = {a.issuer.address for a in actors}
            spender = {a.recipient.address for a in actors}
            funders = {a.issuer_funder.address for a in actors}
            senders = {a.asset_sender.address for a in actors}
            self.assertEqual(len(issuer), n)
            self.assertFalse(issuer & spender)
            self.assertFalse(funders & senders)
            for a in actors:
                self.assertNotEqual(a.issuer_key, a.recipient_key)
                self.assertNotEqual(a.issuer_handle(), a.stealth_handle(B4))

    def test_issuer_keys_are_not_derived_from_spender_data(self):
        """Each key is its own SHA-256 draw keyed by (seed, N, slot, kind): recomputing the
        issuer key needs only the kind name, never the recipient key or address."""
        a = make_actors(5, 4)[2]
        draw = hashlib.sha256(f"privgas-v2/d1/actor/v1/5/4/2/issuer/0".encode()).digest()
        self.assertEqual(a.issuer_key, draw)
        self.assertNotIn(a.recipient.address[2:].lower(), a.issuer_key.hex())

    def test_new_kinds_leave_pilot_identities_unchanged(self):
        a = make_actors(5, 4)[1]
        for kind, value in (("recipient", a.recipient_key), ("asset_sender", a.asset_sender_key),
                            ("wallet", a.wallet_key), ("ephemeral", a.ephemeral_key)):
            self.assertEqual(value, hashlib.sha256(
                f"privgas-v2/d1/actor/v1/5/4/1/{kind}/0".encode()).digest())
        self.assertIn("issuer", KINDS)


class TestB4Schedule(unittest.TestCase):
    params = load_pilot_config().raw["schedule"]

    def sched(self, seed, n, scen, b=B4):
        return make_schedule(seed, n, scen, b, self.params, start_time=1_800_000_000)

    def test_b4_schedule_is_the_b3_schedule(self):
        for scen in SCENARIOS:
            for n in (4, 8, 16, 32):
                b3, b4 = self.sched(11, n, scen, B3), self.sched(11, n, scen, B4)
                self.assertEqual(b3.events, b4.events)
                self.assertEqual({k: v for k, v in b4.orders.items() if k != "setup_issuer"},
                                 b3.orders)
                self.assertEqual(sorted(b4.orders["setup_issuer"]), list(range(n)))
                self.assertEqual(phases_for(B4), phases_for(B3))
                check_constraints(b4)

    def _z(self, fn, scen, n=16, seeds=range(400)):
        zs = [fn(self.sched(seed, n, scen)) * math.sqrt(n - 1) for seed in seeds]
        return sum(zs) / math.sqrt(len(zs))

    def test_s0_no_public_order_encodes_the_slot_or_another_phase(self):
        """Every order the scheduler produces for B4 S0, including the issuer-funder setup
        order, is independent of the slot and of every other order (combined z over 400
        independent schedules; |z| > 3.29 would flag)."""
        def orders(s):
            o = observed_orders(s)
            o["setup"] = s.orders["setup"]
            o["setup_issuer"] = s.orders["setup_issuer"]
            return o
        names = ("setup", "setup_issuer", "deliver", "fund", "issue", "prepare", "act")
        for i, p in enumerate(names):
            z = self._z(lambda s, p=p: spearman(list(range(s.pool_size)), orders(s)[p]), S0)
            self.assertLess(abs(z), 3.29, f"slot~{p} z={z:.2f}")
            for q in names[i + 1:]:
                z = self._z(lambda s, p=p, q=q: spearman(orders(s)[p], orders(s)[q]), S0)
                self.assertLess(abs(z), 3.29, f"{p}~{q} z={z:.2f}")

    def test_s0_hidden_issuer_spender_permutation_is_not_recoverable(self):
        """Direct audit: match the k-th issuance (issuer side, public order) to the k-th
        Spend (spender side, public order), and every other order pairing an issuer-side
        phase with a spender-side phase. Recovery of the true pairing must be at chance
        (1/N) over many schedules."""
        n, seeds = 16, range(400)
        issuer_side = ("setup_issuer", "fund", "issue")
        spender_side = ("setup", "deliver", "prepare", "act")
        for p in issuer_side:
            for q in spender_side:
                hits = 0
                for seed in seeds:
                    s = self.sched(seed, n, S0)
                    o = observed_orders(s)
                    o["setup"], o["setup_issuer"] = s.orders["setup"], s.orders["setup_issuer"]
                    hits += sum(a == b for a, b in zip(o[p], o[q]))
                total = n * len(seeds)
                rate = hits / total
                sd = math.sqrt((1 / n) * (1 - 1 / n) / total)
                self.assertLess(abs(rate - 1 / n), 3.29 * sd,
                                f"{p} rank-matched to {q} recovers {rate:.3f} (chance {1/n:.3f})")

    def test_s1_is_correlated_by_design_but_setup_issuer_is_not(self):
        rhos = [spearman(observed_orders(s)["issue"], observed_orders(s)["act"])
                for s in (self.sched(seed, 16, S1) for seed in range(20))]
        self.assertGreater(sum(rhos) / len(rhos), 0.8)
        z = self._z(lambda s: spearman(s.orders["setup_issuer"], observed_orders(s)["issue"]), S1)
        self.assertLess(abs(z), 3.29)


if __name__ == "__main__":
    unittest.main()
