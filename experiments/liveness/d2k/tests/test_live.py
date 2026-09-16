"""Live D2K tests on anvil: real frozen B3 contracts, real Groth16 proofs, small trees.

* the D2K deployment is the unmodified frozen pool/bootstrap/registry set and every
  acceptance component mirrors the same root;
* the retention boundary is exact on chain: a Spend proven against R is included iff fewer
  than K root updates intervene, and K = 1 behaves exactly like the frozen CreditPaymaster
  in the same trial against the same roots;
* the security invariants hold with real proofs (old-beyond-window, fabricated, future,
  wrong message, wrong scope, invalid Groth16, nullifier reuse, same credit twice);
* the LeanIMT benchmark reproduces the frozen CreditPool's root and deposit gas, so the
  gas decomposition measures the same primitive;
* the frozen callGasLimit still fails at tree size 1, consumes the grant, and the credit is
  still insertable by an unsponsored UserOperation paid from the account's own ETH.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from experiments.liveness.d2k import exp_gas, exp_hist
from experiments.liveness.d2k.__main__ import load_config
from experiments.liveness.d2k.harness import D2KChain
from experiments.liveness.d2k.records import check_classified

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = 424243


def _cfg():
    cfg = load_config(REPO_ROOT)
    cfg["d2k"]["k_values"] = [1, 2, 4]
    return cfg


class TestDeployment(unittest.TestCase):
    def test_d2k_deployment_is_frozen_code_with_one_different_constructor_argument(self):
        cfg = _cfg()
        with D2KChain(SEED, cfg, shape="fanout", ks=cfg["d2k"]["k_values"],
                      root=REPO_ROOT) as ctx:
            arts = ctx.b3arts
            for name, addr in (("CreditPool", ctx.d2k.credit_pool),
                               ("BootstrapPaymaster", ctx.d2k.bootstrap_paymaster),
                               ("AnnouncementRegistry", ctx.d2k.registry),
                               ("CreditPaymaster", ctx.d2k.frozen_credit_paymaster)):
                on_chain = bytes.fromhex(ctx.chain.code(addr, ctx.chain.block_number())[2:])
                self.assertEqual(arts[name].masked_runtime(on_chain),
                                 arts[name].masked_runtime(arts[name].deployed_bytecode),
                                 f"{name} is not the frozen bytecode")
            ctx.build_pool(4, int(cfg["d2a"]["bootstrap_call_gas_limit"]))
            ctx.assert_mirrors_agree()
            for v in ctx.d2k.variants():
                self.assertEqual(ctx.variant_root(v), ctx.pool_root())
            self.assertEqual(ctx.history_state("K4")["capacity"], 4)


class TestRetentionBoundary(unittest.TestCase):
    def test_included_iff_fewer_than_k_root_updates(self):
        cfg = _cfg()
        cfg["d2k"]["boundary"]["pool_size"] = 6
        cfg["d2k"]["boundary"]["intervening_root_updates"] = [0, 1, 2, 4]
        cfg["d2k"]["deterministic_k_values"] = [1, 2, 4]
        rows = exp_hist.run_boundary(cfg, [SEED], log=lambda m: None)["rows"]
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r["included"],
                             r["intervening_root_updates"] < r["history_capacity"], r)
            self.assertTrue(r["prediction_matches_outcome"], r)
            self.assertEqual(r["view_accepts_proof_root"], r["included"], r)
            self.assertEqual(r["nullifier_spent"], r["included"], r)
            if not r["included"]:
                self.assertEqual(r["onchain_revert_inner_error"], "RootMismatch")
                self.assertEqual(r["nonce_advanced"], 0)
        frozen = {r["intervening_root_updates"]: r["included"]
                  for r in rows if r["variant"] == "frozen"}
        k1 = {r["intervening_root_updates"]: r["included"] for r in rows if r["variant"] == "K1"}
        self.assertEqual(frozen, k1, "K = 1 does not reproduce frozen latest-root behaviour")


class TestSecurityInvariants(unittest.TestCase):
    def test_every_invariant_holds_with_real_proofs(self):
        cfg = _cfg()
        cfg["d2k"]["security"]["pool_size"] = 6
        cfg["d2k"]["security"]["capacity_under_test"] = 4
        rows = exp_hist.run_security(cfg, [SEED], log=lambda m: None)["rows"]
        self.assertGreaterEqual(len(rows), 11)
        for r in rows:
            self.assertTrue(r["expectation_met"], r)


class TestBenchmarkPrimitive(unittest.TestCase):
    def test_leanimt_bench_reproduces_the_frozen_pool(self):
        cfg = _cfg()
        d = cfg["d2b_decomposition"]
        d["max_tree_size"] = 6
        d["record_sizes"] = [1, 2, 4]
        d["bootstrap_check_sizes"] = [0, 1, 3]
        d["seeds"] = [SEED]
        out = exp_gas.run_decomp(cfg, [SEED], log=lambda m: None)
        checks = out["checks"][str(SEED)]
        self.assertTrue(checks["offchain_group_root_matches"])
        self.assertTrue(checks["leanimt_bench_root_matches_pool"],
                        "the benchmark uses a different Merkle primitive than B3")
        self.assertEqual(checks["leanimt_bench_size"], checks["final_tree_size"])
        first = out["rows"][0]
        self.assertEqual(first["g0_deposit_frame_gas"], 121763,
                         "frozen CreditPool.deposit at tree size 0 no longer reproduces "
                         "the D2 pilot's measurement")
        warm = out["floor"]["g5_poseidon_hash_gas_warm"]
        self.assertTrue(warm and len(set(warm)) == 1, "PoseidonT3 call gas is not constant")


class TestGrantConsumption(unittest.TestCase):
    def test_failed_bootstrap_consumes_the_grant_but_the_credit_survives(self):
        cfg = _cfg()
        cfg["d2b_decomposition"]["grant"]["starved_call_gas_limits"] = [160000]
        rows = exp_gas.run_grant(cfg, [SEED], log=lambda m: None)["rows"]
        r = rows[0]
        self.assertTrue(r["failed_attempt"]["sim_accepted"])
        self.assertTrue(r["failed_attempt"]["included"])
        self.assertFalse(r["failed_attempt"]["execution_success"])
        self.assertTrue(r["state_after_failure"]["bootstrap_paymaster_is_used"])
        self.assertFalse(r["state_after_failure"]["credit_pool_has_deposited"])
        self.assertFalse(r["commitment_inserted_by_failed_attempt"])
        self.assertEqual(r["nonce_advanced_by_failed_attempt"], 1)
        self.assertGreater(r["sponsor_loss_on_failure_wei"], 0)
        self.assertTrue(r["grant_permanently_consumed"])
        self.assertTrue(r["self_funded_deposit"]["userop_included"])


class TestDetection(unittest.TestCase):
    def test_validation_only_simulation_cannot_see_the_too_low_limit(self):
        cfg = _cfg()
        cfg["d2b_decomposition"]["grant"]["starved_call_gas_limits"] = [160000]
        rows = exp_gas.run_detect(cfg, [SEED], log=lambda m: None)["rows"]
        starved = [r for r in rows if r["is_frozen_limit"]][0]
        enough = [r for r in rows if not r["is_frozen_limit"]][-1]
        self.assertTrue(starved["handleops_eth_call_accepted"])
        self.assertFalse(starved["onchain_userop_success"])
        self.assertTrue(starved["trace_call_execution_out_of_gas"])
        self.assertFalse(enough["trace_call_execution_out_of_gas"])
        self.assertTrue(enough["onchain_userop_success"])
        self.assertGreater(starved["estimate_gas_pool_deposit"], starved["call_gas_limit"])


class TestRecordClassification(unittest.TestCase):
    def test_every_stochastic_record_field_is_classified(self):
        cfg = _cfg()
        c = cfg["d2k"]["stochastic"]
        c.update({"pool_size": 6, "lambdas": [1], "windows": [2], "trials_per_seed": 1,
                  "contender_capacity": 12})
        out = exp_hist.run_stochastic(cfg, [SEED], log=lambda m: None)
        self.assertTrue(out["attempts"])
        from experiments.liveness.d2k.records import ARRIVAL_FIELD_TIERS, FIELD_TIERS
        for r in out["attempts"]:
            check_classified(r, FIELD_TIERS)
            self.assertIsNot(r.get("prediction_matches_outcome"), False)
        for a in out["arrivals"]:
            check_classified(a, ARRIVAL_FIELD_TIERS)


if __name__ == "__main__":
    unittest.main()
