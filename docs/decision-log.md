# Decision log

Chronological record of non-obvious decisions made about this project's
process, scope, or structure. Not a changelog of code — `git log` is
authoritative for that. This is for decisions that aren't self-evident
from reading the code later.

Format for each entry:

```
## YYYY-MM-DD: <short title>

- **Decision**: what was decided.
- **Why**: the reasoning / constraint that drove it.
- **Alternatives considered**: what else was on the table, if relevant.
```

---

## 2026-09-13: Scaffold repository before any application code

- **Decision**: Set up directory structure, docs, `.gitignore`, task
  runner, and `scripts/env-report.sh` before writing any protocol,
  circuit, contract, or benchmark logic.
- **Why**: This is a security-research repository; every later result
  needs to be traceable to a git commit, experiment ID, seed, chain ID,
  EntryPoint version, and tool versions (see
  `docs/experiment-schema.md`). Establishing that contract first, with an
  empty codebase, makes it a hard requirement for everything added later
  rather than a retrofit.
- **Alternatives considered**: Writing scaffolding and application code
  together. Rejected because it risks the reproducibility contract being
  shaped around whatever the first implementation happens to produce,
  rather than being an independent constraint.

## 2026-09-13: `data/private/` is fully gitignored, `data/raw/` and `results/`/`figures/` contents are gitignored but tracked as empty dirs

- **Decision**: `data/private/**` is gitignored except for `.gitkeep` and
  `README.md`. `data/raw/*`, `results/*`, `figures/*` are also gitignored
  (contents only) so the directories exist in a fresh clone but generated
  content doesn't bloat the repo or get committed by accident.
- **Why**: Private/sensitive inputs must never be committable by default —
  a stray `git add -A` should not be able to leak them. Raw/generated
  output is reproducible from `experiments/` + a recorded seed, so it
  doesn't need to live in git.
- **Alternatives considered**: Only gitignoring `data/private/`, leaving
  `results/`/`figures/` tracked. Rejected for now since no application
  code exists yet to produce anything worth committing; revisit once real
  figures need to ship with the paper.

## 2026-09-13: Adopted `docs/research-plan.md` as canonical; reconciled placeholder docs

- **Decision**: `docs/research-plan.md`, `docs/references.md`, and
  `docs/ai-coder-prompts.md` were added to the repo with the full research
  plan (D1/D2/D3 directions, R1-R3 relations, A0-A3 adversary tiers, B0-B6
  baselines, sequential AI-coder prompts). Updated `docs/research-questions.md`
  and `docs/threat-model.md` (previously bare placeholders from the
  initial scaffold) to index that content instead of duplicating it, with
  `research-plan.md` as the source of truth if they ever disagree.
- **Why**: leaving the placeholders un-synced with the real plan would
  have made them actively misleading rather than merely incomplete.
- **Alternatives considered**: none — this is a direct reconciliation, not
  a new decision about project direction.

## 2026-09-13: Confirmed B3 baseline pin is reachable

- **Decision**: Verified via `git ls-remote` that
  `https://github.com/imranpollob/stealth-protocol.git` is reachable and
  that commit `02a3f0abdb979446545aa87149080bfb44e43a3e` matches that
  repository's `HEAD` at verification time. Baseline import (Prompt 1 in
  `docs/ai-coder-prompts.md`) has not been performed yet — this entry only
  records that the pinned commit exists and is fetchable.
- **Why**: catches a stale/typo'd commit hash before any import work
  starts, per the reproducibility contract in `docs/experiment-schema.md`.

## 2026-09-13: Imported B3 as a pinned git submodule; upgraded local Foundry to match

- **Decision**: `baselines/b3_privgas_v1` is a git submodule of
  `https://github.com/imranpollob/stealth-protocol`, explicitly checked
  out (detached HEAD) at `02a3f0abdb979446545aa87149080bfb44e43a3e`. The
  local machine's Foundry install was upgraded from `forge 0.2.0`
  (2024-08-13 build, too old to default Solidity 0.8.28 to the Cancun EVM)
  to the exact version the baseline's own `DEPENDENCIES.md` requires,
  `1.4.1-stable` (`foundryup -i 1.4.1`, attestation-verified).
