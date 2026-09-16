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

## 2026-09-14: State correction — the recorder (Prompt 3) was built before the baselines (Prompt 2)

- **Decision**: Implemented real B0/B1/B2 after the fact and re-validated the
  recorder against them, instead of treating the Prompt-3 synthetic fixtures
  as a description of the baselines. The fixtures stay fixtures
  (`data_origin: "synthetic_fixture"`); every assumption the real runs
  contradicted is listed in `docs/w1-baselines.md` §14 and was corrected
  explicitly (schema 2.0.0 entry below), not silently.
- **Why**: the fixtures encoded guesses about event structure that no chain
  had produced. Measurements must drive the schema, not the reverse.

## 2026-09-14: B0/B1/B2 architecture choices

- **Decision**:
  1. **One shared Foundry project** `baselines/w1_b0_b2/` and one parameter
     file `w1-config.json` read by both the Forge tests and the live runner.
  2. **EntryPoint v0.9.0 at `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410`**, the
     exact commit B3 vendors, compiled with B3's compiler settings. Sources are
     reached by read-only remappings into `baselines/b3_privgas_v1/lib/`
     rather than vendored a second time or fetched with git; tree digests are
     pinned in `dependency-pin.json` and tested.
  3. **Account: unmodified eth-infinitism `SimpleAccount` + `SimpleAccountFactory`
     from that same commit**, for both B1 and B2. It is the reference account
     of the pinned EntryPoint release and needs no new code. (B3's own tests use
     a `MockSimpleAccount`; B3 comparisons will therefore differ in account
     code, which is recorded.)
  4. **B2 authorization = owner-managed public allowlist**
     (`sponsored[userOp.sender]`). A signature-verifying Paymaster was not
     chosen because it requires designing a sponsor-signature domain, which
     `docs/research-plan.md` §18 reserves for human review.
  5. **In-repo instrumented bundler** (`experiments/workloads/w1/bundler.py`)
     shared by B1/B2: simulation by `eth_call handleOps`, no ERC-7562, no public
     mempool. Required for A2 data from a bundler we operate.
  6. **Real signed transactions only** in the live runner (`eth_sendRawTransaction`
     from locally held seed-derived keys; no impersonation, no unlocked
     accounts). Forge tests use `vm.prank` for semantics only; no cost number
     comes from Forge.
  7. **Base fee pinned** to 1 gwei before every block
     (`anvil_setNextBlockBaseFeePerGas`), priority 1 gwei, max fee 2 gwei.
     Without it anvil's base fee decays per block and baselines with different
     block counts would pay different prices.
  8. **Identical setup phase** (funding, all four deployments, Paymaster
     deposit) in every baseline, so addresses and state match; setup is
     environment, not W1 cost, and is not recorded as events.
  9. **Raw-first recording**: role-free chain dump and bundler log under
     `data/raw/`; role assignment and the role-labelled cost reconciliation
     under `data/private/`; public streams are derived from the raw dump by
     classifying on-chain content only, and regenerate byte-identically.
- **Why**: each choice removes a way for B0/B1/B2 to differ in something other
  than account type and gas mechanism, or avoids an AI-designed security
  construct.
- **Alternatives considered**: an external bundler (Alto/Rundler/eth-infinitism
  bundler) — rejected for now: v0.9.0 support, network installs and log access
  were unverified, and A2 instrumentation would be indirect. Per-baseline
  directories per `research-plan.md` §16 — rejected (drift risk). Pre-deploying
  the account outside the measured operation — not done; recorded as fairness
  difference 1 in `docs/w1-baselines.md` §10.
- **Open questions for the user**: (a) allowlist vs. verifying-signature
  Paymaster for B2 — the allowlist publishes the sponsored account on chain
  before the operation, which will matter to D1; (b) whether preVerificationGas
  should be calibrated to cover the bundle overhead (the fixed 50,000
  under-compensates the bundler by ~18k gas per operation); (c) whether account
  deployment should be separated from the measured action.

## 2026-09-14: UserOperation gas limits calibrated before any reported result

- **Decision**: `verification_gas_limit` 300,000 and `call_gas_limit` 60,000
  for both B1 and B2 (initially 400,000 / 80,000).
