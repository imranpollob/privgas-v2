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
    adapters/           Observation -> record, per baseline (B0, B1, B2)
    examples/           synthetic B0/B1/B2 fixture runs
    docgen.py           generates the field tables in the schema doc
  attacker_view/        READ side: public (A0/A1) + bundler (A2) data only
  labels/               READ side: secret ground truth, evaluation, self-check
  tests/                schema, boundary, label-join, integration, self-check

  workloads/ privacy/ liveness/ settlement/ analysis/   (experiment defs)
```

## The rule this code exists to enforce

Importing `experiments.attacker_view` claims the **public** side of the data
boundary for the whole process; importing `experiments.labels` claims the
**private** side. Whichever is claimed first, importing the other raises
`BoundaryViolation` — including through `importlib`. `experiments.recorder`
is neutral and holds no data, so both sides may import it.

Feature generation and evaluation therefore run in **separate processes**,
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
```

## Status

B0, B1 and B2 are **not implemented** in `baselines/` (see
`docs/baseline-spec.md`). The example runs under `recorder/examples/` are
synthetic fixtures — every row carries `data_origin: "synthetic_fixture"` and
a `synthetic-` run_id, and the validator enforces both. They exercise the
recorder for each baseline and show what a real run must produce. They are
not measurements.

No attack, model, metric or privacy mechanism lives here yet. The recorder
observes experiments; it makes no privacy claim of its own.