- **Why**: user chose submodule over vendoring for hash-identical,
  low-duplication tracking of the exact commit (see chat: "How should the
  B3 baseline source be brought into this repo?"). The Foundry upgrade was
  required just to get `forge build` past a `transient storage` compile
  error — not a baseline change, and reversible via `foundryup -u`.
- **Alternatives considered**: vendoring a stripped copy of the source
  directly into the repo — rejected by the user in favor of the submodule.

## 2026-09-13: B3's credit-issuance path fails ordinary-key deployment (PoseidonT3 / EIP-170)

- **Decision**: Recorded, not repaired. `CreditPool` links against
  `PoseidonT3` (a `public`-function library compiled as its own deployed
  contract), whose runtime bytecode is 29,315 bytes — 4,739 bytes over
  EIP-170's 24,576-byte contract-size limit. Confirmed with a real signed
  `forge script --broadcast` against a default (EIP-170-enforcing) Anvil
  node using an ordinary dev private key, which Foundry refused to submit.
  A deterministic, network-independent failing test encodes this at
  `test/b3_ordinary_deploy/test/OrdinaryDeploy.t.sol`. Full narrative in
  `docs/b3-reproduction.md`.
- **Why**: Prompt 1's rule (`docs/ai-coder-prompts.md`) is to attempt
  ordinary-key deployment, not infer deployability from `vm.prank`-based
  demos (the baseline's own `script/Demo.s.sol` uses exactly that kind of
  impersonation and a mock always-true proof verifier, so it doesn't
  count as evidence either way). The baseline's own code comment already
  flagged this size issue; this entry is the independent, measured
  confirmation.
- **Alternatives considered**: none — per the "never silently repair B3"
  rule, no workaround (e.g. linking to a hypothetical pre-deployed
  canonical `PoseidonT3` address) was applied. If B3 needs to actually be
  deployed for a later experiment, that would be a new, explicitly
  labeled change, not an edit to the submodule.

## 2026-09-14: Pre-commit cleanup — regression test inverted to pass; EntryPoint commit identified exactly

- **Decision**: Two changes to the Prompt 1 deliverables before committing,
  requested by the user:
  1. `test/b3_ordinary_deploy/test/OrdinaryDeploy.t.sol` now asserts
     `size > EIP170_CONTRACT_SIZE_LIMIT` (passes) instead of `size <=
     EIP170_CONTRACT_SIZE_LIMIT` (failed by design). It now reads as a
     standing regression check confirming a known, frozen property of the
     pinned B3 commit, not as an unresolved red test. The live
     `scripts/run_b3_ordinary_deploy.sh` / `script/OrdinaryDeploy.s.sol`
     broadcast attempt is unchanged and still records the actual
     deployment failure as data (`results/b3/ordinary-deploy-result.json`).
  2. `docs/b3-reproduction.md`'s EntryPoint version section no longer
     relies only on the baseline's own "pre-release 0.9.0 snapshot" label.
     Cloned `eth-infinitism/account-abstraction` upstream and ran a
     byte-for-byte recursive diff of its `contracts/` tree against
     `lib/account-abstraction/contracts/` in the vendored baseline: zero
     differences against commit `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410`,
     which upstream tags `v0.9.0` (and against `develop`'s later tip,
     which only adds an audit doc on top). Recorded alongside the vendored
     tree's own `package.json` self-identification
     (`@account-abstraction/contracts@0.9.0`).
- **Why**: a red test that's expected to stay red long-term is a worse
  signal than a green test that actively confirms a known, cited fact
  about a *frozen* (submodule-pinned) dependency — it should only turn red
  again if the pin changes, which is exactly when we'd want to notice. The
  commit-identification work replaces an inference ("no stable release
  identity") with a checked fact (exact hash + tag), consistent with the
  project's "no protocol/version claims without a citation" discipline.
- **Alternatives considered**: none for (1) — direct implementation of the
  user's instruction. For (2), relying on an npm registry lookup for
  `@account-abstraction/contracts@0.9.0` was considered but not pursued;
  the git commit/tag match is direct, stronger evidence (byte-for-byte,
  not just a version string) and was sufficient on its own.
