# privgas-v2

Security-research repository. This scaffold exists to make every claim this
project eventually makes **reproducible and falsifiable**: any number in a
figure or paper must be traceable back to the exact code, configuration,
and environment that produced it.

At this stage the repository contains **no application logic** — no
protocol implementation, no circuits, no contracts, no benchmark code.
Only the structure and process needed to do that work reproducibly once it
starts. See `docs/decision-log.md` for why it's being built in this order.

## Layout

```
docs/                     research questions, threat model, specs, decision log
baselines/                reference/baseline implementations to compare against
contracts/                on-chain contracts (empty until work begins)
circuits/                 zero-knowledge / cryptographic circuits (empty until work begins)
test/                     test suites for the above
scripts/                  operational scripts (env-report, etc.)
experiments/
  workloads/              workload/traffic generators and definitions
  privacy/                privacy-focused experiments
  liveness/               liveness/availability experiments
  settlement/             settlement-correctness experiments
  analysis/               scripts that turn raw results into figures/tables
data/
  raw/                    raw experiment output (gitignored, regenerate locally)
  public/                 data cleared for publication (tracked)
  private/                sensitive data — NEVER committed (gitignored)
results/                  processed experiment results
figures/                  generated figures for the paper
paper/                    the paper/writeup itself
```

## Quickstart

```sh
make install          # install/verify toolchain dependencies
make env-report       # print exact tool versions + git state
make test             # run the test suite (placeholder until code exists)
make benchmark        # run the benchmark suite (placeholder until code exists)
make run-local-experiment ID=<experiment-id> SEED=<seed>   # run one experiment locally
make clean            # remove local, regenerable artifacts
```

Run `make help` to list all targets with descriptions.

## The reproducibility contract

Every result produced by this repository — a number in a table, a point on
a plot, a claim in the paper — must be traceable to all of the following:

1. **Git commit** — the exact commit the code was run at (`git rev-parse HEAD`).
2. **Experiment ID** — a stable identifier matching a definition under
   `experiments/` (see `docs/experiment-schema.md`).
3. **Seed** — the RNG seed used, so randomized experiments are re-runnable.
4. **Chain ID** — which chain/network configuration was targeted (including
   local devnets), since gas costs and behavior are chain-dependent.
5. **EntryPoint version** — which ERC-4337 EntryPoint contract version (or
   equivalent account-abstraction entrypoint) was targeted, since semantics
   and gas accounting differ across versions.
6. **Compiler/tool versions** — solc/circom/node/forge/etc., captured via
   `scripts/env-report.sh`.

`docs/experiment-schema.md` defines the metadata record every experiment
run must emit, `make run-local-experiment` shows the mechanism, and
`make env-report` is the single command that produces (5)-(6).

## Reading order for docs

1. `docs/research-questions.md` — what this project is trying to find out (TBD, no protocol claims yet)
2. `docs/threat-model.md` — assets, adversary, trust assumptions (TBD)
3. `docs/baseline-spec.md` — what a "baseline" means here and how one qualifies
4. `docs/experiment-schema.md` — the metadata contract every experiment must satisfy
5. `docs/decision-log.md` — chronological record of non-obvious decisions

## Status

Scaffold only. No protocol, circuit, or contract claims have been made yet.
Do not cite this repository as evidence of any specific privacy or gas
property until `docs/research-questions.md` and `docs/threat-model.md` are
filled in and application code exists.
