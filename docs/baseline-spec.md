# Baseline specification

Status: **placeholder — defines the concept and process; no baselines implemented yet.**

`baselines/` holds reference implementations that experiments compare
against — e.g., an unmodified/standard flow with no privacy or gas
mechanism applied, or a well-known prior approach. Baselines exist so that
every measured effect (privacy, gas overhead, latency, ...) is reported
*relative to* something, never as a bare absolute number.

## What qualifies as a baseline

A baseline must:

1. Be runnable standalone via the same harness experiments use
   (`make run-local-experiment`), with no dependency on unfinished project
   code.
2. Pin its own dependency versions independently of the main project
   (recorded via `scripts/env-report.sh` at run time, per
   `docs/experiment-schema.md`).
3. Have a written description of what it represents and why it's a fair
   comparison point (added to this file when the baseline is added).
4. Not be modified to make later results look better — changes to a
   baseline after it's been used in a reported result require a new
   baseline ID and a decision-log entry, not an in-place edit.

## Registry of baselines

| ID | Directory | Represents | Added (commit) |
|----|-----------|------------|-----------------|
| B3 | `baselines/b3_privgas_v1` (git submodule, pinned `02a3f0ab...e43a3e`) | The accepted PrivGas v1 implementation, reproduced as faithfully as possible — evaluated as a specimen, not improved. See `docs/b3-reproduction.md` for test results, dependency/version provenance, and a documented ordinary-key deployment failure (PoseidonT3 exceeds EIP-170). | (this repo's next commit) |
| B0-B2, B4-B6 | not yet implemented | Sender-funded EOA / sender-funded smart account / observable Paymaster / independent-issuance credit / prior-art prepaid Paymaster / shielded-pool reference — see `docs/research-plan.md` §5. | — |

## Directory convention (once baselines exist)

```
baselines/<baseline-id>/
  README.md        # what this represents, why it's a fair comparison
  <implementation>  # the actual runnable baseline
```
