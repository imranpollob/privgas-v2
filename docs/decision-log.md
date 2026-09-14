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

## 2026-09-14: Experiment recorder — three streams, and `seed` reclassified as secret

- **Decision**: Built the versioned experiment recorder under
  `experiments/` with three JSONL streams (`ground_truth.jsonl`,
  `public_events.jsonl`, `bundler_private.jsonl`), schema version `1.0.0`,
  and `docs/experiment-schema.md` as the canonical definition. Within that,
  one classification was genuinely ambiguous and was resolved deliberately:
  **`seed` is secret**. It lives in `run_manifest.private.json` and
  `ground_truth.jsonl`; the public manifest carries `"seed": null` plus
  `seed_commitment_sha256 = sha256({"namespace": run_id, "value": seed})`.
- **Why**: `docs/research-plan.md` §10 lists `seed` under `ground_truth.jsonl`
  while `docs/experiment-schema.md` §1 lists it in the public per-run
  metadata. Those coexist fine for a metadata-only run, but conflict once an
  attack is run against the data: the seed determines the hidden assignment of
  actors to accounts and to timing, so publishing it during the attack phase
  publishes the answer key in compressed form. The commitment keeps the seed
  pinned — a later reveal is checkable — without disclosing it. It is binding,
  not hiding (the seed space is small and enumerable), and is recorded as such
  so nothing later mistakes it for a privacy mechanism. Metadata-only runs
  that record no linkage labels are unaffected and still carry the seed in the
  clear.
- **Alternatives considered**: leaving the seed public, since the harness is
  ours and the workload is documented — rejected because it would silently
  hand every attack a shortcut and make any measured ΔL meaningless. Omitting
  the seed from public output entirely with no commitment — rejected because
  then nothing pins the value and a seed could be chosen after seeing results.

## 2026-09-14: Public/private data separation is a process boundary, not a convention

- **Decision**: `experiments/attacker_view/` (reads public + bundler data) and
  `experiments/labels/` (reads secret ground truth) are **mutually
  unimportable within one Python process** — importing either installs a
  `sys.meta_path` finder that refuses to resolve the other, so even
  `importlib` fails. Feature generation and evaluation must run in separate
  processes, communicating through a predictions file frozen with a sha256
  that `join_for_evaluation` verifies before any label is loaded.
  `experiments/recorder/` is neutral and importable from both sides.
- **Why**: Prompt 3 §12 requires structural protection rather than a comment
  saying "do not use this file". An import-time `ImportError` is testable,
  survives refactoring, and cannot be bypassed by a dynamic import; a naming
  convention cannot. Freezing predictions before labels are readable is what
  makes "predict, then score" the path of least resistance and makes the
  reverse leave evidence in the recorded artefacts.
- **Alternatives considered**: relying on directory separation plus code
  review alone — rejected as exactly the "comments as enforcement" pattern the
  task rules out. Note the limit, recorded in `docs/experiment-schema.md` §10:
  this stops accidental and casual access, not a script that calls `open()` on
  `data/private/` directly. It is not a sandbox.

## 2026-09-14: B0/B1/B2 recorder integration uses labelled synthetic fixtures, because those baselines do not exist

- **Decision**: Prompt 3 §18 asks for "one representative W1 run" of B0, B1 and
  B2 through the recorder. `baselines/` contains only `b3_privgas_v1` — Prompt
  2 has not been performed, and no Prompt 2 handoff report exists in the
  repository. Rather than skip the integration or manufacture measured runs,
  each baseline gets a **synthetic fixture run** under
  `experiments/recorder/examples/`, with a mandatory `data_origin` field
  (`"measured"` vs `"synthetic_fixture"`) that the validator ties to a
  `synthetic-` run_id prefix in both directions.
- **Why**: the recorder is baseline-independent by design, so it can be built
  and tested in full before the baselines land; but writing invented gas
  figures and transaction hashes into `data/public/` as if they were
  measurements would corrupt the very record the recorder exists to keep
  honest. Making origin a validated schema field — rather than a README
  warning — means a fixture can never later be mistaken for a measurement,
  including by code that only reads a single row.
- **Alternatives considered**: implementing B0/B1/B2 as part of this task —
  rejected, that is Prompt 2's scope and would have been an unreviewed
  expansion. Deferring §18 entirely — rejected, it would have left the
  per-baseline capability rules (no UserOperation for B0, null Paymaster for
  B1, public Paymaster for B2, no bundler stream for B0) untested.

## 2026-09-14: Observer tiers are separate directories, and `bundler_private` is not secret

- **Decision**: `data/public/<experiment>/<run>/observer_a0a1/public_events.jsonl`
  and `.../observer_a2/bundler_private.jsonl`, with ground truth in
  `data/private/`. A baseline with no bundler (B0) gets no bundler file **and**
  no `observer_a2/` directory.
- **Why**: `docs/research-plan.md` §7 and `docs/threat-model.md` require that
  A2 data never leaks into an A0/A1 dataset. With tier subdirectories, an
  A0/A1 dataset is assembled by naming `observer_a0a1/`, and a glob cannot
  pick up bundler rows by accident; including A2 data requires naming the
  other directory, which is the visible, deliberate act the threat model asks
  for. An empty `observer_a2/` directory for B0 was rejected because it reads
  as "we instrumented a bundler and saw nothing", which is false — B0 never
  reaches a mempool. Note the naming trap, recorded in the schema doc:
  `bundler_private.jsonl` is private *with respect to the public ledger*, not
  secret; it is a legitimate attacker input at tier A2. Only
  `ground_truth.jsonl` is secret.
- **Alternatives considered**: a fourth top-level `data/bundler/` root —
  rejected to stay within the `raw/public/private` policy established in
  Prompt 0.
