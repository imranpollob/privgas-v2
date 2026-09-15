"""Static tests of the D1 pilot workload: actor identities and schedules (no chain)."""

from __future__ import annotations

import math
import unittest

from experiments.workloads.d1.actors import make_actors, sponsor_handle
from experiments.workloads.d1.config import (experiment_id, load_pilot_config,
                                             parse_experiment_id)
from experiments.workloads.d1.schedule import (SCENARIOS as ALL_SCENARIOS, check_constraints, make_schedule,
                                               observed_orders, phases_for, spearman)
from experiments.recorder.fieldtypes import RE_EXPERIMENT_ID, RE_OPAQUE_ID

B3 = "B3-PrivGas-v1"
#: the pilot's scenarios; S1b (credit baselines only) is tested in test_s1b_static.py
SCENARIOS = ALL_SCENARIOS[:2]
BASELINES = ("B0", "B1", "B2-Signature", "B2-Allowlist", B3)


class TestActors(unittest.TestCase):
    def test_deterministic_and_distinct(self):
        a, b = make_actors(7, 16), make_actors(7, 16)
        self.assertEqual([x.actor_handle for x in a], [x.actor_handle for x in b])
        keys = [x.recipient_key for x in a] + [x.asset_sender_key for x in a] + \
               [x.wallet_key for x in a] + [x.ephemeral_key for x in a]
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(len({x.semaphore_secret for x in a}), 16)

    def test_handles_are_opaque_and_not_address_derived(self):
        for x in make_actors(11, 8):
            for h in (x.actor_handle, x.wallet_handle, x.asset_sender_handle, x.credit_handle,
                      x.issuance_handle, x.stealth_handle("B1"), sponsor_handle(11)):
                self.assertRegex(h, RE_OPAQUE_ID)
                for addr in (x.wallet.address, x.recipient.address, x.asset_sender.address):
                    self.assertNotIn(h.split("_", 1)[1], addr.lower())

    def test_pool_sizes_and_seeds_are_independent_populations(self):
        a4 = {x.recipient.address for x in make_actors(5, 4)}
        a8 = {x.recipient.address for x in make_actors(5, 8)}
        other = {x.recipient.address for x in make_actors(6, 4)}
        self.assertFalse(a4 & a8, "pool sizes of one seed must not share actors")
        self.assertFalse(a4 & other)

    def test_no_identifier_is_a_function_of_another(self):
        """Changing the derivation kind changes the value: each identity comes from its own
        stream keyed only by (seed, pool size, slot, kind)."""
        x = make_actors(3, 2)[0]
        self.assertNotEqual(x.wallet.address, x.recipient.address)
        self.assertNotEqual(x.semaphore_secret, x.recipient_key.hex())
        self.assertNotEqual(x.ephemeral_key, x.recipient_key)


class TestSchedules(unittest.TestCase):
    params = load_pilot_config().raw["schedule"]

    def sched(self, seed, n, scen, b):
        return make_schedule(seed, n, scen, b, self.params, start_time=1_800_000_000)

    def test_constraints_hold_for_every_variant(self):
        for b in BASELINES:
            for scen in SCENARIOS:
                for n in (4, 8, 16, 32):
                    for seed in range(3):
                        check_constraints(self.sched(seed, n, scen, b))

    def test_b3_every_issuance_precedes_every_spend(self):
        for scen in SCENARIOS:
            s = self.sched(9, 16, scen, B3)
            last_issue = max(i for i, e in enumerate(s.events) if e.phase == "issue")
            first_act = min(i for i, e in enumerate(s.events) if e.phase in ("prepare", "act"))
            self.assertLess(last_issue, first_act)

    def _combined_z(self, pair_fn, scen, b, n=16, seeds=range(60)):
        zs = []
        for seed in seeds:
            s = self.sched(seed, n, scen, b)
            zs.append(pair_fn(s) * math.sqrt(n - 1))
        return sum(zs) / math.sqrt(len(zs))

    def test_s0_orders_are_independent_of_slot_and_of_each_other(self):
        def slot_vs(phase):
            return lambda s: spearman(list(range(s.pool_size)), observed_orders(s)[phase])
        for phase in ("deliver", "fund", "issue", "prepare", "act"):
            z = self._combined_z(slot_vs(phase), "S0-clean-shuffled", B3)
            self.assertLess(abs(z), 3.29, f"slot~{phase} z={z:.2f}")
        z = self._combined_z(lambda s: spearman(observed_orders(s)["issue"],
                                                observed_orders(s)["act"]),
                             "S0-clean-shuffled", B3)
        self.assertLess(abs(z), 3.29, f"issue~act z={z:.2f}")

    def test_s1_actions_follow_issuance_order(self):
        rhos = [spearman(observed_orders(s)["issue"], observed_orders(s)["act"])
                for s in (self.sched(seed, 16, "S1-correlated-timing", B3) for seed in range(20))]
        self.assertGreater(sum(rhos) / len(rhos), 0.8)
        # ... but the slot itself is still not encoded
        z = self._combined_z(lambda s: spearman(list(range(s.pool_size)),
                                                observed_orders(s)["act"]),
                             "S1-correlated-timing", B3)
        self.assertLess(abs(z), 3.29)

    def test_matched_baselines_share_orders(self):
        a = self.sched(4, 8, "S0-clean-shuffled", "B1")
        b = self.sched(4, 8, "S0-clean-shuffled", B3)
        self.assertEqual(a.orders["deliver"], b.orders["deliver"])
        self.assertEqual(a.orders["act"], b.orders["act"])

    def test_phases(self):
        self.assertNotIn("fund", phases_for("B2-Signature"))
        self.assertIn("issue", phases_for(B3))


class TestConfig(unittest.TestCase):
    def test_experiment_ids_roundtrip_and_validate(self):
        for b in BASELINES:
            for scen in SCENARIOS:
                e = experiment_id(b, scen, 16)
                self.assertRegex(e, RE_EXPERIMENT_ID)
                self.assertEqual(parse_experiment_id(e),
                                 {"baseline_id": b, "scenario_id": scen, "pool_size": 16})

    def test_bootstrap_call_gas_limit_respects_frozen_cap(self):
        cfg = load_pilot_config()
        # (verificationGasLimit + callGasLimit + PVG upper bound + paymaster limit) * maxFee
        max_cost = (300_000 + cfg.bootstrap_call_gas_limit + 60_000 + 60_000) * 2 * 10 ** 9
        self.assertLessEqual(max_cost, 5 * 10 ** 15)  # BootstrapPaymaster 0.005 ETH


if __name__ == "__main__":
    unittest.main()
