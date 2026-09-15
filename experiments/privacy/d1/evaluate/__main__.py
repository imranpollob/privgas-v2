"""Evaluation-side CLI for the D1 pilot (reads ground truth; never attack code).

    python3 -m experiments.privacy.d1.evaluate selfcheck --batch <batch>
    python3 -m experiments.privacy.d1.evaluate export-training-labels --batch <batch>
    python3 -m experiments.privacy.d1.evaluate score --batch <batch> --round <round> [--write-doc]

``selfcheck``: the leakage self-check (key + value scan) of every run in the batch;
exit 1 on any finding. ``score`` re-runs it first and refuses to score on a
finding.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from ....labels import scan_public_output
from ....recorder.provenance import repo_root
from . import audit, report, score
from .labels_io import batch_dir, export_training_labels, load_splits_verified, private_run

DOC = Path("docs") / "d1-pilot-results.md"
BEGIN = "<!-- BEGIN GENERATED: d1-pilot-results -->"
END = "<!-- END GENERATED: d1-pilot-results -->"

COMPARISONS = [("none", "T"), ("none", "G"), ("T", "T+AA"), ("T", "T+G"), ("T+AA", "T+AA+G"),
               ("T", "T+AA+G"), ("T+G", "T+AA+G"), ("none", "G-minus-eq"),
               ("none", "T+G-minus-eq"), ("T", "T+G-minus-eq"), ("none", "T+G-minus-timing")]
ABLATIONS = [(f"T+AA+G-minus-{a}", "T+AA+G") for a in ("timing", "gas", "eq", "pm", "app")]


def _runs(root: Path, batch: str) -> List[Dict[str, Any]]:
    m = json.loads((batch_dir(root, batch) / "dataset_manifest.json").read_text())
    return m, [r for r in m["runs"] if r["status"] == "recorded"]


def cmd_selfcheck(root: Path, batch: str) -> Dict[str, Any]:
    _, runs = _runs(root, batch)
    findings, files = [], 0
    for r in runs:
        f, summary = scan_public_output(r["experiment_id"], r["run_id"], root)
        files += summary["files_scanned"]
        findings += [str(x) for x in f]
    return {"runs": len(runs), "files_scanned": files, "findings": findings,
            "value_scan": True, "ok": not findings}


def cmd_score(root: Path, batch: str, round_id: str, write_doc: bool) -> int:
    manifest, runs = _runs(root, batch)
    sc = cmd_selfcheck(root, batch)
    if not sc["ok"]:
        print("LEAKAGE SELF-CHECK FAILED; refusing to score:\n" + "\n".join(sc["findings"][:50]))
        return 1
    split_body, split_sha = load_splits_verified(root, batch)
    out = batch_dir(root, batch) / f"evaluation-{round_id}"
    out.mkdir(parents=True, exist_ok=True)

    rows, manifests = score.score_all(root, runs, round_id)
    attack_kind = {m["attack_id"].split(".", 1)[1]: (m.get("attack_provenance") or {}).get(
        "attack_kind") for m in manifests}
    for r in rows:
        r.setdefault("attack_kind", attack_kind.get(r["attack_id"].split(".", 1)[1]))
    rule_rows = [r for r in rows if r.get("kind") == "rule"]
    learned_rows = [r for r in rows if r.get("kind") == "learned"]
    for r in rule_rows:
        r["attack_kind"] = attack_kind[r["attack"]]
    gk = ("relation", "baseline_id", "scenario_id", "attack", "feature_set", "attack_kind")
    rules = score.summarise(rule_rows, gk)
    rules_by_n = score.summarise(rule_rows, gk + ("pool_size",))
    lk = ("relation", "baseline_id", "scenario_id", "fold_kind", "convention", "feature_set")
    learned = score.summarise(learned_rows, lk)
    learned_by_n = score.summarise(learned_rows, lk + ("pool_size",))
    dk = ("relation", "baseline_id", "scenario_id", "fold_kind")
    deltas = score.delta_bits(learned_rows, COMPARISONS, dk)
    ablations = [d for d in score.delta_bits(learned_rows, ABLATIONS, dk)
                 if d["fold_kind"] == "loro"]
    deltas_by_n = score.delta_bits(learned_rows, [("T", "T+G"), ("T", "T+G-minus-eq"),
                                                  ("none", "T+AA+G")], dk + ("pool_size",))

    harness = audit.harness_audit(root, runs)
    split = audit.split_audit(root, batch, split_body, split_sha,
                              [{k: v for k, v in m.items() if k != "_run"} for m in manifests])

    # R1 structure (public-derived, from the attack round) + private true funder counts
    attack_dir = batch_dir(root, batch) / f"attack-{round_id}"
    structure = json.loads((attack_dir / "r1_structure.json").read_text())
    cand_rows = []
    seen = set()
    r1_rows = []
    for st in structure:
        priv = private_run(root, st["experiment_id"], st["run_id"])
        spec = priv["spec"]
        funders = ({a["asset_sender_address"] for a in priv["actors"]}
                   if spec["baseline_id"] in ("B0", "B1") else {priv["roles"]["sponsor_operator"]})
        st["true_distinct_economic_funders"] = len(funders)
        key = (spec["baseline_id"], spec["pool_size"])
        if key not in seen and spec["scenario_id"] == "S0-clean-shuffled":
            seen.add(key)
            r1_rows.append(st)
            is_b3 = spec["baseline_id"] == "B3-PrivGas-v1"
            cand_rows.append({
                "baseline_id": spec["baseline_id"], "pool_size": spec["pool_size"],
                "eligible_actors": spec["pool_size"],
                "r1_public_candidates": ",".join(map(str, st["public_candidate_economic_funders_per_op"])),
                "r1_distinct_true_funders": len(funders),
                "r2_candidates": spec["pool_size"] if is_b3 else "n/a",
                "r3_candidates": spec["pool_size"],
                "total_commitments": spec["pool_size"] if is_b3 else "n/a",
                "honest_commitments": spec["pool_size"] if is_b3 else "n/a",
                "attacker_controlled_commitments": 0 if is_b3 else "n/a",
                "proof_tree_depth": (priv["b3"] or {}).get("proof_merkle_tree_depth", "n/a")})
    cand_rows.sort(key=lambda c: (c["baseline_id"], c["pool_size"]))
    r1_rows.sort(key=lambda c: (c["baseline_id"], c["pool_size"]))

    # R3 negative control flag: any learned R3 model whose top-1 CI lies above chance + 0.05
    r3_flags = [r for r in learned if r["relation"] == "R3" and r["fold_kind"] == "loro"
                and r["feature_set"] != "none"
                and r["top1_ci_lo"] > r["chance_top1"] + 0.05]
    stops = {
        "leakage_selfcheck_ok": sc["ok"],
        "harness_public_order_equals_schedule": harness["public_order_equals_private_schedule"],
        "harness_order_leak_flags": len(harness["stop_flags"]),
        "split_audit_ok": split["ok"],
        "split_learned_prediction_sets_checked": split["learned_prediction_sets_checked"],
        "r3_above_chance_flags": len(r3_flags),
        "b3_clean_candidate_set_gt_1": all(c["r2_candidates"] != "n/a" and c["r2_candidates"] > 1
                                           for c in cand_rows
                                           if c["baseline_id"] == "B3-PrivGas-v1"),
        "runs_failed": manifest["runs_failed"],
    }
    dataset = defaultdict(lambda: {"recorded": 0, "failed": 0})
    for r in manifest["runs"]:
        dataset[(r["baseline_id"], r["scenario_id"], r["pool_size"])][r["status"]] += 1
    dataset_rows = [{"baseline_id": b, "scenario_id": s, "pool_size": n, **v}
                    for (b, s, n), v in sorted(dataset.items())]

    report.write_csv(out / "rules.csv", rules)
    report.write_csv(out / "rules_by_n.csv", rules_by_n)
    report.write_csv(out / "learned.csv", learned)
    report.write_csv(out / "learned_by_n.csv", learned_by_n)
    report.write_csv(out / "delta_bits.csv", deltas)
    report.write_csv(out / "delta_bits_by_n.csv", deltas_by_n)
    report.write_csv(out / "ablations.csv", ablations)
    report.write_csv(out / "candidate_sets.csv", cand_rows)
    report.write_csv(out / "r1_structure.csv", r1_rows)
    (out / "per_subject_scores.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    for name, obj in (("learned.json", learned), ("rules.json", rules),
                      ("delta_bits.json", deltas), ("ablations.json", ablations),
                      ("harness_audit.json", harness), ("split_audit.json", split),
                      ("selfcheck.json", sc), ("stop_conditions.json", stops),
                      ("r1_structure_all_runs.json", structure),
                      ("r3_negative_control_flags.json", r3_flags)):
        (out / name).write_text(json.dumps(obj, indent=1, sort_keys=True, default=str) + "\n")

    figdir = root / "figures" / "d1-pilot" / batch
    figs = report.plots(figdir, rules_by_n, learned, deltas, learned_by_n)
    ctx = {"batch": batch, "round": round_id, "rules": rules, "rules_by_n": rules_by_n,
           "learned": learned, "deltas": deltas, "ablations": ablations,
           "candidate_sets": cand_rows, "r1_structure": r1_rows, "stops": stops,
           "harness": harness, "figures": figs, "dataset": dataset_rows}
    md = report.markdown(ctx)
    (out / "results.md").write_text(md)
    if write_doc:
        report.write_generated(root / DOC, md, BEGIN, END)
    print(json.dumps(stops, indent=1))
    print(f"scored {len(rows)} subject predictions from {len(manifests)} frozen sets -> "
          f"{out.relative_to(root)}")
    return 0 if (stops["split_audit_ok"] and stops["leakage_selfcheck_ok"]) else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("selfcheck", "export-training-labels", "score"))
    ap.add_argument("--batch", required=True)
    ap.add_argument("--round", default="a1")
    ap.add_argument("--root", default=None)
    ap.add_argument("--write-doc", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    if args.command == "selfcheck":
        res = cmd_selfcheck(root, args.batch)
        print(json.dumps({k: v for k, v in res.items() if k != "findings"}),
              *res["findings"][:50], sep="\n")
        return 0 if res["ok"] else 1
    if args.command == "export-training-labels":
        summary = export_training_labels(root, args.batch)
        print(f"exported training labels for {len(summary)} folds")
        return 0
    return cmd_score(root, args.batch, args.round, args.write_doc)


if __name__ == "__main__":
    sys.exit(main())
