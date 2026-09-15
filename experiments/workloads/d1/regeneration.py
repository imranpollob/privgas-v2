"""Integrity check: B3-PrivGas-v1 runs of a later batch regenerate the pilot's B3 runs.

    python3 -m experiments.workloads.d1.regeneration --reference <pilot batch> --batch <batch>

Run seeds depend only on (secret master seed, replicate, pool size), so a batch recorded
with the same master seed must reproduce the pilot's B3 chains -- evidence that code
added later (B4-CrossAccount) did not change what B3 runs. Compared from the raw chain
dumps (workload side; never an attacker input):

* every transaction that is not a Spend bundle: identical hash (same sender, nonce,
  calldata, value, block time -> same signed bytes);
* every Bootstrap UserOperation: identical packed fields and userop hash;
* every Spend UserOperation, by position: identical sender, nonce, initCode, callData,
  accountGasLimits, gasFees, the proof's root and nullifier. Groth16 proving is
  randomised (fresh blinding), so the proof points -- and through the bundle calldata the
  bundle transaction hash and possibly preVerificationGas and the userop hash -- may
  differ; those are reported, not failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...recorder.provenance import repo_root
from ..w1 import b3

B3_SLUG = "b3-privgas-v1"


def _dump(root: Path, scen: str, n: str, run_id: str) -> Dict[str, Any]:
    return json.loads((root / "data" / "raw" / "d1-pilot" / B3_SLUG / scen / n / run_id
                       / "chain_dump.json").read_text())


def _is_spend(op: Dict[str, Any], credit_paymaster: str) -> bool:
    pmd = op["packed"]["paymasterAndData"]
    return len(pmd) > 42 and pmd[2:42].lower() == credit_paymaster[2:].lower()


def compare(ref: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    cpm = ref["contracts"]["CreditPaymaster"]
    problems: List[str] = []
    notes: Dict[str, int] = {"spend_proof_points_differ": 0, "spend_pvg_differs": 0,
                             "spend_bundle_hash_differs": 0}
    if ref["contracts"] != new["contracts"]:
        problems.append("deployed contract addresses differ")
    if ref["b3_provenance"]["src_tree_digest"] != new["b3_provenance"]["src_tree_digest"]:
        problems.append("frozen B3 src tree digest differs")
    for name in ("CreditPaymaster", "BootstrapPaymaster", "CreditPool", "SemaphoreVerifier"):
        if (ref["artifacts"][name]["deployed_bytecode_sha256"]
                != new["artifacts"][name]["deployed_bytecode_sha256"]):
            problems.append(f"{name} artifact digest differs")
    r_ops, n_ops = ref["userops"], new["userops"]
    if len(r_ops) != len(n_ops):
        problems.append(f"userop count {len(r_ops)} != {len(n_ops)}")
    spend_bundles_ref, spend_bundles_new = set(), set()
    for ro, no in zip(r_ops, n_ops):
        if _is_spend(ro, cpm) != _is_spend(no, cpm):
            problems.append(f"operation kind differs at {ro['label']}")
            continue
        rp, np_ = ro["packed"], no["packed"]
        if not _is_spend(ro, cpm):
            if rp != np_ or ro["userop_hash"] != no["userop_hash"]:
                problems.append(f"bootstrap op differs at {ro['label']}")
            continue
        for k in ("sender", "nonce", "initCode", "callData", "accountGasLimits", "gasFees"):
            if rp[k] != np_[k]:
                problems.append(f"spend {ro['label']} field {k} differs")
        pr = b3.decode_proof(bytes.fromhex(rp["paymasterAndData"][2:])[52:52 + b3.PROOF_BYTE_LENGTH])
        pn = b3.decode_proof(bytes.fromhex(np_["paymasterAndData"][2:])[52:52 + b3.PROOF_BYTE_LENGTH])
        for k in ("nullifier", "merkle_tree_root", "merkle_tree_depth", "scope"):
            if k in pr and pr.get(k) != pn.get(k):
                problems.append(f"spend {ro['label']} proof {k} differs")
        if pr.get("points") != pn.get("points"):
            notes["spend_proof_points_differ"] += 1
        if rp["preVerificationGas"] != np_["preVerificationGas"]:
            notes["spend_pvg_differs"] += 1
    # transactions: the Spend bundles are the ones whose calldata carries a CreditPaymaster proof
    cpm_hex = cpm[2:].lower()
    for rt, nt in zip(ref["transactions"], new["transactions"]):
        r_is_spend = cpm_hex in rt["tx"]["input"].lower() and rt["phase"] == "workflow" \
            and len(rt["tx"]["input"]) > 2000 and "22e325a297439656" in rt["tx"]["input"]
        if rt["tx"]["hash"] == nt["tx"]["hash"]:
            continue
        if r_is_spend:
            notes["spend_bundle_hash_differs"] += 1
            for k in ("from", "to", "nonce", "blockNumber"):
                if rt["tx"][k] != nt["tx"][k]:
                    problems.append(f"spend bundle {rt['tx']['hash']} field {k} differs")
            if rt["block"]["timestamp"] != nt["block"]["timestamp"]:
                problems.append(f"spend bundle {rt['tx']['hash']} block time differs")
        else:
            problems.append(f"non-spend transaction differs: {rt['tx']['hash']}")
    if len(ref["transactions"]) != len(new["transactions"]):
        problems.append("transaction count differs")
    return {"ok": not problems, "problems": problems, "notes": notes,
            "transactions": len(new["transactions"]), "userops": len(new["userops"])}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reference", required=True)
    ap.add_argument("--batch", required=True)
    ap.add_argument("--root", default=None)
    ap.add_argument("--out", default=None, help="write the JSON report here")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    base = root / "data" / "raw" / "d1-pilot" / B3_SLUG
    rows = []
    for scen_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for n_dir in sorted(p for p in scen_dir.iterdir() if p.is_dir()):
            for new_run in sorted(n_dir.glob(f"{args.batch}-r*")):
                rep = new_run.name.rsplit("-", 1)[1]
                ref_run = n_dir / f"{args.reference}-{rep}"
                if not ref_run.is_dir():
                    rows.append({"run": str(new_run.relative_to(base)), "ok": False,
                                 "problems": ["no reference run"]})
                    continue
                res = compare(_dump(root, scen_dir.name, n_dir.name, ref_run.name),
                              _dump(root, scen_dir.name, n_dir.name, new_run.name))
                rows.append({"run": str(new_run.relative_to(base)), **res})
    report = {"reference_batch": args.reference, "batch": args.batch, "runs": rows,
              "runs_compared": len(rows), "ok": bool(rows) and all(r["ok"] for r in rows)}
    text = json.dumps(report, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}))
    for r in rows:
        print(r["run"], "OK" if r["ok"] else "FAIL", r.get("notes"), r["problems"][:3])
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
