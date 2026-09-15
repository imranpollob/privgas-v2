"""D1 pilot runs -> the existing experiment recorder (schema 5.0.0).

Public and bundler streams come from the unchanged W1 classifiers
(``experiments.workloads.w1.recording.public_observations`` /
``bundler_observations``): every mined transaction of the run is recorded from
on-chain content only. Only ground truth uses the private actor table.

Ground truth, per actor (``subject_kind = operation``):

* B0 / B1 / B2-*: one row for the actor's application operation (B0: the action
  transaction hash; AA: the userop hash). R1 observed (B0/B1: the actor's asset
  sender, who funded the recipient's gas; B2: the shared sponsor-operator
  wallet), R2 ``not_applicable``, R3 observed (the actor).
* B3-PrivGas-v1: the Spend row (R2 observed: the actor's issuance; anchors
  carry the actor's Bootstrap op, commitment and nullifier) and the Bootstrap
  row (R2 absent), both with R1 = sponsor wallet, R3 = actor.
* B4-CrossAccount: the same two rows, but they are about two different accounts
  of the actor: the Spend row's stealth account is the SPENDER account (its
  handle and address), the Bootstrap row's is the ISSUER account. R2 of the
  Spend is the issuance made by the actor's issuer account -- the private
  issuer <-> spender handoff exists only here, in ground truth.

Candidate-set ids: ``r1-funders``, ``r2-issuances``, ``r3-wallets``.

Auxiliary public attacker knowledge (``auxiliary/r3_wallet_directory.json``): the
set of the N actors' established-wallet addresses, sorted by address. This is
the standard R3 assumption that the candidate recipients' public wallets are
known; the wallets never transact in W1, and the file carries no mapping.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...recorder import paths as paths_mod
from ...recorder.adapters import GroundTruth, RelationLabel, for_baseline
from ...recorder.provenance import environment_report, software_revision
from ...recorder.writers import ExperimentRecorder
from ..w1 import b3
from ..w1.config import B3_BASELINE_ID
from ..w1.recording import bundler_observations, components, public_observations
from .actors import sponsor_handle
from .config import experiment_id
from .runner import PilotRunResult

AUX_DIR = "auxiliary"
WALLET_DIRECTORY_FILE = "r3_wallet_directory.json"
PRIVATE_RUN_FILE = "d1_private_run.json"

CANDIDATE_SETS = {"R1": "r1-funders", "R2": "r2-issuances", "R3": "r3-wallets"}


def _note(result: PilotRunResult) -> str:
    s = result.spec
    return (f"MEASURED. D1 multi-actor pilot: {s.pool_size} independent actors each performing "
            f"W1-cold under {s.baseline_id}, schedule {s.scenario_id}, on a private local anvil "
            "(chain id 31337) with the EVALUATION PROFILE b3_compat_local (NON-PRODUCTION, "
            "NON-EIP-170-DEPLOYABLE-AS-BUILT, PRIVACY-EVALUATION-ONLY). Identical setup for "
            "every baseline (W1 contracts, frozen B3 contracts, Paymaster deposits, per-actor "
            "asset-sender funding). Block timestamps are schedule chain time. AA operations use "
            "the in-repo INSTRUMENTED EXPERIMENTAL bundler (no public mempool, no ERC-7562). "
            "The complete public trace is recorded.")


def ground_truth_rows(result: PilotRunResult, record_ids_by_tx: Dict[str, List[str]]
                      ) -> List[GroundTruth]:
    s = result.spec
    priv = result.private
    dump = result.chain_dump
    roles = priv["roles"]
    contracts = dump["contracts"]
    by_label = {u["label"]: u for u in dump["userops"]}
    tx_of_label = {label: h for h, label in priv["tx_labels"].items()}
    ops_by_slot: Dict[int, Dict[str, str]] = {}
    for label, meta in priv["op_labels"].items():
        ops_by_slot.setdefault(meta["slot"], {})[meta["stage"]] = label
    sponsor = sponsor_handle(s.seed)
    sponsored = s.baseline_id not in ("B0", "B1")
    rows: List[GroundTruth] = []

    for a in priv["actors"]:
        slot = a["slot"]
        funder_handle = sponsor if sponsored else a["asset_sender_handle"]
        funder_address = roles["sponsor_operator"] if sponsored else a["asset_sender_address"]
        common = dict(
            scenario_id="scn-0", subject_kind="operation", actor_id=a["actor_handle"],
            established_wallet_id=a["wallet_handle"],
            economic_funding_source_id=funder_handle,
            asset_sender_id=a["asset_sender_handle"],
            stealth_account_id=a["stealth_handle"])
        base_anchors = {
            "stealth_account_address": a["recipient_account"],
            "economic_funding_address": funder_address,
            "asset_sender_address": a["asset_sender_address"],
            "established_wallet_address": a["wallet_address"],
        }

        def r1(ref: str) -> RelationLabel:
            return RelationLabel("R1", "observed", subject_ref=ref, true_value=funder_handle,
                                 candidate_set_id=CANDIDATE_SETS["R1"])

        def r3(ref: str) -> RelationLabel:
            return RelationLabel("R3", "observed", subject_ref=ref, true_value=a["actor_handle"],
                                 candidate_set_id=CANDIDATE_SETS["R3"])

        if s.baseline_id == "B0":
            tx = tx_of_label[f"act/{slot}"]
            rows.append(GroundTruth(
                **common, immediate_gas_payer_kind="eoa_balance",
                r1=r1(tx), r2=RelationLabel("R2", "not_applicable"), r3=r3(tx),
                public_anchors={**base_anchors,
                                "immediate_gas_payer_address": a["recipient_account"],
                                "transaction_hash": tx, "userop_hash": None,
                                "public_event_record_ids": record_ids_by_tx.get(tx, [])}))
            continue

        app_label = ops_by_slot[slot]["application"]
        app_hash = by_label[app_label]["userop_hash"]
        app_tx = tx_of_label[app_label]
        if s.baseline_id == "B1":
            rows.append(GroundTruth(
                **common, immediate_gas_payer_kind="smart_account_entrypoint_deposit",
                r1=r1(app_hash), r2=RelationLabel("R2", "not_applicable"), r3=r3(app_hash),
                public_anchors={**base_anchors,
                                "immediate_gas_payer_address": a["recipient_account"],
                                "transaction_hash": app_tx, "userop_hash": app_hash,
                                "public_event_record_ids": record_ids_by_tx.get(app_tx, [])}))
            continue
        if s.baseline_id in ("B2-Signature", "B2-Allowlist"):
            pm = contracts[dump["paymaster_used"]]
            rows.append(GroundTruth(
                **common, immediate_gas_payer_kind="paymaster_entrypoint_deposit",
                r1=r1(app_hash), r2=RelationLabel("R2", "not_applicable"), r3=r3(app_hash),
                public_anchors={**base_anchors, "immediate_gas_payer_address": pm,
                                "transaction_hash": app_tx, "userop_hash": app_hash,
                                "public_event_record_ids": record_ids_by_tx.get(app_tx, [])}))
            continue

        # B3-PrivGas-v1 / B4-CrossAccount
        is_b4 = s.baseline_id == "B4-CrossAccount"
        boot_label = ops_by_slot[slot]["bootstrap"]
        boot_hash = by_label[boot_label]["userop_hash"]
        boot_tx = tx_of_label[boot_label]
        pmd = bytes.fromhex(by_label[app_label]["packed"]["paymasterAndData"][2:])
        nullifier = b3.decode_proof(pmd[52:52 + b3.PROOF_BYTE_LENGTH])["nullifier"]
        credit_anchors = {"issuance_transaction_hash": boot_tx,
                          "issuance_userop_hash": boot_hash,
                          "credit_commitment": b3.word(int(a["commitment"])),
                          "credit_nullifier": b3.word(nullifier)}
        b3_common = dict(common, immediate_gas_payer_kind="paymaster_entrypoint_deposit",
                         credit_id=a["credit_handle"], issuance_id=a["issuance_handle"])
        for ref, tx, pm, r2 in (
                (app_hash, app_tx, contracts["CreditPaymaster"],
                 RelationLabel("R2", "observed", subject_ref=app_hash,
                               true_value=a["issuance_handle"],
                               candidate_set_id=CANDIDATE_SETS["R2"])),
                (boot_hash, boot_tx, contracts["BootstrapPaymaster"],
                 RelationLabel("R2", "absent", subject_ref=boot_hash,
                               candidate_set_id=CANDIDATE_SETS["R2"]))):
            row_common, row_anchors = b3_common, base_anchors
            if is_b4 and ref == boot_hash:
                # The Bootstrap row is about the issuer account, not the spender account.
                row_common = dict(b3_common, stealth_account_id=a["issuer_handle"])
                row_anchors = dict(base_anchors, stealth_account_address=a["issuer_account"])
            rows.append(GroundTruth(
                **row_common, r1=r1(ref), r2=r2, r3=r3(ref),
                public_anchors={**row_anchors, **credit_anchors,
                                "immediate_gas_payer_address": pm, "transaction_hash": tx,
                                "userop_hash": ref,
                                "public_event_record_ids": record_ids_by_tx.get(tx, [])}))
    return rows


def record_pilot_run(result: PilotRunResult, run_id: str, root: Path,
                     env_report=None, revision=None) -> Dict[str, Any]:
    s = result.spec
    exp_id = experiment_id(s.baseline_id, s.scenario_id, s.pool_size)
    rp = paths_mod.run_paths(exp_id, run_id, root)
    adapter = for_baseline(s.baseline_id)()
    adapter.chain_id = result.chain_dump["environment"]["chain_id"]
    comps = components(result.chain_dump, {"roles": result.private["roles"]})
    comps["d1_pilot"] = {"baseline_id": s.baseline_id, "scenario_id": s.scenario_id,
                         "pool_size": s.pool_size,
                         "pilot_config_sha256": result.chain_dump["pilot_config_sha256"]}
    rec = ExperimentRecorder(
        experiment_id=exp_id, run_id=run_id, baseline_id=s.baseline_id,
        workload_id=result.chain_dump["workload_id"], seed=s.seed, chain_id=adapter.chain_id,
        components=comps, data_origin="measured", paths=rp,
        revision=revision or software_revision(root),
        env_report=env_report or environment_report(root), notes=_note(result))
    written: Dict[str, List[Dict[str, Any]]] = {"public_events": [], "bundler_private": [],
                                                "ground_truth": []}
    with rec:
        for obs in public_observations(result.chain_dump):
            written["public_events"].append(rec.record_public_event(adapter.public_event(obs)))
        for bobs in bundler_observations(result.bundler_log):
            written["bundler_private"].append(
                rec.record_bundler_private(adapter.bundler_private(bobs)))
        ids_by_tx: Dict[str, List[str]] = {}
        for r in written["public_events"]:
            ids_by_tx.setdefault(r["transaction_hash"], []).append(r["record_id"])
        for gt in ground_truth_rows(result, ids_by_tx):
            written["ground_truth"].append(rec.record_ground_truth(adapter.ground_truth(gt)))

    aux = rp.public_run_dir / AUX_DIR
    aux.mkdir(parents=True, exist_ok=True)
    directory = sorted(a["wallet_address"].lower() for a in result.private["actors"])
    (aux / WALLET_DIRECTORY_FILE).write_text(json.dumps({
        "note": "Auxiliary attacker knowledge for R3: the established-wallet addresses of the "
                "run's candidate recipients, sorted by address. No mapping to any account.",
        "candidate_wallet_addresses": directory}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")

    rp.private_run_dir.mkdir(parents=True, exist_ok=True)
    (rp.private_run_dir / PRIVATE_RUN_FILE).write_text(
        json.dumps(result.private, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"experiment_id": exp_id, "run_id": run_id, "paths": rp,
            "rows": {k: len(v) for k, v in written.items()}}


def write_raw(result: PilotRunResult, raw_dir: Path) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / "chain_dump.json"
    if path.exists():
        raise FileExistsError(f"{path} exists; raw files are never overwritten")
    path.write_text(json.dumps(result.chain_dump, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    if result.bundler_log:
        with open(raw_dir / "bundler_log.jsonl", "w", encoding="utf-8") as fh:
            for entry in result.bundler_log:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
