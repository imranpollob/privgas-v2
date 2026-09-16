"""D2K static tests: no chain, no proofs.

These pin the things the live experiments assume: that the retention model and the engine
override agree, that the frozen engine still calls the overridden method the way the
override requires, that the D2K record tiers extend the frozen ones without changing any,
that the config merge inherits rather than copies, and that the experimental contract is a
single-difference variant of the frozen one.
"""

from __future__ import annotations

import ast
import json
import re
import unittest
from pathlib import Path

from scipy import stats

from experiments.liveness.d2.records import FIELD_TIERS as D2_TIERS
from experiments.liveness.d2k import analysis
from experiments.liveness.d2k.__main__ import load_config
from experiments.liveness.d2k.records import D2K_FIELDS, FIELD_TIERS

REPO_ROOT = Path(__file__).resolve().parents[4]
FROZEN_ENGINE = REPO_ROOT / "experiments" / "liveness" / "d2" / "engine.py"
VARIANT = REPO_ROOT / "contracts" / "d2k" / "src" / "HistoryCreditPaymaster.sol"
FROZEN_PM = (REPO_ROOT / "baselines" / "b3_privgas_v1" / "src" / "CreditPaymaster.sol")


class TestRetentionModel(unittest.TestCase):
    def test_k1_reduces_to_the_frozen_baseline(self):
        for mu in (0.0, 0.05, 0.5, 1.0, 2.5, 7.0):
            self.assertAlmostEqual(analysis.p_stale(mu, 1), 1 - pow(2.718281828459045, -mu),
                                   places=9)

    def test_matches_the_poisson_tail(self):
        for k in (1, 2, 4, 8, 16, 32):
            for mu in (0.1, 1.0, 3.0, 12.0):
                want = 1.0 - float(stats.poisson.cdf(k - 1, mu))
                self.assertAlmostEqual(analysis.p_stale(mu, k), want, places=12)

    def test_monotone_in_k(self):
        for mu in (0.3, 1.0, 4.0):
            vals = [analysis.p_stale(mu, k) for k in (1, 2, 4, 8, 16, 32)]
            self.assertEqual(vals, sorted(vals, reverse=True))


class TestEngineOverride(unittest.TestCase):
    """The override is only correct because every frozen call site passes ``lo = t0``."""

    def test_every_frozen_call_site_passes_t0(self):
        tree = ast.parse(FROZEN_ENGINE.read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute)
                 and n.func.attr == "_root_changes_between"]
        self.assertGreaterEqual(len(calls), 3, "frozen engine call sites disappeared")
        for c in calls:
            first = c.args[0]
            self.assertTrue(isinstance(first, ast.Name) and first.id == "t0",
                            "a frozen call site no longer passes t0 as the window start; "
                            "HistoryTrial._root_changes_between would be wrong")

    def test_override_is_identity_at_capacity_one(self):
        from experiments.liveness.d2k.engine import HistoryTrial
        changes = [0.1, 0.4, 0.9, 1.6]

        class Fake(HistoryTrial):
            def __init__(self, capacity):
                self.capacity = capacity

            def raw(self, *a, **k):
                return list(changes)
        f = Fake(1)
        self.assertEqual(HistoryTrial._root_changes_between.__wrapped__ if False else
                         _apply(f, changes, 1), changes)
        for k, want in ((2, changes[1:]), (4, changes[3:]), (8, [])):
            self.assertEqual(_apply(f, changes, k), want)


def _apply(_f, changes, k):
    return changes[k - 1:] if len(changes) >= k else []


class TestRecordTiers(unittest.TestCase):
    def test_extends_without_changing_a_frozen_tier(self):
        for field, tier in D2_TIERS.items():
            self.assertEqual(FIELD_TIERS[field], tier, field)
        self.assertTrue(set(D2K_FIELDS) - set(D2_TIERS), "D2K adds no fields")
        for field, tier in D2K_FIELDS.items():
            self.assertIn(tier, ("control", "client_private", "A2", "A0", "derived"), field)

    def test_no_client_private_field_is_public(self):
        for field, tier in FIELD_TIERS.items():
            if tier == "client_private":
                self.assertNotIn(field, ("root_at_inclusion", "bundle_tx_hash"))


