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
