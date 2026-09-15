"""Live anvil tests of B4-CrossAccount: frozen B3 contracts, real Semaphore/Groth16 proofs.

Functional / security properties (docs/d1-b4-results.md Sec. 5), on the UNMODIFIED
contracts, with two actors A and B, each owning a distinct issuer account and spender
account:

* issuer != spender (keys and accounts); the issuer's Bootstrap succeeds although the
  issuer never held the W1 asset; the spender was never announced, eligible or a depositor;
* the spender's Spend succeeds because the proof is generated for the SPENDER's own
  userOpHash (CreditPaymaster checks no sender);
* A's finalized proof cannot be reused by an unrelated spender's operation, nor by a
  different operation of the same spender (WrongMessage);
* nullifier reuse is rejected (NullifierSpent) even from another account;
* a stale (prefix-root) proof from a cross-account spender is rejected (RootMismatch), and a
  Spend never changes the root: root handling is unchanged;
* the run gate FAILS a B4 run whose issuer equals its spender;
* full B4 runs (S0, S1, N = 4) pass every separation check, record, pass the leakage
  self-check and the harness order audit, and no account-equality rule fires on them;
* the deployed Paymasters' bytecode equals the frozen artifacts and the frozen source trees
  still match their pin.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from experiments.recorder.provenance import environment_report, software_revision
from experiments.workloads.d1 import runner as d1_runner
from experiments.workloads.d1.actors import make_actors
from experiments.workloads.d1.config import B4_CONFIG_RELPATH, load_pilot_config
from experiments.workloads.d1.recording import record_pilot_run
from experiments.workloads.d1.runner import PilotRunFailure, RunSpec, run_pilot
from experiments.workloads.w1 import abi, b3, profiles
from experiments.workloads.w1.artifacts import dependency_tree_digest, load_all
from experiments.workloads.w1.bundler import InstrumentedBundler
from experiments.workloads.w1.chain import Chain
from experiments.workloads.w1.config import load_config
from experiments.workloads.w1.keys import faucet, role_keys
from experiments.workloads.w1.prover import SemaphoreProver, group_depth
from experiments.workloads.w1.rpc import AnvilProcess
from experiments.workloads.w1.runner import (_application_call, _token_transfer_data,
                                             setup_environment)
from experiments.workloads.w1.userop import (UserOp, counterfactual_address, get_userop_hash,
                                             init_code, sign_userop)

REPO_ROOT = Path(__file__).resolve().parents[4]
B4 = "B4-CrossAccount"
SEED = 31337004


def _inner_selector(outcome) -> str:
    return (outcome.log[-1].get("raw_error") or {}).get("decoded", {}).get("inner", "")


def _sel(sig: str) -> str:
    return "0x" + abi.selector(sig).hex()


class TestCrossAccountSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg, arts = load_config(REPO_ROOT), load_all(REPO_ROOT)
        cls.b3a, b3c = b3.load_b3_all(REPO_ROOT), b3.load_b3_config(REPO_ROOT)
        cls.b3c = b3c
        prof = profiles.B3_COMPAT
        cls.keys = role_keys(SEED)
        cls.actors = make_actors(SEED, 2)
        cls._anvil = AnvilProcess(cls.cfg.chain_id, cls.cfg.base_fee, prof.anvil_args())
        anvil = cls._anvil.__enter__()
        cls._prover = SemaphoreProver(REPO_ROOT)
        cls.prover = cls._prover.__enter__()
        cfg = cls.cfg
        chain = cls.chain = Chain(rpc=anvil.rpc, chain_id=cfg.chain_id, base_fee=cfg.base_fee,
                                  max_fee=cfg.max_fee, max_priority_fee=cfg.max_priority_fee)
        env = cls.env = setup_environment(chain, cfg, cls.keys, arts, prof, cls.b3a, b3c)
        cls.bundler = InstrumentedBundler(chain=chain, entrypoint=env.entrypoint,
                                          account=cls.keys.account("bundler"),
                                          beneficiary=cls.keys.address("beneficiary"),
                                          bundle_gas_limit=cfg.gas_limit("bundle"))
        cls.issuer = [counterfactual_address(chain, env.factory, a.issuer.address, 0)
                      for a in cls.actors]
        cls.spender = [counterfactual_address(chain, env.factory, a.recipient.address, 0)
                       for a in cls.actors]
        cls.commits, cls.boot_outcomes, cls.issuer_token_before_boot = [], [], []
        for a, iss, spd in zip(cls.actors, cls.issuer, cls.spender):
            chain.send(faucet(), label="f", phase="setup", to=a.asset_sender.address,
                       value=10 ** 17, gas=21000)
            chain.send(faucet(), label="f", phase="setup", to=a.issuer_funder.address,
                       value=10 ** 17, gas=21000)
            # the W1 asset goes to the SPENDER only
            chain.send(cls.keys.account("asset_sender"), label="t", phase="setup", to=env.token,
                       data=_token_transfer_data(a.asset_sender.address, cfg.transfer_amount),
                       gas=65000)
            chain.send(a.asset_sender, label="d", phase="workflow", to=env.token,
                       data=_token_transfer_data(spd, cfg.transfer_amount), gas=65000)
            # the ISSUER is announced, by its own funder
            chain.send(a.issuer_funder, label="a", phase="workflow", to=env.b3.registry,
                       value=b3c.v_min + b3c.non_refundable_fee,
                       data=b3.announce_and_fund_calldata(1, iss, b3.ephemeral_public_key(
                           a.ephemeral), b""), gas=300000)
            cls.issuer_token_before_boot.append(cls.token_balance(iss))
            c = cls.prover.commitment(a.semaphore_secret)
            cls.commits.append(c)
            op = UserOp(sender=iss, nonce=0, init_code=init_code(env.factory, a.issuer.address, 0),
                        call_data=b3.bootstrap_call_data(env.b3.credit_pool, c),
                        verification_gas_limit=300000, call_gas_limit=450000,
                        pre_verification_gas=80000, max_priority_fee_per_gas=cfg.max_priority_fee,
                        max_fee_per_gas=cfg.max_fee, paymaster=env.b3.bootstrap_paymaster,
                        paymaster_verification_gas_limit=60000, paymaster_post_op_gas_limit=0)
            sign_userop(chain, env.entrypoint, op, a.issuer)
            cls.boot_outcomes.append(cls.bundler.send_user_operation(op, label="boot"))
        cls.final_root = b3.view_uint(chain, env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT)
        cls.results = cls._scenario()

    @classmethod
    def tearDownClass(cls):
        cls._prover.__exit__(None, None, None)
        cls._anvil.__exit__(None, None, None)

    @classmethod
    def token_balance(cls, account: str) -> int:
        d = abi.call(abi.SIG_ERC20_BALANCE_OF, ["address"], [account])
        return int(cls.chain.eth_call(cls.env.token, d), 16)

    @classmethod
    def spend_op(cls, sender_idx: int, *, call_gas: int = 60000, deployed: bool = False) -> UserOp:
        a = cls.actors[sender_idx]
        return UserOp(sender=cls.spender[sender_idx], nonce=0,
                      init_code=b"" if deployed else init_code(cls.env.factory, a.recipient.address, 0),
                      call_data=_application_call(cls.cfg, cls.env, cls.keys),
                      verification_gas_limit=300000, call_gas_limit=call_gas,
                      pre_verification_gas=80000, max_priority_fee_per_gas=cls.cfg.max_priority_fee,
                      max_fee_per_gas=cls.cfg.max_fee, paymaster=cls.env.b3.credit_paymaster,
                      paymaster_verification_gas_limit=400000, paymaster_post_op_gas_limit=0)

    @classmethod
    def prove(cls, identity_idx: int, op: UserOp, members=None, depth=None):
        op.paymaster_signature = b3.PLACEHOLDER_PROOF
        h = get_userop_hash(cls.chain, cls.env.entrypoint, op)
        return cls.prover.prove(identity_secret=cls.actors[identity_idx].semaphore_secret,
                                members=members or cls.commits, message=int(h, 16),
                                scope=cls.env.b3.credit_scope,
                                merkle_tree_depth=depth or group_depth(len(members or cls.commits)),
                                label="t"), h

    @classmethod
    def submit(cls, sender_idx: int, op: UserOp, proof) -> object:
        op.paymaster_signature = b3.encode_proof(proof)
        sign_userop(cls.chain, cls.env.entrypoint, op, cls.actors[sender_idx].recipient)
        return cls.bundler.send_user_operation(op, label="spend")

    @classmethod
    def _scenario(cls):
        """Ordered attack/acceptance sequence on one chain; each test asserts one step."""
        r = {}
        # (1) stale root: A's identity, proof against the prefix root, for A's spender
        op = cls.spend_op(0)
        stale, _ = cls.prove(0, op, members=cls.commits[:1], depth=1)
        r["stale"] = cls.submit(0, op, stale.proof)
        # (2) A's valid, finalized proof for A's spender operation ...
        op_a = cls.spend_op(0)
        proof_a, h_a = cls.prove(0, op_a)
        r["proof_a_hash"] = h_a
        # ... reused by an UNRELATED spender (B's spender account)
        op_b = cls.spend_op(1)
        r["reuse_other_sender"] = cls.submit(1, op_b, proof_a.proof)
        # ... reused by a DIFFERENT operation of A's spender (call gas changed)
        op_a2 = cls.spend_op(0, call_gas=61000)
        r["reuse_other_op"] = cls.submit(0, op_a2, proof_a.proof)
        # (3) the proof on the operation it was made for: accepted
        root_before = b3.view_uint(cls.chain, cls.env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT)
        dest_before = cls.token_balance(cls.keys.address("destination"))
        r["valid"] = cls.submit(0, op_a, proof_a.proof)
        r["root_changed_by_spend"] = root_before != b3.view_uint(
            cls.chain, cls.env.b3.credit_paymaster, b3.SIG_CPM_MERKLE_ROOT)
        r["destination_gain"] = cls.token_balance(cls.keys.address("destination")) - dest_before
        # (4) nullifier reuse: a FRESH valid proof of A's identity for B's spender operation
        op_b2 = cls.spend_op(1)
        fresh, _ = cls.prove(0, op_b2)
        r["nullifier_reuse"] = cls.submit(1, op_b2, fresh.proof)
        # (5) B redeems its own credit from its own spender account: accepted
        op_b3 = cls.spend_op(1)
        proof_b, _ = cls.prove(1, op_b3)
        r["valid_b"] = cls.submit(1, op_b3, proof_b.proof)
        return r

    # ---- issuance side ---------------------------------------------------------
    def test_issuer_differs_from_spender(self):
        for a, iss, spd in zip(self.actors, self.issuer, self.spender):
            self.assertNotEqual(a.issuer.address, a.recipient.address)
            self.assertNotEqual(iss, spd)
            self.assertNotEqual(a.issuer_funder.address, a.asset_sender.address)

    def test_issuer_bootstrap_succeeds_without_the_w1_asset(self):
        self.assertEqual(self.issuer_token_before_boot, [0, 0])
        for out, iss in zip(self.boot_outcomes, self.issuer):
            self.assertTrue(out.accepted)
            uoe = next(d for d in (abi.decode_log(l) for l in out.bundle.receipt["logs"])
                       if d and d["event"] == "UserOperationEvent")
            self.assertTrue(uoe["success"])
            self.assertEqual(uoe["sender"].lower(), iss.lower())
            self.assertEqual(b3.view_uint(self.chain, self.env.b3.credit_pool,
                                          b3.SIG_POOL_HAS_DEPOSITED, ("address",), (iss,)), 1)
            self.assertEqual(self.token_balance(iss), 0)
        self.assertEqual(self.prover.group_root(self.commits)["root"], self.final_root)

    def test_spender_never_bootstrapped(self):
        for spd in self.spender:
            for to, sig in ((self.env.b3.bootstrap_paymaster, b3.SIG_BPM_IS_ELIGIBLE),
                            (self.env.b3.bootstrap_paymaster, b3.SIG_BPM_IS_USED),
                            (self.env.b3.credit_pool, b3.SIG_POOL_HAS_DEPOSITED)):
                self.assertEqual(b3.view_uint(self.chain, to, sig, ("address",), (spd,)), 0)

    # ---- redemption side -------------------------------------------------------
    def test_different_sender_redeems_with_proof_over_its_own_userop_hash(self):
        out = self.results["valid"]
        self.assertTrue(out.accepted, out.log[-1])
        uoe = next(d for d in (abi.decode_log(l) for l in out.bundle.receipt["logs"])
                   if d and d["event"] == "UserOperationEvent")
        self.assertTrue(uoe["success"])
        self.assertEqual(uoe["sender"].lower(), self.spender[0].lower())
        self.assertNotEqual(uoe["sender"].lower(), self.issuer[0].lower())
        self.assertEqual(uoe["userop_hash"], self.results["proof_a_hash"])
        self.assertEqual(self.results["destination_gain"], self.cfg.transfer_amount)
        spent = [b3.decode_b3_log(l) for l in out.bundle.receipt["logs"]]
        spent = next(d for d in spent if d and d["event"] == "CreditSpent")
        self.assertEqual(spent["sender"].lower(), self.spender[0].lower())
        self.assertTrue(self.results["valid_b"].accepted)

    def test_finalized_proof_not_reusable_by_an_unrelated_spender(self):
        out = self.results["reuse_other_sender"]
        self.assertFalse(out.accepted)
        self.assertTrue(_inner_selector(out).startswith(_sel("WrongMessage()")), out.log[-1])

    def test_wrong_proof_message_rejected_for_a_different_operation(self):
        out = self.results["reuse_other_op"]
        self.assertFalse(out.accepted)
        self.assertTrue(_inner_selector(out).startswith(_sel("WrongMessage()")), out.log[-1])

    def test_nullifier_reuse_rejected_from_another_account(self):
        out = self.results["nullifier_reuse"]
        self.assertFalse(out.accepted)
        self.assertTrue(_inner_selector(out).startswith(_sel("NullifierSpent(uint256)")),
                        out.log[-1])

    def test_root_handling_unchanged(self):
        out = self.results["stale"]
        self.assertFalse(out.accepted)
        self.assertTrue(_inner_selector(out).startswith(_sel("RootMismatch(uint256,uint256)")),
                        out.log[-1])
        self.assertFalse(self.results["root_changed_by_spend"])

    # ---- frozen B3 -------------------------------------------------------------
    def test_frozen_b3_unmodified(self):
        pin = json.loads((REPO_ROOT / "baselines/b3_eval/dependency-pin.json").read_text())
        for name, entry in pin["trees"].items():
            with self.subTest(tree=name):
                self.assertEqual(dependency_tree_digest(REPO_ROOT / entry["path"]),
                                 entry["tree_sha256"])
        # Deployed runtime vs the frozen artifact, immutables and library links masked
        # (the comparison experiments/workloads/w1/tests/test_b3_live.py uses).
        deployed = self.env.b3.contracts()
        for name in b3.B3_CONTRACTS:
            art = b3.load_b3_artifact(name, REPO_ROOT)
            runtime = bytes.fromhex(self.chain.code(deployed[name],
                                                    self.chain.block_number())[2:])
            with self.subTest(contract=name):
                self.assertEqual(len(runtime), art.runtime_size)
                self.assertEqual(art.masked_runtime(runtime),
                                 art.masked_runtime(art.deployed_bytecode))


class TestB4RunGate(unittest.TestCase):
    def test_run_fails_when_issuer_equals_spender(self):
        real = d1_runner.make_actors

        def same_key(seed, n):
            return [dataclasses.replace(a, issuer_key=a.recipient_key) for a in real(seed, n)]

        pilot = load_pilot_config(REPO_ROOT, B4_CONFIG_RELPATH)
        d1_runner.make_actors = same_key
        try:
            with self.assertRaises(PilotRunFailure) as ctx:
                run_pilot(RunSpec(B4, "S0-clean-shuffled", 4, 1, SEED), REPO_ROOT, pilot)
        finally:
            d1_runner.make_actors = real
        self.assertIn("b4_issuer_key_ne_spender_key", str(ctx.exception))


class TestB4RunsAndRecords(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="d1-b4-live-"))
        env, rev = environment_report(REPO_ROOT), software_revision(REPO_ROOT)
        pilot = load_pilot_config(REPO_ROOT, B4_CONFIG_RELPATH)
        cls.results = {}
        for s in ("S0-clean-shuffled", "S1-correlated-timing"):
            r = run_pilot(RunSpec(B4, s, 4, 1, SEED), REPO_ROOT, pilot)
            rec = record_pilot_run(r, "20260915T000000Z-r1", cls.tmp, env_report=env, revision=rev)
            cls.results[s] = (r, rec)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_every_separation_check_ran_and_passed(self):
        for s, (r, _) in self.results.items():
            names = [c["name"] for c in r.checks]
            for required in ("b4_bootstrap_sender_ne_spend_sender/0",
                             "b4_no_account_both_bootstraps_and_spends",
                             "b4_mined_bootstrap_and_spend_senders_disjoint",
                             "b4_no_transaction_or_transfer_between_issuer_and_spender_sides",
                             "b4_issuer_never_received_the_w1_asset",
                             "b4_spender_never_announced_or_bootstrapped/3",
                             "b3_offchain_root_equals_credit_paymaster_root",
                             "b3_nullifiers_spent"):
                self.assertIn(required, names, s)
            self.assertTrue(all(c["ok"] for c in r.checks))
            sep = r.private["b4"]["account_separation"]
            self.assertFalse(set(sep["bootstrap_senders"]) & set(sep["spend_senders"]))

    def test_ground_truth_keeps_the_handoff_private(self):
        for s, (r, rec) in self.results.items():
            rp = rec["paths"]
            public = rp.public_events_path.read_text().lower()
            manifest = (rp.public_run_dir / "run_manifest.public.json").read_text().lower()
            for a in r.private["actors"]:
                for h in (a["issuer_handle"], a["credit_handle"], a["issuance_handle"],
                          a["actor_handle"]):
                    self.assertNotIn(h, public)
                    self.assertNotIn(h, manifest)
            gt = [json.loads(l) for l in rp.ground_truth_path.read_text().splitlines()]
            spends = [g for g in gt if g["issuance_to_redemption_label"]["status"] == "observed"]
            boots = [g for g in gt if g["issuance_to_redemption_label"]["status"] == "absent"]
            self.assertEqual(len(spends), 4)
            self.assertEqual(len(boots), 4)
            for sp in spends:
                bt = next(b for b in boots if b["issuance_id"] == sp["issuance_id"])
                self.assertNotEqual(sp["public_anchors"]["stealth_account_address"],
                                    bt["public_anchors"]["stealth_account_address"])
                self.assertEqual(sp["public_anchors"]["issuance_userop_hash"],
                                 bt["public_anchors"]["userop_hash"])

    def test_selfcheck_order_audit_and_no_equality_rule_fires(self):
        proc = subprocess.run([sys.executable, "-m", "experiments.labels", "--all-runs", "--root",
                               str(self.tmp)], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        runs = [{"experiment_id": rec["experiment_id"], "run_id": rec["run_id"], "baseline_id": B4,
                 "scenario_id": s} for s, (_, rec) in self.results.items()]
        code = textwrap.dedent(f"""
            import json
            from pathlib import Path
            from experiments.privacy.d1.evaluate.audit import harness_audit
            res = harness_audit(Path({str(self.tmp)!r}), json.loads({json.dumps(json.dumps(runs))}))
            print("ORDER_OK", res["public_order_equals_private_schedule"])
        """)
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                              text=True)
        self.assertIn("ORDER_OK True", proc.stdout, proc.stderr)
        code = textwrap.dedent(f"""
            from pathlib import Path
            from experiments.privacy.d1.attack.io import load_trace
            from experiments.privacy.d1 import extract, rules
            root = Path({str(self.tmp)!r})
            eq = ("rule.r2-bootstrap-sender-eq-spend-sender", "rule.r2-creditspent-sender-eq-depositor",
                  "rule.r2-transfer-account-eq-depositor", "rule.r2-deployed-account-eq-spender")
            for exp in {[rec["experiment_id"] for _, rec in self.results.values()]!r}:
                t = load_trace(root, exp, "20260915T000000Z-r1")
                for rel in ("R2", "R3"):
                    assert all(len(c.candidates) == 4 for c in extract.features(t, rel))
                for rule in rules.rules_for("R2", t.baseline_id):
                    if rule.rule_id in eq:
                        assert all(p["selected"] == [] for p in rule.fn(t)), rule.rule_id
            print("NO_EQUALITY_FIRES")
        """)
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                              text=True)
        self.assertIn("NO_EQUALITY_FIRES", proc.stdout, proc.stderr)


if __name__ == "__main__":
    unittest.main()
