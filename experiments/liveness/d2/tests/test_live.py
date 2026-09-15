"""Live D2 tests on anvil with the frozen B3 contracts (small trees).

* the deterministic race reproduces: valid at simulation, one unrelated Bootstrap, the
  unchanged operation fails ON CHAIN with RootMismatch(proof root, new root); the bundler
  pays the reverted transaction, the CreditPaymaster deposit, sender nonce and nullifier are
  untouched; the inverse control is included; re-simulation drops it instead;
* the engine classifies an arrival between simulation and submission as
  VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION, consistently, and a retry re-proves and succeeds;
* D2-B: the frozen Bootstrap callGasLimit inserts at tree size 0 and fails at size 1 with the
  sponsored grant consumed and no deposit;
* a depth-6 proof (tree of 33, pinned artifact) verifies on chain.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from experiments.liveness.d2 import exp_a, exp_b
from experiments.liveness.d2.__main__ import load_d2_config
from experiments.liveness.d2.engine import (ArrivalProcess, ContenderPool, Segments, SpenderState, Trial,
                                            TrialSpec)
from experiments.liveness.d2.harness import D2Chain
from experiments.liveness.d2.records import check_classified

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = 424242


class TestDeterministicRace(unittest.TestCase):
    def test_race_variants(self):
        cfg = load_d2_config(REPO_ROOT)
        cfg["d2a"]["race"]["pool_sizes"] = [4]
        rows = {r["variant"]: r for r in exp_a.run_race(cfg, [SEED], log=lambda m: None)["rows"]}
        r = rows["race_P0"]
        self.assertTrue(r["simulation_accepted"])
        self.assertTrue(r["intervening_bootstrap_root_changed"])
        self.assertEqual(r["bundle_status"], 0)
        self.assertEqual(r["onchain_revert_inner_error"], "RootMismatch")
        self.assertEqual(r["onchain_revert_proof_root"], r["root_R"])
        self.assertEqual(r["onchain_revert_stored_root"], r["root_after_bootstrap"])
        self.assertEqual((r["trace_revert"] or {}).get("inner_error"), "RootMismatch")
        self.assertLess(r["bundler_net_wei"], 0)
        self.assertEqual(r["credit_paymaster_deposit_delta_wei"], 0)
        self.assertEqual(r["sender_eth_delta_wei"], 0)
        self.assertEqual(r["sender_nonce_after"], r["sender_nonce_before"])
        self.assertFalse(r["nullifier_spent"])
        self.assertEqual(rows["inverse_control"]["outcome"], "INCLUDED")
        self.assertEqual(rows["race_P1_resimulation"]["outcome"], "DROPPED_AT_RESIMULATION")
        self.assertEqual(rows["race_then_reprove"]["retry_outcome"], "INCLUDED")
        self.assertTrue(rows["race_then_reprove"]["reprove_signature_unchanged"])


class TestEngineClassification(unittest.TestCase):
    def test_arrival_in_queue_is_valid_at_simulation_stale_before_inclusion(self):
        cfg = load_d2_config(REPO_ROOT)
        ctx, states, honest, _ = exp_a._chain(SEED, cfg, 4, 1, 3)
        try:
            for pol, obs in (("P0", "ONCHAIN_ROOT_MISMATCH"), ("P1", "RESIMULATION_ROOT_MISMATCH"),
                             ("P2", "RESIMULATION_ROOT_MISMATCH")):
                snap = ctx.snapshot()
                honest.reset()
                try:
                    spec = TrialSpec("test", f"t/{pol}", SEED, 4, 0.0, Segments(0.1, 0.1, 0.1, 1.0, 1.0), pol, 2)
                    arr = ArrivalProcess(0.0, 0)
                    arr.insert(0.8, "honest")   # after simulation (t4 = 0.3), before submission (t7 = 1.3)
                    s = SpenderState(*states[0])
                    tr = Trial(ctx, spec, [s], arr, honest)
                    tr.run()
                    first, second = tr.records
                    for rec in tr.records:
                        check_classified(rec)
                    self.assertEqual(first["outcome_class"], "VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION")
                    self.assertEqual(first["failure_observation"], obs)
                    self.assertEqual(first["stale_onset_segment"], "queue")
                    self.assertTrue(first["consistent"])
                    self.assertEqual(second["outcome_class"], "VALID_PROOF_INCLUDED")
                    self.assertTrue(second["reproved"])
                    self.assertNotEqual(second["proof_root"], first["proof_root"])
                    self.assertEqual(ctx.ep_nonce_of(s.participant), s.base_op.nonce + 1)
                finally:
                    ctx.revert(snap)
        finally:
            ctx.__exit__(None, None, None)


class TestFrozenBootstrapLimit(unittest.TestCase):
    def test_frozen_limit_fails_at_tree_size_one(self):
        cfg = load_d2_config(REPO_ROOT)
        cfg["d2b"]["natural_sequence_attempts"] = 2
        rows = exp_b.run_natural(SEED, cfg, REPO_ROOT)["rows"]
        self.assertTrue(rows[0]["root_changed"])
        self.assertFalse(rows[1]["root_changed"])
        self.assertTrue(rows[1]["included"])
        self.assertFalse(rows[1]["execution_success"])
        self.assertTrue(rows[1]["grant_consumed"])
        self.assertFalse(rows[1]["has_deposited"])


class TestDepthSixOnChain(unittest.TestCase):
    def test_pinned_depth_six_proof_verifies_on_chain(self):
        cfg = load_d2_config(REPO_ROOT)
        with D2Chain(SEED, cfg, REPO_ROOT) as ctx:
            ctx.build_pool(33, int(cfg["d2a"]["bootstrap_call_gas_limit"]))
            p = ctx.participant("member", 0)
            ctx.give_tokens(p)
            op, h = ctx.spend_op(p)
            pr = ctx.prove_for(p, h)
            self.assertEqual(pr.depth, 6)
            self.assertTrue(ctx.bundler.simulate([ctx.with_proof(op, h, pr)]).accepted)


if __name__ == "__main__":
    unittest.main()
