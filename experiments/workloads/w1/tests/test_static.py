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
            c.required_prefund(False, 42_000),
            (c.verification_gas_limit + c.call_gas_limit + 42_000) * c.max_fee)

    def test_pre_verification_gas_is_calibrated_not_fixed(self):
        self.assertNotIn("pre_verification_gas", self.cfg.raw["userop"])
        self.assertEqual(self.cfg.raw["userop"]["pre_verification_gas_method"],
                         "calibrated_overhead_v1")

    def test_b2_carries_no_postop_limit(self):
        self.assertEqual(self.cfg.paymaster_post_op_gas_limit, 0)


class TestCalibrationArtifact(unittest.TestCase):
    def test_artifact_is_present_consistent_and_matches_this_build(self):
        import subprocess
        from experiments.workloads.w1 import calibration
        from experiments.workloads.w1.artifacts import load_all
        artifact = calibration.load_artifact(REPO_ROOT)
        by_shape = artifact["entrypoint_unmeasured_overhead_by_shape"]
        self.assertEqual(set(by_shape), set(calibration.SHAPES_BY_PROFILE["eip170_standard"]))
        for s in artifact["samples"]:
            self.assertEqual(s["entrypoint_unmeasured_overhead"], by_shape[s["op_shape"]])
        self.assertGreaterEqual(artifact["seed_count"], 2)

        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from keys(v)
            elif isinstance(o, list):
                for v in o:
                    yield from keys(v)

        self.assertNotIn("seed", set(keys(artifact)), "calibration seeds only as commitments")
        anvil = subprocess.run(["anvil", "--version"], capture_output=True, text=True)
        if anvil.returncode == 0 and (REPO_ROOT / "baselines/w1_b0_b2/out").is_dir():
            fp = calibration.environment_fingerprint(
                load_config(REPO_ROOT), load_all(REPO_ROOT), anvil.stdout.strip())
            for shape in calibration.SHAPES_BY_PROFILE["eip170_standard"]:
                calibration.overhead_for(artifact, shape, fp)
            if (REPO_ROOT / "baselines/b3_eval/out").is_dir():
                from experiments.workloads.w1 import b3, profiles
                compat = calibration.load_artifact(REPO_ROOT, "b3_compat_local")
                fp3 = calibration.environment_fingerprint(
                    load_config(REPO_ROOT), load_all(REPO_ROOT), anvil.stdout.strip(),
                    profiles.B3_COMPAT, b3.load_b3_all(REPO_ROOT))
                for shape in calibration.SHAPES_BY_PROFILE["b3_compat_local"]:
                    calibration.overhead_for(compat, shape, fp3)
                # One environment's O must never price another environment's ops.
                with self.assertRaises(calibration.RecalibrationRequired):
                    calibration.overhead_for(artifact, "execute_call", fp3)


class TestKeys(unittest.TestCase):
    def test_keys_depend_on_seed_and_role_only(self):
        a, b = role_keys(7), role_keys(7)
        self.assertEqual(a.addresses(), b.addresses())
        self.assertNotEqual(role_keys(8).address("recipient"), a.address("recipient"))
        self.assertEqual(len(set(a.addresses().values())), len(ROLES))

    def test_handles_are_opaque(self):
        h = opaque_handle(7, "actor", "actor")
        self.assertRegex(h, r"^actor_[0-9a-f]{10}$")


class TestCalldataGas(unittest.TestCase):
    def test_eip2028_costs(self):
        from experiments.workloads.w1.pvg import calldata_gas, calldata_tokens
        self.assertEqual(calldata_gas(bytes([0, 0, 1, 255])), 4 + 4 + 16 + 16)
        self.assertEqual(calldata_tokens(bytes([0, 1])), 1 + 4)


class TestRejectionClassification(unittest.TestCase):
    def test_entrypoint_reason_codes(self):
        c = bundler_mod.classify_rejection
        self.assertEqual(c("AA21 didn't pay prefund"), "insufficient_prefund")
        self.assertEqual(c("AA31 paymaster deposit too low"), "insufficient_prefund")
        self.assertEqual(c("AA33 reverted"), "paymaster_validation_revert")
        self.assertEqual(c("AA34 signature error"), "paymaster_validation_revert")
        self.assertEqual(c("AA24 signature error"), "aa_validation_revert")
        self.assertEqual(c("AA25 invalid account nonce"), "nonce_conflict")
        self.assertEqual(c(None), "other")


if __name__ == "__main__":
    unittest.main()
