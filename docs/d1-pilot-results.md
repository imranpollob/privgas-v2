# D1 pilot: controlled multi-actor dataset and first linkage attacks

Status: **pilot complete (2026-09-15); not scaled.** No novelty or production claim.
Every number below the "Generated results" marker is produced by
`python3 -m experiments.privacy.d1.evaluate score --write-doc` from frozen
predictions; the narrative sections above it cite those tables and add no
number of their own except where marked as a design parameter.

Labels used in this document: **FACT** (directly observed implementation or
measurement result), **INFERENCE** (interpretation supported by a result),
**HYPOTHESIS** (not established), **NEGATIVE RESULT** (a tested effect was
absent / at chance).

- Workload: `experiments/workloads/d1/` (`pilot-config.json`, `actors.py`, `schedule.py`, `runner.py`, `recording.py`)
- Attacks and evaluation: `experiments/privacy/d1/` (`registry.py`, `extract.py`, `rules.py`, `models.py`, `metrics.py`, `splits.py`, `attack/`, `evaluate/`)
- Feature partition: `docs/d1-feature-registry.md`
- Run: `make d1-pilot-run SEED_FILE=... BATCH=...`, `make d1-pilot-attack BATCH=... ROUND=...`; tests: `make d1-test`

## 1. Question and relations

Under matched application behaviour, what incremental privacy does the gas
mechanism add or destroy? Three relations, never pooled
(`docs/threat-model.md`):

- **R1** economic gas-funding source ↔ operation;
- **R2** private credit issuance ↔ redemption (B3 only);
- **R3** stealth account ↔ actor / established wallet (negative control in W1).

## 2. Dataset design

**Matrix** (design parameters, `pilot-config.json`): B0, B1, B2-Signature and
B3-PrivGas-v1 (primary), B2-Allowlist (auxiliary), all W1-cold, all on the
`b3_compat_local` profile so every run has the identical setup (W1 contracts,
frozen B3 contracts, all Paymaster deposits); pool sizes N = 4, 8, 16, 32; 3
replicates each; timing scenario S0-clean-shuffled for every baseline and
additionally S1-correlated-timing for B3 — 72 runs.

**One run = one chain** with N independent actors. Per actor, independent
identities drawn from (secret seed, N, private slot, kind) only: opaque actor
handle, established wallet (a real key that never transacts), asset sender,
fresh recipient key (the B0 EOA / the SimpleAccount owner), Semaphore identity,
credit and issuance handles, announcement ephemeral key. No identifier is
derived from another. The secret master seed lives in `data/private/`; run
seeds derive from (master seed, replicate, N), so baselines and scenarios at
one (replicate, N) share actors (matched), and different replicates or pool
sizes never do.

**Per-actor workflow.** setup (faucet ETH and treasury W1T to the asset
sender) → deliver (asset sender → account, 100 W1T) → fund (B0: ETH allowance;
B1: ETH = required prefund; B2-Allowlist: `setSponsored`; B3:
`announceAndFund`) → issue (B3 Bootstrap) → prepare (off chain; B3: proof) →
act (the byte-identical W1 application call to one shared destination).

**Chain time** is set explicitly for every block from the schedule; the
bundler's A2 timestamps use the same clock; proof generation time never
reaches the chain.

### 2.1 B3 multi-member procedure (frozen B3, unmodified)

1. N actors; all asset deliveries and `announceAndFund` admissions.
2. All N Bootstrap operations; the insertion order is recorded privately.
3. The harness rebuilds `Group(commitments in on-chain Deposited order)` with
   the pinned `@semaphore-protocol/core` 4.14.2 and requires: the on-chain
   insertion order equals the private record; every intermediate root emitted
   by `Deposited` equals the off-chain prefix root; the final root equals
   `CreditPool.currentRoot()` and `CreditPaymaster.merkleRoot()`; the tree size
   equals N. Any mismatch aborts the run.
4. Every Spend proof is generated against that one final root, in an
   independently permuted preparation order, with the circuit of the group's
   depth (`semaphore-2` … `semaphore-5` for N = 4 … 32; artifacts 4.13.0 pinned
   by sha256 in `experiments/workloads/w1/prover/artifacts-pin.json` and verified
   on chain by the frozen `SemaphoreVerifier`).
5. Spends are submitted in the schedule's action order; before each, the
   harness checks the mirrored root is still the proven root; after all, that
   it is unchanged and every nullifier is spent and distinct.

The latest-root assumption was tested directly
(`experiments/workloads/d1/tests/test_live.py`): a valid proof against the
earlier prefix root is rejected by the frozen `CreditPaymaster`
(`RootMismatch`); the same identity's proof against the current root is
accepted; a Spend does not change the root. No root history was added.

**Bootstrap `callGasLimit`.** FACT (measured with `eth_estimateGas` on the
frozen contracts): `CreditPool.deposit` execution grows with the LeanIMT (from
143,327 gas as an EOA call at size 0 to 400,442 at size 31), so the single-actor
evaluation value 160,000 would make every insertion after the first revert
inside execution — after `BootstrapPaymaster` has consumed the account's
one-time grant. The pilot uses one fixed 450,000 for every Bootstrap at every
N (a wallet-side parameter; `BootstrapPaymaster`'s frozen 0.005 ETH cap holds).
The EntryPoint's 10 % unused-gas penalty therefore applies to shallow insertions
(cost only). Recorded in `docs/decision-log.md`.

### 2.2 Scenarios

- **S0-clean-shuffled**: every phase (setup, deliver, fund, issue, prepare,
  act) has its own independent uniform permutation and independent exponential
  gaps (mean 600 s); phases are 6 h apart. Nothing is a function of the slot or
  of another phase's order.
- **S1-correlated-timing**: one random arrival order drives every phase
  (deliver at arrival, fund +300 s, issue +900 s); actions come after a common
  offset (all issuances precede all actions, so the single-root schedule is
  kept) plus ±900 s uniform jitter, so action order follows issuance order up
  to local swaps.

Both are audited (§5): the slot is uncorrelated with every public order in both
scenarios; in S0 phase orders are uncorrelated with each other.

## 3. Feature partition

Canonical: `docs/d1-feature-registry.md` (816 row-kind × field
classifications, 41 derived features). Summary of the decisions that matter
most for the results:

- T: ERC-20 transfers (sender, recipient, token, amount), application timing.
- AA: EntryPoint, factory, UserOperation sender, bundle metadata, account gas
  limits and fees of the application operation.
- G: every row of a gas-mechanism-only transaction or operation (B0/B1 ETH
  funding, Paymaster deposits, `setSponsored`, `announceAndFund`, the whole B3
  Bootstrap operation, `CreditSpent`, roots, nullifiers, proof metadata) plus
  mechanism-set values of the application op (Paymaster fields,
  preVerificationGas, gas used, B3 Spend nonce).
- Ambiguities are listed there; R2 is evaluated under both the primary and the
  `field_kind` convention.

## 4. Attacks

All attacks read tier-A0 public events only (plus the AUX wallet directory for
R3), through `experiments.attacker_view` in a process that cannot import
ground truth.

- **A — exact rules** (`rules.py`, kind `exact`): direct ETH / asset edges
  (R1), Bootstrap sender == Spend sender, `CreditSpent` sender == depositor,
  transfer account == depositor, deployed account == spender, latest-root
  match (R2), wallet appears on chain (R3).
- **B — timing rules** (R2): FIFO insertion order, nearest prior issuance,
  unsupervised common-delay windows (k = 1, 2, 4 median issuance gaps), and
  controls (uniform, FIFO against a pseudo-randomly permuted redemption order).
- **C/D/E — learned** (`models.py`): conditional logit (multinomial logistic
  regression over each subject's candidate set) with an L2 penalty chosen by
  inner leave-one-replicate-out CV on the fold's training runs (grid 0.1, 1,
  10, 100). Feature sets T, T+AA, G, T+G, T+AA+G (and `none` = uniform), family
  ablations of T+AA+G (timing, gas, eq, pm, app) and, for R2, G / T+G without
  equality relations and T+G without timing.

Candidate sets: R1 (B0/B1) every sender of a plain ETH transfer in the run
(N asset senders + the faucet); R2 every Bootstrap op in the run (N); R3 the N
wallet addresses. R1 is **not** classified for B2/B3 (one public candidate
funder, §6).

`delta_bits(A→B) = CE_A − CE_B` with CE in bits (the natural-log difference
divided by ln 2) on identical held-out subjects; an operational
predictive-information estimate, not a conditional mutual information.

## 5. Splits and leakage control

- Never row-level. Folds: leave-one-replicate-out (all N of one replicate held
  out); configuration holdout (train N ≤ 16, test N = 32); B3 scenario transfer
  (train S1 of other replicates → test S0 of one replicate, and reverse).
- Actors are disjoint across replicates and pool sizes by construction; the
  evaluation-side split audit checks every fold's actor addresses (asset
  senders, recipient keys, accounts, wallets) for overlap.
- Training labels (subject → true candidate public ref) are exported by the
  evaluation process per fold for that fold's training runs only; the export
  refuses a test run; the attack refuses any label outside its fold; each
  frozen prediction manifest records the label file digest and runs read, and
  the audit re-verifies them against the export manifest.
- The leakage self-check (key + value scan) runs over every pilot run before
  labels are exported and again before scoring; scoring refuses on a finding.
- Predictions are frozen (sha256) before evaluation; evaluation joins only via
  `experiments.labels.join_for_evaluation`.

## 6. Findings

All statements refer to batch `20260915T120000Z`, round `a1`, tier A0; numbers
are in the generated tables below.

### 6.1 Audits and stop conditions

- FACT: 72/72 runs recorded, none failed or retried; every run passed all of its
  end-of-run checks (root reconstruction for every intermediate and final root,
  distinct and spent nullifiers, unchanged root, bundler net within tolerance).
- FACT: the leakage self-check found nothing; the split audit found no shared
  actor address in any of the 30 folds and verified the training-label
  provenance of every learned prediction set; the public order of every phase
  equals the private schedule.
