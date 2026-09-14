# data/public/

Attacker-visible recorder output: tier A0/A1 streams under `observer_a0a1/`
and tier A2 (instrumented-bundler) streams under `observer_a2/`. Layout and
schema: `docs/experiment-schema.md`.

**Generated runs here are gitignored by default** (see `.gitignore` and
`docs/decision-log.md`, 2026-09-14). They are regenerable from `data/raw/` and
the secret seed in `data/private/`, so they are treated like `data/raw/` and
`results/`. Publishing a generated run is an explicit decision, taken only
after `make recorder-selfcheck` passes.

Committable exceptions: this README, `.gitkeep`, and the tiny synthetic
recorder examples `baselines/*-example/` (every row `data_origin:
"synthetic_fixture"`, run_id prefixed `synthetic-`), regenerated with
`make recorder-examples`. They document the schema. They are not measurements.
