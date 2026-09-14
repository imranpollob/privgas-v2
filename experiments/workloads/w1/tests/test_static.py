"""Chain-free checks: dependency pin, matched config, accounting arithmetic."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from experiments.workloads.w1 import bundler as bundler_mod
from experiments.workloads.w1.artifacts import dependency_tree_digest
from experiments.workloads.w1.config import load_config
from experiments.workloads.w1.keys import ROLES, opaque_handle, role_keys

REPO_ROOT = Path(__file__).resolve().parents[4]


class TestDependencyPin(unittest.TestCase):
    def test_vendored_trees_match_the_pinned_digests(self):
        pin = json.loads((REPO_ROOT / "baselines/w1_b0_b2/dependency-pin.json").read_text())
        for name in ("account-abstraction", "openzeppelin-contracts"):
            with self.subTest(dependency=name):
                self.assertEqual(
                    dependency_tree_digest(REPO_ROOT / pin[name]["path"]),
                    pin[name]["tree_sha256"],
                    f"{name} changed under baselines/w1_b0_b2; B0-B2 must not "
                    "silently follow a B3 re-pin")
        self.assertEqual(pin["account-abstraction"]["commit"],
                         "b36a1ed52ae00da6f8a4c8d50181e2877e4fa410")


class TestMatchedConfig(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(REPO_ROOT)

    def test_one_fee_policy_yields_the_same_effective_price(self):
        c = self.cfg
        self.assertEqual(min(c.max_fee, c.base_fee + c.max_priority_fee), 2 * 10**9)

    def test_allowances_are_exactly_the_protocol_maximum(self):
        c = self.cfg
        self.assertEqual(c.b0_eth_allowance, c.gas_limit("b0_action") * c.max_fee)
        self.assertEqual(
            c.b1_eth_allowance,
            (c.verification_gas_limit + c.call_gas_limit + c.pre_verification_gas)
            * c.max_fee)

    def test_b2_carries_no_postop_limit(self):
        self.assertEqual(self.cfg.paymaster_post_op_gas_limit, 0)


class TestKeys(unittest.TestCase):
    def test_keys_depend_on_seed_and_role_only(self):
        a, b = role_keys(7), role_keys(7)
        self.assertEqual(a.addresses(), b.addresses())
        self.assertNotEqual(role_keys(8).address("recipient"), a.address("recipient"))
        self.assertEqual(len(set(a.addresses().values())), len(ROLES))

    def test_handles_are_opaque(self):
        h = opaque_handle(7, "actor", "actor")
        self.assertRegex(h, r"^actor_[0-9a-f]{10}$")


class TestRejectionClassification(unittest.TestCase):
    def test_entrypoint_reason_codes(self):
        c = bundler_mod.classify_rejection
        self.assertEqual(c("AA21 didn't pay prefund"), "insufficient_prefund")
        self.assertEqual(c("AA31 paymaster deposit too low"), "insufficient_prefund")
        self.assertEqual(c("AA33 reverted"), "paymaster_validation_revert")
        self.assertEqual(c("AA24 signature error"), "aa_validation_revert")
        self.assertEqual(c("AA25 invalid account nonce"), "nonce_conflict")
        self.assertEqual(c(None), "other")


if __name__ == "__main__":
    unittest.main()
