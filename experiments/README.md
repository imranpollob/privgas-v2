# experiments/

Experiment definitions, the recorder, and the two read-side packages that
keep secret ground truth away from attack code.

Canonical schema documentation: **`docs/experiment-schema.md`**. This file is
a map of the code, not a second definition — if the two disagree, the doc is
authoritative and the drift is a bug.

## Layout

```
experiments/
  _boundary.py          process-level public/private mutual exclusion
  recorder/             WRITE side (neutral: importable from either side)
    version.py          schema version + compatibility policy
    baselines.py        per-baseline capability table (B0..B6)
    fieldtypes.py       deterministic primitive validators
    privatekeys.py      the denylist of private field names
    schemas/            one module per stream + the shared envelope
    validate.py         the single validation entry point
    provenance.py       software revision + scripts/env-report.sh integration
    paths.py            on-disk layout, incl. observer-tier directories
    digest.py           content digests shared across the boundary
    writers.py          JSONL writers + ExperimentRecorder
    adapters/           Observation -> record, per baseline (B0, B1, B2, B3-PrivGas-v1)
    examples/           synthetic B0/B1/B2 fixture runs (schema examples only)
    docgen.py           generates the field tables in the schema doc
  attacker_view/        READ side: public (A0/A1) + bundler (A2) data only
  labels/               READ side: secret ground truth, evaluation, self-check
  tests/                schema, boundary, label-join, integration, self-check

  workloads/w1/         REAL W1 runner (B0, B1, B2-Allowlist, B2-Signature;
                        W1-cold/W1-warm; and the frozen B3-PrivGas-v1 on the
                        b3_compat_local profile): signed txs on anvil,
                        instrumented bundler, preVerificationGas calibration
                        (pvg.py, calibration.py), evaluation profiles
                        (profiles.py), B3 deployment/ops (b3.py), real Semaphore
                        prover (prover.py, prover/), cost reconciliation
                        (accounting.py, accounting_b3.py), raw -> records,
                        fairness and profile effect (compare.py)
    tests/              live anvil tests (B0-B2, test_b3_live.py) + dependency pins
  privacy/ liveness/ settlement/ analysis/   (experiment defs, empty)
```

## The rule this code exists to enforce

Attack code must never read secret ground truth. The separation rests on
(`docs/experiment-schema.md` §8.2): distinct data paths (`data/private/` vs.
`data/public/.../observer_a0a1/` and `observer_a2/`), distinct reader APIs
(`attacker_view` vs. `labels`), an explicit process boundary with frozen,
digest-checked predictions, and validation/path guards.

As defence in depth only, importing `experiments.attacker_view` claims the
public side for the whole process and importing `experiments.labels` claims
the private side; importing the other then raises `BoundaryViolation`. That
hook is bypassable and nothing relies on it. `experiments.recorder` is neutral
and holds no data, so both sides may import it.

Feature generation and evaluation run in **separate processes**,
communicating only through a frozen predictions file:

```
process 1   experiments.attacker_view    read public/bundler data
                                         -> features -> predictions
                                         -> freeze_predictions()  [sha256]
process 2   experiments.labels           verify the digest
                                         -> load ground truth
                                         -> join_for_evaluation()
```

## Commands

```
make recorder-test        # schema, boundary, label-join, integration tests
make recorder-examples    # regenerate the synthetic B0/B1/B2 example runs
make recorder-selfcheck   # scan data/public/ for leaked keys and values
make recorder-docs        # regenerate the field tables in the schema doc
make baselines-test       # forge + live anvil tests of the real B0/B1/B2
make calibrate-pvg                   # calibration phase: EntryPoint overhead artifacts (both profiles)
make run-matched-baselines SEED=<n>   # real runs for all variants, recorded
make run-b3-evaluation SEED=<n>       # matched B0/B1/B2-Signature on both profiles + B3-PrivGas-v1
make b3-eip170-test                   # the frozen PoseidonT3 still exceeds EIP-170
```

## Status

B0, B1, B2-Signature and auxiliary B2-Allowlist are implemented, with
workloads W1-cold (primary) and W1-warm (B1 ablation) (`baselines/w1_b0_b2`,
`workloads/w1`, `docs/w1-baselines.md`), and record `data_origin: "measured"`.
The AA baselines use an in-repo INSTRUMENTED EXPERIMENTAL bundler that does not
establish ERC-7562 or production compatibility. The example runs
under `recorder/examples/` remain synthetic fixtures — every row carries
`data_origin: "synthetic_fixture"` and a `synthetic-` run_id, and the validator
enforces both. They document the schema. They are not measurements.
Schema version: 4.0.0.

The D1 pilot (multi-actor workload `workloads/d1/`, attacks and evaluation
`privacy/d1/`, results `docs/d1-pilot-results.md`) is the first attack code; it
keeps attack (`privacy/d1/attack`) and evaluation (`privacy/d1/evaluate`) in
separate processes. The recorder
observes experiments; it makes no privacy claim of its own.