- FACT (unexpected, investigated): the harness audit flagged the S0 correlation
  between the setup-funding order and the gas-funding order (identical flag for
  the four baselines that share those permutations — one statistic over 12
  runs). Regenerating the statistic for 400 fresh seeds at each pool size gives
  combined z ≈ 0, and the two orders come from separate SHA-256 streams.
  INFERENCE: a multiple-comparison chance fluctuation of this dataset, not
  encoded by the harness; no attack feature reads the setup-funding order. The
  slot is uncorrelated with every public order (no flag). The flag criterion
  was not relaxed after the fact.
- FACT: R3 above-chance flags: none. B3 clean candidate sets are > 1.

### 6.2 R1 — economic funder ↔ operation

- FACT (structure): B0/B1 have one direct, account-specific ETH edge per
  operation and N + 1 public candidate funders; B2-Signature, B2-Allowlist and
  B3 have exactly one public candidate funder (the sponsor wallet that funded
  the Paymaster deposit), shared by all N operations. R1 classification was
  therefore run only for B0/B1.
- FACT: in B0/B1 the direct ETH edge and the direct asset edge each identify
  the funder with full precision and coverage. The G-only prefund-amount rule
  (B1) narrows the candidates without identifying the funder uniquely.
- FACT / INFERENCE: delta_bits(T → T+G) and (T+AA → T+AA+G) are ≈ 0 for B0 and
  B1 because T alone (the sender's token transfer to the same account) already
  saturates R1: in W1 the gas funder and the asset sender are the same wallet.
  B0 with G only stays near chance (the B0 action exposes no G identity of its
  sender; the small gain is the faucet's fan-out excluding one candidate), while
  B1 with G only is already exact (the prefund `Deposited` event names the
  account).
- INFERENCE: sponsorship (B2/B3) replaces an actor-specific public funding edge
  that W1's application trace already revealed by a shared, structurally known
  funder. It does not remove R1 linkage that T did not already expose.

### 6.3 R2 — issuance ↔ redemption (B3)

- FACT: `Bootstrap sender == Spend sender`, `CreditSpent.sender == depositor`,
  `transfer account == depositor` and `deployed account == spender` each select
  the true issuance for every redemption in both scenarios.
- What account equality reveals: that the account which inserted a commitment
  is the account which later redeemed a credit (account-level Bootstrap ↔ Spend
  linkage, H1). Under W1 every account redeems its own credit, so this coincides
  with the true R2 answer. What it does NOT reveal: any binding between the
  public nullifier and a commitment or leaf — the proof itself is not broken, and
  the inference would fail for cross-account redemption, which the frozen
  source permits but W1 (and this pilot) does not exercise.
- FACT: with equality relations removed, S0 is at chance on every measure: FIFO,
  nearest-prior and root-match rules match the uniform guess; the unsupervised
  delay windows reduce the candidate set only as much as their retention rate
  predicts; `T+G-minus-eq`, `G-minus-eq` and `T+AA+G-minus-eq` have held-out CE
  at the uniform value and delta_bits CIs containing 0; the
  nullifier/commitment bit-agreement control carries nothing.
  **NEGATIVE RESULT**: in the clean single-root schedule, proof, root, nullifier,
  commitment, gas and timing observations do not link issuance to redemption.
- FACT: S1 (correlated timing) degrades R2 without any equality: FIFO top-1 and
  the delay windows are far above chance at every N ≥ 8, and the timing-only
  learned model gains roughly half of the chance entropy (delta_bits for
  `T → T+G-minus-eq` with CIs excluding 0 at N = 8, 16 and 32; not at N = 4).
- FACT: primary vs `field_kind` convention changes only which family is
  credited: under the primary rule T and T+AA are uniform (every attribute of a
  Bootstrap is G), under `field_kind` T+AA is already exact (Bootstrap sender as
  AA). Every G or T+G result is identical under both conventions.
- INFERENCE: delta_bits(T → T+G) equals the full chance entropy log2 N because
  the R2 candidates exist only through G; its size is a property of the
  relation, not a measured leakage magnitude. The informative comparisons are
  the equality ablations and S0 vs S1.
- FACT (unexpected): a timing model trained on S1 and applied to S0
  (scenario transfer) is confidently wrong — held-out CE far above chance while
  top-1 stays at chance; trained on S0 and applied to S1 it gains little
  (a small delta_bits whose CI excludes 0). The configuration holdout (train N ≤ 16, test N = 32) transfers
  within a scenario.

### 6.4 R3 — account ↔ established wallet (negative control)

- FACT: no wallet appears anywhere in any public trace (coverage 0); every
  learned R3 model (T, T+AA, G, T+G, T+AA+G, all baselines, both B3 scenarios,
  all fold kinds) has top-1 CIs containing chance and CE at or slightly above
  the uniform value; the order-match leak check is at chance.
  **NEGATIVE RESULT** (as designed): no label leakage detected. Slightly negative
  delta_bits (B1/B2-Allowlist gas features, B3 S1 T) are finite-sample
  overfitting, not information.

### 6.5 Ablations and gas features

- FACT: for every relation, removing `timing`, `gas` or `pm` from T+AA+G changes
  held-out CE by ≈ 0; removing `eq` accounts for the entire gain in R1 and R2
  (in B3 S1 part of it is recovered by timing). Removing `app` (T) matters only
  for B0 R1.
- NEGATIVE RESULT: gas / fee features (PVG, gas used, their ranks and within-run
  z-scores; Paymaster type is constant within a run) add nothing to R2 or R3 in
  the pilot; B1's prefund amount is a partial G-only fingerprint for R1.

## 7. Assumptions

- Tier A0 only; the A2 stream adds nothing here (private bundler, single-op
  bundles, simulated clock equal to block time). No A1 data exists.
- Profiling attacker with labelled training runs of the same configuration.
- Every actor spends its own credit from its own announced account (W1); one
  shared destination and amount (matched application behaviour, minimal T
  variation); honest actors only; no attacker-controlled commitments.
- Auxiliary R3 knowledge: the candidate wallet directory.
- All B3 spends use the final root (no contention); unstaked Paymasters on the
  experimental bundler; `b3_compat_local` profile.

## 8. Limitations

- Small pilot: 3 replicates; per-N CIs are wide; holdout CIs over identical
  N = 32 runs are degenerate where per-subject CE is constant.
- W1 fixes amount, destination and target, so T is weaker than in real traffic;
  conversely W1 places tokens at the announced account, which forces the
  account-equality result for B3.
- One schedule family per scenario; S1's jitter scale is one design choice.
- Features are hand-built, relation-specific and run-scoped: no cross-run joins
  (although matched baselines share actors, e.g. the SimpleAccount owner is the
  B0 EOA address).
- The registry's primary rule credits co-emitted values and mechanism-set
  generic fields to G; the alternative convention is reported for R2 only.
- Experimental in-repo bundler, local anvil, simulated fee environment; no
  production or ERC-7562 claim.
- The Bootstrap call gas limit (450,000) and its unused-gas penalty are an
  evaluation choice; cost figures from the pilot are not comparable with the
  single-actor W1 tables.

## 9. Unresolved questions

- R2 under cross-account redemption (frozen source allows it; not a W1 action;
  not run by instruction).
- R2 under root contention / realistic interleaving (D2 territory; not run).
- Whether any ERC-4337-specific signal survives when T carries realistic
  variation (amounts, destinations, return-to-wallet behaviour).
- Calibration of learned timing models across schedules (scenario transfer).

## 10. D1 falsification criterion (research-plan §3)

INFERENCE: in this pilot every non-trivial linkage reduces to (a) address /
account equality — for R1 already present in the application trace, for B3 R2
created by the protocol's account-level Bootstrap → Spend design and emitted
even by its own sponsorship events — or (b) ordinary timing correlation (S1).
No ERC-4337- or gas-sponsorship-specific metadata (gas fields, PVG, Paymaster
limits, proof metadata, roots) added held-out information beyond these. The
kill condition is therefore **met for the questions tested so far**: D1 does not
yet survive, pending at most one justified experiment that removes the
account-equality confound (independent issuance, i.e. the planned B4) — which
this prompt did not authorise.

<!-- BEGIN GENERATED: d1-pilot-results -->

Batch `20260915T120000Z`, attack round `a1`. Generated by `python3 -m experiments.privacy.d1.evaluate score`; machine-readable tables in `results/d1-pilot/20260915T120000Z/evaluation-a1/`.

#### Dataset

| baseline | scenario | N | runs recorded | runs failed |
|---|---|---|---|---|
| B0 | S0 | 4 | 3 | 0 |
| B0 | S0 | 8 | 3 | 0 |
| B0 | S0 | 16 | 3 | 0 |
| B0 | S0 | 32 | 3 | 0 |
| B1 | S0 | 4 | 3 | 0 |
| B1 | S0 | 8 | 3 | 0 |
| B1 | S0 | 16 | 3 | 0 |
| B1 | S0 | 32 | 3 | 0 |
| B2-Allowlist | S0 | 4 | 3 | 0 |
| B2-Allowlist | S0 | 8 | 3 | 0 |
| B2-Allowlist | S0 | 16 | 3 | 0 |
| B2-Allowlist | S0 | 32 | 3 | 0 |
| B2-Signature | S0 | 4 | 3 | 0 |
| B2-Signature | S0 | 8 | 3 | 0 |
| B2-Signature | S0 | 16 | 3 | 0 |
| B2-Signature | S0 | 32 | 3 | 0 |
| B3-PrivGas-v1 | S0 | 4 | 3 | 0 |
| B3-PrivGas-v1 | S0 | 8 | 3 | 0 |
| B3-PrivGas-v1 | S0 | 16 | 3 | 0 |
| B3-PrivGas-v1 | S0 | 32 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 4 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 8 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 16 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 32 | 3 | 0 |

#### Candidate sets (per run; identical across replicates)

| baseline | N | R1 public candidates | R1 true funders | R2 candidates | R3 candidates | total commitments | honest commitments | attacker commitments |
|---|---|---|---|---|---|---|---|---|
| B0 | 4 | 5 | 4 | n/a | 4 | n/a | n/a | n/a |
| B0 | 8 | 9 | 8 | n/a | 8 | n/a | n/a | n/a |
| B0 | 16 | 17 | 16 | n/a | 16 | n/a | n/a | n/a |
| B0 | 32 | 33 | 32 | n/a | 32 | n/a | n/a | n/a |
| B1 | 4 | 5 | 4 | n/a | 4 | n/a | n/a | n/a |
| B1 | 8 | 9 | 8 | n/a | 8 | n/a | n/a | n/a |
| B1 | 16 | 17 | 16 | n/a | 16 | n/a | n/a | n/a |
| B1 | 32 | 33 | 32 | n/a | 32 | n/a | n/a | n/a |
| B2-Allowlist | 4 | 1 | 1 | n/a | 4 | n/a | n/a | n/a |
| B2-Allowlist | 8 | 1 | 1 | n/a | 8 | n/a | n/a | n/a |
| B2-Allowlist | 16 | 1 | 1 | n/a | 16 | n/a | n/a | n/a |
| B2-Allowlist | 32 | 1 | 1 | n/a | 32 | n/a | n/a | n/a |
| B2-Signature | 4 | 1 | 1 | n/a | 4 | n/a | n/a | n/a |
| B2-Signature | 8 | 1 | 1 | n/a | 8 | n/a | n/a | n/a |
| B2-Signature | 16 | 1 | 1 | n/a | 16 | n/a | n/a | n/a |
| B2-Signature | 32 | 1 | 1 | n/a | 32 | n/a | n/a | n/a |
| B3-PrivGas-v1 | 4 | 1 | 1 | 4 | 4 | 4 | 4 | 0 |
| B3-PrivGas-v1 | 8 | 1 | 1 | 8 | 8 | 8 | 8 | 0 |
| B3-PrivGas-v1 | 16 | 1 | 1 | 16 | 16 | 16 | 16 | 0 |
| B3-PrivGas-v1 | 32 | 1 | 1 | 32 | 32 | 32 | 32 | 0 |

#### R1 structure (public trace)

| baseline | N | immediate payer | distinct immediate payers | public candidate funders / op | ops with direct account edge | funding shared across ops | R1 classification run |
|---|---|---|---|---|---|---|---|
| B0 | 4 | eoa_balance | 4 | 5 | 4/4 | False | True |
| B0 | 8 | eoa_balance | 8 | 9 | 8/8 | False | True |
| B0 | 16 | eoa_balance | 16 | 17 | 16/16 | False | True |
| B0 | 32 | eoa_balance | 32 | 33 | 32/32 | False | True |
| B1 | 4 | smart_account_entrypoint_deposit | 4 | 5 | 4/4 | False | True |
| B1 | 8 | smart_account_entrypoint_deposit | 8 | 9 | 8/8 | False | True |
| B1 | 16 | smart_account_entrypoint_deposit | 16 | 17 | 16/16 | False | True |
| B1 | 32 | smart_account_entrypoint_deposit | 32 | 33 | 32/32 | False | True |
| B2-Allowlist | 4 | paymaster_entrypoint_deposit | 1 | 1 | 0/4 | True | False |
| B2-Allowlist | 8 | paymaster_entrypoint_deposit | 1 | 1 | 0/8 | True | False |
| B2-Allowlist | 16 | paymaster_entrypoint_deposit | 1 | 1 | 0/16 | True | False |
| B2-Allowlist | 32 | paymaster_entrypoint_deposit | 1 | 1 | 0/32 | True | False |
| B2-Signature | 4 | paymaster_entrypoint_deposit | 1 | 1 | 0/4 | True | False |
| B2-Signature | 8 | paymaster_entrypoint_deposit | 1 | 1 | 0/8 | True | False |
| B2-Signature | 16 | paymaster_entrypoint_deposit | 1 | 1 | 0/16 | True | False |
| B2-Signature | 32 | paymaster_entrypoint_deposit | 1 | 1 | 0/32 | True | False |
| B3-PrivGas-v1 | 4 | paymaster_entrypoint_deposit | 1 | 1 | 0/4 | True | False |
| B3-PrivGas-v1 | 8 | paymaster_entrypoint_deposit | 1 | 1 | 0/8 | True | False |
| B3-PrivGas-v1 | 16 | paymaster_entrypoint_deposit | 1 | 1 | 0/16 | True | False |
| B3-PrivGas-v1 | 32 | paymaster_entrypoint_deposit | 1 | 1 | 0/32 | True | False |

#### Exact / deterministic rules (pooled over N; 95% CIs)

| relation | baseline | scen. | rule | families | tier | coverage | precision | top-1 | chance top-1 | mean |C| | reduction |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | B0 | S0 | r1-direct-asset-edge-b0 | T | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.060 | 23.7 | 0.940 |
| R1 | B0 | S0 | r1-direct-eth-edge-b0 | T+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.060 | 23.7 | 0.940 |
| R1 | B0 | S0 | r1-uniform | none | A0 | 0.000 | – | 0.060 [0.044, 0.095] | 0.060 | 23.7 | – |
| R1 | B1 | S0 | r1-direct-asset-edge-b1 | T | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.060 | 23.7 | 0.940 |
| R1 | B1 | S0 | r1-direct-eth-edge-b1 | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.060 | 23.7 | 0.940 |
| R1 | B1 | S0 | r1-direct-eth-edge-g-only | G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.060 | 23.7 | 0.940 |
| R1 | B1 | S0 | r1-prefund-amount-match | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 0.156 [0.112, 0.233] | 0.060 | 23.7 | 0.358 |
| R1 | B1 | S0 | r1-uniform | none | A0 | 0.000 | – | 0.060 [0.044, 0.095] | 0.060 | 23.7 | – |
| R2 | B3-PrivGas-v1 | S0 | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-creditspent-sender-eq-depositor | G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-deployed-account-eq-spender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-root-match | G | A0 | 1.000 | 0.067 [0.039, 0.113] | 0.067 [0.031, 0.132] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.050 [0.027, 0.092] | 0.050 [0.016, 0.096] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-transfer-account-eq-depositor | T+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B3-PrivGas-v1 | S1 | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-creditspent-sender-eq-depositor | G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-deployed-account-eq-spender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-root-match | G | A0 | 1.000 | 0.067 [0.039, 0.113] | 0.067 [0.032, 0.135] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.044 [0.023, 0.085] | 0.044 [0.000, 0.138] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-transfer-account-eq-depositor | T+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B0 | S0 | r3-order-match-action | T | A0 | 1.000 | 0.100 [0.064, 0.153] | 0.100 [0.037, 0.205] | 0.067 | 22.7 | 0.933 |
| R3 | B0 | S0 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B0 | S0 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B1 | S0 | r3-order-match-action | T | A0 | 1.000 | 0.100 [0.064, 0.153] | 0.100 [0.037, 0.205] | 0.067 | 22.7 | 0.933 |
| R3 | B1 | S0 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B1 | S0 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B2-Allowlist | S0 | r3-order-match-action | T | A0 | 1.000 | 0.100 [0.064, 0.153] | 0.100 [0.037, 0.205] | 0.067 | 22.7 | 0.933 |
| R3 | B2-Allowlist | S0 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B2-Allowlist | S0 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B2-Signature | S0 | r3-order-match-action | T | A0 | 1.000 | 0.100 [0.064, 0.153] | 0.100 [0.037, 0.205] | 0.067 | 22.7 | 0.933 |
| R3 | B2-Signature | S0 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B2-Signature | S0 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S0 | r3-order-match-action | T | A0 | 1.000 | 0.100 [0.064, 0.153] | 0.100 [0.037, 0.205] | 0.067 | 22.7 | 0.933 |
| R3 | B3-PrivGas-v1 | S0 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S0 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S1 | r3-order-match-action | T | A0 | 1.000 | 0.078 [0.047, 0.126] | 0.078 [0.024, 0.160] | 0.067 | 22.7 | 0.933 |
| R3 | B3-PrivGas-v1 | S1 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S1 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |

#### R2 timing rules by pool size

| scen. | rule | N | top-1 | top-3 | top-5 | coverage | precision | reduction | chance top-1 |
|---|---|---|---|---|---|---|---|---|---|
| S0 | insertion-order-fifo | 16 | 0.062 | 0.250 | 0.354 | 1.000 | 0.062 | 0.938 | 0.062 |
| S0 | insertion-order-fifo | 32 | 0.021 | 0.094 | 0.156 | 1.000 | 0.021 | 0.969 | 0.031 |
| S0 | insertion-order-fifo | 4 | 0.333 | 0.833 | 1.000 | 1.000 | 0.333 | 0.750 | 0.250 |
| S0 | insertion-order-fifo | 8 | 0.125 | 0.333 | 0.583 | 1.000 | 0.125 | 0.875 | 0.125 |
| S0 | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| S0 | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| S0 | nearest-prior-issuance | 4 | 0.250 | 0.750 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| S0 | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| S0 | shuffled-fifo-control | 16 | 0.062 | 0.229 | 0.292 | 1.000 | 0.062 | 0.938 | 0.062 |
| S0 | shuffled-fifo-control | 32 | 0.042 | 0.135 | 0.177 | 1.000 | 0.042 | 0.969 | 0.031 |
| S0 | shuffled-fifo-control | 4 | 0.083 | 0.583 | 1.000 | 1.000 | 0.083 | 0.750 | 0.250 |
| S0 | shuffled-fifo-control | 8 | 0.042 | 0.333 | 0.542 | 1.000 | 0.042 | 0.875 | 0.125 |
| S0 | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| S0 | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| S0 | uniform | 4 | 0.250 | 0.750 | 1.000 | 0.000 | – | – | 0.250 |
| S0 | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| S0 | window-k1 | 16 | 0.080 | 0.271 | 0.417 | 0.583 | 0.143 | 0.879 | 0.062 |
| S0 | window-k1 | 32 | 0.043 | 0.156 | 0.229 | 0.708 | 0.074 | 0.943 | 0.031 |
| S0 | window-k1 | 4 | 0.222 | 0.917 | 1.000 | 0.500 | 0.500 | 0.417 | 0.250 |
| S0 | window-k1 | 8 | 0.082 | 0.292 | 0.583 | 0.625 | 0.133 | 0.792 | 0.125 |
| S0 | window-k2 | 16 | 0.107 | 0.271 | 0.417 | 0.708 | 0.294 | 0.805 | 0.062 |
| S0 | window-k2 | 32 | 0.042 | 0.156 | 0.229 | 0.906 | 0.138 | 0.909 | 0.031 |
| S0 | window-k2 | 4 | 0.312 | 0.917 | 1.000 | 0.417 | 0.800 | 0.400 | 0.250 |
| S0 | window-k2 | 8 | 0.071 | 0.292 | 0.583 | 0.875 | 0.190 | 0.667 | 0.125 |
| S0 | window-k4 | 16 | 0.079 | 0.271 | 0.417 | 0.812 | 0.462 | 0.638 | 0.062 |
| S0 | window-k4 | 32 | 0.032 | 0.156 | 0.229 | 0.990 | 0.189 | 0.830 | 0.031 |
| S0 | window-k4 | 4 | 0.306 | 0.917 | 1.000 | 0.333 | 0.750 | 0.438 | 0.250 |
| S0 | window-k4 | 8 | 0.111 | 0.292 | 0.583 | 0.917 | 0.545 | 0.449 | 0.125 |
| S1 | insertion-order-fifo | 16 | 0.500 | 0.833 | 0.979 | 1.000 | 0.500 | 0.938 | 0.062 |
| S1 | insertion-order-fifo | 32 | 0.344 | 0.760 | 0.958 | 1.000 | 0.344 | 0.969 | 0.031 |
| S1 | insertion-order-fifo | 4 | 0.417 | 0.750 | 1.000 | 1.000 | 0.417 | 0.750 | 0.250 |
| S1 | insertion-order-fifo | 8 | 0.667 | 0.917 | 1.000 | 1.000 | 0.667 | 0.875 | 0.125 |
| S1 | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| S1 | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| S1 | nearest-prior-issuance | 4 | 0.250 | 0.750 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| S1 | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| S1 | shuffled-fifo-control | 16 | 0.042 | 0.167 | 0.250 | 1.000 | 0.042 | 0.938 | 0.062 |
| S1 | shuffled-fifo-control | 32 | 0.000 | 0.042 | 0.073 | 1.000 | 0.000 | 0.969 | 0.031 |
| S1 | shuffled-fifo-control | 4 | 0.417 | 0.750 | 1.000 | 1.000 | 0.417 | 0.750 | 0.250 |
| S1 | shuffled-fifo-control | 8 | 0.042 | 0.208 | 0.583 | 1.000 | 0.042 | 0.875 | 0.125 |
| S1 | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| S1 | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| S1 | uniform | 4 | 0.250 | 0.750 | 1.000 | 0.000 | – | – | 0.250 |
| S1 | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| S1 | window-k1 | 16 | 0.367 | 0.875 | 0.979 | 0.771 | 0.649 | 0.899 | 0.062 |
| S1 | window-k1 | 32 | 0.288 | 0.802 | 0.948 | 0.875 | 0.643 | 0.930 | 0.031 |
| S1 | window-k1 | 4 | 0.347 | 0.833 | 1.000 | 0.833 | 0.600 | 0.525 | 0.250 |
| S1 | window-k1 | 8 | 0.368 | 0.958 | 1.000 | 0.667 | 0.812 | 0.781 | 0.125 |
| S1 | window-k2 | 16 | 0.294 | 0.875 | 0.979 | 0.896 | 0.791 | 0.840 | 0.062 |
| S1 | window-k2 | 32 | 0.265 | 0.802 | 0.948 | 0.969 | 0.817 | 0.887 | 0.031 |
| S1 | window-k2 | 4 | 0.250 | 0.833 | 1.000 | 0.833 | 0.700 | 0.375 | 0.250 |
| S1 | window-k2 | 8 | 0.375 | 0.958 | 1.000 | 0.833 | 0.950 | 0.681 | 0.125 |
| S1 | window-k4 | 16 | 0.251 | 0.875 | 0.979 | 1.000 | 0.917 | 0.737 | 0.062 |
| S1 | window-k4 | 32 | 0.190 | 0.802 | 0.948 | 1.000 | 1.000 | 0.804 | 0.031 |
| S1 | window-k4 | 4 | 0.250 | 0.833 | 1.000 | 0.167 | 0.500 | 0.375 | 0.250 |
| S1 | window-k4 | 8 | 0.311 | 0.958 | 1.000 | 0.875 | 0.952 | 0.536 | 0.125 |

#### Learned models (conditional logit; L2 chosen by inner CV on training runs; leave-one-replicate-out, pooled N)

| relation | baseline | scen. | conv. | feature set | subjects | top-1 | top-3 | CE bits | chance bits | Brier | ECE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R1 | B0 | S0 | primary | G | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.518, 4.645] | 4.358 | 0.933 | 0.000 |
| R1 | B0 | S0 | primary | T | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.358 | 0.000 | 0.000 |
| R1 | B0 | S0 | primary | T+AA | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.358 | 0.000 | 0.000 |
| R1 | B0 | S0 | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B0 | S0 | primary | T+AA+G-minus-app | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.518, 4.645] | 4.358 | 0.933 | 0.000 |
| R1 | B0 | S0 | primary | T+AA+G-minus-eq | 180 | 0.089 [0.034, 0.177] | 0.261 | 4.266 [3.527, 4.656] | 4.358 | 0.933 | 0.007 |
| R1 | B0 | S0 | primary | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B0 | S0 | primary | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B0 | S0 | primary | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B0 | S0 | primary | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B0 | S0 | primary | none | 180 | 0.060 [0.044, 0.095] | 0.180 | 4.358 [3.657, 4.714] | 4.358 | 0.940 | 0.000 |
| R1 | B1 | S0 | primary | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T+AA | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T+AA+G-minus-eq | 180 | 0.178 [0.109, 0.271] | 0.367 | 3.458 [2.773, 3.852] | 4.358 | 0.844 | 0.015 |
| R1 | B1 | S0 | primary | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.358 | 0.000 | 0.000 |
| R1 | B1 | S0 | primary | none | 180 | 0.060 [0.044, 0.095] | 0.180 | 4.358 [3.657, 4.714] | 4.358 | 0.940 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | G-minus-eq | 180 | 0.061 [0.021, 0.125] | 0.233 | 4.259 [3.505, 4.640] | 4.267 | 0.933 | 0.015 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-eq | 180 | 0.094 [0.043, 0.170] | 0.233 | 4.253 [3.507, 4.634] | 4.267 | 0.933 | 0.019 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+G-minus-eq | 180 | 0.094 [0.039, 0.176] | 0.228 | 4.252 [3.508, 4.633] | 4.267 | 0.933 | 0.020 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | G-minus-eq | 180 | 0.061 [0.021, 0.125] | 0.233 | 4.259 [3.505, 4.640] | 4.267 | 0.933 | 0.015 |
| R2 | B3-PrivGas-v1 | S0 | primary | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-eq | 180 | 0.094 [0.043, 0.170] | 0.233 | 4.253 [3.507, 4.634] | 4.267 | 0.933 | 0.019 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+G-minus-eq | 180 | 0.094 [0.039, 0.176] | 0.228 | 4.252 [3.508, 4.633] | 4.267 | 0.933 | 0.020 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | G-minus-eq | 180 | 0.333 [0.222, 0.466] | 0.833 | 2.091 [1.720, 2.393] | 4.267 | 0.721 | 0.127 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-eq | 180 | 0.333 [0.222, 0.466] | 0.833 | 2.092 [1.720, 2.395] | 4.267 | 0.721 | 0.127 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+G-minus-eq | 180 | 0.333 [0.222, 0.466] | 0.833 | 2.092 [1.720, 2.395] | 4.267 | 0.721 | 0.127 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | G-minus-eq | 180 | 0.333 [0.222, 0.466] | 0.833 | 2.091 [1.720, 2.393] | 4.267 | 0.721 | 0.127 |
| R2 | B3-PrivGas-v1 | S1 | primary | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-eq | 180 | 0.333 [0.222, 0.466] | 0.833 | 2.092 [1.720, 2.395] | 4.267 | 0.721 | 0.127 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+G-minus-eq | 180 | 0.333 [0.222, 0.466] | 0.833 | 2.092 [1.720, 2.395] | 4.267 | 0.721 | 0.127 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B0 | S0 | primary | G | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B0 | S0 | primary | T | 180 | 0.072 [0.022, 0.174] | 0.206 | 4.255 [3.512, 4.634] | 4.267 | 0.932 | 0.046 |
| R3 | B0 | S0 | primary | T+AA | 180 | 0.072 [0.022, 0.174] | 0.206 | 4.255 [3.512, 4.634] | 4.267 | 0.932 | 0.046 |
| R3 | B0 | S0 | primary | T+AA+G | 180 | 0.067 [0.025, 0.133] | 0.256 | 4.243 [3.524, 4.609] | 4.267 | 0.932 | 0.017 |
| R3 | B0 | S0 | primary | T+AA+G-minus-app | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B0 | S0 | primary | T+AA+G-minus-eq | 180 | 0.100 [0.041, 0.213] | 0.228 | 4.238 [3.510, 4.603] | 4.267 | 0.931 | 0.019 |
| R3 | B0 | S0 | primary | T+AA+G-minus-gas | 180 | 0.067 [0.025, 0.133] | 0.256 | 4.243 [3.524, 4.609] | 4.267 | 0.932 | 0.017 |
| R3 | B0 | S0 | primary | T+AA+G-minus-pm | 180 | 0.067 [0.025, 0.133] | 0.256 | 4.243 [3.524, 4.609] | 4.267 | 0.932 | 0.017 |
| R3 | B0 | S0 | primary | T+AA+G-minus-timing | 180 | 0.067 [0.024, 0.138] | 0.197 | 4.266 [3.516, 4.648] | 4.267 | 0.933 | 0.003 |
| R3 | B0 | S0 | primary | T+G | 180 | 0.067 [0.025, 0.133] | 0.256 | 4.243 [3.524, 4.609] | 4.267 | 0.932 | 0.017 |
| R3 | B0 | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B1 | S0 | primary | G | 180 | 0.106 [0.050, 0.190] | 0.233 | 4.309 [3.623, 4.671] | 4.267 | 0.941 | 0.052 |
| R3 | B1 | S0 | primary | T | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.634] | 4.267 | 0.933 | 0.042 |
| R3 | B1 | S0 | primary | T+AA | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B1 | S0 | primary | T+AA+G | 180 | 0.072 [0.031, 0.151] | 0.200 | 4.298 [3.641, 4.648] | 4.267 | 0.939 | 0.016 |
| R3 | B1 | S0 | primary | T+AA+G-minus-app | 180 | 0.111 [0.051, 0.204] | 0.250 | 4.302 [3.612, 4.668] | 4.267 | 0.940 | 0.057 |
| R3 | B1 | S0 | primary | T+AA+G-minus-eq | 180 | 0.089 [0.037, 0.177] | 0.211 | 4.294 [3.620, 4.645] | 4.267 | 0.939 | 0.014 |
| R3 | B1 | S0 | primary | T+AA+G-minus-gas | 180 | 0.106 [0.050, 0.215] | 0.222 | 4.248 [3.536, 4.614] | 4.267 | 0.933 | 0.026 |
| R3 | B1 | S0 | primary | T+AA+G-minus-pm | 180 | 0.072 [0.031, 0.151] | 0.200 | 4.298 [3.641, 4.648] | 4.267 | 0.939 | 0.016 |
| R3 | B1 | S0 | primary | T+AA+G-minus-timing | 180 | 0.061 [0.025, 0.110] | 0.189 | 4.313 [3.601, 4.683] | 4.267 | 0.940 | 0.019 |
| R3 | B1 | S0 | primary | T+G | 180 | 0.072 [0.031, 0.151] | 0.194 | 4.292 [3.623, 4.644] | 4.267 | 0.939 | 0.016 |
| R3 | B1 | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B2-Allowlist | S0 | primary | G | 180 | 0.039 [0.011, 0.080] | 0.172 | 4.315 [3.583, 4.686] | 4.267 | 0.940 | 0.039 |
| R3 | B2-Allowlist | S0 | primary | T | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.634] | 4.267 | 0.933 | 0.042 |
| R3 | B2-Allowlist | S0 | primary | T+AA | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B2-Allowlist | S0 | primary | T+AA+G | 180 | 0.083 [0.036, 0.167] | 0.233 | 4.305 [3.641, 4.656] | 4.267 | 0.939 | 0.008 |
| R3 | B2-Allowlist | S0 | primary | T+AA+G-minus-app | 180 | 0.111 [0.050, 0.201] | 0.239 | 4.319 [3.627, 4.683] | 4.267 | 0.942 | 0.063 |
| R3 | B2-Allowlist | S0 | primary | T+AA+G-minus-eq | 180 | 0.100 [0.047, 0.203] | 0.222 | 4.302 [3.632, 4.653] | 4.267 | 0.939 | 0.028 |
| R3 | B2-Allowlist | S0 | primary | T+AA+G-minus-gas | 180 | 0.106 [0.050, 0.215] | 0.222 | 4.248 [3.536, 4.614] | 4.267 | 0.933 | 0.026 |
| R3 | B2-Allowlist | S0 | primary | T+AA+G-minus-pm | 180 | 0.083 [0.036, 0.167] | 0.233 | 4.305 [3.641, 4.656] | 4.267 | 0.939 | 0.008 |
| R3 | B2-Allowlist | S0 | primary | T+AA+G-minus-timing | 180 | 0.050 [0.015, 0.102] | 0.189 | 4.313 [3.598, 4.683] | 4.267 | 0.939 | 0.032 |
| R3 | B2-Allowlist | S0 | primary | T+G | 180 | 0.094 [0.040, 0.190] | 0.233 | 4.297 [3.591, 4.658] | 4.267 | 0.938 | 0.027 |
| R3 | B2-Allowlist | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B2-Signature | S0 | primary | G | 180 | 0.061 [0.019, 0.129] | 0.164 | 4.287 [3.553, 4.662] | 4.267 | 0.937 | 0.020 |
| R3 | B2-Signature | S0 | primary | T | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.634] | 4.267 | 0.933 | 0.042 |
| R3 | B2-Signature | S0 | primary | T+AA | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B2-Signature | S0 | primary | T+AA+G | 180 | 0.078 [0.024, 0.181] | 0.211 | 4.279 [3.563, 4.648] | 4.267 | 0.936 | 0.030 |
| R3 | B2-Signature | S0 | primary | T+AA+G-minus-app | 180 | 0.089 [0.031, 0.179] | 0.178 | 4.289 [3.547, 4.665] | 4.267 | 0.937 | 0.016 |
| R3 | B2-Signature | S0 | primary | T+AA+G-minus-eq | 180 | 0.056 [0.006, 0.142] | 0.211 | 4.276 [3.545, 4.644] | 4.267 | 0.936 | 0.049 |
| R3 | B2-Signature | S0 | primary | T+AA+G-minus-gas | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B2-Signature | S0 | primary | T+AA+G-minus-pm | 180 | 0.078 [0.024, 0.181] | 0.211 | 4.279 [3.563, 4.648] | 4.267 | 0.936 | 0.030 |
| R3 | B2-Signature | S0 | primary | T+AA+G-minus-timing | 180 | 0.078 [0.038, 0.145] | 0.172 | 4.290 [3.561, 4.665] | 4.267 | 0.937 | 0.007 |
| R3 | B2-Signature | S0 | primary | T+G | 180 | 0.078 [0.024, 0.181] | 0.211 | 4.279 [3.562, 4.648] | 4.267 | 0.936 | 0.030 |
| R3 | B2-Signature | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B3-PrivGas-v1 | S0 | primary | G | 180 | 0.044 [0.008, 0.104] | 0.167 | 4.271 [3.520, 4.652] | 4.267 | 0.934 | 0.026 |
| R3 | B3-PrivGas-v1 | S0 | primary | T | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.634] | 4.267 | 0.933 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G | 180 | 0.056 [0.010, 0.138] | 0.228 | 4.266 [3.533, 4.638] | 4.267 | 0.934 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-app | 180 | 0.056 [0.020, 0.114] | 0.217 | 4.272 [3.519, 4.653] | 4.267 | 0.934 | 0.015 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-eq | 180 | 0.061 [0.013, 0.159] | 0.200 | 4.267 [3.528, 4.637] | 4.267 | 0.934 | 0.033 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-gas | 180 | 0.078 [0.027, 0.169] | 0.217 | 4.262 [3.532, 4.640] | 4.267 | 0.933 | 0.031 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-pm | 180 | 0.056 [0.010, 0.138] | 0.228 | 4.266 [3.533, 4.638] | 4.267 | 0.934 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-timing | 180 | 0.067 [0.024, 0.122] | 0.183 | 4.276 [3.525, 4.654] | 4.267 | 0.935 | 0.010 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+G | 180 | 0.056 [0.010, 0.138] | 0.244 | 4.266 [3.532, 4.638] | 4.267 | 0.934 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B3-PrivGas-v1 | S1 | primary | G | 180 | 0.061 [0.023, 0.118] | 0.189 | 4.280 [3.537, 4.659] | 4.267 | 0.936 | 0.025 |
| R3 | B3-PrivGas-v1 | S1 | primary | T | 180 | 0.056 [0.019, 0.098] | 0.200 | 4.345 [3.650, 4.706] | 4.267 | 0.950 | 0.031 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA | 180 | 0.050 [0.016, 0.090] | 0.178 | 4.351 [3.665, 4.709] | 4.267 | 0.951 | 0.037 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G | 180 | 0.056 [0.022, 0.100] | 0.167 | 4.372 [3.698, 4.731] | 4.267 | 0.954 | 0.034 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-app | 180 | 0.033 [0.005, 0.081] | 0.144 | 4.358 [3.675, 4.726] | 4.267 | 0.952 | 0.050 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-eq | 180 | 0.028 [0.000, 0.077] | 0.144 | 4.368 [3.689, 4.735] | 4.267 | 0.953 | 0.057 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-gas | 180 | 0.061 [0.021, 0.103] | 0.189 | 4.354 [3.684, 4.716] | 4.267 | 0.951 | 0.027 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-pm | 180 | 0.056 [0.022, 0.100] | 0.167 | 4.372 [3.698, 4.731] | 4.267 | 0.954 | 0.034 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-timing | 180 | 0.050 [0.014, 0.112] | 0.156 | 4.278 [3.535, 4.653] | 4.267 | 0.936 | 0.033 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+G | 180 | 0.061 [0.023, 0.111] | 0.178 | 4.364 [3.689, 4.725] | 4.267 | 0.953 | 0.028 |
| R3 | B3-PrivGas-v1 | S1 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |

