"""Live anvil tests of the D1 pilot workload (frozen B3, real proofs).

* multi-member B3: every Spend proof is made against the ONE final root, spends
  in an order independent of insertion all succeed, the off-chain group root
  equals CreditPool / CreditPaymaster and every emitted intermediate root, and
  spends never change the root;
* the latest-root assumption is checked directly on the frozen contracts: a
  valid proof against an earlier (prefix) root is rejected (RootMismatch), the
  same identity's proof against the current root is accepted;
* every pilot baseline runs and records at N=4; the leakage self-check passes;
  the public order of every phase equals the private schedule;
* extracted features respect the registry; training-label export refuses to
  put a test run in a training fold.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from eth_abi import encode

from experiments.recorder.provenance import environment_report, software_revision
from experiments.workloads.d1.actors import make_actors
from experiments.workloads.d1.recording import record_pilot_run
from experiments.workloads.d1.runner import RunSpec, run_pilot
from experiments.workloads.w1 import abi, b3, calibration, profiles
from experiments.workloads.w1.artifacts import load_all
from experiments.workloads.w1.bundler import InstrumentedBundler
from experiments.workloads.w1.chain import Chain
from experiments.workloads.w1.config import load_config
from experiments.workloads.w1.keys import faucet, role_keys
from experiments.workloads.w1.prover import SemaphoreProver, group_depth
from experiments.workloads.w1.rpc import AnvilProcess
from experiments.workloads.w1.runner import _application_call, _token_transfer_data, setup_environment
from experiments.workloads.w1.userop import (UserOp, counterfactual_address, get_userop_hash,
                                             init_code, sign_userop)

REPO_ROOT = Path(__file__).resolve().parents[4]
B3 = "B3-PrivGas-v1"
SEED = 31337001


class TestB3LatestRootSemantics(unittest.TestCase):
    """Two actors on the frozen contracts: a stale-root proof fails, a final-root proof works."""

    def test_stale_root_rejected_final_root_accepted_spend_keeps_root(self):
        cfg, arts = load_config(REPO_ROOT), load_all(REPO_ROOT)
        b3a, b3c = b3.load_b3_all(REPO_ROOT), b3.load_b3_config(REPO_ROOT)
        prof = profiles.B3_COMPAT
        keys = role_keys(SEED)
        actors = make_actors(SEED, 2)
        with AnvilProcess(cfg.chain_id, cfg.base_fee, prof.anvil_args()) as anvil, \
                SemaphoreProver(REPO_ROOT) as prover:
            chain = Chain(rpc=anvil.rpc, chain_id=cfg.chain_id, base_fee=cfg.base_fee,
                          max_fee=cfg.max_fee, max_priority_fee=cfg.max_priority_fee)
            env = setup_environment(chain, cfg, keys, arts, prof, b3a, b3c)
            bundler = InstrumentedBundler(chain=chain, entrypoint=env.entrypoint,
                                          account=keys.account("bundler"),
                                          beneficiary=keys.address("beneficiary"),
                                          bundle_gas_limit=cfg.gas_limit("bundle"))
            commits, accts = [], []
            for a in actors:
                acct = counterfactual_address(chain, env.factory, a.recipient.address, 0)
                accts.append(acct)
                chain.send(faucet(), label="f", phase="setup", to=a.asset_sender.address,
                           value=10 ** 17, gas=21000)
                chain.send(keys.account("asset_sender"), label="t", phase="setup", to=env.token,
                           data=_token_transfer_data(acct, cfg.transfer_amount), gas=65000)
                chain.send(a.asset_sender, label="a", phase="workflow", to=env.b3.registry,
                           value=b3c.v_min + b3c.non_refundable_fee,
                           data=b3.announce_and_fund_calldata(1, acct, b3.ephemeral_public_key(
                               a.ephemeral), b""), gas=300000)
                c = prover.commitment(a.semaphore_secret)
                commits.append(c)
                op = UserOp(sender=acct, nonce=0, init_code=init_code(env.factory, a.recipient.address, 0),
                            call_data=b3.bootstrap_call_data(env.b3.credit_pool, c),
                            verification_gas_limit=300000, call_gas_limit=450000,
                            pre_verification_gas=80000, max_priority_fee_per_gas=cfg.max_priority_fee,
                            max_fee_per_gas=cfg.max_fee, paymaster=env.b3.bootstrap_paymaster,
                            paymaster_verification_gas_limit=60000, paymaster_post_op_gas_limit=0)
                sign_userop(chain, env.entrypoint, op, a.recipient)
                self.assertTrue(bundler.send_user_operation(op, label="boot").accepted)

            final_root = b3.view_uint(chain, env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT)
            self.assertEqual(prover.group_root(commits)["root"], final_root)
            prefix_root = prover.group_root(commits[:1])["root"]
            self.assertNotEqual(prefix_root, final_root)

            def spend(members, depth):
                a, acct = actors[0], accts[0]
                op = UserOp(sender=acct, nonce=1, init_code=b"", call_data=_application_call(cfg, env, keys),
                            verification_gas_limit=300000, call_gas_limit=60000,
                            pre_verification_gas=80000, max_priority_fee_per_gas=cfg.max_priority_fee,
                            max_fee_per_gas=cfg.max_fee, paymaster=env.b3.credit_paymaster,
                            paymaster_verification_gas_limit=400000, paymaster_post_op_gas_limit=0)
                op.paymaster_signature = b3.PLACEHOLDER_PROOF
                h = get_userop_hash(chain, env.entrypoint, op)
                res = prover.prove(identity_secret=a.semaphore_secret, members=members,
                                   message=int(h, 16), scope=env.b3.credit_scope,
                                   merkle_tree_depth=depth, label="t")
                op.paymaster_signature = b3.encode_proof(res.proof)
                sign_userop(chain, env.entrypoint, op, a.recipient)
                return bundler.send_user_operation(op, label="spend")

            stale = spend(commits[:1], 1)  # valid proof, but against the prefix root
            self.assertFalse(stale.accepted)
            inner = stale.log[-1]["raw_error"]["decoded"].get("inner", "")
            self.assertTrue(inner.startswith("0x" + abi.selector("RootMismatch(uint256,uint256)").hex()),
                            stale.log[-1]["raw_error"]["decoded"])
            fresh = spend(commits, group_depth(2))
            self.assertTrue(fresh.accepted)
            self.assertEqual(b3.view_uint(chain, env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT),
                             final_root, "a Spend must not change the root")


class TestPilotRunsAndRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="d1-live-"))
        cls.env = environment_report(REPO_ROOT)
        cls.rev = software_revision(REPO_ROOT)
        cls.results = {}
        for b, s in (("B0", "S0-clean-shuffled"), ("B1", "S0-clean-shuffled"),
                     ("B2-Signature", "S0-clean-shuffled"), ("B2-Allowlist", "S0-clean-shuffled"),
                     (B3, "S0-clean-shuffled"), (B3, "S1-correlated-timing")):
            r = run_pilot(RunSpec(b, s, 4, 1, SEED), REPO_ROOT)
            rec = record_pilot_run(r, "20260915T000000Z-r1", cls.tmp, env_report=cls.env,
                                   revision=cls.rev)
            cls.results[(b, s)] = (r, rec)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_b3_root_checks_and_final_root_proofs(self):
        for s in ("S0-clean-shuffled", "S1-correlated-timing"):
            r, _ = self.results[(B3, s)]
            names = {c["name"] for c in r.checks}
            for required in ("b3_offchain_root_equals_credit_pool_root",
                             "b3_offchain_root_equals_credit_paymaster_root",
                             "b3_tree_size_equals_pool_size", "b3_nullifiers_distinct",
                             "b3_root_unchanged_after_all_spends", "bundler_net_within_tolerance"):
                self.assertIn(required, names)
            self.assertTrue(all(c["ok"] for c in r.checks))
            proofs = r.private["wallclock"]["proofs"]
            self.assertTrue(proofs and all(p["group_size"] == 4 and p["merkle_tree_depth"] == 2
                                           for p in proofs))

    def test_s0_spend_order_differs_from_insertion_order_somewhere(self):
        r, _ = self.results[(B3, "S0-clean-shuffled")]
        self.assertEqual(sorted(r.private["b3"]["insertion_order"]), [0, 1, 2, 3])

    def test_timestamps_are_schedule_time(self):
        r, _ = self.results[("B1", "S0-clean-shuffled")]
        sched = {tuple(e[1:]): e[0] for e in r.private["schedule"]["events"]}
        by_hash = {t["tx"]["hash"]: int(t["block"]["timestamp"], 16) for t in r.chain_dump["transactions"]}
        for h, label in r.private["tx_labels"].items():
            if label.startswith("deliver/"):
                self.assertEqual(by_hash[h], sched[("deliver", int(label.split("/")[1]))])

    def test_selfcheck_and_evaluation_side_audits(self):
        proc = subprocess.run([sys.executable, "-m", "experiments.labels", "--all-runs", "--root",
                               str(self.tmp)], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        runs = [{"experiment_id": rec["experiment_id"], "run_id": rec["run_id"], "baseline_id": b,
                 "scenario_id": s} for (b, s), (_, rec) in self.results.items()]
        code = textwrap.dedent(f"""
            import json
            from pathlib import Path
            from experiments.privacy.d1.evaluate.audit import harness_audit
            res = harness_audit(Path({str(self.tmp)!r}), json.loads({json.dumps(json.dumps(runs))}))
            print("ORDER_OK", res["public_order_equals_private_schedule"])
        """)
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertIn("ORDER_OK True", proc.stdout, proc.stderr)

    def test_features_extract_for_every_baseline(self):
        code = textwrap.dedent(f"""
            from pathlib import Path
            from experiments.privacy.d1.attack.io import load_trace
            from experiments.privacy.d1 import extract
            root = Path({str(self.tmp)!r})
            for exp in {[rec["experiment_id"] for _, rec in self.results.values()]!r}:
                t = load_trace(root, exp, "20260915T000000Z-r1")
                for rel in ("R1", "R2", "R3"):
                    sc = extract.features(t, rel)
                    assert all(len(c.candidates) >= 4 for c in sc), (exp, rel)
            print("FEATURES_OK")
        """)
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertIn("FEATURES_OK", proc.stdout, proc.stderr)

    def test_training_label_export_refuses_a_test_run_in_training(self):
        batch = self.tmp / "results" / "d1-pilot" / "bad"
        batch.mkdir(parents=True, exist_ok=True)
        (_, rec) = self.results[("B1", "S0-clean-shuffled")]
        ref = [rec["experiment_id"], rec["run_id"]]
        body = {"batch": "bad", "folds": [{"fold_id": "x", "baseline_id": "B1",
                                           "scenario_id": "S0-clean-shuffled", "kind": "loro",
                                           "train_runs": [ref], "test_runs": [ref]}]}
        from experiments.privacy.d1 import splits
        (batch / "splits.json").write_text(json.dumps(body))
        (batch / "splits.sha256").write_text(splits.canonical_sha256(body))
        code = textwrap.dedent(f"""
            from pathlib import Path
            from experiments.privacy.d1.evaluate.labels_io import export_training_labels
            try:
                export_training_labels(Path({str(self.tmp)!r}), "bad")
            except RuntimeError as e:
                print("REFUSED", e)
        """)
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertIn("REFUSED", proc.stdout, proc.stderr)


if __name__ == "__main__":
    unittest.main()
