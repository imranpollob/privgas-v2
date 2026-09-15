"""Live tests of the frozen B3 specimen (B3-PrivGas-v1) in the W1 framework.

NON-PRODUCTION | NON-EIP-170-DEPLOYABLE-AS-BUILT | PRIVACY-EVALUATION-ONLY.

Every transaction is locally signed and submitted raw to a throwaway anvil;
every rejection below is one the node, the EntryPoint or a frozen B3 contract
actually produced. Proofs are real Semaphore v4 / Groth16 proofs verified on
chain by B3's vendored SemaphoreVerifier. Skipped (not passed) when anvil, forge
or node is unavailable.

Coverage (task list numbers in brackets):
[1] frozen submodule unchanged          [2] EIP-170 limitation still holds
[3] compat profile deploys unchanged B3 [4] real Groth16 proof verifies
[5] Bootstrap succeeds                  [6] Spend succeeds
[7] replay of a redeemed credit fails   [8] final W1 ERC-20 transfer succeeds
[9] Bootstrap/Spend public senders      [10] R2 answer absent from attacker data
[11] public trace has every B3 stage    [12] cost reconciliation
[13] leakage self-check                 [14] B0/B1/B2 on the compat profile
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from experiments.recorder.provenance import environment_report, software_revision
from experiments.recorder.version import SCHEMA_VERSION
from experiments.workloads.w1 import abi, b3, calibration, compare, profiles
from experiments.workloads.w1.accounting import AccountingError, reconcile
from experiments.workloads.w1.artifacts import dependency_tree_digest, forge_build
from experiments.workloads.w1.chain import Chain, TxRejected
from experiments.workloads.w1.config import (
    B3_BASELINE_ID,
    B3_COMPAT_PROFILE,
    RUN_ID_SUFFIX,
    STANDARD_PROFILE,
    load_config,
)
from experiments.workloads.w1.keys import faucet
from experiments.workloads.w1.recording import record_run
from experiments.workloads.w1.rpc import AnvilProcess
from experiments.workloads.w1.runner import Variation, run_baseline
from experiments.workloads.w1.userop import unpack

REPO_ROOT = Path(__file__).resolve().parents[4]
SEED = 20260915
TOOLS = all(shutil.which(t) for t in ("anvil", "forge", "node", "git"))
B3C = (B3_BASELINE_ID, "W1-cold")
MATCHED_NON_B3 = [("B0", "W1-cold"), ("B1", "W1-cold"), ("B2-Signature", "W1-cold")]
SELECTOR_NULLIFIER_SPENT = "b7517d93"  # CreditPaymaster.NullifierSpent(uint256)
SELECTOR_INVALID_PROOF = "09bde339"    # CreditPaymaster.InvalidProof()


def label_tx(result, label):
    hashes = [h for h, l in result.private["tx_labels"].items() if l == label]
    return next(t for t in result.chain_dump["transactions"] if t["tx"]["hash"] in hashes)


def bundle_op(result, label):
    ops, _ = abi.decode_handle_ops(abi.data_bytes(label_tx(result, label)["tx"]["input"]))
    return unpack(ops[0])


def logs_of(result, label):
    t = label_tx(result, label)
    return [abi.decode_log(l) or b3.decode_b3_log(l) for l in t["receipt"]["logs"]]


def state_b3(result, which):
    blk = result.chain_dump["blocks"]["setup_end" if which == "start" else "workflow_end"]
    return result.chain_dump["state"]["b3"][str(blk)]


@unittest.skipUnless(TOOLS, "anvil, forge, node and git are required")
class LiveB3TestCase(unittest.TestCase):
    runs = {}

    @classmethod
    def setUpClass(cls):
        if not LiveB3TestCase.runs:
            forge_build(REPO_ROOT)
            b3.forge_build_b3(REPO_ROOT)
            r = LiveB3TestCase.runs
            r["b3"] = run_baseline(B3_BASELINE_ID, SEED, REPO_ROOT, build=False,
                                   profile_id=B3_COMPAT_PROFILE)
            r["replay"] = run_baseline(B3_BASELINE_ID, SEED, REPO_ROOT, build=False,
                                       profile_id=B3_COMPAT_PROFILE,
                                       variation=Variation(b3_replay_spend=True))
            r["tamper"] = run_baseline(B3_BASELINE_ID, SEED, REPO_ROOT, build=False,
                                       profile_id=B3_COMPAT_PROFILE,
                                       variation=Variation(b3_tamper_proof=True))
            r["unannounced"] = run_baseline(B3_BASELINE_ID, SEED, REPO_ROOT, build=False,
                                            profile_id=B3_COMPAT_PROFILE,
                                            variation=Variation(b3_skip_announcement=True))
            for v in MATCHED_NON_B3:
                for p in (STANDARD_PROFILE, B3_COMPAT_PROFILE):
                    r[(p, v)] = run_baseline(v[0], SEED, REPO_ROOT, build=False,
                                             workload_id=v[1], profile_id=p)
        cls.cfg = load_config(REPO_ROOT)
        cls.b3cfg = b3.load_b3_config(REPO_ROOT)

    @property
    def b3run(self):
        return self.runs["b3"]


class TestFrozenSpecimen(LiveB3TestCase):
    """[1] The frozen B3 submodule is unchanged and is what gets compiled."""

    def git(self, *args, cwd=REPO_ROOT):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              check=True).stdout.strip()

    def test_submodule_is_at_the_pinned_commit_and_clean(self):
        sub = REPO_ROOT / b3.B3_SUBMODULE
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=sub), b3.B3_SOURCE_COMMIT)
        self.assertEqual(self.git("status", "--porcelain", "--untracked-files=no", cwd=sub), "")
        gitlink = self.git("ls-tree", "HEAD", str(b3.B3_SUBMODULE))
        self.assertIn(b3.B3_SOURCE_COMMIT, gitlink)

    def test_compiled_source_trees_match_the_pin(self):
        pin = json.loads((REPO_ROOT / "baselines/b3_eval/dependency-pin.json").read_text())
        self.assertEqual(pin["b3_submodule_commit"], b3.B3_SOURCE_COMMIT)
        for name, entry in pin["trees"].items():
            with self.subTest(tree=name):
                self.assertEqual(dependency_tree_digest(REPO_ROOT / entry["path"]),
                                 entry["tree_sha256"])
        import hashlib
        for name, entry in pin["files"].items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((REPO_ROOT / entry["path"]).read_bytes())
                                 .hexdigest(), entry["sha256"])

    def test_eval_project_only_imports_frozen_sources(self):
        src = (REPO_ROOT / "baselines/b3_eval/src/FrozenB3Artifacts.sol").read_text()
        imports = [l for l in src.splitlines() if l.startswith("import")]
        self.assertEqual(len(imports), 7)
        for line in imports:
            self.assertRegex(line, r'"(b3-frozen-src|b3-frozen-test/mock|@semaphore-protocol/'
                                   r'contracts/base|poseidon-solidity)/')
        declarations = [l for l in src.splitlines()
                        if l.split(" ", 1)[0] in ("contract", "library", "interface",
                                                  "abstract")]
        self.assertEqual(declarations, [], "the eval project must declare no contract")

    def test_eval_bytecode_equals_the_submodules_own_build_when_present(self):
        own = REPO_ROOT / b3.B3_SUBMODULE / "out"
        if not own.is_dir():
            self.skipTest("the submodule has no local forge build output to compare with")
        for name in b3.B3_CONTRACTS:
            with self.subTest(contract=name):
                ours = b3.load_b3_artifact(name, REPO_ROOT)
                theirs = b3.load_b3_artifact(name, out_dir=own)
                self.assertEqual(b3.executable_code(ours.deployed_bytecode),
                                 b3.executable_code(theirs.deployed_bytecode))

    def test_b3_is_not_runnable_on_the_standard_profile(self):
        with self.assertRaises(ValueError):
            run_baseline(B3_BASELINE_ID, SEED, REPO_ROOT, build=False,
                         profile_id=STANDARD_PROFILE)


class TestEip170Limitation(LiveB3TestCase):
    """[2] The ordinary EIP-170 finding is unchanged and still reproduces."""

    def test_documented_finding_is_unchanged(self):
        doc = (REPO_ROOT / "docs/b3-reproduction.md").read_text()
        self.assertIn("`PoseidonT3` is above the contract size limit (29315 > 24576)", doc)
        self.assertIn("**29,315 bytes**", doc)

    def test_poseidon_runtime_exceeds_eip170(self):
        size = b3.load_b3_artifact("PoseidonT3", REPO_ROOT).runtime_size
        self.assertEqual(size, 29_315)
        self.assertGreater(size, profiles.EIP170_CODE_SIZE_LIMIT)
        self.assertGreaterEqual(profiles.B3_COMPAT.code_size_limit, size)

    def _deploy_poseidon(self, profile):
        cfg = self.cfg
        with AnvilProcess(cfg.chain_id, cfg.base_fee, profile.anvil_args()) as anvil:
            chain = Chain(rpc=anvil.rpc, chain_id=cfg.chain_id, base_fee=cfg.base_fee,
                          max_fee=cfg.max_fee, max_priority_fee=cfg.max_priority_fee)
            art = b3.load_b3_artifact("PoseidonT3", REPO_ROOT)
            try:
                st = chain.send(faucet(), label="deploy_poseidon", phase="probe", to=None,
                                data=art.linked_bytecode({}), gas=cfg.gas_limit("deployment"))
            except TxRejected as e:
                return {"rejected": str(e.rpc_error), "code": "0x"}
            addr = st.receipt["contractAddress"]
            return {"status": int(st.receipt["status"], 16),
                    "code": chain.code(addr, chain.block_number()) if addr else "0x"}

    def test_ordinary_eip170_chain_refuses_the_frozen_poseidon(self):
        out = self._deploy_poseidon(profiles.STANDARD)
        self.assertEqual(out["code"], "0x", out)
        self.assertTrue("rejected" in out or out["status"] == 0, out)

    def test_compat_profile_is_explicitly_labelled(self):
        self.assertEqual(profiles.B3_COMPAT.labels, ("NON-PRODUCTION",
                                                     "NON-EIP-170-DEPLOYABLE-AS-BUILT",
                                                     "PRIVACY-EVALUATION-ONLY"))
        self.assertIn("--code-size-limit", self.b3run.chain_dump["environment"]["anvil_args"])
        self.assertFalse(self.b3run.chain_dump["evaluation_profile"]["eip170_enforced"])


class TestCompatDeployment(LiveB3TestCase):
    """[3] b3_compat_local deploys the unchanged frozen contracts."""

    def test_deployed_runtime_equals_the_frozen_artifacts(self):
        code = self.b3run.chain_dump["state"]["b3_runtime_code"]
        for name in b3.B3_CONTRACTS:
            with self.subTest(contract=name):
                art = b3.load_b3_artifact(name, REPO_ROOT)
                runtime = bytes.fromhex(code[name][2:])
                self.assertEqual(len(runtime), art.runtime_size)
                self.assertEqual(art.masked_runtime(runtime),
                                 art.masked_runtime(art.deployed_bytecode))

    def test_credit_pool_is_linked_to_the_deployed_poseidon(self):
        c = self.b3run.chain_dump["contracts"]
        art = b3.load_b3_artifact("CreditPool", REPO_ROOT)
        runtime = bytes.fromhex(self.b3run.chain_dump["state"]["b3_runtime_code"]
                                ["CreditPool"][2:])
        (ref,) = [r for libs in art.deployed_link_references.values()
                  for refs in libs.values() for r in refs]
        self.assertEqual("0x" + runtime[ref["start"]:ref["start"] + 20].hex(),
                         c["PoseidonT3"].lower())

    def test_real_verifier_not_a_mock(self):
        arts = self.b3run.chain_dump["artifacts"]
        self.assertEqual(arts["SemaphoreVerifier"]["deployed_bytecode_sha256"],
                         b3.load_b3_artifact("SemaphoreVerifier", REPO_ROOT)
                         .deployed_bytecode_sha256)
        self.assertNotIn("MockSemaphoreVerifier", self.b3run.chain_dump["contracts"])
        self.assertNotIn("DemoVerifier", json.dumps(self.b3run.chain_dump["contracts"]))

    def test_same_entrypoint_and_account_implementation_as_b1_b2(self):
        b1 = self.runs[(B3_COMPAT_PROFILE, ("B1", "W1-cold"))].chain_dump
        for key in ("EntryPoint", "SimpleAccountFactory", "SimpleAccount_implementation",
                    "W1Token"):
            self.assertEqual(self.b3run.chain_dump["contracts"][key], b1["contracts"][key])
        self.assertEqual(self.b3run.chain_dump["artifacts"]["EntryPoint"],
                         b1["artifacts"]["EntryPoint"])
        self.assertEqual(self.b3run.chain_dump["entrypoint_provenance"]["source_commit"],
                         "b36a1ed52ae00da6f8a4c8d50181e2877e4fa410")

    def test_paymasters_funded_by_depositto_and_not_staked(self):
        c = self.b3run.chain_dump["contracts"]
        start = str(self.b3run.chain_dump["blocks"]["setup_end"])
        for pm in ("BootstrapPaymaster", "CreditPaymaster"):
            self.assertEqual(int(self.b3run.chain_dump["state"]["entrypoint_deposit"][c[pm]][start]),
                             self.b3cfg.paymaster_deposit)
        self.assertIn("not staked", self.b3run.chain_dump["b3_provenance"]["staking"])


class TestB3Protocol(LiveB3TestCase):
    """[4]-[9] the real protocol flow around the W1 application call."""

    def test_canonical_run_has_no_failure_and_takes_no_snapshots(self):
        self.assertIsNone(self.b3run.failure)
        self.assertEqual(self.b3run.chain_dump["environment"]["evm_snapshots_taken"], 0)

    def test_real_groth16_proof_verifies_on_chain(self):  # [4]
        evs = logs_of(self.b3run, "w4_spend_bundle")
        spent = [e for e in evs if e and e["event"] == "CreditSpent"]
        self.assertEqual(len(spent), 1)
        op = bundle_op(self.b3run, "w4_spend_bundle")
        proof = b3.decode_proof(op["paymaster_and_data"][52:52 + b3.PROOF_BYTE_LENGTH])
        uoe = next(e for e in evs if e and e["event"] == "UserOperationEvent")
        self.assertEqual(proof["message"], int(uoe["userop_hash"], 16))
        self.assertEqual(proof["scope"], int.from_bytes(
            __import__("eth_utils").keccak(text=b3.CREDIT_SCOPE_PREIMAGE), "big"))
        self.assertEqual(proof["nullifier"], spent[0]["nullifier"])
        self.assertIs(state_b3(self.b3run, "end")["nullifier_spent"], True)
        mined = [p for p in self.b3run.private["b3"]["proof_log"]
                 if int(p["message"], 16) == proof["message"]]
        self.assertEqual(len(mined), 1)

    def test_a_tampered_proof_is_rejected_by_the_real_verifier(self):  # [4]
        f = self.runs["tamper"].failure
        self.assertIsNotNone(f)
        self.assertEqual((f.step, f.detail["reason"]), ("w4_spend_bundle", "AA33 reverted"))
        sim = [e for e in self.runs["tamper"].bundler_log if e["event"] == "simulation"][-1]
        self.assertIn(SELECTOR_INVALID_PROOF, sim["raw_error"]["decoded"]["inner"])

    def test_bootstrap_succeeds(self):  # [5]
        evs = [e for e in logs_of(self.b3run, "w3_bootstrap_bundle") if e]
        names = [e["event"] for e in evs]
        for ev in ("AccountDeployed", "BootstrapSponsored", "RootMirrored",
                   "CreditDeposited", "UserOperationEvent"):
            self.assertIn(ev, names)
        uoe = next(e for e in evs if e["event"] == "UserOperationEvent")
        self.assertTrue(uoe["success"])
        self.assertEqual(uoe["paymaster"], self.b3run.chain_dump["contracts"]["BootstrapPaymaster"])
        s0, s1 = state_b3(self.b3run, "start"), state_b3(self.b3run, "end")
        self.assertEqual((s0["credit_pool_tree_size"], s1["credit_pool_tree_size"]), (0, 1))
        self.assertEqual(int(s1["credit_pool_current_root"]),
                         int(self.b3run.private["b3"]["identity_commitment"]))
        self.assertTrue(s1["bootstrap_used"] and s1["pool_has_deposited"])
        op = bundle_op(self.b3run, "w3_bootstrap_bundle")
        self.assertGreater(op["init_code_length"], 0)
        self.assertEqual(op["call_data"], b3.bootstrap_call_data(
            self.b3run.chain_dump["contracts"]["CreditPool"],
            int(self.b3run.private["b3"]["identity_commitment"])))

    def test_unannounced_account_is_not_bootstrapped(self):
        f = self.runs["unannounced"].failure
        self.assertEqual((f.step, f.detail["reason"]), ("w3_bootstrap_bundle",
                                                        "AA34 signature error"))

    def test_spend_succeeds(self):  # [6]
        evs = [e for e in logs_of(self.b3run, "w4_spend_bundle") if e]
        uoe = next(e for e in evs if e["event"] == "UserOperationEvent")
        self.assertTrue(uoe["success"])
        self.assertEqual(uoe["paymaster"], self.b3run.chain_dump["contracts"]["CreditPaymaster"])
        op = bundle_op(self.b3run, "w4_spend_bundle")
        self.assertEqual(op["init_code_length"], 0)
        self.assertEqual(op["nonce"], 1)
        self.assertTrue(op["paymaster_signature_present"])

    def test_redeemed_credit_cannot_be_redeemed_again(self):  # [7]
        rr = self.runs["replay"]
        self.assertIsNone(rr.failure)
        attempt = rr.private["b3"]["replay_attempt"]
        self.assertFalse(attempt["accepted"])
        self.assertEqual(attempt["reason"], "AA33 reverted")
        self.assertIn(SELECTOR_NULLIFIER_SPENT, attempt["inner_revert"])
        self.assertEqual(sum(1 for t in rr.chain_dump["transactions"]
                             if t["phase"] == "workflow"
                             and t["tx"]["input"][:10] == abi.SELECTOR_HANDLE_OPS), 2)
        proofs = [p for p in rr.private["b3"]["proof_log"] if p["label"] == "replay_spend"]
        self.assertEqual(len(proofs), 1, "the replay carried a freshly generated real proof")

    def test_final_w1_erc20_transfer_succeeds(self):  # [8]
        evs = [e for e in logs_of(self.b3run, "w4_spend_bundle") if e]
        roles = self.b3run.private["roles"]
        (tr,) = [e for e in evs if e["event"] == "Transfer"]
        self.assertEqual((tr["from"], tr["to"], tr["amount"]),
                         (roles["recipient_account"], roles["destination"],
                          self.cfg.transfer_amount))
        b1 = self.runs[(B3_COMPAT_PROFILE, ("B1", "W1-cold"))]
        self.assertEqual(bundle_op(self.b3run, "w4_spend_bundle")["call_data"],
                         bundle_op(b1, "w3_bundle")["call_data"])

    def test_bootstrap_and_spend_share_the_public_sender(self):  # [9]
        boot, spend = (bundle_op(self.b3run, "w3_bootstrap_bundle"),
                       bundle_op(self.b3run, "w4_spend_bundle"))
        account = self.b3run.private["roles"]["recipient_account"]
        self.assertEqual(boot["sender"], account)
        self.assertEqual(spend["sender"], account)
        costs = reconcile(self.b3run.chain_dump, self.b3run.private)
        self.assertIs(costs["summary"]["bootstrap_and_spend_same_public_sender"], True)


class TestB3Recording(LiveB3TestCase):
    """[9]-[13] the recorded streams."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = Path(tempfile.mkdtemp(prefix="privgas-b3-rec-"))
        subprocess.run(["git", "init", "-q"], cwd=cls.tmp, check=True)
        cls.env = environment_report(REPO_ROOT)
        r = cls.runs["b3"]
        cls.run_id = f"20260915T000000Z-{RUN_ID_SUFFIX[B3C]}"
        cls.out = record_run(r.chain_dump, r.bundler_log, r.private, SEED, cls.run_id,
                             cls.tmp, clock=lambda: "2026-09-15T00:00:00Z",
                             env_report=cls.env, revision=software_revision(REPO_ROOT))
        cls.public = cls.out["rows"]["public_events"]
        cls.gt = cls.out["rows"]["ground_truth"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_records_are_measured_schema_5_with_provenance(self):
        rp = self.out["paths"]
        manifest = json.loads(rp.public_manifest_path.read_text())
        self.assertEqual(manifest["schema_version"], SCHEMA_VERSION)
        self.assertEqual(manifest["baseline_id"], B3_BASELINE_ID)
        self.assertEqual(manifest["data_origin"], "measured")
        comp = manifest["components"]
        self.assertEqual(comp["b3_provenance"]["source_commit"], b3.B3_SOURCE_COMMIT)
        self.assertEqual(comp["evaluation_profile"]["profile_id"], B3_COMPAT_PROFILE)
        self.assertEqual(comp["entrypoint"]["source"]["source_commit"],
                         "b36a1ed52ae00da6f8a4c8d50181e2877e4fa410")
        mech = comp["paymaster"]["privacy_mechanism"]
        self.assertEqual(mech["circuit"]["name"], "semaphore-1")
        self.assertRegex(mech["circuit"]["zkey_sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("environment_fingerprint", comp["bundler"])
        self.assertEqual(comp["bundler"]["environment_fingerprint"]["evaluation_profile"],
                         B3_COMPAT_PROFILE)
        self.assertIn("NON-PRODUCTION", manifest["notes"])
        self.assertTrue(rp.experiment_id.startswith("baselines/b3-compat-local/"))

    def test_bootstrap_and_spend_sender_fields_recorded(self):  # [9]
        account = self.b3run.private["roles"]["recipient_account"].lower()
        uoes = [r for r in self.public if r["event_type"] == "user_operation_event"]
        self.assertEqual(len(uoes), 2)
        self.assertEqual({r["sender"] for r in uoes}, {account})
        self.assertEqual({r["paymaster"] for r in uoes},
                         {self.b3run.chain_dump["contracts"][n].lower()
                          for n in ("BootstrapPaymaster", "CreditPaymaster")})
        bundler_rows = self.out["rows"]["bundler_private"]
        self.assertEqual([r["sender"] for r in bundler_rows], [account, account])

    def test_public_trace_contains_every_b3_stage(self):  # [11]
        mined = {t["tx"]["hash"] for t in self.b3run.chain_dump["transactions"]}
        self.assertEqual({r["transaction_hash"] for r in self.public}, mined)
        kinds = Counter((r["event_type"], r["calldata_class"]) for r in self.public)
        expected = {
            ("paymaster_event", "paymaster_deposit"): 4,      # 2 W1 + 2 B3 Paymasters
            ("asset_transfer", "erc20_transfer"): 2,          # asset delivery + application
            ("eoa_transaction", "stealth_announce_and_fund"): 1,
            ("stealth_announcement", None): 1,
            ("sponsorship_eligibility", None): 2,
            ("native_transfer", "fee_burn"): 1,
            ("eoa_transaction", "entrypoint_handle_ops"): 2,  # Bootstrap + Spend bundles
            ("account_deployment", "account_deploy"): 1,
            ("paymaster_event", "paymaster_sponsorship"): 1,
            ("privacy_pool_event", "pool_root_update"): 1,
            ("privacy_pool_event", "pool_deposit"): 1,
            ("privacy_pool_event", "pool_redeem"): 1,
            ("user_operation_event", "account_execute"): 2,
        }
        for k, n in expected.items():
            with self.subTest(kind=k):
                self.assertEqual(kinds[k], n)
        roles = self.b3run.private["roles"]
        forward = [r for r in self.public if r["event_type"] == "native_transfer"
                   and r["target"] == roles["recipient_account"].lower()]
        self.assertEqual([int(r["asset_amount"]) for r in forward], [self.b3cfg.v_min])
        deposit = next(r for r in self.public if r["calldata_class"] == "pool_deposit")
        redeem = next(r for r in self.public if r["calldata_class"] == "pool_redeem")
        self.assertEqual(int(deposit["commitment"], 16),
                         int(self.b3run.private["b3"]["identity_commitment"]))
        self.assertEqual(redeem["merkle_root"], deposit["merkle_root"])
        self.assertEqual(redeem["proof_metadata"]["scheme"], "groth16")
        self.assertIsNotNone(redeem["nullifier"])
        phases = Counter(r["trace_phase"] for r in self.public)
        self.assertEqual(sum(phases.values()), len(self.public))

    def test_r1_r2_r3_ground_truth(self):  # [10] (answer key side)
        self.assertEqual(len(self.gt), 2)
        spend, boot = self.gt
        roles = self.b3run.private["roles"]
        c = self.b3run.chain_dump["contracts"]
        for row, pm in ((spend, "CreditPaymaster"), (boot, "BootstrapPaymaster")):
            a = row["public_anchors"]
            self.assertEqual(row["immediate_gas_payer_kind"], "paymaster_entrypoint_deposit")
            self.assertEqual(a["immediate_gas_payer_address"], c[pm].lower())
            self.assertEqual(a["economic_funding_address"], roles["sponsor_operator"].lower())
            self.assertNotEqual(a["economic_funding_address"], a["immediate_gas_payer_address"])
            self.assertEqual(row["stealth_to_actor_label"]["true_value"], row["actor_id"])
        self.assertEqual(spend["issuance_to_redemption_label"]["status"], "observed")
        self.assertEqual(spend["issuance_to_redemption_label"]["true_value"],
                         spend["issuance_id"])
        self.assertEqual(boot["issuance_to_redemption_label"]["status"], "absent")
        self.assertEqual(spend["public_anchors"]["issuance_userop_hash"],
                         boot["public_anchors"]["userop_hash"])
        self.assertNotEqual(spend["credit_id"], "not_applicable")

    def test_r2_answer_is_absent_from_attacker_visible_data(self):  # [10]
        rp = self.out["paths"]
        # The attacker-side reader runs in its own process (import boundary) and
        # consumes the public B3 trace without touching ground truth.
        code = ("import json,sys; from pathlib import Path; "
                "from experiments.attacker_view.readers import load_run; "
                f"r = load_run({rp.experiment_id!r}, {self.run_id!r}, 'A2', "
                f"root=Path({str(self.tmp)!r})); "
                "print(json.dumps([len(r.public_events), len(r.bundler_private), "
                "r.baseline_id]))")
        proc = subprocess.run(["python3", "-c", code], cwd=REPO_ROOT, capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), [len(self.public), 2, B3_BASELINE_ID])
        proc = subprocess.run(["python3", "-c", code.replace(
            "load_run(", "load_run(").replace("'A2'", "'A2'") + "; "
            "from experiments.attacker_view.readers import load_public_events; "
            f"load_public_events(Path({str(rp.ground_truth_path)!r}), "
            f"root=Path({str(self.tmp)!r}))"], cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0, "ground truth must be unreadable attacker-side")
        self.assertIn("PrivateDataAccessError", proc.stderr)
        text = "".join(p.read_text() for p in rp.public_run_dir.rglob("*") if p.is_file())
        secrets = {self.gt[0]["credit_id"], self.gt[0]["issuance_id"],
                   self.gt[0]["actor_id"], self.gt[0]["stealth_account_id"],
                   self.gt[0]["economic_funding_source_id"]}
        for s in secrets:
            self.assertNotIn(s, text)
        for key in ("issuance_to_redemption_label", "credit_id", "issuance_id",
                    "identity_commitment", "proof_log", "prove_ms"):
            self.assertNotIn(f'"{key}"', text)
        self.assertFalse(any(p.name == "ground_truth.jsonl"
                             for p in rp.public_run_dir.rglob("*")))

    def test_leakage_selfcheck_passes(self):  # [13]
        proc = subprocess.run(["python3", "-m", "experiments.labels", "--all-runs",
                               "--root", str(self.tmp)], cwd=REPO_ROOT,
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("value scan ran for 1 run(s); 0 finding(s)", proc.stdout)

    def test_cost_window_is_private(self):
        window = json.loads((self.out["paths"].private_run_dir / "w1_cost_window.json")
                            .read_text())
        in_window = [r for r in window["rows"] if r["in_measured_cost_window"]]
        self.assertTrue(0 < len(in_window) < len(window["rows"]))


class TestB3Costs(LiveB3TestCase):
    """[12] cost reconciliation and PVG pricing."""

    def test_reconciliation_succeeds(self):
        costs = reconcile(self.b3run.chain_dump, self.b3run.private)
        self.assertTrue(all(c["ok"] for c in costs["checks"]))
        s = costs["summary"]
        self.assertEqual(int(s["eth_forwarded_to_stealth_account"]), self.b3cfg.v_min)
        self.assertEqual(int(s["non_refundable_admission_fee_burned"]),
                         self.b3cfg.non_refundable_fee)
        self.assertEqual(int(s["transferred_but_retained_eth"]), self.b3cfg.v_min)
        self.assertEqual(int(s["sponsor_cost"]), int(s["bootstrap_paymaster_charge"])
                         + int(s["credit_paymaster_charge"]))
        self.assertEqual(int(s["total_eth_irrecoverable_including_admission_fee"]),
                         int(s["total_eth_consumed_by_workflow"])
                         + self.b3cfg.non_refundable_fee)
        self.assertNotIn(self.b3cfg.v_min, (int(s["total_eth_consumed_by_workflow"]),))
        self.assertGreaterEqual(int(s["bundler_net_gas"]), -100)
        self.assertIsNotNone(s["proof_generation_ms_mined_proof"])

    def test_tampered_balance_does_not_reconcile(self):
        import copy
        dump = copy.deepcopy(self.b3run.chain_dump)
        end = str(dump["blocks"]["workflow_end"])
        acct = self.b3run.private["roles"]["recipient_account"]
        dump["state"]["eth_balance"][acct][end] = str(
            int(dump["state"]["eth_balance"][acct][end]) - 1)
        with self.assertRaises(AccountingError):
            reconcile(dump, self.b3run.private)

    def test_pvg_uses_the_compat_artifact_and_shapes(self):
        artifact = calibration.load_artifact(REPO_ROOT, B3_COMPAT_PROFILE)
        recs = self.b3run.chain_dump["pvg_records"]
        self.assertEqual(recs["w3_bootstrap_bundle"]["op_shape"], "execute_pool_deposit")
        self.assertEqual(recs["w4_spend_bundle"]["op_shape"], "execute_call")
        for rec in recs.values():
            self.assertEqual(rec["method"], "calibrated_overhead_v1")
            self.assertEqual(rec["calibration_artifact_sha256"],
                             calibration.artifact_sha256(artifact))
            self.assertEqual(rec["entrypoint_unmeasured_overhead"],
                             artifact["entrypoint_unmeasured_overhead_by_shape"][rec["op_shape"]])

    def test_standard_artifact_is_refused_on_the_compat_profile(self):
        std = calibration.load_artifact(REPO_ROOT, STANDARD_PROFILE)
        fp = self.b3run.chain_dump["bundler"]["environment_fingerprint"]
        with self.assertRaises(calibration.RecalibrationRequired) as ctx:
            calibration.overhead_for(std, "execute_call", fp)
        self.assertIn("evaluation_profile", str(ctx.exception))


class TestMatchedBaselinesOnCompatProfile(LiveB3TestCase):
    """[14] B0/B1/B2 still run, reconcile and match under b3_compat_local."""

    def test_b0_b1_b2_run_and_reconcile_on_both_profiles(self):
        for p in (STANDARD_PROFILE, B3_COMPAT_PROFILE):
            for v in MATCHED_NON_B3:
                with self.subTest(profile=p, variant=v):
                    r = self.runs[(p, v)]
                    self.assertIsNone(r.failure)
                    costs = reconcile(r.chain_dump, r.private)
                    self.assertTrue(all(c["ok"] for c in costs["checks"]))

    def test_compat_setup_is_identical_for_every_baseline(self):
        contracts = [self.runs[(B3_COMPAT_PROFILE, v)].chain_dump["contracts"]
                     for v in MATCHED_NON_B3] + [self.b3run.chain_dump["contracts"]]
        self.assertTrue(all(c == contracts[0] for c in contracts))
        setup = [[(t["tx"]["input"][:10], int(t["tx"]["value"], 16),
                   int(t["receipt"]["gasUsed"], 16))
                  for t in r.chain_dump["transactions"] if t["phase"] == "setup"]
                 for r in [self.runs[(B3_COMPAT_PROFILE, v)] for v in MATCHED_NON_B3]
                 + [self.b3run]]
        self.assertTrue(all(s == setup[0] for s in setup))

    def test_matched_fairness_checks_pass_with_b3(self):
        runs = {v: {"chain_dump": self.runs[(B3_COMPAT_PROFILE, v)].chain_dump,
                    "private": self.runs[(B3_COMPAT_PROFILE, v)].private}
                for v in MATCHED_NON_B3}
        runs[B3C] = {"chain_dump": self.b3run.chain_dump, "private": self.b3run.private}
        failed = [c for c in compare.fairness_checks(runs) if not c["ok"]]
        self.assertEqual(failed, [])

    def test_raising_the_code_size_limit_changes_no_b0_b1_b2_workflow_quantity(self):
        def view(p):
            return {v: {"chain_dump": self.runs[(p, v)].chain_dump,
                        "costs": reconcile(self.runs[(p, v)].chain_dump,
                                           self.runs[(p, v)].private)}
                    for v in MATCHED_NON_B3}
        effect = compare.profile_effect(view(STANDARD_PROFILE), view(B3_COMPAT_PROFILE))
        self.assertFalse(effect["any_workflow_difference"], json.dumps(effect, indent=1))


class TestStaticB3(unittest.TestCase):
    def test_compat_artifact_has_every_shape(self):
        for p, shapes in calibration.SHAPES_BY_PROFILE.items():
            with self.subTest(profile=p):
                a = calibration.load_artifact(REPO_ROOT, p)
                self.assertEqual(set(a["entrypoint_unmeasured_overhead_by_shape"]), set(shapes))
                self.assertEqual(a["environment_fingerprint"]["evaluation_profile"], p)

    def test_bootstrap_shape_is_classified_from_calldata(self):
        self.assertEqual(calibration.op_shape(b3.bootstrap_call_data("0x" + "11" * 20, 7)),
                         "execute_pool_deposit")
        self.assertEqual(calibration.op_shape(b""), "empty_calldata")

    def test_protocol_parameters_come_from_the_frozen_source(self):
        cfg = b3.load_b3_config(REPO_ROOT)
        fixture = (REPO_ROOT / b3.B3_SUBMODULE / "test/FunctionalCorrectnessFixture.sol").read_text()
        self.assertIn("V_MIN = 0.01 ether", fixture)
        self.assertIn("NONREFUNDABLE_FEE = 0.021 ether", fixture)
        self.assertIn("PM_VERIFICATION_GAS_LIMIT = 400_000", fixture)
        self.assertEqual((cfg.v_min, cfg.non_refundable_fee), (10**16, 21 * 10**15))
        self.assertEqual(cfg.userop("spend_paymaster_verification_gas_limit"), 400_000)

    def test_proof_codec_round_trips(self):
        proof = {"merkleTreeDepth": 1, "merkleTreeRoot": 5, "nullifier": 6, "message": 7,
                 "scope": 8, "points": list(range(10, 18))}
        enc = b3.encode_proof(proof)
        self.assertEqual(len(enc), b3.PROOF_BYTE_LENGTH)
        self.assertEqual(b3.decode_proof(enc)["points"], list(range(10, 18)))


if __name__ == "__main__":
    unittest.main()