#### delta_bits (held-out CE difference in bits; paired cluster bootstrap 95% CI)

| relation | baseline | scen. | fold | conv. | from | to | CE from | CE to | delta_bits [CI] |
|---|---|---|---|---|---|---|---|---|---|
| R1 | B0 | S0 | holdout | primary | none | T | 5.044 | 0.003 | 5.041 [5.041, 5.041] |
| R1 | B0 | S0 | holdout | primary | none | G | 5.044 | 5.000 | 0.044 [0.044, 0.044] |
| R1 | B0 | S0 | holdout | primary | T | T+AA | 0.003 | 0.003 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | holdout | primary | T | T+G | 0.003 | 0.002 | 0.001 [0.001, 0.001] |
| R1 | B0 | S0 | holdout | primary | T+AA | T+AA+G | 0.003 | 0.002 | 0.001 [0.001, 0.001] |
| R1 | B0 | S0 | holdout | primary | T | T+AA+G | 0.003 | 0.002 | 0.001 [0.001, 0.001] |
| R1 | B0 | S0 | holdout | primary | T+G | T+AA+G | 0.002 | 0.002 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | loro | primary | none | T | 4.358 | 0.001 | 4.357 [3.664, 4.715] |
| R1 | B0 | S0 | loro | primary | none | G | 4.358 | 4.267 | 0.091 [0.065, 0.146] |
| R1 | B0 | S0 | loro | primary | T | T+AA | 0.001 | 0.001 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | loro | primary | T | T+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | loro | primary | T+AA | T+AA+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | loro | primary | T | T+AA+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | loro | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B1 | S0 | holdout | primary | none | T | 5.044 | 0.003 | 5.041 [5.041, 5.041] |
| R1 | B1 | S0 | holdout | primary | none | G | 5.044 | 0.003 | 5.041 [5.041, 5.041] |
| R1 | B1 | S0 | holdout | primary | T | T+AA | 0.003 | 0.002 | 0.001 [0.001, 0.001] |
| R1 | B1 | S0 | holdout | primary | T | T+G | 0.003 | 0.001 | 0.002 [0.002, 0.002] |
| R1 | B1 | S0 | holdout | primary | T+AA | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R1 | B1 | S0 | holdout | primary | T | T+AA+G | 0.003 | 0.001 | 0.002 [0.002, 0.002] |
| R1 | B1 | S0 | holdout | primary | T+G | T+AA+G | 0.001 | 0.001 | 0.000 [0.000, 0.000] |
| R1 | B1 | S0 | loro | primary | none | T | 4.358 | 0.001 | 4.357 [3.664, 4.715] |
| R1 | B1 | S0 | loro | primary | none | G | 4.358 | 0.001 | 4.357 [3.664, 4.715] |
| R1 | B1 | S0 | loro | primary | T | T+AA | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B1 | S0 | loro | primary | T | T+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B1 | S0 | loro | primary | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B1 | S0 | loro | primary | T | T+AA+G | 0.001 | 0.000 | 0.000 [0.000, 0.001] |
| R1 | B1 | S0 | loro | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | G | 5.000 | 0.004 | 4.996 [4.996, 4.997] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+AA | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+AA | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | G-minus-eq | 5.000 | 5.011 | -0.011 [-0.053, 0.031] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T+G-minus-eq | 5.000 | 5.002 | -0.002 [-0.054, 0.047] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+G-minus-eq | 5.000 | 5.002 | -0.002 [-0.054, 0.047] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | G | 5.000 | 0.004 | 4.996 [4.996, 4.997] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | G-minus-eq | 5.000 | 5.011 | -0.011 [-0.053, 0.031] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T+G-minus-eq | 5.000 | 5.002 | -0.002 [-0.054, 0.047] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+G-minus-eq | 5.000 | 5.002 | -0.002 [-0.054, 0.047] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | G-minus-eq | 4.267 | 4.259 | 0.008 [-0.020, 0.032] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T+G-minus-eq | 4.267 | 4.252 | 0.014 [-0.025, 0.046] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+G-minus-eq | 4.267 | 4.252 | 0.014 [-0.025, 0.046] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | G-minus-eq | 4.267 | 4.259 | 0.008 [-0.020, 0.032] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T+G-minus-eq | 4.267 | 4.252 | 0.014 [-0.025, 0.046] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+G-minus-eq | 4.267 | 4.252 | 0.014 [-0.025, 0.046] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | G | 4.267 | 0.001 | 4.265 [3.517, 4.646] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+G | T+AA+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | G-minus-eq | 4.267 | 9.143 | -4.876 [-6.357, -2.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T+G-minus-eq | 4.267 | 8.745 | -4.478 [-5.878, -2.277] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+G-minus-eq | 4.267 | 8.745 | -4.478 [-5.878, -2.277] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | G | 4.267 | 0.001 | 4.265 [3.517, 4.646] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+G | T+AA+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | G-minus-eq | 4.267 | 9.143 | -4.876 [-6.357, -2.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T+G-minus-eq | 4.267 | 8.745 | -4.478 [-5.878, -2.277] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+G-minus-eq | 4.267 | 8.745 | -4.478 [-5.878, -2.277] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | G | 5.000 | 0.003 | 4.997 [4.997, 4.997] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+AA | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+AA | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | G-minus-eq | 5.000 | 2.381 | 2.619 [2.362, 2.831] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T+G-minus-eq | 5.000 | 2.381 | 2.619 [2.362, 2.831] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+G-minus-eq | 5.000 | 2.381 | 2.619 [2.362, 2.831] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | G | 5.000 | 0.003 | 4.997 [4.997, 4.997] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | G-minus-eq | 5.000 | 2.381 | 2.619 [2.362, 2.831] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T+G-minus-eq | 5.000 | 2.381 | 2.619 [2.362, 2.831] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+G-minus-eq | 5.000 | 2.381 | 2.619 [2.362, 2.831] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | G-minus-eq | 4.267 | 2.091 | 2.176 [1.482, 2.522] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T+G-minus-eq | 4.267 | 2.092 | 2.175 [1.481, 2.522] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+G-minus-eq | 4.267 | 2.092 | 2.175 [1.481, 2.522] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | G-minus-eq | 4.267 | 2.091 | 2.176 [1.482, 2.522] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T+G-minus-eq | 4.267 | 2.092 | 2.175 [1.481, 2.522] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+G-minus-eq | 4.267 | 2.092 | 2.175 [1.481, 2.522] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | G-minus-eq | 4.267 | 4.195 | 0.072 [0.033, 0.101] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T+G-minus-eq | 4.267 | 4.067 | 0.200 [0.128, 0.259] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+G-minus-eq | 4.267 | 4.067 | 0.200 [0.128, 0.259] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | G-minus-eq | 4.267 | 4.195 | 0.072 [0.033, 0.101] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T+G-minus-eq | 4.267 | 4.067 | 0.200 [0.128, 0.259] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+G-minus-eq | 4.267 | 4.067 | 0.200 [0.128, 0.259] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R3 | B0 | S0 | holdout | primary | none | T | 5.000 | 5.001 | -0.001 [-0.016, 0.014] |
| R3 | B0 | S0 | holdout | primary | none | G | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | holdout | primary | T | T+AA | 5.001 | 5.001 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | holdout | primary | T | T+G | 5.001 | 4.987 | 0.014 [0.001, 0.028] |
| R3 | B0 | S0 | holdout | primary | T+AA | T+AA+G | 5.001 | 4.987 | 0.014 [0.001, 0.028] |
| R3 | B0 | S0 | holdout | primary | T | T+AA+G | 5.001 | 4.987 | 0.014 [0.001, 0.028] |
| R3 | B0 | S0 | holdout | primary | T+G | T+AA+G | 4.987 | 4.987 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | loro | primary | none | T | 4.267 | 4.255 | 0.012 [-0.030, 0.048] |
| R3 | B0 | S0 | loro | primary | none | G | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | loro | primary | T | T+AA | 4.255 | 4.255 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | loro | primary | T | T+G | 4.255 | 4.243 | 0.012 [-0.041, 0.049] |
| R3 | B0 | S0 | loro | primary | T+AA | T+AA+G | 4.255 | 4.243 | 0.012 [-0.041, 0.049] |
| R3 | B0 | S0 | loro | primary | T | T+AA+G | 4.255 | 4.243 | 0.012 [-0.041, 0.049] |
| R3 | B0 | S0 | loro | primary | T+G | T+AA+G | 4.243 | 4.243 | 0.000 [0.000, 0.000] |
| R3 | B1 | S0 | holdout | primary | none | T | 5.000 | 4.997 | 0.003 [-0.010, 0.014] |
| R3 | B1 | S0 | holdout | primary | none | G | 5.000 | 4.985 | 0.015 [0.001, 0.030] |
| R3 | B1 | S0 | holdout | primary | T | T+AA | 4.997 | 4.997 | -0.000 [-0.002, 0.001] |
| R3 | B1 | S0 | holdout | primary | T | T+G | 4.997 | 4.982 | 0.015 [0.001, 0.031] |
| R3 | B1 | S0 | holdout | primary | T+AA | T+AA+G | 4.997 | 4.982 | 0.015 [0.001, 0.031] |
| R3 | B1 | S0 | holdout | primary | T | T+AA+G | 4.997 | 4.982 | 0.015 [0.000, 0.030] |
| R3 | B1 | S0 | holdout | primary | T+G | T+AA+G | 4.982 | 4.982 | -0.000 [-0.002, 0.001] |
| R3 | B1 | S0 | loro | primary | none | T | 4.267 | 4.260 | 0.007 [-0.036, 0.043] |
| R3 | B1 | S0 | loro | primary | none | G | 4.267 | 4.309 | -0.043 [-0.188, 0.025] |
| R3 | B1 | S0 | loro | primary | T | T+AA | 4.260 | 4.260 | -0.000 [-0.001, 0.001] |
| R3 | B1 | S0 | loro | primary | T | T+G | 4.260 | 4.292 | -0.032 [-0.161, 0.028] |
| R3 | B1 | S0 | loro | primary | T+AA | T+AA+G | 4.260 | 4.298 | -0.038 [-0.182, 0.027] |
| R3 | B1 | S0 | loro | primary | T | T+AA+G | 4.260 | 4.298 | -0.038 [-0.181, 0.027] |
| R3 | B1 | S0 | loro | primary | T+G | T+AA+G | 4.292 | 4.298 | -0.006 [-0.021, 0.000] |
| R3 | B2-Allowlist | S0 | holdout | primary | none | T | 5.000 | 4.997 | 0.003 [-0.010, 0.014] |
| R3 | B2-Allowlist | S0 | holdout | primary | none | G | 5.000 | 4.999 | 0.001 [-0.010, 0.011] |
| R3 | B2-Allowlist | S0 | holdout | primary | T | T+AA | 4.997 | 4.997 | -0.000 [-0.002, 0.001] |
| R3 | B2-Allowlist | S0 | holdout | primary | T | T+G | 4.997 | 4.997 | 0.000 [-0.009, 0.009] |
| R3 | B2-Allowlist | S0 | holdout | primary | T+AA | T+AA+G | 4.997 | 4.984 | 0.014 [-0.003, 0.030] |
| R3 | B2-Allowlist | S0 | holdout | primary | T | T+AA+G | 4.997 | 4.984 | 0.014 [-0.003, 0.030] |
| R3 | B2-Allowlist | S0 | holdout | primary | T+G | T+AA+G | 4.997 | 4.984 | 0.013 [-0.000, 0.028] |
| R3 | B2-Allowlist | S0 | loro | primary | none | T | 4.267 | 4.260 | 0.007 [-0.036, 0.043] |
| R3 | B2-Allowlist | S0 | loro | primary | none | G | 4.267 | 4.315 | -0.048 [-0.172, 0.013] |
| R3 | B2-Allowlist | S0 | loro | primary | T | T+AA | 4.260 | 4.260 | -0.000 [-0.001, 0.001] |
| R3 | B2-Allowlist | S0 | loro | primary | T | T+G | 4.260 | 4.297 | -0.038 [-0.127, 0.008] |
| R3 | B2-Allowlist | S0 | loro | primary | T+AA | T+AA+G | 4.260 | 4.305 | -0.045 [-0.200, 0.027] |
| R3 | B2-Allowlist | S0 | loro | primary | T | T+AA+G | 4.260 | 4.305 | -0.045 [-0.201, 0.027] |
| R3 | B2-Allowlist | S0 | loro | primary | T+G | T+AA+G | 4.297 | 4.305 | -0.008 [-0.089, 0.036] |
| R3 | B2-Signature | S0 | holdout | primary | none | T | 5.000 | 4.997 | 0.003 [-0.010, 0.014] |
| R3 | B2-Signature | S0 | holdout | primary | none | G | 5.000 | 5.001 | -0.001 [-0.006, 0.002] |
| R3 | B2-Signature | S0 | holdout | primary | T | T+AA | 4.997 | 4.997 | -0.000 [-0.002, 0.001] |
| R3 | B2-Signature | S0 | holdout | primary | T | T+G | 4.997 | 4.998 | -0.001 [-0.005, 0.002] |
| R3 | B2-Signature | S0 | holdout | primary | T+AA | T+AA+G | 4.997 | 4.998 | -0.001 [-0.005, 0.002] |
| R3 | B2-Signature | S0 | holdout | primary | T | T+AA+G | 4.997 | 4.998 | -0.001 [-0.006, 0.002] |
| R3 | B2-Signature | S0 | holdout | primary | T+G | T+AA+G | 4.998 | 4.998 | -0.000 [-0.001, 0.001] |
| R3 | B2-Signature | S0 | loro | primary | none | T | 4.267 | 4.260 | 0.007 [-0.036, 0.043] |
| R3 | B2-Signature | S0 | loro | primary | none | G | 4.267 | 4.287 | -0.020 [-0.055, -0.001] |
| R3 | B2-Signature | S0 | loro | primary | T | T+AA | 4.260 | 4.260 | -0.000 [-0.001, 0.001] |
| R3 | B2-Signature | S0 | loro | primary | T | T+G | 4.260 | 4.279 | -0.019 [-0.054, 0.001] |
| R3 | B2-Signature | S0 | loro | primary | T+AA | T+AA+G | 4.260 | 4.279 | -0.019 [-0.054, 0.001] |
| R3 | B2-Signature | S0 | loro | primary | T | T+AA+G | 4.260 | 4.279 | -0.019 [-0.054, 0.001] |
| R3 | B2-Signature | S0 | loro | primary | T+G | T+AA+G | 4.279 | 4.279 | -0.000 [-0.001, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | none | T | 5.000 | 4.997 | 0.003 [-0.010, 0.014] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | none | G | 5.000 | 5.002 | -0.002 [-0.006, 0.002] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA | 4.997 | 4.997 | -0.000 [-0.002, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+G | 4.997 | 5.000 | -0.003 [-0.009, 0.003] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA | T+AA+G | 4.997 | 5.000 | -0.003 [-0.009, 0.003] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA+G | 4.997 | 5.000 | -0.003 [-0.010, 0.003] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T+G | T+AA+G | 5.000 | 5.000 | -0.000 [-0.002, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | none | T | 4.267 | 4.260 | 0.007 [-0.036, 0.043] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | none | G | 4.267 | 4.271 | -0.004 [-0.016, 0.006] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA | 4.260 | 4.260 | -0.000 [-0.001, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T | T+G | 4.260 | 4.266 | -0.006 [-0.021, 0.006] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T+AA | T+AA+G | 4.260 | 4.266 | -0.006 [-0.021, 0.006] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA+G | 4.260 | 4.266 | -0.007 [-0.021, 0.006] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T+G | T+AA+G | 4.266 | 4.266 | -0.000 [-0.001, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | none | T | 4.267 | 4.345 | -0.078 [-0.352, 0.076] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | none | G | 4.267 | 4.269 | -0.002 [-0.019, 0.016] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA | 4.345 | 4.354 | -0.009 [-0.026, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+G | 4.345 | 4.352 | -0.008 [-0.087, 0.085] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA | T+AA+G | 4.354 | 4.361 | -0.007 [-0.091, 0.089] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA+G | 4.345 | 4.361 | -0.017 [-0.101, 0.069] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T+G | T+AA+G | 4.352 | 4.361 | -0.009 [-0.025, 0.002] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | none | T | 5.000 | 5.004 | -0.004 [-0.023, 0.014] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | none | G | 5.000 | 5.006 | -0.006 [-0.026, 0.014] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA | 5.004 | 5.004 | -0.000 [-0.001, 0.001] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+G | 5.004 | 5.010 | -0.006 [-0.018, 0.006] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA | T+AA+G | 5.004 | 5.010 | -0.006 [-0.018, 0.006] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA+G | 5.004 | 5.010 | -0.006 [-0.018, 0.006] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T+G | T+AA+G | 5.010 | 5.010 | 0.000 [-0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | none | T | 4.267 | 4.345 | -0.078 [-0.280, -0.003] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | none | G | 4.267 | 4.280 | -0.013 [-0.039, 0.005] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA | 4.345 | 4.351 | -0.007 [-0.019, -0.001] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T | T+G | 4.345 | 4.364 | -0.020 [-0.059, 0.002] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T+AA | T+AA+G | 4.351 | 4.372 | -0.020 [-0.061, 0.002] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA+G | 4.345 | 4.372 | -0.027 [-0.079, -0.002] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T+G | T+AA+G | 4.364 | 4.372 | -0.007 [-0.021, -0.002] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | none | T | 4.267 | 4.257 | 0.010 [-0.028, 0.054] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | none | G | 4.267 | 4.267 | -0.000 [-0.010, 0.013] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA | 4.257 | 4.256 | 0.000 [-0.000, 0.001] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+G | 4.257 | 4.256 | 0.000 [-0.012, 0.017] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA | T+AA+G | 4.256 | 4.256 | 0.000 [-0.012, 0.017] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA+G | 4.257 | 4.256 | 0.001 [-0.011, 0.017] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T+G | T+AA+G | 4.256 | 4.256 | 0.000 [-0.000, 0.001] |

#### Feature-family ablations of T+AA+G (positive = the removed family carried held-out information)

| relation | baseline | scen. | conv. | removed | CE full | CE without | delta_bits [CI] |
|---|---|---|---|---|---|---|---|
| R1 | B0 | S0 | primary | timing | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R1 | B0 | S0 | primary | gas | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | primary | eq | 0.000 | 4.266 | 4.266 [3.527, 4.657] |
| R1 | B0 | S0 | primary | pm | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B0 | S0 | primary | app | 0.000 | 4.267 | 4.267 [3.518, 4.647] |
| R1 | B1 | S0 | primary | timing | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R1 | B1 | S0 | primary | gas | 0.000 | 0.000 | 0.000 [-0.000, 0.000] |
| R1 | B1 | S0 | primary | eq | 0.000 | 3.458 | 3.458 [2.775, 3.857] |
| R1 | B1 | S0 | primary | pm | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R1 | B1 | S0 | primary | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | timing | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | eq | 0.000 | 4.253 | 4.253 [3.509, 4.637] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | timing | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | eq | 0.000 | 4.253 | 4.253 [3.509, 4.637] |
| R2 | B3-PrivGas-v1 | S0 | primary | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | timing | 0.000 | 0.000 | 0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | eq | 0.000 | 2.092 | 2.092 [1.703, 2.398] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | timing | 0.000 | 0.000 | 0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | eq | 0.000 | 2.092 | 2.092 [1.703, 2.398] |
| R2 | B3-PrivGas-v1 | S1 | primary | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | primary | timing | 4.243 | 4.266 | 0.024 [-0.053, 0.081] |
| R3 | B0 | S0 | primary | gas | 4.243 | 4.243 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | primary | eq | 4.243 | 4.238 | -0.005 [-0.021, 0.010] |
| R3 | B0 | S0 | primary | pm | 4.243 | 4.243 | 0.000 [0.000, 0.000] |
| R3 | B0 | S0 | primary | app | 4.243 | 4.267 | 0.024 [-0.054, 0.080] |
| R3 | B1 | S0 | primary | timing | 4.298 | 4.313 | 0.014 [-0.075, 0.077] |
| R3 | B1 | S0 | primary | gas | 4.298 | 4.248 | -0.050 [-0.155, -0.002] |
| R3 | B1 | S0 | primary | eq | 4.298 | 4.294 | -0.004 [-0.027, 0.014] |
| R3 | B1 | S0 | primary | pm | 4.298 | 4.298 | 0.000 [0.000, 0.000] |
| R3 | B1 | S0 | primary | app | 4.298 | 4.302 | 0.004 [-0.054, 0.048] |
| R3 | B2-Allowlist | S0 | primary | timing | 4.305 | 4.313 | 0.008 [-0.091, 0.071] |
| R3 | B2-Allowlist | S0 | primary | gas | 4.305 | 4.248 | -0.057 [-0.185, -0.001] |
| R3 | B2-Allowlist | S0 | primary | eq | 4.305 | 4.302 | -0.003 [-0.025, 0.015] |
| R3 | B2-Allowlist | S0 | primary | pm | 4.305 | 4.305 | 0.000 [0.000, 0.000] |
| R3 | B2-Allowlist | S0 | primary | app | 4.305 | 4.319 | 0.014 [-0.039, 0.058] |
| R3 | B2-Signature | S0 | primary | timing | 4.279 | 4.290 | 0.011 [-0.033, 0.050] |
| R3 | B2-Signature | S0 | primary | gas | 4.279 | 4.260 | -0.019 [-0.054, 0.001] |
| R3 | B2-Signature | S0 | primary | eq | 4.279 | 4.276 | -0.003 [-0.023, 0.014] |
| R3 | B2-Signature | S0 | primary | pm | 4.279 | 4.279 | 0.000 [0.000, 0.000] |
| R3 | B2-Signature | S0 | primary | app | 4.279 | 4.289 | 0.010 [-0.036, 0.046] |
| R3 | B3-PrivGas-v1 | S0 | primary | timing | 4.266 | 4.276 | 0.010 [-0.031, 0.051] |
| R3 | B3-PrivGas-v1 | S0 | primary | gas | 4.266 | 4.262 | -0.005 [-0.017, 0.005] |
| R3 | B3-PrivGas-v1 | S0 | primary | eq | 4.266 | 4.267 | 0.000 [-0.018, 0.017] |
| R3 | B3-PrivGas-v1 | S0 | primary | pm | 4.266 | 4.266 | 0.000 [0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S0 | primary | app | 4.266 | 4.272 | 0.006 [-0.034, 0.039] |
| R3 | B3-PrivGas-v1 | S1 | primary | timing | 4.372 | 4.278 | -0.094 [-0.341, -0.005] |
| R3 | B3-PrivGas-v1 | S1 | primary | gas | 4.372 | 4.354 | -0.017 [-0.050, 0.002] |
| R3 | B3-PrivGas-v1 | S1 | primary | eq | 4.372 | 4.368 | -0.004 [-0.024, 0.013] |
| R3 | B3-PrivGas-v1 | S1 | primary | pm | 4.372 | 4.372 | 0.000 [0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S1 | primary | app | 4.372 | 4.358 | -0.014 [-0.045, 0.006] |

#### Configuration and scenario holdouts (T+AA+G and T+G-minus-eq)

| relation | baseline | scen. | fold kind | conv. | feature set | subjects | top-1 | CE bits | chance bits |
|---|---|---|---|---|---|---|---|---|---|
| R1 | B0 | S0 | holdout | primary | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.002 [0.002, 0.002] | 5.044 |
| R1 | B0 | S0 | holdout | primary | none | 96 | 0.030 [0.030, 0.030] | 5.044 [5.044, 5.044] | 5.044 |
| R1 | B1 | S0 | holdout | primary | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.044 |
| R1 | B1 | S0 | holdout | primary | none | 96 | 0.030 [0.030, 0.030] | 5.044 [5.044, 5.044] | 5.044 |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+G-minus-eq | 96 | 0.031 [0.000, 0.073] | 5.002 [4.953, 5.054] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+G-minus-eq | 96 | 0.031 [0.000, 0.073] | 5.002 [4.953, 5.054] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+G-minus-eq | 180 | 0.100 [0.045, 0.194] | 8.745 [5.795, 10.440] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+G-minus-eq | 180 | 0.100 [0.045, 0.194] | 8.745 [5.795, 10.440] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+G-minus-eq | 96 | 0.260 [0.177, 0.354] | 2.381 [2.171, 2.630] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+G-minus-eq | 96 | 0.260 [0.177, 0.354] | 2.381 [2.171, 2.630] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+G-minus-eq | 180 | 0.228 [0.134, 0.371] | 4.067 [3.325, 4.439] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+G-minus-eq | 180 | 0.228 [0.134, 0.371] | 4.067 [3.325, 4.439] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R3 | B0 | S0 | holdout | primary | T+AA+G | 96 | 0.052 [0.010, 0.115] | 4.987 [4.967, 5.006] | 5.000 |
| R3 | B0 | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B1 | S0 | holdout | primary | T+AA+G | 96 | 0.042 [0.010, 0.083] | 4.982 [4.963, 5.001] | 5.000 |
| R3 | B1 | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B2-Allowlist | S0 | holdout | primary | T+AA+G | 96 | 0.062 [0.000, 0.135] | 4.984 [4.960, 5.008] | 5.000 |
| R3 | B2-Allowlist | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B2-Signature | S0 | holdout | primary | T+AA+G | 96 | 0.031 [0.000, 0.083] | 4.998 [4.986, 5.011] | 5.000 |
| R3 | B2-Signature | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA+G | 96 | 0.031 [0.000, 0.104] | 5.000 [4.986, 5.017] | 5.000 |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA+G | 180 | 0.072 [0.029, 0.144] | 4.361 [3.682, 4.723] | 4.267 |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA+G | 96 | 0.073 [0.021, 0.146] | 5.010 [4.985, 5.036] | 5.000 |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA+G | 180 | 0.078 [0.036, 0.154] | 4.256 [3.452, 4.650] | 4.267 |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |

#### Audits and stop conditions

| check | result |
|---|---|
| leakage_selfcheck_ok | True |
| harness_public_order_equals_schedule | True |
| harness_order_leak_flags | 4 |
| split_audit_ok | True |
| split_learned_prediction_sets_checked | 3096 |
| r3_above_chance_flags | 0 |
| b3_clean_candidate_set_gt_1 | True |
| runs_failed | 0 |

Harness order audit (combined z over runs; |z| > 3.29 flags):

| baseline | scen. | pair | runs | mean rho | z |
|---|---|---|---|---|---|
| B0 | S0 | deliver~act | 12 | 0.173 | 1.90 |
| B0 | S0 | fund~act | 12 | 0.018 | -0.25 |
| B0 | S0 | slot~act | 12 | 0.064 | 0.98 |
| B0 | S0 | slot~deliver | 12 | 0.009 | 0.88 |
| B0 | S0 | slot~fund | 12 | 0.143 | 0.60 |
| B0 | S0 | slot~setup | 12 | 0.065 | 0.21 |
| B1 | S0 | deliver~act | 12 | 0.173 | 1.90 |
| B1 | S0 | fund~act | 12 | 0.018 | -0.25 |
| B1 | S0 | prepare~act | 12 | 0.001 | 0.03 |
| B1 | S0 | slot~act | 12 | 0.064 | 0.98 |
| B1 | S0 | slot~deliver | 12 | 0.009 | 0.88 |
| B1 | S0 | slot~fund | 12 | 0.143 | 0.60 |
| B1 | S0 | slot~prepare | 12 | -0.040 | -0.00 |
| B1 | S0 | slot~setup | 12 | 0.065 | 0.21 |
| B2-Allowlist | S0 | deliver~act | 12 | 0.173 | 1.90 |
| B2-Allowlist | S0 | fund~act | 12 | 0.018 | -0.25 |
| B2-Allowlist | S0 | prepare~act | 12 | 0.001 | 0.03 |
| B2-Allowlist | S0 | slot~act | 12 | 0.064 | 0.98 |
| B2-Allowlist | S0 | slot~deliver | 12 | 0.009 | 0.88 |
| B2-Allowlist | S0 | slot~fund | 12 | 0.143 | 0.60 |
| B2-Allowlist | S0 | slot~prepare | 12 | -0.040 | -0.00 |
| B2-Allowlist | S0 | slot~setup | 12 | 0.065 | 0.21 |
| B2-Signature | S0 | deliver~act | 12 | 0.173 | 1.90 |
| B2-Signature | S0 | prepare~act | 12 | 0.001 | 0.03 |
| B2-Signature | S0 | slot~act | 12 | 0.064 | 0.98 |
| B2-Signature | S0 | slot~deliver | 12 | 0.009 | 0.88 |
| B2-Signature | S0 | slot~prepare | 12 | -0.040 | -0.00 |
| B2-Signature | S0 | slot~setup | 12 | 0.065 | 0.21 |
| B3-PrivGas-v1 | S0 | deliver~act | 12 | 0.173 | 1.90 |
| B3-PrivGas-v1 | S0 | fund~act | 12 | 0.018 | -0.25 |
| B3-PrivGas-v1 | S0 | issue~act | 12 | 0.087 | 0.79 |
| B3-PrivGas-v1 | S0 | prepare~act | 12 | 0.001 | 0.03 |
| B3-PrivGas-v1 | S0 | slot~act | 12 | 0.064 | 0.98 |
| B3-PrivGas-v1 | S0 | slot~deliver | 12 | 0.009 | 0.88 |
| B3-PrivGas-v1 | S0 | slot~fund | 12 | 0.143 | 0.60 |
| B3-PrivGas-v1 | S0 | slot~issue | 12 | -0.025 | -0.16 |
| B3-PrivGas-v1 | S0 | slot~prepare | 12 | -0.040 | -0.00 |
| B3-PrivGas-v1 | S0 | slot~setup | 12 | 0.065 | 0.21 |
| B3-PrivGas-v1 | S1 | deliver~act | 12 | 0.841 | 10.87 |
| B3-PrivGas-v1 | S1 | fund~act | 12 | 0.841 | 10.87 |
| B3-PrivGas-v1 | S1 | issue~act | 12 | 0.841 | 10.87 |
| B3-PrivGas-v1 | S1 | prepare~act | 12 | 0.841 | 10.87 |
| B3-PrivGas-v1 | S1 | slot~act | 12 | 0.017 | -0.41 |
| B3-PrivGas-v1 | S1 | slot~deliver | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~fund | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~issue | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~prepare | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~setup | 12 | 0.004 | -0.56 |

Figures: `figures/d1-pilot/20260915T120000Z/r2_timing_rules_s0_vs_s1.png`, `figures/d1-pilot/20260915T120000Z/learned_cross_entropy.png`, `figures/d1-pilot/20260915T120000Z/r3_negative_control.png`, `figures/d1-pilot/20260915T120000Z/delta_bits.png`

<!-- END GENERATED: d1-pilot-results -->