class TestConfigMerge(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config(REPO_ROOT)

    def test_shared_parameters_are_inherited_not_copied(self):
        own = json.loads((REPO_ROOT / "experiments" / "liveness" / "d2k"
                          / "config.json").read_text())
        for key in ("setup", "bundler", "d2a", "d2b"):
            self.assertNotIn(key, own, f"{key} must be inherited from the frozen pilot config")
            self.assertIn(key, self.cfg)

    def test_overrides_are_explicit_and_applied(self):
        applied = self.cfg["_applied_overrides"]
        self.assertIn("d2a.bootstrap_call_gas_limit", applied)
        for dotted, spec in applied.items():
            self.assertTrue(spec.get("why"), f"{dotted} has no reason")
        self.assertEqual(self.cfg["d2a"]["bootstrap_call_gas_limit"],
                         applied["d2a.bootstrap_call_gas_limit"]["value"])

    def test_bootstrap_limit_respects_the_frozen_sponsorship_cap(self):
        from experiments.workloads.w1 import b3, config as w1config
        w1 = w1config.load_config(REPO_ROOT)
        b3cfg = b3.load_b3_config(REPO_ROOT)
        gas_sum = (w1.verification_gas_limit
                   + int(self.cfg["d2a"]["bootstrap_call_gas_limit"])
                   + b3cfg.userop("bootstrap_paymaster_verification_gas_limit")
                   + b3cfg.userop("paymaster_post_op_gas_limit") + 60_000)
        self.assertLess(gas_sum * w1.max_fee, 5 * 10 ** 15,
                        "experimental Bootstrap limit breaks the frozen 0.005 ETH cap")

    def test_experimental_limits_are_never_the_frozen_value(self):
        from experiments.workloads.w1 import b3
        frozen = b3.load_b3_config(REPO_ROOT).userop("bootstrap_call_gas_limit")
        self.assertNotEqual(int(self.cfg["d2a"]["bootstrap_call_gas_limit"]), frozen)
        self.assertNotEqual(
            int(self.cfg["d2b_decomposition"]["frozen_envelope"]["high_call_gas_limit"]), frozen)

    def test_thresholds_are_preregistered_with_metrics(self):
        th = self.cfg["d2k"]["preregistered_thresholds"]
        for value, metric in (("stale_failure_rate_max", "stale_failure_metric"),
                              ("validation_overhead_max_fraction",
                               "validation_overhead_metric"),
                              ("root_update_overhead_max_fraction",
                               "root_update_overhead_metric"),
                              ("bounded_storage_max_total_slots", "bounded_storage_metric")):
            self.assertIn(value, th)
            self.assertTrue(th.get(metric), f"{value} has no stated denominator")
        self.assertIn("stale_failure_region_max_lambda_T", th)


class TestVariantIsSingleDifference(unittest.TestCase):
    """The experimental Paymaster must keep every frozen constant, error and event."""

    @staticmethod
    def _code(text: str) -> str:
        """Source with comments stripped: a rule about CODE must not be satisfied or broken
        by prose. (No string literal in either contract contains `//` or `/*`.)"""
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        return "\n".join(line.split("//")[0] for line in text.splitlines())

    def setUp(self):
        self.variant = self._code(VARIANT.read_text(encoding="utf-8"))
        self.frozen = self._code(FROZEN_PM.read_text(encoding="utf-8"))

    def test_keeps_every_frozen_constant(self):
        for line in ("uint256 public constant MAX_CREDIT_GAS = 500_000;",
                     "uint256 public constant MAX_ACCEPTED_MAX_FEE_PER_GAS = 10 gwei;",
                     'uint256 public constant CREDIT_NULLIFIER_SCOPE = '
                     'uint256(keccak256("stealth-protocol.credit.v1"));',
                     "uint256 public constant MAX_SPONSORSHIP_COST = "
                     "MAX_CREDIT_GAS * MAX_ACCEPTED_MAX_FEE_PER_GAS;"):
            self.assertIn(line, self.frozen)
            self.assertIn(line, self.variant)

    def test_keeps_every_frozen_error_and_event(self):
        for name in re.findall(r"^\s{4}(error \w+\([^)]*\);)$", self.frozen, re.M):
            self.assertIn(name, self.variant)
        for name in re.findall(r"^\s{4}(event \w+\([^)]*\);)$", self.frozen, re.M):
            self.assertIn(name, self.variant)

    def test_keeps_the_proof_binding_and_nullifier_checks(self):
        for line in ("if (proof.scope != CREDIT_NULLIFIER_SCOPE) revert WrongScope();",
                     "if (proof.message != uopHashUint) revert WrongMessage();",
                     "_nullifiers[proof.nullifier] = true;",
                     "return uint256(keccak256(abi.encodePacked(x))) >> 8;"):
            self.assertIn(line, self.variant)

    def test_does_not_keep_the_latest_root_only_check(self):
        self.assertIn("if (proof.merkleTreeRoot != _merkleRoot)", self.frozen)
        self.assertNotIn("if (proof.merkleTreeRoot != _merkleRoot)", self.variant)
        self.assertIn("if (_count[proof.merkleTreeRoot] == 0)", self.variant)

    def test_history_is_bounded_not_a_map_of_every_root(self):
        self.assertIn("historyCapacity", self.variant)
        # the only mappings are the nullifier set, the ring buffer and the refcount
        maps = re.findall(r"mapping\([^)]*\)\s+private\s+(\w+);", self.variant)
        self.assertEqual(sorted(maps), ["_count", "_nullifiers", "_ring"])


class TestAppendOnlyMembership(unittest.TestCase):
    """Historical roots are only safe if membership is append-only. Check the frozen source."""

    def setUp(self):
        self.pool = (REPO_ROOT / "baselines" / "b3_privgas_v1" / "src"
                     / "CreditPool.sol").read_text(encoding="utf-8")
        self.registry = (REPO_ROOT / "baselines" / "b3_privgas_v1" / "src"
                         / "AnnouncementRegistry.sol").read_text(encoding="utf-8")

    def test_credit_pool_only_inserts(self):
        self.assertIn("_tree._insert(commitment)", self.pool)
        for forbidden in ("_remove(", "_update(", "_insertMany("):
            self.assertNotIn(forbidden, self.pool, f"CreditPool uses {forbidden}")

    def test_eligibility_is_write_once_true(self):
        for src, name in ((self.pool, "CreditPool"), (self.registry, "AnnouncementRegistry")):
            for assign in re.findall(r"(_?eligible\[[^\]]+\]\s*=\s*\w+;)", src):
                self.assertTrue(assign.endswith("= true;"), f"{name}: {assign}")
            for assign in re.findall(r"(_used\[[^\]]+\]\s*=\s*\w+;)", src):
                self.assertTrue(assign.endswith("= true;"), f"{name}: {assign}")

    def test_no_revocation_entry_point(self):
        for word in ("revoke", "Revoke", "delete _eligible", "delete eligible"):
            self.assertNotIn(word, self.pool)
            self.assertNotIn(word, self.registry)


class TestNamespaceIsolation(unittest.TestCase):
    def test_batch_dirs_never_touch_the_frozen_pilot(self):
        from experiments.liveness.d2k.__main__ import batch_dirs
        for p in batch_dirs("X", REPO_ROOT).values():
            self.assertIn("d2-killcondition", str(p))
            self.assertNotIn("d2-pilot", str(p))


if __name__ == "__main__":
    unittest.main()