- **Why**: calibration runs showed (i) with `callGasLimit` 80,000 EntryPoint
  v0.9.0 charged its 10% unused-execution-gas penalty (4,601 gas) in both B1
  and B2 — execution uses ~34k gas and the penalty applies once unused gas
  exceeds 40,000; (ii) B1 validation (deploy + signature + prefund payment)
  needs between 200,000 and 250,000 gas (fails `AA26` at 200,000), B2's fits
  within 200,000. 300,000 is one shared value with margin; 60,000 avoids the
  penalty. A live test asserts that lowering the call limit by 10,000 does not
  change `actualGasUsed`. The earlier runs with the old limits were deleted
  before any result was reported (they were this session's own output).
- **Alternatives considered**: per-baseline limits sized to each baseline's
  need — rejected: identical limits are part of the B1/B2 match.

## 2026-09-14: Schema 2.0.0 — corrections forced by the first real runs

- **Decision**: bump the recorder schema to `2.0.0` (MAJOR), with:
  `bundler_private.bundle_transaction_hash` replaced by
  `submitted_bundle_transaction_hash` + `bundle_submission_timestamp_utc`
  (a mined bundle hash is public; only the bundler's pre-inclusion association
  is A2); lowercase-only addresses; ERC-4337 field tier annotations A1 → A0 for
  included operations; additive `public_events.subject_account`, event type
  `entrypoint_deposit`, calldata classes `entrypoint_handle_ops` and
  `paymaster_policy`, rejection category `paymaster_validation_revert`; §3.5
  of the schema doc corrected (a `not_included` public row only when a public
  observer saw the operation); a validator bug fixed (fractional-second
  timestamps were rejected). Synthetic examples regenerated under 2.0.0 with
  their corrections annotated in `w1_fixtures.py`.
- **Why**: each item was contradicted by real B0/B1/B2 behaviour
  (`docs/w1-baselines.md` §14). No measured 1.0.0 data ever existed, so the bump
  strands nothing real; 1.0.0 is removed from `SUPPORTED_SCHEMA_VERSIONS`.
- **Alternatives considered**: keeping `bundle_transaction_hash` and only
  editing its description — rejected: that changes a field's meaning under the
  same name, which §9 forbids.

## 2026-09-14: The research boundary does not rely on the import hook

- **Decision**: documentation (`docs/experiment-schema.md` §8.2,
  `experiments/_boundary.py`, `experiments/README.md`) now states that the
  public/private separation rests on distinct data paths, distinct reader
  APIs, the frozen-predictions attack/evaluation process boundary, and
  validation/path guards. The `sys.meta_path` mutual-exclusion hook remains as
  defence in depth only. Code behaviour is unchanged.
- **Why**: the hook is trivially bypassable; presenting it as the primary
  mechanism overstated what is enforced. This refines, and does not reverse,
  the earlier entry "Public/private data separation is a process boundary, not
  a convention".

## 2026-09-14: Generated `data/public/` runs are gitignored by default

- **Decision**: `.gitignore` now ignores `data/public/**` except `.gitkeep`,
  `README.md` and the synthetic `data/public/baselines/*-example/` runs.
  Schema code and fixture generators under `experiments/` are unaffected.
  `make scaffold-test` checks both directions.
- **Why**: recorder output is regenerable from `data/raw/` plus the secret
  seed, like `data/raw/` and `results/`, and a measured run should be published
  only by an explicit reviewed decision after the leakage self-check. This
  revises the 2026-09-13 policy under which public observations were
  committable by default.
- **Existing data**: nothing was deleted by the policy change. The nine staged
  synthetic example files under `data/public/baselines/*-example/` remain
  committable and were regenerated in 2.0.0 form (their content changed). The
  measured runs under `data/public/baselines/b{0,1,2}-w1/` are ignored.

## 2026-09-14: Pre-Prompt-4 hardening — B2 split into B2-Signature (primary) and B2-Allowlist (auxiliary)

- **Decision**: keep `ObservablePaymaster` unchanged as **B2-Allowlist**, an
  auxiliary, intentionally public on-chain authorization baseline, and add
  **B2-Signature** (`SignatureVerifyingPaymaster`) as the primary ordinary
  Paymaster baseline. They get distinct `baseline_id`s and are never pooled.
  B2-Allowlist must not be the sole public-Paymaster baseline for a privacy
  claim.
- **Why**: B2-Allowlist's `setSponsored(account, true)` publishes an explicit
  sponsor→account relationship before the UserOperation, which may produce
  stronger linkage than ordinary Paymasters that authorize off chain; using it
  alone would bias any later B2-vs-B3/B4 comparison.
- **How B2-Signature avoids designing cryptography**: the pinned
  account-abstraction tree (b36a1ed, v0.9.0) contains no `VerifyingPaymaster`
  sample. v0.9.0 does define a Paymaster-signature suffix
  (`PAYMASTER_SIG_MAGIC`; `UserOperationLib.getPaymasterSignature` etc.) whose
  bytes the EntryPoint excludes from `userOpHash`. The sponsor therefore signs
  the EntryPoint's own EIP-712 `userOpHash` — the digest `SimpleAccount`
  already verifies — and signed Paymaster data carries `validUntil/validAfter`
  through upstream `_packValidationData`. What is bound, and how replay is
  prevented (EntryPoint nonce), is documented and tested in
  `docs/w1-baselines.md` §4. Human review of the binding is still required.
- **Alternatives considered**: porting the v0.6/v0.7 upstream
  `VerifyingPaymaster` (custom hash over selected fields + EIP-191 prefix) —
  rejected: it is not in the pinned tree and would duplicate, with a
  hand-picked field list, what the v0.9.0 `userOpHash` already binds.

## 2026-09-14: preVerificationGas is calibrated per operation; beneficiary pre-funded

- **Decision**: replace the fixed preVerificationGas (50,000) with
  `break_even_calibration_v1` (`experiments/workloads/w1/pvg.py`): a dry run of
  the exact encoded bundle inside a reverted `evm_snapshot` measures the gas
  the EntryPoint does not charge, decomposed as 21,000 + EIP-2028 calldata gas
  + EntryPoint unmeasured overhead, then solved for the final signed op.
  Pre-fund the EntryPoint beneficiary in setup. Reconciliation now fails if the
  bundler's net is worse than −100 gas × price.
- **Why**: the old value left the bundler ~17,800 gas short per op. Measuring
  it showed the shortfall was dominated by a 25,000-gas new-account charge on
  the unfunded beneficiary; with that removed, 50,000 over-paid by ~7,000 gas.
  Neither error is acceptable in a cost comparison. After calibration the
  bundler net is 0 gas for B1 cold/warm and B2-Allowlist and +12 gas for
  B2-Signature (deterministic re-signing rounding). The EntryPoint overhead O
  was 14,985 gas for every measured op.
- **Alternatives considered**: a fixed constant fitted to one run (rejected by
  instruction and because it hides the new-account artefact); an estimate
  from eth-infinitism bundler overhead constants (rejected: not verifiable
  offline for v0.9.0 and not derived from our encoded bundle). Limitation:
  snapshot dry runs are a devnet facility; a production bundler must estimate
  and add margin.

## 2026-09-14: W1-cold (primary) and W1-warm (ablation)

- **Decision**: the existing fresh-account workflow is **W1-cold**, the primary
  workload. **W1-warm** (implemented for B1) deploys the same SimpleAccount by
  an earlier sender-funded warm-up UserOperation (initCode, empty callData);
  warm-up cost is excluded from the measured action and reported separately;
  its public rows stay in the record (they are part of the trace T). B0 is not
  changed. B2 warm variants are optional and not implemented.
- **Why**: separate first-use deployment overhead (measured by difference:
  173,841 gas, with the nonce-first-write confound) from recurring execution.
- **Consequence found while implementing**: sending ETH to an already-deployed
  SimpleAccount cannot fit in 21,000 gas (payable `receive()` via the ERC-1967
  proxy); W1-warm funding uses a 60,000-gas limit (25,868 used). The runner now
  aborts if any non-measured workflow step reverts, instead of recording it.

## 2026-09-14: Schema 3.0.0 — split baseline and workload identifiers

- **Decision**: `baseline_id` `"B2"` → `"B2-Allowlist"`, `"B2-Signature"`;
  `workload_id` `"W1"` → `"W1-cold"`, `"W1-warm"`; new rule rejecting
  `W1-warm` for non-ERC-4337 baselines. MAJOR bump. The schema-2.0.0 measured
  runs were **moved** (not deleted) to `data/private/archive/schema-2.0.0/`;
  synthetic examples were regenerated (`b2-w1-example` replaced by
  `b2-allowlist-w1-example` and a new `b2-signature-w1-example`).
- **Why**: an existing value's meaning split in two; keeping `"B2"` or `"W1"`
  valid would allow exactly the pooling the split exists to prevent.

## 2026-09-14: No external bundler yet; the in-repo bundler is experimental

- **Decision**: do not integrate an external bundler now. Document everywhere
  results are produced that `privgas-minibundler-v1` is an instrumented
  experimental bundler that does not establish ERC-7562 or production
  compatibility. A real, independent compatible bundler is required before any
  D2 liveness claim, any production-compatibility claim, and to replicate D1
  results. Staking requirements are not inferred without testing.

## 2026-09-14: B3 reproduction doc corrected

- **Decision**: `docs/b3-reproduction.md` no longer says the EIP-170 regression
  test "fails by design". It passes when it confirms the frozen PoseidonT3
  runtime bytecode exceeds EIP-170; the separate ordinary-key broadcast
  experiment records the actual deployment failure. Documentation only; B3
  untouched.

## 2026-09-14: R1 refined — economic funding source is not the immediate gas payer

- **Decision**: R1 is **economic funding source ↔ operation**. The ground truth
  records separately (schema 4.0.0): `immediate_gas_payer_kind` +
  `public_anchors.immediate_gas_payer_address` (public context: B0 recipient
  EOA balance, B1 SimpleAccount EntryPoint deposit, B2 Paymaster EntryPoint
  deposit) and `economic_funding_source_id` +
  `public_anchors.economic_funding_address` (the hidden answer: the wallet that
  sent ETH to the B0 EOA, the wallet that funded the B1 account, the sponsor
  wallet that funded the B2 Paymaster's deposit). A validation rule rejects a
  sponsored row whose economic funder equals the Paymaster. `docs/threat-model.md`,
  `docs/research-questions.md` and a refinement note in `docs/research-plan.md`
  §6 state the definition.
- **Why**: schema 3.0.0 anchored B2's funding on the Paymaster contract, which
  is intentionally public and would make R1 trivially answerable and
  meaningless for sponsorship privacy. Collapsing an EOA, a smart account, a
  Paymaster contract and an economic actor into one "payer" hides exactly the
  distinction D1 measures.
- **Scope choice**: the funding source is defined one hop back (whoever
  directly funded the charged balance). Deeper provenance (e.g. the devnet
  faucet that funded the sponsor) is in the public trace, not the label.

## 2026-09-14: The complete public trace is recorded; cost window is private

- **Decision**: every mined transaction of a run — including setup (faucet
  funding, deployments, Paymaster deposits) and warm-up — is recorded in
  `public_events`, each row with a required `trace_phase`
  (`infrastructure`/`funding`/`authorization`/`application`/`settlement`) that
  the validator forces to be a deterministic function of the row's event type
  and calldata class. Whether a row is in the measured cost window is written
  only to `data/private/.../w1_cost_window.json`.
- **Why**: "setup" is a cost-accounting boundary, not a privacy boundary. The
  sponsor's Paymaster deposit is precisely the public evidence R1 concerns;
  hiding it would give attacks an artificially weak trace. A public cost-window
  flag, by contrast, would mark which transactions belong to the experiment — a
  label leak — so it stays private.
- **Also found and fixed**: raw chain dumps stored role-naming step labels
  (`w2_eth_allowance`, `setup_fund_sponsor_operator`) next to each transaction,
  although earlier docs called the dump role-free. Labels now live only in the
  private role file, and attacker-side readers refuse `data/raw/`.

## 2026-09-14: preVerificationGas calibration separated from experiment runs

- **Decision**: a calibration phase (`python3 -m experiments.workloads.w1.calibrate`,
  exact-bundle snapshot dry runs) measures the EntryPoint unmeasured overhead O
  per operation shape and writes a committable artifact
  (`baselines/w1_b0_b2/calibration/pvg-overhead.json`: O = 14,985 gas for
  `execute_call`, 13,708 for `empty_calldata`; 10 samples over 2 seeds, all
  equal within shape; environment fingerprint; seed commitments only).
  Experiment runs price PVG as 21,000 + calldata gas of the exact final bundle +
  O, never executing their own operation; the runner refuses to run
  (`RecalibrationRequired`) if the fingerprint changed. The dry-run mode stays
  available for calibration/diagnostics.
- **Why**: rediscovering O by executing each research sample under
  snapshot/revert is a devnet-only oracle that no real bundler has, and it ties
  every sample's pricing to a privileged execution. O is an environment
  property; measuring it once, reproducibly, is the defensible split.
- **Finding**: O depends on operation shape (a deploy-only op with empty
  callData has 1,277 gas less overhead), so the artifact is keyed by shape
  rather than holding one number. Also, the covering fixed point's ±12-gas
  signature-rounding surplus moved from B2-Signature (dry-run mode) to B1 warm
  (estimate mode) because the search starts from a different value.

## 2026-09-14: B2-Signature single-field mutation tests; configuration kept

- **Decision**: add Forge tests that isolate initCode/factory data (trailing
  byte keeps the sender), `maxFeePerGas`, `maxPriorityFeePerGas`,
  `verificationGasLimit`, `callGasLimit`, `paymasterVerificationGasLimit` and
  `paymasterPostOpGasLimit`: valid authorization → mutate one field → re-sign
  the account → `AA34`, each after an accepted control. The signature
  mechanism is unchanged. The 0/0 validity window is kept (a finite window
  would add a timing feature before D1). No B2 warm variants are added.

## 2026-09-15: The frozen B3 specimen is measured as `B3-PrivGas-v1` on a labelled evaluation profile

- **Decision**: make the unmodified PrivGas v1 contracts observable under W1 by
  running them on a separate local chain profile, `b3_compat_local` (anvil
  `--code-size-limit 32768`), labelled NON-PRODUCTION,
  NON-EIP-170-DEPLOYABLE-AS-BUILT, PRIVACY-EVALUATION-ONLY. The frozen sources
  are compiled read-only from `baselines/b3_eval` (executable bytecode equal to
  the submodule's own build) and deployed in the frozen fixture's order. The
  recorder baseline id is `B3-PrivGas-v1` (schema 5.0.0); it names the
  unmodified specimen at `02a3f0ab…`, and a changed protocol would need a new id.
  `docs/b3-evaluation.md`.
- **Why not "the smallest explicit fix"** (`docs/research-plan.md` §15 gate): any
  source fix — linking a pre-deployed canonical PoseidonT3, inlining, a smaller
  hash — would change what is measured or introduce an unverified dependency.
  D1 measures privacy traces, which do not depend on the code-size limit; the
  limit is raised only on a chain that is explicitly not a deployment target,
  and `docs/b3-reproduction.md`'s ordinary deployability finding stands and is
  re-checked live.
- **Matched comparisons**: every baseline run on the profile gets the identical
  setup, B3 contracts included, so B3 is not fingerprinted by chain
  configuration. Measured: B0/B1 cold/B1 warm/B2-Allowlist/B2-Signature have
  identical workflow transactions, UserOperation fields, calibrated overheads
  and cost summaries on both profiles (`compare.profile_effect`).
- **Not done, deliberately**: no staking API, no ERC-7562 claim, no production
  bundler claim, no Poseidon/Merkle/CreditPool change, no root history, no B4/B5,
  no attacks.

## 2026-09-15: B3 W1-cold workflow choices

- **Account deployment in Bootstrap via initCode.** The paper models a
  counterfactual account deployed on first use; `BootstrapPaymaster` does not
  inspect initCode. The Bootstrap operation therefore deploys the same
  counterfactual `SimpleAccount` B1/B2 use; B3's Spend operation (the W1
  application call, byte-identical to B1/B2) carries no initCode. Recorded as an
  unavoidable fairness difference.
- **Same public sender for Bootstrap and Spend.** The source lets any address
  spend, but in W1 the tokens and the Bootstrap eligibility sit at the announced
  account, so Spend comes from it. The equality is recorded as mined and not
  normalised.
- **Parameters from the frozen source**: vMin 0.01 ETH, F 0.021 ETH, scheme id 1,
  Spend Paymaster verification limit 400,000 (fixture value). From traces:
  Bootstrap call gas 160,000 (126k used; below the 40k unused-gas penalty
  threshold), Bootstrap Paymaster verification 60,000 (the shared W1 value; 27k
  used). `MockAnnouncer` is B3's own announcer. Ephemeral public key seed-derived;
  metadata empty (B3 implements no ERC-5564 derivation).
- **1 wei to `address(0)` in the compat setup**: otherwise B3's fee burn pays a
  devnet-only 25,000-gas new-account charge (measured 178,789 vs 153,789 gas).
- **Real proofs**: `@semaphore-protocol/core` 4.14.2 (the version B3's fixture
  scripts use), Semaphore artifacts 4.13.0 pinned by sha256; one deterministic
  witness from the secret seed; the proof is regenerated at each PVG fixed-point
  step because PVG changes `userOpHash`.

## 2026-09-15: preVerificationGas overhead is net of the execution refund; shapes keyed by call

- **Finding**: B3's Bootstrap operation calibrated to O = 19,776 gas against
  14,985 for every W1 application call. Transferring `amount − 1` instead of the
  whole balance raises B2-Signature's O to 19,785 — exactly the EIP-3529 4,800-gas
  SSTORE-clear refund the W1 transfer earns. O is therefore EntryPoint overhead
  net of the executed call's refund, not an EntryPoint constant.
- **Decision**: key the artifact by executed call: `execute_call` (W1 application
  call, including B3 Spend), `execute_pool_deposit` (B3 Bootstrap),
  `empty_calldata`. One artifact per evaluation profile; the profile id and
  code-size limit join the fingerprint. The standard artifact's values and
  dry-run gas are unchanged.

## 2026-09-15: Schema 5.0.0

- **Decision**: `baseline_id` `B3` → `B3-PrivGas-v1`; B3 public event types and
  calldata classes with deterministic trace phases; R2 public anchors
  (`issuance_transaction_hash`, `issuance_userop_hash`, `credit_commitment`,
  `credit_nullifier`) required for an observed R2 label and forbidden without a
  credit system; B3 records a Spend row (R2 observed) and a Bootstrap row (R2
  absent). `docs/experiment-schema.md` §9.0.
- **Data**: B0–B2 re-recorded with the same private seed; every transaction hash
  and cost summary value matched the 4.0.0 runs, which were then moved (not
  deleted) to `data/private/archive/schema-4.0.0/`.
- **Also found and fixed**: the profile dict used a bare `labels` key, which the
  recorder's public-output denylist rejects (caught by the leakage self-check);
  renamed `profile_labels`. The Semaphore proof encoding is 416 bytes (13 words),
  not 448.


## 2026-09-15: D1 pilot — multi-actor dataset design

- **Decision**: one run = one chain with N independent actors (N = 4, 8, 16, 32; 3
  replicates; B0, B1, B2-Signature, B3-PrivGas-v1 primary, B2-Allowlist auxiliary; S0 for
  every baseline, S1 additionally for B3), all on `b3_compat_local` with an identical setup.
  Per-actor identities are drawn from (secret seed, N, slot, kind) with no identifier derived
  from another; run seeds derive from a secret master seed file under `data/private/`, so
  baselines/scenarios at one (replicate, N) share actors (matched) and replicates / pool sizes
  never do. Block timestamps and the bundler's A2 clock are schedule time.
- **Why**: candidate sets > 1 require concurrency on one chain; matched actors isolate the
  gas mechanism; independent draws and simulated time keep the harness from encoding actor
  order or wall-clock artefacts (audited in every scoring run).
- **Alternatives considered**: one actor per chain with post-hoc pooling (no real candidate
  set, no shared root); wall-clock delays (would leak proof-generation time).

## 2026-09-15: D1 pilot — B3 single-final-root schedule and Bootstrap callGasLimit

- **Decision**: all Bootstraps before any Spend; every Spend proof against the one final root,
  verified off chain against every emitted intermediate root and both on-chain roots. The
  pilot's Bootstrap `callGasLimit` is 450,000 (fixed for every Bootstrap and N). No B3 source,
  root policy or verifier changed.
- **Why**: latest-root-only validation would otherwise make root contention a confound (a
  separate D2 question). Frozen `CreditPool.deposit` gas grows with the LeanIMT (measured
  143,327 → 400,442 gas as an EOA call for tree sizes 0 → 31); with the single-actor value
  160,000 every insertion after the first reverts inside execution after BootstrapPaymaster
  consumed the grant. 450,000 respects the frozen 0.005 ETH cap; the 10 % unused-gas penalty
  on shallow insertions is a cost effect. The b3-eval-config.json single-actor value is
  unchanged.
- **Verified**: a stale-root proof is rejected (`RootMismatch`) and Spends do not change the
  root (`experiments/workloads/d1/tests/test_live.py`).

## 2026-09-15: Semaphore artifacts for depths 2–5 pinned on first download

- **Decision**: `semaphore-{2..5}.wasm/zkey` (artifact version 4.13.0, the URLs the pinned
  library resolves) added to `artifacts-pin.json` with sha256 of the first download. The prover
  gained a `group_root` operation and refuses a proof depth different from the group depth.
- **Why**: groups of 4–32 members need depths 2–5. The host publishes no checksums; authenticity
  is established by proofs verifying on chain against the frozen `SemaphoreVerifier` key
  points of the same depth.

## 2026-09-15: Recorder completeness fix — ERC-20 recipient in `subject_account`

- **Decision**: W1 recorders now populate `public_events.subject_account` with the ERC-20
  recipient (transaction-level transfers, in-bundle Transfer logs, mint). Schema stays 5.0.0
  (the field's definition — the account an event is about that is neither sender nor target —
  already covers it; description text extended, docs regenerated). Earlier recordings are
  unchanged and lack the recipient.
- **Why**: found while building the D1 attacks: the recipient is public in calldata and logs,
  so omitting it gave attacks an artificially incomplete T trace (Prompt 4 §23).

## 2026-09-15: D1 feature registry and conventions

- **Decision**: one canonical registry (`experiments/privacy/d1/registry.py`,
  `docs/d1-feature-registry.md`) classifies every row-kind × field as T / AA / G by causal
  origin (row origin; counterfactual value among B1 / B2-Signature / B3 for the application
  op). Genuine ambiguities carry notes and an alternative `field_kind` convention (AA-shaped
  fields of the B3 Bootstrap op → AA; the B3 announcement → T); R2 is evaluated under both.
  `freeze_predictions` now accepts any T/AA/G combination with `-minus-<family>` ablation
  suffixes, plus an `attack_provenance` record.

## 2026-09-15: D1 learned attacks use profiling training labels, fold-scoped

- **Decision**: learned attacks (conditional logit, L2 by inner leave-one-replicate-out CV)
  train on binary pair labels of their fold's training runs only, exported by a separate
  `experiments.labels` process per frozen split; provenance digests are re-audited at scoring.
- **Why**: a held-out cross entropy requires a trained probabilistic model; a profiling
  attacker that can label its own simulated runs is the standard assumption. Test-run labels
  never reach the attack process. A fixed L2 = 1 was tried first on a scratch batch and
  produced below-chance held-out CE for timing-only S0 models (overfitting); the inner-CV
  selection replaced it before any pilot result was produced.

## 2026-09-15: B4-CrossAccount — a causal ablation of B3, not a protocol

- **Decision**: add baseline id `B4-CrossAccount` (schema 5.1.0, MINOR: one new enum
  member; 5.0.0 rows remain readable; a 5.0.0 row naming the new id is rejected). It runs
  the unmodified frozen B3 contracts, real Semaphore v4 / Groth16 proofs and every B3
  parameter on `b3_compat_local`; it differs from `B3-PrivGas-v1` only in the actor
  workflow. The reserved `B4` of `docs/research-plan.md` §5 / Prompt 6 (a new binding
  prototype) keeps its own id and is not implemented.
- **Verified first** (live, frozen contracts): `CreditPaymaster.validatePaymasterUserOp`
  checks maxCost, gas/fee caps, root, scope, `message == userOpHash`, nullifier and the
  Groth16 proof; it never reads `userOp.sender` except to emit `CreditSpent`.
  `CreditPool.deposit` requires only that `msg.sender` is eligible and has not deposited.
  A Spend from an account that was never announced, eligible or a depositor succeeds with
  a proof over its own userOpHash. No B3 change and no public handoff are needed.
- **Workflow choices** (each is the minimal change that removes the issuer↔spender
  coupling, recorded as a fairness difference):
  1. Two new independent identity kinds per actor: `issuer` (owner key of the issuer
     SimpleAccount) and `issuer_funder` (the wallet that pays the issuer's
     `announceAndFund`). Existing identity draws are unchanged (keyed by kind name).
  2. The spender is the account B3 would use (same recipient key), so B3 and B4 share the
     Spend sender, asset sender, delivery and Semaphore identity at one (replicate, N).
  3. The asset sender does NOT pay the admission (in B3 it does): otherwise one wallet
     would publicly fund both sides, a deterministic issuer↔spender edge. The faucet funds
     each issuer funder with the asset senders' ETH value in an independently permuted
     setup order (`orders["setup_issuer"]`, in both scenarios).
  4. The spender account was never deployed, so its Spend carries initCode (like B1/B2's
     application op); the Spend nonce is 0 (B3: 1). Constant within a run.
  5. The issuer account keeps the forwarded vMin (as B3's account does); it never holds
     the W1 asset.
  6. Schedules: identical streams and events to B3 (verified equal), so the comparison is
     paired.
  7. A run FAILS unless every per-actor and set-level separation check holds (keys,
     accounts, funders distinct; mined Bootstrap senders ≠ Spend senders; no transaction or
     token/ETH/announcement edge between the issuer side and the spender side; the issuer
     never held W1T; the spender never announced/eligible/deposited).
- **Alternatives considered**: asset sender funds the issuer's admission (rejected:
  trivial public funding edge); a separate deployment op for the spender (rejected: needs a
  gas payer, i.e. a new funding edge); an on-chain handoff (forbidden and unnecessary).

## 2026-09-15: B4 analysis pre-registration (written before the B4 dataset was recorded)

- **Matrix**: `experiments/workloads/d1/b4-config.json` — B3-PrivGas-v1 and
  B4-CrossAccount × S0/S1 × N ∈ {4, 8, 16, 32} × 3 replicates = 48 runs, same secret master
  seed as the pilot (so B3 is the pilot's B3 regenerated; integrity check: every
  non-Spend transaction hash and every Spend's sender, nonce, callData, root and nullifier
  equal the pilot's; Spend bundle bytes differ only through fresh Groth16 randomness).
- **Attacks**: every pilot rule and learned configuration, unchanged, applied to B4 (R3
  drops `r3_dir_vs_issuance_rank_g`, which is defined through spender == depositor). Added
  before any B4 dataset run, for B3 and B4 alike: exact rules
  `r2-announcer-eq-asset-sender`, `r2-shared-eth-funder`, `r2-shared-identifier-scan`
  (Prompt §15 examples; merkle_root excluded from the scan because root equality is its own
  rule), and learned selections `G-minus-eq-minus-timing` and
  `T+AA+G-minus-eq-minus-timing` (R2 timing features are family G, so `G-minus-eq` alone
  cannot isolate gas/proof metadata). A scratch end-to-end run (different seed, N = 4/8,
  2 replicates) was used only to debug the pipeline; nothing was tuned on it.
- **Operational criteria for the decision rule** (pooled over N, leave-one-replicate-out,
  primary convention):
  - *near chance (S0)*: the best exact rule's top-1 CI contains chance, and
    delta_bits(none → T+AA+G-minus-eq) has a CI containing 0 or a point estimate below
    0.1 × mean log2 N;
  - *meaningfully linkable through timing (S1)*: delta_bits(none → T+G-minus-eq) CI
    excludes 0 and its point estimate is ≥ 0.25 × mean log2 N, or a timing rule's top-1 CI
    lies above chance by ≥ 0.1;
  - *another public feature (Case B)*: any exact rule with precision CI above chance and
    coverage > 0.1 in B4 S0, or `T+AA+G-minus-eq-minus-timing` / `G-minus-eq-minus-timing`
    with delta_bits CI excluding 0 in B4 S0.

## 2026-09-15: Final D1 timing sanity experiment — S1b (pre-registration, before the dataset)

- **Why**: the B4 ablation found that S1 drives delivery, admission, issuance and action
  from one arrival order; in B4, rank-matching spender delivery with issuer admission
  recovers 100% of pairs, so S1 cannot isolate issuance → redemption timing.
- **Decision**: scenario `S1b-issuance-redemption-timing-only`
  (`experiments/workloads/d1/schedule.py`, `s1b-config.json`). Issuance timing and
  redemption timing use exactly S1's model and parameters (issuance at arrival A_k,
  exponential inter-arrivals with mean 600 s; action at A_k + common offset + U(−900, +900) s).
  Asset-sender setup, issuer-funder setup, delivery, admission and proof preparation each
  get an independent permutation; delivery and admission are sequential phases with
  independent exponential gaps (mean 600 s) before the issuances. Account creation cannot
  be separated: the issuer account is deployed by its Bootstrap and the B4 spender by its
  Spend, so both follow the correlated channels by construction. S1b is defined for B3 and
  B4 only; B3 and B4 schedules are identical at one seed.
- **Gates**: (1) the runner fails a run before any workflow transaction if any unintended
  pair of orders is identical; (2) `evaluate schedule-gate` must pass before splits and
  attacks. Scoring refuses an S1b batch without a passing gate. The gate pools public-derived
  orders per (baseline, pair) and rejects on |z| > 3.29 for rank-match recovery or Spearman,
  or on any identical pair, for every pair except issuance~redemption. Positive control: on
  the B4 batch's S1 runs the gate rejects (delivery~fund identical in 12/12 B4 runs).
- **Matrix**: B3 and B4 × S1b × N ∈ {8, 16, 32} × 3 replicates = 18 runs, pilot master seed
  (same actors as the earlier batches; independent S1b schedule streams).
- **Attacks**: every registered rule and learned configuration, unchanged (none added).
- **Criteria** (pooled over N, LORO, primary convention): *B4 meaningfully linkable* =
  delta_bits(none → T+G-minus-eq) CI excludes 0 and point estimate ≥ 0.25 × mean log2 N,
  or FIFO / delay-window top-1 CI above chance by ≥ 0.1. *Falls to chance* = that delta_bits
  CI contains 0 or its estimate < 0.1 × mean log2 N, and every timing rule's top-1 CI
  contains chance. *Negative control holds* = G-minus-eq-minus-timing delta_bits CI contains 0.
- **Stated expectation (HYPOTHESIS, recorded before data)**: the registered timing attacks
  read only issuance / redemption order and time, which S1b keeps with S1's model, so S1b
  should reproduce S1's registered-attack linkage within sampling error.

## 2026-09-15: D1 falsification phase closed; D2 is the primary direction

- **Decision**: D1 (privacy limits of stealth-account gas sponsorship) is closed as the primary
  research direction. Its models, attacks, datasets and docs (`docs/d1-*.md`,
  `experiments/privacy/d1`, `experiments/workloads/d1`) are frozen; they are changed only for
  API compatibility and rerun only as regression tests. D2 (validation-state contention and
  liveness) becomes the primary direction, starting with a falsification pilot of the frozen
  B3 specimen (`docs/d2-pilot-results.md`).
- **Why**: the completed D1 experiments met the D1 kill condition (`docs/d1-s1b-results.md`):
  B3's deterministic linkage is same-account Bootstrap/Spend; cross-account redemption removes
  it (clean linkage at chance); correlated issuance→redemption timing stays linkable; no
  ERC-4337-, Paymaster-, gas- or proof-specific feature added measurable linkage.
- **Alternatives considered**: D3 (private actual-cost settlement) — deferred; D2 is the
  fallback whose question the existing harness can already test on the unmodified specimen.

## 2026-09-15: D2 pilot design (recorded before the stochastic / policy / adversary data)

- **No B3 change.** Frozen contracts via the unchanged W1 setup on `b3_compat_local`; no root
  history, epochs, reservations, locking, Paymaster or Semaphore change. Bundler policies P1/P2
  are experimental bundler behaviour, not protocol defenses.
- **Two phenomena, separate code paths and tables.** D2-A root contention
  (`experiments/liveness/d2/{harness,engine,exp_a}.py`) and D2-B Bootstrap gas scaling
  (`exp_b.py`).
- **Staged bundler.** `StagedBundler` splits the W1 bundler's atomic simulate+submit so a
  Bootstrap can land between simulation and inclusion; same simulation method, fee pinning,
  beneficiary and EOA. Bundles may contain several ops; bundle gas = Σ op limits + 100,000 per op.
- **Virtual clock, real chain.** Stage durations (T_prove, T_submit, T_sim, T_queue, T_chain) are
  controlled virtual seconds; root-changing arrivals are real frozen-B3 Bootstraps executed at
  their virtual position (arrivals before a checkpoint are mined before its chain action;
  arrivals in (t7, t8) are mined before the bundle — a modelling assumption). Poisson arrivals
  seeded per trial index, shared across P0/P1/P2 (paired). Only the `measured` experiment lets
  real proof time drive the clock.
- **Trial isolation by `evm_snapshot`/`evm_revert`**; snapshots never price anything.
- **Proof reuse.** Identical proof inputs (identity, member list, userOpHash, depth) reuse the
  first real proof within one chain; the attempt carries that proof's measured time and
  `proof_cache_hit`. A real client would generate one proof per attempt; "proofs per success"
  counts attempts, not cache misses.
- **Spend preVerificationGas** priced once with an all-non-zero 416-byte placeholder proof (covers
  every real proof's calldata; surplus recorded) so the userOpHash — which excludes the proof —
  is fixed before proving; every retry proves over the same hash and the account signature is
  unchanged (checked on every attempt).
- **Bootstrap callGasLimit.** D2-A uses an experimental 1,000,000 for every Bootstrap (initial
  pools, contenders, adversary); the frozen 160,000 (`b3-eval-config.json`, unchanged) cannot
  build a tree beyond one member (measured in D2-B). D2-B measures the frozen value at every
  tree size and separately uses an experimental 1,500,000 to keep growing the tree. Neither
  experimental value is reported as the frozen baseline or as a fix; both respect
  BootstrapPaymaster's 0.005 ETH cap at the W1 fee (tested).
- **D2 setup top-ups** (not B3): the faucet funds the bundler and sponsor operator with 50 ETH and
  each B3 Paymaster deposit gets +20 ETH via `EntryPoint.depositTo`, because one chain sponsors
  hundreds of operations.
- **Records.** D2 attempts are not written into the linkage recorder's streams (no hidden
  relation, no labels). Every D2 field has a tier in `experiments/liveness/d2/records.py`
  (control / client_private / A2 / A0 / derived); unclassified fields are refused. Attempt
  records (with client-private proof timing) go to `data/private/d2-pilot/`; aggregates to
  `results/d2-pilot/`. D2 seeds are recorded in the clear (no linkage labels exist).
- **Semaphore artifacts depths 6–7** pinned by first-download sha256 (same precedent as depths
  2–5); a depth-6 proof verifies on chain against the frozen `SemaphoreVerifier`
  (`experiments/liveness/d2/tests/test_live.py`).
- **Adversary.** Only an A2 observer exists in this harness (no public mempool): the adversary is
  the bundler operator or a party fed its simulation results, depositing 0.05 s after a
  simulation acceptance, with honest λ = 0. No A0/A1 targeted schedule is modelled because no
  A0/A1 observer can see a pending Spend here.
- **Stop conditions checked in code**: proof root ≠ recorded root (raises); classification
  inconsistent with the root timeline (`consistent = False`, counted); included Spend without
  nonce advance or failed Spend with nonce advance (raises); capacity exhaustion recorded as
  `HARNESS_CAPACITY_EXCEEDED`, never truncated.

## 2026-09-16: D2 falsification pilot CLOSED; kill-condition phase opened in a new namespace

- **Decision**: the D2 falsification pilot (`docs/d2-pilot-results.md`, batch `20260915T223607Z`,
  code `experiments/liveness/d2/`) is **closed**. Its measurements are frozen: no number in that
  document is regenerated, recomputed or re-derived by any later phase, and its tables are never
  rewritten with changed semantics. The pilot's code is changed only for API compatibility and is
  rerun only as a regression test.
- **Every new experiment uses a new result namespace**: `d2-killcondition`
  (`results/d2-killcondition/<batch>/`, `data/private/d2-killcondition/<batch>/`,
  `figures/d2-killcondition/<batch>/`, code `experiments/liveness/d2k/`,
  doc `docs/d2-killcondition-results.md`). The pilot's `d2-pilot` directories are never written by
  it. The pilot's harness, contention engine, state machine, records tiers and D2-B measurement
  helpers are **imported unchanged** rather than copied or rewritten.
- **Why**: the pilot answered its own question (D2 case D) but explicitly did not test the D2 kill
  condition in `docs/research-plan.md` §3 — whether ordinary bounded root history removes the
  contention problem at realistic load with no significant tradeoff — and did not decompose the
  D2-B gas growth. Those are the two questions of this phase.
- **Alternatives considered**: extending the pilot batch in place (rejected: it would mix frozen
  and new semantics in one table); re-running the pilot on this machine (rejected: unnecessary,
  and it would overwrite reported numbers).

## 2026-09-16: preVerificationGas recalibrated for a new machine; overheads unchanged

- **Decision**: `baselines/w1_b0_b2/calibration/pvg-overhead.json` and
  `pvg-overhead.b3_compat_local.json` were regenerated on the Linux machine that runs this phase.
  The previous artifacts are kept verbatim in `baselines/w1_b0_b2/calibration/archive/` under their
  creation stamp and machine.
- **Why**: the calibration artifact is fingerprinted to the environment, and two fingerprint fields
  changed on this machine (`anvil_version` build string — same commit SHA — and the `SimpleAccount`
  artifact digest). `RecalibrationRequired` therefore blocked every live run. The dependency-tree
  pins (`baselines/w1_b0_b2/dependency-pin.json`) still pass, so the compiled sources are identical.
- **What did NOT change**: the measured EntryPoint unmeasured overheads are **identical** to the
  archived ones — `empty_calldata` 13,708, `execute_call` 14,985, `execute_pool_deposit` 19,776 —
  so no previously reported number depends on the recalibration. Recalibration was required to run,
  not to change a measurement.

## 2026-09-16: D2 kill-condition design and pre-registration (recorded before the final matrix)

Pre-registered before `make d2k-run` produced the reported batch. Everything here is a *design*
decision or a *threshold*; no result informed any of it except where explicitly stated.

- **No B3 change.** `baselines/b3_privgas_v1` and `baselines/b3_eval` are untouched. The
  experimental root-acceptance component is reached only through the frozen `CreditPool`'s own
  constructor argument (`constructor(address _creditPaymaster, address _registry)`), so a D2K
  environment is a second, complete, UNMODIFIED frozen deployment (`CreditPool`,
  `BootstrapPaymaster`, `AnnouncementRegistry`) whose single difference is the address the pool
  mirrors roots to. CreditPool semantics, the Bootstrap flow, the Semaphore verifier, proof message
  binding, nullifier handling, the EntryPoint, the account implementation, Paymaster sponsorship
  semantics and the W1 application call are all unchanged. No epoch roots, reservations, locking,
  Semaphore redesign, production bundler or staking.
- **D2-History-K** (`contracts/d2k/src/HistoryCreditPaymaster.sol`) is an EXPERIMENTAL variant, not
  a proposed protocol. Its only intended semantic difference from the frozen `CreditPaymaster` is
  step 3 of validation: accept the current root **and the previous K−1 roots** instead of the
  current root only. Retention is a **K-slot ring buffer** with a refcount map and a write cursor:
  a root enters on `mirrorRoot`, leaves when the slot it occupies is overwritten (the K-th update
  after it), the current root counts toward K, lookup is one own-storage `SLOAD` (O(1) in K),
  update is a fixed five-slot touch (O(1) in K), and the steady-state footprint is 2K + 1 non-zero
  slots. Duplicate roots are refcounted, so retention never depends on eviction order. Root 0 is the
  empty-slot sentinel and is never accepted. **K = 1 must reproduce frozen latest-root behaviour**;
  that is a stop condition and is measured on the same chain, in the same trials, against the same
  roots as the frozen contract itself.
- **Append-only precondition, checked before interpreting old roots as safe.** `CreditPool` uses
  `InternalLeanIMT._insert` only (never `_update` or `_remove`) and only ever sets `_eligible` /
  `_used` to true; `AnnouncementRegistry.eligible` is likewise write-once-true. There is no
  revocation or deletion path, so an older root is a prefix of later membership. Independently, the
  nullifier scope is the CONSTANT `CREDIT_NULLIFIER_SCOPE`, so one credit yields the same nullifier
  whichever retained root it proves against and an old root cannot enable a second spend. Both are
  re-established experimentally (security invariants) rather than assumed.
- **Paired comparison via a fan-out mirror.** A frozen `CreditPool` mirrors to exactly one
  immutable address, so the contention experiments deploy `FanOutRootMirror` as that address and
  fan out to the frozen `CreditPaymaster` plus one `HistoryCreditPaymaster` per K. Every variant
  therefore sees the same deposits, the same roots and the same block order. The fan-out inflates
  the Bootstrap's own gas, so **no gas, storage, code-size or overhead number is ever taken from a
  fan-out deployment**: every §11 number comes from a DEDICATED deployment (one frozen CreditPool →
  one Paymaster), exactly as B3 deploys.
- **Bootstrap `callGasLimit` for the contention experiments is raised to 1,200,000** (override
  recorded in `experiments/liveness/d2k/config.json` with its reason) because of the fan-out. Like
  the pilot's 1,000,000 it is a wallet-side experimental parameter, never the frozen 160,000 and
  never a proposed fix; it respects `BootstrapPaymaster`'s frozen 0.005 ETH cap at the W1 fee.
- **Retention-aware engine reuse.** The frozen contention engine is reused; `HistoryTrial`
  overrides exactly one method, `_root_changes_between`, so that only the K-th and later root
  changes after the proof count as invalidating. Every call site in the frozen engine passes
  `lo = t0`, which a static test pins. `capacity = 1` makes the override the identity.
- **Analytical baseline.** Under Poisson root updates with μ = λ·T,
  `P(valid | K) = Σ_{j<K} e^{−μ} μ^j / j!`, so `P(stale | K) = 1 − P(valid | K)`, reducing to
  `1 − e^{−μ}` at K = 1. Every attempt record carries the model's prediction and whether the chain
  agreed; **a single disagreement is a stop condition** (`check_model_agreement`).
- **Pre-registered kill-condition thresholds** (`config.json → d2k.preregistered_thresholds`).
  A capacity K "removes practical contention at negligible cost" iff all four hold:
  1. stale-root failure: Wilson 95% upper bound **< 1 %**, pooled over all cells with
     0 < λ·T ≤ 1;
  2. Spend-validation overhead **< 5 %** of the frozen UserOperation's `actualGasUsed`;
  3. root-update overhead **< 10 %** of the frozen Bootstrap UserOperation's `actualGasUsed`,
     worst case over tested tree sizes (the `CreditPool.deposit`-frame fraction, always larger, is
     reported beside it);
  4. steady-state root-history storage **≤ 128 slots**.
  *Refinement, stated plainly:* the four percentages were fixed before any D2K run. Their
  **denominators** were made explicit after a reduced smoke run (one seed, K ∈ {1, 4, 32}, tree
  sizes ≤ 15) showed that "overhead < x %" is ambiguous without one — a root-update delta of about
  +33 k gas is ≈ 37 % of the deposit frame at tree size 0 and ≈ 6 % at size 255. No percentage was
  changed, and the smallest-K answer is computed from the recorded batch, not from the smoke run.
- **Decision rule, pre-registered.** CASE A (root history trivially solves D2-A) if a small bounded
  K meets all four thresholds; CASE B if meaningful residual failures or meaningful
  validation/storage/update cost remain; CASE C (D2-B is mostly a B3 parameter bug) if the
  decomposition shows little fundamental scaling beyond a bad frozen limit; CASE D (D2-B is
  structural) if Merkle insertion intrinsically scales against a fixed sponsorship budget.
  Combined classifications (A+D, B+D, A+C, B+C) are allowed.
- **Gas-decomposition architecture.** G0 = the frozen `CreditPool.deposit` frame inside a real
  sponsored Bootstrap UserOperation (the pilot's own quantity, measured the same way); G1 = the
  LeanIMT insertion alone, using the SAME `InternalLeanIMT` and the SAME deployed `PoseidonT3`, at
  the same storage slots; G2 = publishing a changing root into a Paymaster-like contract with no
  Merkle work; G3a/G3b = `CreditPool.deposit`'s surrounding logic with the insertion replaced,
  without and with the tree's size/leaf bookkeeping; G4 = the external-call floor; G5 = one
  `PoseidonT3.hash` delegatecall. Every G-series number is a CALL sub-frame, so no intrinsic-gas or
  calldata accounting enters a comparison. **Benchmark-only simplification:** the benchmark pool's
  registry address is an EOA, so eligibility can be granted without 256 announcements; both frozen
  contracts take the registry as a constructor argument, so neither their code nor their eligibility
  rule changes, and the announcement path is measured separately on the ordinary frozen deployment.
- **Stop conditions checked in code**: frozen-CreditPool semantics needed for historical roots
  (none: only a constructor argument); revoked/invalid membership reachable from an old root
  (append-only, plus the security invariants); nullifier protection weakened (nullifier-reuse and
  same-credit-twice invariants); K = 1 not reproducing frozen behaviour (measured side by side);
  analytical K model inconsistent with the implementation (`check_model_agreement`, raises); the
  benchmark using a different Merkle primitive (the LeanIMT bench root must equal the frozen pool's
  root after the same insertions, checked); the decomposition failing to reproduce frozen behaviour
  (G0 at each size must match the pilot's frozen curve); failed-grant behaviour not reproducing.
- **Limitation recorded now, not after the fact**: this phase isolates protocol-state behaviour. No
  ERC-7562 bundler, no staking, no public mempool, one bundler (ours), one chain configuration. If
  bounded history survives the kill condition, production-bundler and staking compatibility are the
  NEXT phase, and nothing here establishes them.

## 2026-09-16: D2 kill-condition outcome — D2-A meets its kill condition; D2-B is C + D

Recorded after the reported batch `20260916T055452Z`
(`docs/d2-killcondition-results.md`). The classification rule was pre-registered above.

- **D2-A — CASE A.** Bounded root history trivially solves it. The retention boundary is exact on
  chain (a proof survives K − 1 root updates; 150/150 deterministic runs agreed with the model, and
  0 of 7,000 stochastic attempts disagreed), K = 1 reproduces the frozen contract in every cell of
  every experiment, and all eleven security invariants hold with real Groth16 proofs. **The smallest
  K meeting every pre-registered threshold is K = 8**: 0/520 stale failures for 0 < λ·T ≤ 1 (Wilson
  upper 0.73 %), +114 gas per Spend validation (+0.031 % of `actualGasUsed`, independent of K),
  +32,630 gas per root update (≈ 8.3 % of a Bootstrap, worst tested size), 17 storage slots,
  +1,196 bytes of runtime code, +258,337 gas of deployment. K = 4 misses only on the interval upper
  bound (0.58 % point estimate, CI upper 1.68 %). **D2-A alone is engineering, not research**, and
  must not be the main contribution of a paper.
- **D2-B — CASE C + D.** C: the frozen 160,000 `callGasLimit` covers exactly one insertion into an
  empty tree and the decomposition finds no B3-specific overhead beyond a flat 35,772 gas, so the
  immediate symptom is a parameter bug. D: what remains is intrinsic — `LeanIMT._insert` costs one
  61,337-gas `PoseidonT3.hash` delegatecall per set bit of the insertion index, and `deposit` gas is
  that plus a constant to within a median 119 gas — running against a **fixed wei** sponsorship
  budget, so the maximum sponsorable gas price falls as the pool grows (8.8 gwei at tree size 0,
  5.0 gwei at 256 members, against an advertised 10 gwei cap that is unreachable everywhere).
- **Refinement of a pilot claim.** The pilot called a failed Bootstrap's loss "non-recoverable". The
  *sponsored grant* is indeed permanently consumed (`AA34 signature error` on a correctly nonced
  retry) and the sponsor is charged 0.00061–0.00084 ETH, but the **credit is recoverable**: an
  unsponsored UserOperation from the same account inserts the commitment for ≈ 0.0008 ETH out of the
  vMin the registry already forwarded, with no externally funded EOA. The frozen
  `BootstrapPaymaster`'s own source comment was correct. The pilot's number is unchanged; this is a
  new measurement in a new batch, not a rewrite.
- **No stop condition fired.** Historical-root acceptance needed no change to frozen `CreditPool`
  semantics (only a constructor argument); membership is append-only so no old root can carry a
  revoked state; nullifier protection is intact (same-credit-twice is rejected even against a
  different retained root); K = 1 reproduced frozen behaviour; the analytical model never disagreed
  with the implementation; the benchmark reproduced the frozen pool's root and its exact deposit
  gas (121,763 at size 0, 562,428 at size 255 — the pilot's own figures) at both seeds; the
  failed-grant behaviour reproduced 15/15.
- **Consequence for the project.** Neither half of D2 carries a paper on its own. D2-A is closed as
  a candidate contribution. D2-B retains one quantified systems boundary — privacy-state maintenance
  scaling logarithmically against a fixed per-credit sponsorship budget — which is a finding, not a
  direction. No next direction is chosen in this entry.
