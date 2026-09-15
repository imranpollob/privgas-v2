"""Attacker-side CLI for the D1 pilot (public data only).

    python3 -m experiments.privacy.d1.attack splits --batch <batch>
    python3 -m experiments.privacy.d1.attack run --batch <batch> --round <round>

``splits`` freezes the run-level split manifest (``results/d1-pilot/<batch>/
splits.json`` + its sha256) from the public dataset manifest. It must exist
before training labels are exported.

``run`` extracts pair features, applies every deterministic / timing rule, fits
the conditional-logit models per fold, feature set, ablation and registry
convention, and freezes one predictions file per (run, attack, relation). Frozen
files are never overwritten; a new round id starts a new attack round.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from ....recorder.provenance import repo_root
from .. import extract, models, registry, rules, splits
from . import freeze_predictions
from .io import (batch_dir, load_dataset_manifest, load_fold_training_labels, load_splits,
                 load_trace)

RELATIONS = ("R1", "R2", "R3")
MAIN_SETS = (("none", ()), ("T", ("T",)), ("T+AA", ("T", "AA")), ("G", ("G",)),
             ("T+G", ("T", "G")), ("T+AA+G", ("T", "AA", "G")))
ABLATIONS = ("timing", "gas", "eq", "pm", "app")
R2_EXTRA = (("G", "eq"), ("T+G", "eq"), ("T+G", "timing"))
#: L2 grid; the strength is chosen per (fold, relation, feature configuration) by inner
#: leave-one-replicate-out cross-validation on that fold's TRAINING runs only (mean
#: held-out log loss; ties -> the stronger penalty). Test runs never influence it.
L2_GRID = (0.1, 1.0, 10.0, 100.0)


def model_configs(relation: str) -> List[Dict[str, Any]]:
    out = []
    conventions = ("primary", "field_kind") if relation == "R2" else ("primary",)
    for conv in conventions:
        for name, fams in MAIN_SETS:
            out.append({"feature_set": name, "families": fams, "drop_sub": (),
                        "drop_family": (), "convention": conv})
        for abl in ABLATIONS:
            out.append({"feature_set": f"T+AA+G-minus-{abl}", "families": ("T", "AA", "G"),
                        "drop_sub": () if abl == "app" else (abl,),
                        "drop_family": ("T",) if abl == "app" else (), "convention": conv})
        if relation == "R2":
            for name, abl in R2_EXTRA:
                out.append({"feature_set": f"{name}-minus-{abl}",
                            "families": tuple(name.split("+")), "drop_sub": (abl,),
                            "drop_family": (), "convention": conv})
    return out


def relations_for(baseline_id: str) -> List[str]:
    out = []
    if baseline_id in ("B0", "B1"):
        out.append("R1")
    if baseline_id == "B3-PrivGas-v1":
        out.append("R2")
    out.append("R3")
    return out


def fit_with_inner_cv(train_sc: List[extract.SubjectCandidates], train_idx: List[int],
                      train_groups: List[str], names: List[str]
                      ) -> Tuple[models.ConditionalLogit, Dict[str, Any]]:
    """Choose L2 by inner leave-one-group-out CV on the training data, then refit."""
    X = [_matrix(sc, names) for sc in train_sc]
    groups = sorted(set(train_groups))
    record: Dict[str, Any] = {"grid": list(L2_GRID), "inner_groups": groups, "inner_loss": {}}
    if not names or len(groups) < 2:
        lam = 1.0
        record["reason"] = "no features" if not names else "fewer than two inner groups"
    else:
        losses = {}
        for lam in L2_GRID:
            nll, count = 0.0, 0
            for g in groups:
                tr = [i for i, gg in enumerate(train_groups) if gg != g]
                te = [i for i, gg in enumerate(train_groups) if gg == g]
                m = models.ConditionalLogit(l2=lam, feature_names=names)
                m.fit([X[i] for i in tr], [train_idx[i] for i in tr])
                for i in te:
                    p = m.predict_proba(X[i])
                    nll -= float(np.log(max(p[train_idx[i]], 1e-12)))
                    count += 1
            losses[lam] = nll / max(count, 1)
        record["inner_loss"] = {str(k): v for k, v in losses.items()}
        best = min(losses.values())
        lam = max(k for k, v in losses.items() if v <= best + 1e-12)
    model = models.ConditionalLogit(l2=lam, feature_names=names)
    model.fit(X, train_idx)
    record["chosen_l2"] = lam
    return model, record


def cmd_splits(root: Path, batch: str) -> int:
    manifest = load_dataset_manifest(root, batch)
    body = splits.build_splits(manifest)
    d = batch_dir(root, batch)
    if (d / "splits.json").exists():
        raise SystemExit(f"{d / 'splits.json'} already frozen")
    (d / "splits.json").write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")
    (d / "splits.sha256").write_text(splits.canonical_sha256(body) + "\n")
    print(f"froze {len(body['folds'])} folds -> {(d / 'splits.json').relative_to(root)}")
    return 0


def _matrix(sc: extract.SubjectCandidates, names: List[str]) -> np.ndarray:
    if not names:
        return np.zeros((len(sc.candidates), 0))
    return np.column_stack([np.asarray(sc.features[n], dtype=float) for n in names])


def cmd_run(root: Path, batch: str, round_id: str) -> int:
    started = time.time()
    manifest = load_dataset_manifest(root, batch)
    split_body, split_sha = load_splits(root, batch)
    runs = [r for r in manifest["runs"] if r["status"] == "recorded"]
    # Public replicate ids group runs for inner cross-validation (pool sizes of one
    # replicate never share actors with another replicate).
    replicate_of = {(r["experiment_id"], r["run_id"]): r["replicate"] for r in runs}
    out_dir = batch_dir(root, batch) / f"attack-{round_id}"
    if out_dir.exists():
        raise SystemExit(f"{out_dir} exists; use a new --round")
    out_dir.mkdir(parents=True)

    traces: Dict[Tuple[str, str], extract.RunTrace] = {}
    feats: Dict[Tuple[str, str, str], List[extract.SubjectCandidates]] = {}
    structure = []
    for r in runs:
        key = (r["experiment_id"], r["run_id"])
        t = load_trace(root, *key)
        traces[key] = t
        s = extract.r1_structure(t)
        structure.append({"experiment_id": key[0], "run_id": key[1],
                          "scenario_id": r["scenario_id"], **s})
        for rel in relations_for(t.baseline_id):
            feats[key + (rel,)] = extract.features(t, rel)
    (out_dir / "r1_structure.json").write_text(json.dumps(structure, indent=2) + "\n")
    feature_dump = {f"{k[0]}|{k[1]}|{k[2]}": [
        {"subject_ref": sc.subject_ref, "candidates": sc.candidates, "features": sc.features}
        for sc in v] for k, v in feats.items()}
    (out_dir / "features.json").write_text(json.dumps(feature_dump) + "\n")

    frozen = 0
    # ---- deterministic and timing rules -------------------------------------------
    for (exp, run), t in traces.items():
        for rel in relations_for(t.baseline_id):
            for rule in rules.rules_for(rel, t.baseline_id):
                preds = rule.fn(t)
                freeze_predictions(
                    experiment_id=exp, run_id=run, attack_id=f"{round_id}.{rule.rule_id}",
                    relation=rel, observer_tier=rule.observer_tier, feature_set=rule.feature_set,
                    root=root,
                    predictions=[{"subject_ref": p["subject_ref"],
                                  "prediction": {"kind": "rule", "candidates": p["candidates"],
                                                 "scores": p["scores"],
                                                 "selected": p["selected"]}} for p in preds],
                    extra={"attack_kind": rule.kind, "rule_id": rule.rule_id,
                           "description": rule.description, "round": round_id,
                           "uses_labels": False})
                frozen += 1

    # ---- learned models per fold ----------------------------------------------------
    fits = []
    for fold in split_body["folds"]:
        b = fold["baseline_id"]
        for rel in relations_for(b):
            labels, provenance = load_fold_training_labels(root, batch, fold, rel, split_sha)
            train_groups: Dict[str, List] = {"sc": [], "idx": [], "group": []}
            missing = 0
            for exp, run in fold["train_runs"]:
                for sc in feats[(exp, run, rel)]:
                    truth = labels.get((exp, run, sc.subject_ref))
                    if truth is None or truth not in sc.candidates:
                        missing += 1
                        continue
                    train_groups["sc"].append(sc)
                    train_groups["idx"].append(sc.candidates.index(truth))
                    train_groups["group"].append(replicate_of[(exp, run)])
            for cfg in model_configs(rel):
                chosen = registry.select(rel, b, cfg["families"], cfg["convention"],
                                         cfg["drop_sub"], cfg["drop_family"])
                names = [f.name for f in chosen]
                model, cv = fit_with_inner_cv(train_groups["sc"], train_groups["idx"],
                                              train_groups["group"], names)
                attack_id = (f"{round_id}.clogit.{fold['kind']}.{cfg['convention']}."
                             f"{cfg['feature_set']}")
                desc = {**model.describe(), "inner_cv": cv}
                fits.append({"fold_id": fold["fold_id"], "relation": rel, "attack_id": attack_id,
                             "train_subjects": len(train_groups["sc"]),
                             "train_subjects_without_label": missing, **desc})
                for exp, run in fold["test_runs"]:
                    rows = []
                    for sc in feats[(exp, run, rel)]:
                        p = model.predict_proba(_matrix(sc, names))
                        rows.append({"subject_ref": sc.subject_ref,
                                     "prediction": {"kind": "probabilities",
                                                    "candidates": sc.candidates,
                                                    "scores": [float(x) for x in p],
                                                    "selected": sc.candidates}})
                    freeze_predictions(
                        experiment_id=exp, run_id=run, attack_id=attack_id, relation=rel,
                        observer_tier="A0", feature_set=cfg["feature_set"], root=root,
                        predictions=rows,
                        extra={"attack_kind": "learned", "round": round_id,
                               "fold_id": fold["fold_id"], "fold_kind": fold["kind"],
                               "split_sha256": split_sha,
                               "train_runs": fold["train_runs"],
                               "training_labels_read": provenance,
                               "registry_convention": cfg["convention"],
                               "model": desc, "uses_labels": "training runs only"})
                    frozen += 1
    (out_dir / "model_fits.json").write_text(json.dumps(fits, indent=1) + "\n")
    (out_dir / "attack_manifest.json").write_text(json.dumps({
        "batch": batch, "round": round_id, "split_sha256": split_sha,
        "frozen_prediction_sets": frozen, "model_fits": len(fits), "l2_grid": list(L2_GRID),
        "model_id": models.MODEL_ID, "observer_tier": "A0",
        "seconds": round(time.time() - started, 1)}, indent=2) + "\n")
    print(f"froze {frozen} prediction sets ({len(fits)} model fits) in "
          f"{time.time() - started:.0f}s -> {out_dir.relative_to(root)}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("splits", "run"))
    ap.add_argument("--batch", required=True)
    ap.add_argument("--round", default="a1")
    ap.add_argument("--root", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    if args.command == "splits":
        return cmd_splits(root, args.batch)
    return cmd_run(root, args.batch, args.round)


if __name__ == "__main__":
    sys.exit(main())
