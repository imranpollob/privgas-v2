# PrivGas v2 — First AI-Coder Prompts v1

Use these prompts sequentially. Do not ask the coder to implement a novel cryptographic protocol yet.

## Prompt 0 — Repository scaffold and reproducibility contract

You are setting up a security-research repository named `privgas-v2`.

Create:

```text
docs/
baselines/
contracts/
circuits/
test/
scripts/
experiments/workloads/
experiments/privacy/
experiments/liveness/
experiments/settlement/
experiments/analysis/
data/raw/
data/public/
data/private/
results/
figures/
paper/
```

Create `README.md`, `docs/research-questions.md`, `docs/threat-model.md`, `docs/baseline-spec.md`, `docs/experiment-schema.md`, `docs/decision-log.md`, `.gitignore`, a `Makefile` or equivalent task runner, and `scripts/env-report.sh`.

Requirements:

1. `data/private/` must be gitignored.
2. Record exact tool versions.
3. Add commands for install, test, benchmark, run-local-experiment, clean, and env-report.
4. Do not add application logic yet.
5. Do not invent protocol claims.
6. Explain that every result must be traceable to git commit, experiment ID, seed, chain ID, EntryPoint version, and compiler/tool versions.

Acceptance criteria:
- clean setup from a fresh clone,
- one command prints the environment/version report,
- private data cannot be committed accidentally,
- placeholder docs explain their intended role.

---

## Prompt 1 — Import and freeze PrivGas v1 as B3

Goal: create an immutable evaluation baseline for the accepted PrivGas implementation.

Instructions:

1. Import or reference the exact PrivGas v1 repository commit as `baselines/b3_privgas_v1`.
2. Do not silently modify source behavior.
3. Record source repository URL, exact commit hash, Solidity version, Foundry version, EntryPoint dependency/version, Semaphore dependency/version, and circuit/proving artifacts.
4. Add `scripts/run_b3_original.sh` to reproduce the existing test suite and emit machine-readable output.
5. Generate `results/b3/reproduction.json` with passed/failed tests, duration, environment metadata, and commit hashes.
6. Attempt deployment using ordinary authorized keys only. Do not use test impersonation such as `vm.prank(address(paymaster))` to claim deployability.
7. If ordinary deployment fails, create a failing integration test and document the exact reason. Do not repair it in the baseline branch.
8. Output `docs/b3-reproduction.md`.

Do not make novelty or security claims.

Acceptance criteria:
- existing tests reproduce or failures are documented,
- original code remains hash-identical where possible,
- ordinary-key deployment status is explicitly known,
- no deployment success is inferred from impersonated local tests.

---

## Prompt 2 — Implement matched B0, B1, B2 baselines

Goal: implement three matched baselines that perform the same ERC-20 application action.

Canonical workload W1:

1. A sender transfers an ERC-20 token to a fresh recipient-controlled account.
2. The recipient account transfers the token to a fixed destination.
3. The difference between B0/B1/B2 should be the gas mechanism and account type, not the application action.

Implement:

### B0
Sender funds a fresh EOA with the ERC-20 asset and sufficient ETH for the later token transfer.

### B1
Use the same ERC-4337 smart-account implementation intended for the research baselines. Sender funds the fresh smart account with the ERC-20 asset and sufficient ETH/native balance. No Paymaster.

### B2
Same smart-account code and same ERC-20 action as B1. Use a simple observable Paymaster with no privacy mechanism.

Fairness requirements:
- same token contract,
- same destination,
- same transfer amount,
- same chain,
- same fee policy where technically possible,
- same account bytecode for B1/B2,
- same bundler for B1/B2.

Record separately:
- ETH initially supplied,
- ETH retained after action,
- actual gas cost,
- sponsor cost,
- sender cost,
- user cost.

Do not aggregate these into one vague “cost.”

Add Foundry integration tests and one experiment runner per baseline.

Acceptance criteria:
- all three complete W1,
- emitted event records follow `docs/experiment-schema.md`,
- repeated runs are deterministic under a provided seed where possible,
- cost accounting reconciles to balances before/after the experiment.

---

## Prompt 3 — Build the versioned experiment recorder

Goal: separate private ground truth from attacker-visible observations.

Implement three JSONL streams:

1. `ground_truth.jsonl`
2. `public_events.jsonl`
3. `bundler_private.jsonl`

`ground_truth.jsonl` must contain at least:
- experiment_id
- seed
- actor_id
- established_wallet_id
- funding_wallet_id
- asset_sender_id
- stealth_account_id
- credit_id
- issuance_id
- scenario_id
- relation labels

`public_events.jsonl` must contain only fields recoverable by the declared public observer, including:
- tx hash
- userOp hash
- block/timestamp
- sender
- paymaster
- target
- method selector or public call class
- nonce
- fee fields
- gas limits
- actual gas
- event type
- public root/commitment/nullifier fields
- outcome

`bundler_private.jsonl` is only for an instrumented bundler and may include:
- receive timestamp
- simulation result
- rejection category
- replacement lineage
- inclusion timestamp
- bundler identifier

Research constraints:
- attack scripts must never load `ground_truth.jsonl` as input features,
- labels may be joined only inside evaluation code after predictions are frozen,
- private data directory must remain gitignored,
- schema version must be included in each row,
- every row must carry experiment_id and software commit.

Add schema validation tests.

Acceptance criteria:
- malformed records fail validation,
- attack code cannot import the private-data helper module,
- public records can be regenerated from raw chain/bundler logs,
- relation labels are unavailable to feature-generation code.

---

## Prompt 4 — D1 attack ladder: simple models first

Goal: build the initial privacy-measurement pipeline without GNNs.

Use only controlled experiment data.

Implement separate attacks:

### A. Exact/equality rules
- account equality
- direct funding edge
- obvious issuance/account reuse

### B. Timing/candidate filtering
- issuance-to-use delay
- block distance
- root age
- candidate pool occupancy

### C. Gas/fee model
- maxFeePerGas
- maxPriorityFeePerGas
- verificationGasLimit
- callGasLimit
- preVerificationGas
- actual gas
- replacement count if available

### D. Application-only model T
- target
- method selector/call class
- asset class
- amount bucket if public
- transaction-neighborhood summary

### E. Combined model T+G

Evaluation rules:

1. Split by actor/account, not random rows.
2. Add a separate time-based holdout.
3. Report top-1, top-k, precision/coverage, AUROC/AUPRC where appropriate, calibration/Brier, and cross-entropy/log-loss.
4. Compute incremental predictive information operationally as:

   `delta_bits = (CE_T - CE_TplusG) / ln(2)`

5. Bootstrap confidence intervals across actors or experiment groups.
6. Do not claim mutual information is exactly measured unless an estimator and assumptions justify that statement.
7. Produce ablations for T only, G only, T+G.

Do not implement a GNN unless these baselines leave a clear unresolved structural signal.

Acceptance criteria:
- no label leakage,
- actor-disjoint test set,
- reproducible seeds,
- one command regenerates tables/figures,
- negative or near-zero results are preserved rather than filtered out.

---

## Prompt 5 — Reproduce and quantify latest-root contention

Goal: test whether B3's accepted-root policy creates meaningful liveness loss.

First inspect B3 and confirm the semantics from code. Do not assume the diagnosis is correct.

If it is latest-root-only, create workloads with:
- deposit arrival rate λ,
- proof-generation delay,
- proof-to-submission delay,
- bundler delay,
- concurrent deposits,
- concurrent redemptions.

Measure:
- proof invalidation rate,
- reproof count,
- validation rejection reason,
- end-to-end completion latency,
- gas spent on completed actions,
- gas spent on failed attempts if applicable.

Compare:
1. original latest-root policy,
2. bounded historical-root ring buffer,
3. epoch/snapshot-root policy.

Preserve each implementation in a separate branch or configuration.

Include an analytical sanity check:

`P(no intervening deposit during T) = exp(-λT)`

for a Poisson arrival model.

Do not treat agreement with this toy model as the research contribution.

Acceptance criteria:
- deterministic synthetic workload generator,
- bursty/non-Poisson workload too,
- adversarial deposit-burst scenario,
- plots of invalidation/reproof vs λ and proof delay,
- explicit determination whether simple root history solves the practical issue.

---

## Prompt 6 — Minimal B4 independently issued credit prototype

Goal: test one hypothesis only:

> Does removing stealth-account-linked issuance materially reduce issuance-to-redemption linkage?

Do not design a new e-cash system.

Use existing established proof/membership machinery where possible.

Requirements:

1. A funding/issuance action inserts or creates an authorization commitment without using the later stealth account as the public issuer.
2. The later ERC-4337 operation redeems one authorization using a ZK membership proof/nullifier.
3. Bind redemption to the intended UserOperation domain, including chain ID, EntryPoint, Paymaster, sender, nonce, and canonical operation semantics for the pinned EntryPoint version.
4. Prevent replay.
5. Do not add private balances, refunds, change, or multi-use credits.
6. Treat this as B4 experimental baseline, not final novelty.

Add tests:
- valid redemption
- wrong sender
- wrong chain/domain
- wrong operation
- replay
- stale/invalid root
- two candidate issuances
- cross-account redemption if the design permits it

Acceptance criteria:
- all invariants are explicit,
- no novel cryptographic primitive is introduced,
- B4 runs through the same W1 harness as B1–B3,
- D1 attack pipeline compares B3 vs B4 directly.

---

## Prompt 7 — D3 accounting model only, no circuits

Goal: determine whether private actual-cost settlement is worth pursuing.

Implement a pure state-machine/reference model with:
- issued credit q
- reservation r
- actual charge c
- failure charge cf
- returned change q'
- reservation expiry
- concurrent spends
- double-spend attempts

Required properties:
1. conservation,
2. no overspend,
3. failed execution cannot generate value,
4. failed execution cannot create unlimited free retries,
5. concurrent reservations cannot exceed available value,
6. cancellation/expiry cannot duplicate value.

Use property-based testing/fuzzing.

Generate adversarial interleavings:
- reserve A, reserve B, settle A, fail B
- reserve A, expire A, late settle A
- duplicate settlement
- replacement operation
- partial charge
- sponsor insolvency boundary

Do not implement a ZK circuit or smart contract until this model passes.

Output `docs/d3-feasibility.md` saying either:
- proceed to cryptographic design, with exact unresolved privacy requirement, or
- stop, with the violated invariant / prior-art equivalence / impracticality.

---

## Prompt 8 — Research evidence discipline

Apply these rules to all future coding tasks:

1. Never delete a negative result because it weakens the hypothesis.
2. Never modify a baseline after seeing results without creating a new version/configuration.
3. Every benchmark must emit machine-readable raw data.
4. Every figure must be generated from checked-in analysis code.
5. Do not manually type measured numbers into tables.
6. Pin dependencies and record commits.
7. Use fixed seeds plus multiple independent seeds.
8. Log failed transactions and rejected UserOperations, not only successes.
9. Separate hypothesis, implementation observation, measured result, and interpretation.
10. Do not describe AI-generated code as verified until tests and manual review support it.
11. Do not invent cryptographic security claims from passing tests.
12. Flag any place where implementation semantics differ from the research plan.

When uncertain about ERC-4337 or cryptographic semantics, stop and request human review rather than guessing.
