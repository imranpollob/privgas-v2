# Experiment schema

This defines the metadata record every experiment run must produce. It is
the concrete form of the reproducibility contract stated in `README.md`.

No experiment result (a number, a plot, a table row) may be cited in
`paper/` or `results/` unless it is accompanied by a record matching this
schema.

## Required fields

Every experiment run emits a `metadata.json` (or equivalent) alongside its
raw output, with at minimum:

| Field                 | Type     | Meaning                                                                 |
|------------------------|----------|--------------------------------------------------------------------------|
| `experiment_id`        | string   | Identifier matching a definition under `experiments/<category>/`        |
| `git_commit`           | string   | Full commit SHA the run executed at (`git rev-parse HEAD`)              |
| `git_dirty`            | boolean  | Whether the worktree had uncommitted changes at run time                |
| `seed`                 | integer  | RNG seed used for the run                                                |
| `chain_id`             | integer  | Chain/network ID targeted (including local devnets, e.g. anvil default) |
| `entrypoint_version`   | string   | ERC-4337 EntryPoint (or equivalent AA entrypoint) version targeted      |
| `tool_versions`        | object   | Output of `scripts/env-report.sh`, captured at run time                 |
| `started_at_utc`       | string   | ISO-8601 UTC timestamp                                                  |
| `finished_at_utc`      | string   | ISO-8601 UTC timestamp                                                  |
| `parameters`           | object   | All experiment-specific inputs (workload size, config, etc.)             |
| `outputs`              | object or path | The measured result(s), or a path to where they're stored          |

## Why each field is required

- **experiment_id**: makes results discoverable and links them back to a
  research question in `docs/research-questions.md`.
- **git_commit** + **git_dirty**: without this, "which code produced this
  number" is unanswerable. A dirty worktree at run time should be treated
  as non-reproducible and flagged, not silently accepted.
- **seed**: required for any randomized workload or sampling; without it,
  variance can't be distinguished from a real effect.
- **chain_id**: gas costs, block gas limits, and opcode pricing are
  chain-specific; a result without this is not comparable across networks.
- **entrypoint_version**: ERC-4337 EntryPoint semantics and gas accounting
  have changed across versions; mixing versions silently invalidates
  comparisons.
- **tool_versions**: compiler and library versions can change measured gas
  costs and correctness even with identical source code.

## Example record

```json
{
  "experiment_id": "workloads/example-001",
  "git_commit": "0000000000000000000000000000000000000000",
  "git_dirty": false,
  "seed": 42,
  "chain_id": 31337,
  "entrypoint_version": "TBD",
  "tool_versions": { "...": "see scripts/env-report.sh output" },
  "started_at_utc": "2026-01-01T00:00:00Z",
  "finished_at_utc": "2026-01-01T00:00:01Z",
  "parameters": {},
  "outputs": {}
}
```

## Storage convention

```
results/<experiment_id>/<run_timestamp>/
  metadata.json     # this schema
  raw/              # raw output referenced by `outputs`, if not inline
```

`make run-local-experiment ID=<id> SEED=<seed>` is the reference mechanism
for producing a directory in this shape; see the Makefile.
