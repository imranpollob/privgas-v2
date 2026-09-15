# D1 final timing sanity experiment: S1b (issuance ↔ redemption timing only)

Status: **complete (2026-09-15); closes the D1 falsification phase.** No defense designed, no
attack added, no novelty or production claim. Labels: **FACT**, **INFERENCE**,
**HYPOTHESIS**, **NEGATIVE RESULT** as in `docs/d1-b4-results.md`. Numbers are quoted from
the generated tables below (batch `20260915T212911Z`, round `a1`, tier A0); the prior S1
rows come from batch `20260915T201434Z` (`docs/d1-b4-results.md`).

- Scheduler: `experiments/workloads/d1/schedule.py` (`S1b-issuance-redemption-timing-only`,
  `s1b_unintended_exposure`), `experiments/workloads/d1/s1b-config.json`
- Gates: runner check `s1b_no_unintended_order_equals_another`;
  `python3 -m experiments.privacy.d1.evaluate schedule-gate`
  (`experiments/privacy/d1/evaluate/schedule_gate.py`, output
  `results/d1-pilot/20260915T212911Z/schedule_gate.json`)
- Tests: `experiments/workloads/d1/tests/test_s1b_static.py`
- Run: `make d1-s1b-run SEED_FILE=data/private/d1-pilot/master_seed.txt BATCH=...`;
  `make d1-s1b-attack BATCH=... ROUND=... COMPARE=results/d1-pilot/<b4 batch>/evaluation-a1`
- Pre-registration: `docs/decision-log.md` "Final D1 timing sanity experiment — S1b"

## 1. Why

In the B4 ablation, S1 drove asset delivery, admission, issuance and action from one arrival
order. Rank-matching the B4 spender's delivery with the issuer's admission recovered 100% of
pairs, so S1 could not isolate issuance → redemption timing. S1b correlates only that
relation.

## 2. S1b scheduler

Per run (seed, N), for B3 and B4 alike (identical schedules at one seed; tested):

1. **Setup** (before the workflow, 12 s blocks): faucet/treasury → asset senders in an
   independent permutation; B4: faucet → issuer funders in another independent permutation.
2. **Delivery**: asset sender → W1T to the (spender) account, independent permutation,
   exponential gaps (mean 600 s); then a 6 h gap.
3. **Admission** (`announceAndFund`): independent permutation, exponential gaps (mean 600 s);
   then a 6 h gap.
4. **Issuance** (Bootstrap): arrival order A (independent permutation), exponential
   inter-arrivals (mean 600 s).
5. **Proof preparation** (off chain, after the last issuance, against the final root):
   independent permutation.
6. **Redemption** (Spend) of actor k at A_k + (A_last − A_first + 6 h) + U(−900, +900) s,
   so redemption order follows issuance order up to local swaps.

Steps 4 and 6 are S1's model with S1's parameters (tested). Account creation cannot be
separated: the issuer account is deployed by its Bootstrap (issuance timing) and the B4
spender account by its Spend (redemption timing). All issuances precede all spends
(single final root, unchanged).

## 3. Scheduler leakage audits

- FACT (static, 400 schedules at N = 16, `test_s1b_static.py`): every pair of orders other
  than issuance~redemption (asset-sender setup, issuer-funder setup, delivery, admission,
  issuance, proof preparation, redemption) and every order vs slot has combined Spearman and
  rank-match |z| < 3.29; issuance~redemption ρ > 0.8.
- FACT (per run): the runner check found no pair of unintended orders identical in any of
  the 18 runs.
- FACT (batch gate, before splits, labels and attacks; public-derived orders equal to the
  private schedule): every unintended pair is at chance. All eight pairs the specification
  names (delivery / admission / asset-sender setup / issuer-funder setup vs issuance /
  redemption), and all other unintended pairs, have |z| ≤ 1.87 for both statistics (e.g.
  B4 delivery~issuance rank-match 0.054 vs chance 0.054; admission~redemption 0.036; setup~
  issuance 0.024; issuer-funder setup~issuance 0.071). No identical orders. The intended
  pair: rank-match 0.417, z = 20.3. **Gate PASSED.**
- FACT (positive control): the same gate on the earlier batch's S1 runs rejects, e.g. B4
  delivery~admission identical in 12/12 runs (rank-match z 48.5).
- FACT: harness order audit 0 flags; leakage self-check clean (72 files); split audit 8 folds,
  no actor overlap, 1,032 learned prediction sets' label provenance verified; R2 candidate
  universe identical for every subject and attack; every B4 run passed every
  account-separation check.

## 4. Matrix and failures

- FACT: B3-PrivGas-v1 and B4-CrossAccount × S1b × N ∈ {8, 16, 32} × 3 replicates = 18 runs;
  18 recorded, 0 failed, 0 retried. No N = 4. Pilot master seed (same actors as the earlier
  batches; independent S1b schedule streams).

## 5. Results (registered attacks, unchanged)

Pooled over N (chance top-1 0.054, chance CE 4.429 bits):

| baseline | FIFO top-1 | window k=2 precision / coverage | timing model T+G-minus-eq top-1 / top-3 / top-5 | CE bits | timing delta_bits | gas/proof-only delta_bits |
|---|---|---|---|---|---|---|
| B3 | 0.417 [0.316, 0.535] | 0.831 [0.766, 0.881] / 0.952 | 0.387 [0.300, 0.482] / 0.851 / 0.952 | 2.161 [1.839, 2.562] | 2.267 [1.524, 2.714] | 0.035 [−0.037, 0.100] |
| B4 | 0.417 [0.316, 0.535] | 0.831 [0.766, 0.881] / 0.952 | 0.363 [0.281, 0.469] / 0.839 / 0.958 | 2.182 [1.885, 2.553] | 2.246 [1.523, 2.656] | 0.002 [−0.020, 0.021] |

- FACT (B3): exact equality rules still select the true issuance with precision 1.000;
  full-trace T+AA+G is exact (CE 0.000). Without equality (T+AA+G-minus-eq) the result is
  the timing level above.
- FACT (B4): no equality rule fires; full trace equals the no-equality model (top-1 0.369,
  CE 2.181). By N: FIFO top-1 0.583 / 0.396 / 0.385 (chance 0.125 / 0.063 / 0.031); timing
  delta_bits (T → T+G-minus-eq) 0.893 [−0.830, 1.999] (N = 8), 1.834 [1.414, 2.217]
  (N = 16), 2.791 [2.506, 3.053] (N = 32). Configuration holdout (train N ≤ 16, test N = 32):
  top-1 0.323, CE 2.576 vs chance 5.000.
- FACT (paired B4 − B3): timing model CE +0.021 [−0.045, 0.085]; top-1 −0.024
  [−0.047, 0.007]; timing rules identical by construction.
- **NEGATIVE RESULT (control holds)**: gas/proof-only `G-minus-eq-minus-timing` stays at
  chance in both baselines (B4 top-1 0.065, CE 4.427 vs 4.429). R3 stays at chance (B4
  T+AA+G top-1 0.054 [0.014, 0.101]; no flag).

## 6. Comparison with prior S1

| baseline | scenario | FIFO top-1 | timing top-1 | timing delta_bits (pooled) | by N: 8 / 16 / 32 |
|---|---|---|---|---|---|
| B4 | S1 (confounded) | 0.433 | 0.339 | 2.163 [1.464, 2.528] | 1.312 / 2.221 / 2.672 |
| B4 | S1b (timing only) | 0.417 | 0.363 | 2.246 [1.523, 2.656] | 0.893 / 1.834 / 2.791 |

Pooled figures are not strictly comparable: S1 included N = 4 (chance 4.267 bits) and S1b
does not (4.429). The N-matched values overlap within their CIs.

- INFERENCE: removing every workflow-order correlation except issuance → redemption leaves
  the registered attacks' linkage unchanged. This matches the hypothesis recorded before the
  data: those attacks never read the confounded delivery/admission channel. The S1 confound
  (100% via delivery ↔ admission) was additional exposure, not the source of the
  registered-attack result.

## 7. Interpretation (rule fixed by the experiment specification)

- Pre-registered criteria: B4 timing delta_bits CI excludes 0 and 2.246 ≥ 0.25 × 4.429 ✓;
  FIFO top-1 CI [0.316, 0.535] above chance by ≥ 0.1 ✓; gas/proof control at chance ✓.
- **Conclusion: B4 remains meaningfully linkable. Issuance → redemption timing alone creates
  residual linkage after account decoupling**, recovering about half of the chance entropy at
  N ≥ 16 under this delay model, in both B3-without-equality and B4.

## 8. Final D1 conclusion (closes the falsification phase)

INFERENCE, across the pilot, the B4 ablation and S1b:

1. B3's issuance ↔ redemption linkage is fully explained by public account coupling
   (Bootstrap sender = Spend sender), which the frozen contracts already let a user avoid.
2. With accounts decoupled and a clean schedule, R2 is at chance on every registered measure.
3. The residual linkage is ordinary timing: issuance → redemption delay correlation alone
   links about half the entropy, and additional workflow-order correlation can link it
   completely.
4. No ERC-4337- or sponsorship-specific observable (Paymaster fields, PVG, gas limits and
   used, fees, roots, commitments, nullifiers, proof metadata) carried held-out R2
   information in any scenario.

Against `docs/research-plan.md` §3 the D1 kill condition is **met**: every measured effect
reduces to trivial account equality or ordinary timing / workflow-order correlation, with no
meaningful ERC-4337-specific boundary. D1 stands as a measurement and negative result, not
as the main contribution. D2 is not started here.

## 9. Unresolved limitations

- One delay model (exponential arrivals, common offset, ±900 s uniform jitter). Linkage
  under heterogeneous or user-chosen delays, and the delay needed to reach chance, are not
  measured; that is ordinary mixing-latency analysis.
- N ≤ 32, 3 replicates; at N = 8 timing delta_bits CIs include 0, while FIFO is clearly above
  chance.
- Account creation cannot be decoupled from the correlated channels (the issuer account is
  deployed at issuance, the B4 spender at redemption).
- Tier A0 only; honest actors; single final root (no contention, which is D2 territory);
  idealised off-chain handoff; minimal application variation; experimental bundler on
  `b3_compat_local`.
- The S1b gate tests rank-order relations and Spearman correlation; it does not rule out
  every conceivable joint timing pattern, though the registered attacks do not read any
  other channel.

## Generated results

<!-- BEGIN GENERATED: d1-s1b-results -->

Batch `20260915T212911Z`, attack round `a1`. Generated by `python3 -m experiments.privacy.d1.evaluate score`; machine-readable tables in `results/d1-pilot/20260915T212911Z/evaluation-a1/`.

#### Dataset

| baseline | scenario | N | runs recorded | runs failed |
|---|---|---|---|---|
| B3-PrivGas-v1 | S1b | 8 | 3 | 0 |
| B3-PrivGas-v1 | S1b | 16 | 3 | 0 |
| B3-PrivGas-v1 | S1b | 32 | 3 | 0 |
| B4-CrossAccount | S1b | 8 | 3 | 0 |
| B4-CrossAccount | S1b | 16 | 3 | 0 |
| B4-CrossAccount | S1b | 32 | 3 | 0 |

#### Candidate sets (per run; identical across replicates)

| baseline | N | R1 public candidates | R1 true funders | R2 candidates | R3 candidates | total commitments | honest commitments | attacker commitments |
|---|---|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | 8 | 1 | 1 | 8 | 8 | 8 | 8 | 0 |
| B3-PrivGas-v1 | 16 | 1 | 1 | 16 | 16 | 16 | 16 | 0 |
| B3-PrivGas-v1 | 32 | 1 | 1 | 32 | 32 | 32 | 32 | 0 |
| B4-CrossAccount | 8 | 1 | 1 | 8 | 8 | 8 | 8 | 0 |
| B4-CrossAccount | 16 | 1 | 1 | 16 | 16 | 16 | 16 | 0 |
| B4-CrossAccount | 32 | 1 | 1 | 32 | 32 | 32 | 32 | 0 |

#### R1 structure (public trace)

| baseline | N | immediate payer | distinct immediate payers | public candidate funders / op | ops with direct account edge | funding shared across ops | R1 classification run |
|---|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | 8 | paymaster_entrypoint_deposit | 1 | 1 | 0/8 | True | False |
| B3-PrivGas-v1 | 16 | paymaster_entrypoint_deposit | 1 | 1 | 0/16 | True | False |
| B3-PrivGas-v1 | 32 | paymaster_entrypoint_deposit | 1 | 1 | 0/32 | True | False |
| B4-CrossAccount | 8 | paymaster_entrypoint_deposit | 1 | 1 | 0/8 | True | False |
| B4-CrossAccount | 16 | paymaster_entrypoint_deposit | 1 | 1 | 0/16 | True | False |
| B4-CrossAccount | 32 | paymaster_entrypoint_deposit | 1 | 1 | 0/32 | True | False |

#### Exact / deterministic rules (pooled over N; 95% CIs)

| relation | baseline | scen. | rule | families | tier | coverage | precision | top-1 | chance top-1 | mean |C| | reduction |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S1b | r2-announcer-eq-asset-sender | T+G | A0 | 1.000 | 1.000 [0.978, 1.000] | 1.000 [1.000, 1.000] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 1.000 | 1.000 [0.978, 1.000] | 1.000 [1.000, 1.000] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-creditspent-sender-eq-depositor | G | A0 | 1.000 | 1.000 [0.978, 1.000] | 1.000 [1.000, 1.000] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-deployed-account-eq-spender | AA+G | A0 | 1.000 | 1.000 [0.978, 1.000] | 1.000 [1.000, 1.000] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-root-match | G | A0 | 1.000 | 0.054 [0.028, 0.099] | 0.054 [0.023, 0.099] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-shared-eth-funder | T+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B3-PrivGas-v1 | S1b | r2-shared-identifier-scan | T+AA+G | A0 | 1.000 | 1.000 [0.978, 1.000] | 1.000 [1.000, 1.000] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.077 [0.046, 0.128] | 0.077 [0.035, 0.133] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-transfer-account-eq-depositor | T+G | A0 | 1.000 | 1.000 [0.978, 1.000] | 1.000 [1.000, 1.000] | 0.054 | 24.0 | 0.946 |
| R2 | B3-PrivGas-v1 | S1b | r2-uniform | none | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-announcer-eq-asset-sender | T+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-creditspent-sender-eq-depositor | G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-deployed-account-eq-spender | AA+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-root-match | G | A0 | 1.000 | 0.054 [0.028, 0.099] | 0.054 [0.023, 0.099] | 0.054 | 24.0 | 0.946 |
| R2 | B4-CrossAccount | S1b | r2-shared-eth-funder | T+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-shared-identifier-scan | T+AA+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.060 [0.033, 0.106] | 0.060 [0.018, 0.119] | 0.054 | 24.0 | 0.946 |
| R2 | B4-CrossAccount | S1b | r2-transfer-account-eq-depositor | T+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R2 | B4-CrossAccount | S1b | r2-uniform | none | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R3 | B3-PrivGas-v1 | S1b | r3-order-match-action | T | A0 | 1.000 | 0.048 [0.024, 0.091] | 0.048 [0.010, 0.108] | 0.054 | 24.0 | 0.946 |
| R3 | B3-PrivGas-v1 | S1b | r3-uniform | none | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R3 | B3-PrivGas-v1 | S1b | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R3 | B4-CrossAccount | S1b | r3-order-match-action | T | A0 | 1.000 | 0.048 [0.024, 0.091] | 0.048 [0.010, 0.108] | 0.054 | 24.0 | 0.946 |
| R3 | B4-CrossAccount | S1b | r3-uniform | none | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |
| R3 | B4-CrossAccount | S1b | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.054 [0.039, 0.080] | 0.054 | 24.0 | – |

#### R2 timing rules by pool size

| baseline | scen. | rule | N | top-1 | top-3 | top-5 | coverage | precision | reduction | chance top-1 |
|---|---|---|---|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | S1b | insertion-order-fifo | 16 | 0.396 | 0.833 | 0.958 | 1.000 | 0.396 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S1b | insertion-order-fifo | 32 | 0.385 | 0.812 | 0.948 | 1.000 | 0.385 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S1b | insertion-order-fifo | 8 | 0.583 | 0.917 | 0.958 | 1.000 | 0.583 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S1b | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S1b | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S1b | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S1b | shuffled-fifo-control | 16 | 0.083 | 0.208 | 0.250 | 1.000 | 0.083 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S1b | shuffled-fifo-control | 32 | 0.062 | 0.125 | 0.198 | 1.000 | 0.062 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S1b | shuffled-fifo-control | 8 | 0.125 | 0.417 | 0.708 | 1.000 | 0.125 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S1b | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| B3-PrivGas-v1 | S1b | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| B3-PrivGas-v1 | S1b | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| B3-PrivGas-v1 | S1b | window-k1 | 16 | 0.240 | 0.771 | 0.979 | 0.875 | 0.524 | 0.868 | 0.062 |
| B3-PrivGas-v1 | S1b | window-k1 | 32 | 0.285 | 0.792 | 0.927 | 0.812 | 0.679 | 0.927 | 0.031 |
| B3-PrivGas-v1 | S1b | window-k1 | 8 | 0.330 | 0.833 | 0.958 | 0.917 | 0.500 | 0.795 | 0.125 |
| B3-PrivGas-v1 | S1b | window-k2 | 16 | 0.263 | 0.771 | 0.979 | 0.958 | 0.826 | 0.784 | 0.062 |
| B3-PrivGas-v1 | S1b | window-k2 | 32 | 0.266 | 0.792 | 0.927 | 0.948 | 0.813 | 0.883 | 0.031 |
| B3-PrivGas-v1 | S1b | window-k2 | 8 | 0.355 | 0.833 | 0.958 | 0.958 | 0.913 | 0.576 | 0.125 |
| B3-PrivGas-v1 | S1b | window-k4 | 16 | 0.197 | 0.771 | 0.979 | 1.000 | 1.000 | 0.638 | 0.062 |
| B3-PrivGas-v1 | S1b | window-k4 | 32 | 0.205 | 0.792 | 0.927 | 1.000 | 0.948 | 0.807 | 0.031 |
| B3-PrivGas-v1 | S1b | window-k4 | 8 | 0.234 | 0.833 | 0.958 | 0.917 | 1.000 | 0.352 | 0.125 |
| B4-CrossAccount | S1b | insertion-order-fifo | 16 | 0.396 | 0.833 | 0.958 | 1.000 | 0.396 | 0.938 | 0.062 |
| B4-CrossAccount | S1b | insertion-order-fifo | 32 | 0.385 | 0.812 | 0.948 | 1.000 | 0.385 | 0.969 | 0.031 |
| B4-CrossAccount | S1b | insertion-order-fifo | 8 | 0.583 | 0.917 | 0.958 | 1.000 | 0.583 | 0.875 | 0.125 |
| B4-CrossAccount | S1b | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| B4-CrossAccount | S1b | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| B4-CrossAccount | S1b | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| B4-CrossAccount | S1b | shuffled-fifo-control | 16 | 0.083 | 0.271 | 0.458 | 1.000 | 0.083 | 0.938 | 0.062 |
| B4-CrossAccount | S1b | shuffled-fifo-control | 32 | 0.042 | 0.083 | 0.115 | 1.000 | 0.042 | 0.969 | 0.031 |
| B4-CrossAccount | S1b | shuffled-fifo-control | 8 | 0.083 | 0.500 | 0.708 | 1.000 | 0.083 | 0.875 | 0.125 |
| B4-CrossAccount | S1b | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| B4-CrossAccount | S1b | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| B4-CrossAccount | S1b | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| B4-CrossAccount | S1b | window-k1 | 16 | 0.240 | 0.771 | 0.979 | 0.875 | 0.524 | 0.868 | 0.062 |
| B4-CrossAccount | S1b | window-k1 | 32 | 0.285 | 0.792 | 0.927 | 0.812 | 0.679 | 0.927 | 0.031 |
| B4-CrossAccount | S1b | window-k1 | 8 | 0.330 | 0.833 | 0.958 | 0.917 | 0.500 | 0.795 | 0.125 |
| B4-CrossAccount | S1b | window-k2 | 16 | 0.263 | 0.771 | 0.979 | 0.958 | 0.826 | 0.784 | 0.062 |
| B4-CrossAccount | S1b | window-k2 | 32 | 0.266 | 0.792 | 0.927 | 0.948 | 0.813 | 0.883 | 0.031 |
| B4-CrossAccount | S1b | window-k2 | 8 | 0.355 | 0.833 | 0.958 | 0.958 | 0.913 | 0.576 | 0.125 |
| B4-CrossAccount | S1b | window-k4 | 16 | 0.197 | 0.771 | 0.979 | 1.000 | 1.000 | 0.638 | 0.062 |
| B4-CrossAccount | S1b | window-k4 | 32 | 0.205 | 0.792 | 0.927 | 1.000 | 0.948 | 0.807 | 0.031 |
| B4-CrossAccount | S1b | window-k4 | 8 | 0.234 | 0.833 | 0.958 | 0.917 | 1.000 | 0.352 | 0.125 |

#### Learned models (conditional logit; L2 chosen by inner CV on training runs; leave-one-replicate-out, pooled N)

| relation | baseline | scen. | conv. | feature set | subjects | top-1 | top-3 | CE bits | chance bits | Brier | ECE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S1b | field_kind | G | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | G-minus-eq | 168 | 0.381 [0.289, 0.475] | 0.839 | 2.160 [1.839, 2.560] | 4.429 | 0.712 | 0.058 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.118] | 0.205 | 4.394 [3.826, 4.754] | 4.429 | 0.945 | 0.008 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA+G | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA+G-minus-app | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA+G-minus-eq | 168 | 0.387 [0.299, 0.482] | 0.851 | 2.160 [1.837, 2.566] | 4.429 | 0.712 | 0.055 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA+G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.118] | 0.205 | 4.394 [3.826, 4.754] | 4.429 | 0.945 | 0.008 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA+G-minus-gas | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA+G-minus-pm | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+AA+G-minus-timing | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+G | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+G-minus-eq | 168 | 0.387 [0.300, 0.482] | 0.851 | 2.161 [1.839, 2.562] | 4.429 | 0.712 | 0.051 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | T+G-minus-timing | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | field_kind | none | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | G | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | G-minus-eq | 168 | 0.381 [0.289, 0.475] | 0.839 | 2.160 [1.839, 2.560] | 4.429 | 0.712 | 0.058 |
| R2 | B3-PrivGas-v1 | S1b | primary | G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.118] | 0.205 | 4.394 [3.826, 4.754] | 4.429 | 0.945 | 0.008 |
| R2 | B3-PrivGas-v1 | S1b | primary | T | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA+G | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-app | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-eq | 168 | 0.387 [0.299, 0.482] | 0.851 | 2.160 [1.837, 2.566] | 4.429 | 0.712 | 0.055 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.118] | 0.205 | 4.394 [3.826, 4.754] | 4.429 | 0.945 | 0.008 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-gas | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-pm | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-timing | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+G | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+G-minus-eq | 168 | 0.387 [0.300, 0.482] | 0.851 | 2.161 [1.839, 2.562] | 4.429 | 0.712 | 0.051 |
| R2 | B3-PrivGas-v1 | S1b | primary | T+G-minus-timing | 168 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.429 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1b | primary | none | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B4-CrossAccount | S1b | field_kind | G | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | field_kind | G-minus-eq | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | field_kind | G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | field_kind | T | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA | 168 | 0.417 [0.316, 0.535] | 0.833 | 2.409 [2.044, 2.819] | 4.429 | 0.755 | 0.132 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA+G | 168 | 0.369 [0.282, 0.475] | 0.839 | 2.181 [1.882, 2.557] | 4.429 | 0.724 | 0.069 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA+G-minus-app | 168 | 0.369 [0.282, 0.475] | 0.839 | 2.181 [1.882, 2.557] | 4.429 | 0.724 | 0.069 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA+G-minus-eq | 168 | 0.369 [0.282, 0.475] | 0.839 | 2.181 [1.882, 2.557] | 4.429 | 0.724 | 0.069 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA+G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA+G-minus-gas | 168 | 0.363 [0.275, 0.464] | 0.839 | 2.166 [1.875, 2.536] | 4.429 | 0.723 | 0.072 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA+G-minus-pm | 168 | 0.363 [0.276, 0.473] | 0.839 | 2.177 [1.879, 2.553] | 4.429 | 0.723 | 0.076 |
| R2 | B4-CrossAccount | S1b | field_kind | T+AA+G-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | field_kind | T+G | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | field_kind | T+G-minus-eq | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | field_kind | T+G-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | field_kind | none | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B4-CrossAccount | S1b | primary | G | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | primary | G-minus-eq | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | primary | G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | primary | T | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B4-CrossAccount | S1b | primary | T+AA | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R2 | B4-CrossAccount | S1b | primary | T+AA+G | 168 | 0.369 [0.282, 0.475] | 0.839 | 2.181 [1.882, 2.557] | 4.429 | 0.724 | 0.069 |
| R2 | B4-CrossAccount | S1b | primary | T+AA+G-minus-app | 168 | 0.369 [0.282, 0.475] | 0.839 | 2.181 [1.882, 2.557] | 4.429 | 0.724 | 0.069 |
| R2 | B4-CrossAccount | S1b | primary | T+AA+G-minus-eq | 168 | 0.369 [0.282, 0.475] | 0.839 | 2.181 [1.882, 2.557] | 4.429 | 0.724 | 0.069 |
| R2 | B4-CrossAccount | S1b | primary | T+AA+G-minus-eq-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | primary | T+AA+G-minus-gas | 168 | 0.363 [0.275, 0.464] | 0.839 | 2.166 [1.875, 2.536] | 4.429 | 0.723 | 0.072 |
| R2 | B4-CrossAccount | S1b | primary | T+AA+G-minus-pm | 168 | 0.363 [0.276, 0.473] | 0.839 | 2.177 [1.879, 2.553] | 4.429 | 0.723 | 0.076 |
| R2 | B4-CrossAccount | S1b | primary | T+AA+G-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | primary | T+G | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | primary | T+G-minus-eq | 168 | 0.363 [0.281, 0.469] | 0.839 | 2.182 [1.885, 2.553] | 4.429 | 0.725 | 0.070 |
| R2 | B4-CrossAccount | S1b | primary | T+G-minus-timing | 168 | 0.065 [0.023, 0.133] | 0.196 | 4.427 [3.833, 4.790] | 4.429 | 0.946 | 0.005 |
| R2 | B4-CrossAccount | S1b | primary | none | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R3 | B3-PrivGas-v1 | S1b | primary | G | 168 | 0.065 [0.023, 0.118] | 0.185 | 4.440 [3.877, 4.795] | 4.429 | 0.948 | 0.009 |
| R3 | B3-PrivGas-v1 | S1b | primary | T | 168 | 0.060 [0.022, 0.100] | 0.202 | 4.423 [3.842, 4.777] | 4.429 | 0.947 | 0.009 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+AA | 168 | 0.065 [0.028, 0.107] | 0.202 | 4.420 [3.838, 4.777] | 4.429 | 0.947 | 0.001 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+AA+G | 168 | 0.042 [0.009, 0.085] | 0.179 | 4.451 [3.892, 4.790] | 4.429 | 0.951 | 0.031 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-app | 168 | 0.054 [0.017, 0.108] | 0.173 | 4.457 [3.903, 4.797] | 4.429 | 0.951 | 0.015 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-eq | 168 | 0.048 [0.012, 0.092] | 0.155 | 4.447 [3.887, 4.791] | 4.429 | 0.950 | 0.020 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-gas | 168 | 0.060 [0.020, 0.103] | 0.202 | 4.431 [3.835, 4.776] | 4.429 | 0.948 | 0.012 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-pm | 168 | 0.042 [0.009, 0.085] | 0.179 | 4.451 [3.892, 4.790] | 4.429 | 0.951 | 0.031 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+AA+G-minus-timing | 168 | 0.060 [0.025, 0.110] | 0.167 | 4.457 [3.910, 4.801] | 4.429 | 0.950 | 0.006 |
| R3 | B3-PrivGas-v1 | S1b | primary | T+G | 168 | 0.060 [0.019, 0.103] | 0.179 | 4.450 [3.888, 4.789] | 4.429 | 0.950 | 0.012 |
| R3 | B3-PrivGas-v1 | S1b | primary | none | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |
| R3 | B4-CrossAccount | S1b | primary | G | 168 | 0.036 [0.007, 0.071] | 0.146 | 4.440 [3.861, 4.800] | 4.429 | 0.947 | 0.022 |
| R3 | B4-CrossAccount | S1b | primary | T | 168 | 0.060 [0.022, 0.100] | 0.202 | 4.423 [3.842, 4.777] | 4.429 | 0.947 | 0.009 |
| R3 | B4-CrossAccount | S1b | primary | T+AA | 168 | 0.065 [0.028, 0.107] | 0.202 | 4.420 [3.838, 4.777] | 4.429 | 0.947 | 0.001 |
| R3 | B4-CrossAccount | S1b | primary | T+AA+G | 168 | 0.054 [0.014, 0.101] | 0.179 | 4.430 [3.853, 4.785] | 4.429 | 0.947 | 0.011 |
| R3 | B4-CrossAccount | S1b | primary | T+AA+G-minus-app | 168 | 0.048 [0.010, 0.108] | 0.155 | 4.432 [3.850, 4.795] | 4.429 | 0.947 | 0.011 |
| R3 | B4-CrossAccount | S1b | primary | T+AA+G-minus-eq | 168 | 0.054 [0.011, 0.117] | 0.185 | 4.430 [3.852, 4.790] | 4.429 | 0.947 | 0.007 |
| R3 | B4-CrossAccount | S1b | primary | T+AA+G-minus-gas | 168 | 0.065 [0.028, 0.107] | 0.202 | 4.420 [3.838, 4.777] | 4.429 | 0.947 | 0.001 |
| R3 | B4-CrossAccount | S1b | primary | T+AA+G-minus-pm | 168 | 0.054 [0.014, 0.101] | 0.179 | 4.430 [3.853, 4.785] | 4.429 | 0.947 | 0.011 |
| R3 | B4-CrossAccount | S1b | primary | T+AA+G-minus-timing | 168 | 0.036 [0.006, 0.068] | 0.131 | 4.440 [3.866, 4.793] | 4.429 | 0.948 | 0.027 |
| R3 | B4-CrossAccount | S1b | primary | T+G | 168 | 0.054 [0.017, 0.099] | 0.167 | 4.431 [3.855, 4.785] | 4.429 | 0.947 | 0.010 |
| R3 | B4-CrossAccount | S1b | primary | none | 168 | 0.054 [0.039, 0.080] | 0.161 | 4.429 [3.857, 4.793] | 4.429 | 0.946 | 0.000 |

#### delta_bits (held-out CE difference in bits; paired cluster bootstrap 95% CI)

| relation | baseline | scen. | fold | conv. | from | to | CE from | CE to | delta_bits [CI] |
|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | G | 5.000 | 0.003 | 4.997 [4.997, 4.997] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T | T+AA | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.999] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T+AA | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | G-minus-eq | 5.000 | 2.516 | 2.484 [2.279, 2.693] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | T+G-minus-eq | 5.000 | 2.516 | 2.484 [2.279, 2.693] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T | T+G-minus-eq | 5.000 | 2.516 | 2.484 [2.279, 2.693] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | T+AA+G-minus-eq | 5.000 | 2.512 | 2.488 [2.280, 2.699] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | G-minus-eq-minus-timing | 5.000 | 4.997 | 0.003 [-0.023, 0.028] |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | T+AA+G-minus-eq-minus-timing | 5.000 | 4.997 | 0.003 [-0.023, 0.028] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | G | 5.000 | 0.003 | 4.997 [4.997, 4.997] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.999] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T+AA | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | G-minus-eq | 5.000 | 2.516 | 2.484 [2.279, 2.693] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | T+G-minus-eq | 5.000 | 2.516 | 2.484 [2.279, 2.693] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T | T+G-minus-eq | 5.000 | 2.516 | 2.484 [2.279, 2.693] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 2.512 | 2.488 [2.280, 2.699] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | G-minus-eq-minus-timing | 5.000 | 4.997 | 0.003 [-0.023, 0.028] |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | T+AA+G-minus-eq-minus-timing | 5.000 | 4.997 | 0.003 [-0.023, 0.028] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | T | 4.429 | 4.429 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | G | 4.429 | 0.001 | 4.428 [3.800, 4.792] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | T | T+AA | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | T | T+G | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | T | T+AA+G | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | G-minus-eq | 4.429 | 2.160 | 2.268 [1.518, 2.714] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | T+G-minus-eq | 4.429 | 2.161 | 2.267 [1.524, 2.714] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | T | T+G-minus-eq | 4.429 | 2.161 | 2.267 [1.524, 2.714] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | T+G-minus-timing | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | T+AA+G-minus-eq | 4.429 | 2.160 | 2.268 [1.527, 2.715] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | G-minus-eq-minus-timing | 4.429 | 4.394 | 0.035 [-0.037, 0.100] |
| R2 | B3-PrivGas-v1 | S1b | loro | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.429 | 4.394 | 0.035 [-0.037, 0.100] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | T | 4.429 | 4.429 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | G | 4.429 | 0.001 | 4.428 [3.800, 4.792] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | T | T+AA | 4.429 | 4.429 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | T | T+G | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | T+AA | T+AA+G | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | T | T+AA+G | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | G-minus-eq | 4.429 | 2.160 | 2.268 [1.518, 2.714] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | T+G-minus-eq | 4.429 | 2.161 | 2.267 [1.524, 2.714] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | T | T+G-minus-eq | 4.429 | 2.161 | 2.267 [1.524, 2.714] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | T+G-minus-timing | 4.429 | 0.000 | 4.428 [3.800, 4.793] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | T+AA+G-minus-eq | 4.429 | 2.160 | 2.268 [1.527, 2.715] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | G-minus-eq-minus-timing | 4.429 | 4.394 | 0.035 [-0.037, 0.100] |
| R2 | B3-PrivGas-v1 | S1b | loro | primary | none | T+AA+G-minus-eq-minus-timing | 4.429 | 4.394 | 0.035 [-0.037, 0.100] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | G | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T | T+AA | 5.000 | 2.888 | 2.112 [1.931, 2.276] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T | T+G | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T+AA | T+AA+G | 2.888 | 2.572 | 0.315 [0.230, 0.399] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T | T+AA+G | 5.000 | 2.572 | 2.428 [2.232, 2.595] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T+G | T+AA+G | 2.576 | 2.572 | 0.004 [-0.003, 0.010] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | G-minus-eq | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | T+G-minus-eq | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T | T+G-minus-eq | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | T+G-minus-timing | 5.000 | 5.007 | -0.007 [-0.038, 0.018] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | T+AA+G-minus-eq | 5.000 | 2.572 | 2.428 [2.232, 2.595] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | G-minus-eq-minus-timing | 5.000 | 5.007 | -0.007 [-0.038, 0.018] |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.007 | -0.007 [-0.038, 0.018] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | G | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | holdout | primary | T | T+G | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | primary | T+AA | T+AA+G | 5.000 | 2.572 | 2.428 [2.232, 2.595] |
| R2 | B4-CrossAccount | S1b | holdout | primary | T | T+AA+G | 5.000 | 2.572 | 2.428 [2.232, 2.595] |
| R2 | B4-CrossAccount | S1b | holdout | primary | T+G | T+AA+G | 2.576 | 2.572 | 0.004 [-0.003, 0.010] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | G-minus-eq | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | T+G-minus-eq | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | primary | T | T+G-minus-eq | 5.000 | 2.576 | 2.424 [2.234, 2.589] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | T+G-minus-timing | 5.000 | 5.007 | -0.007 [-0.038, 0.018] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 2.572 | 2.428 [2.232, 2.595] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | G-minus-eq-minus-timing | 5.000 | 5.007 | -0.007 [-0.038, 0.018] |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.007 | -0.007 [-0.038, 0.018] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | T | 4.429 | 4.429 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | G | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | T | T+AA | 4.429 | 2.409 | 2.020 [1.329, 2.435] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | T | T+G | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | T+AA | T+AA+G | 2.409 | 2.181 | 0.228 [0.078, 0.350] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | T | T+AA+G | 4.429 | 2.181 | 2.247 [1.520, 2.658] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | T+G | T+AA+G | 2.182 | 2.181 | 0.001 [-0.005, 0.008] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | G-minus-eq | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | T+G-minus-eq | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | T | T+G-minus-eq | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | T+G-minus-timing | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | T+AA+G-minus-eq | 4.429 | 2.181 | 2.247 [1.520, 2.658] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | G-minus-eq-minus-timing | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| R2 | B4-CrossAccount | S1b | loro | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | T | 4.429 | 4.429 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | G | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | primary | T | T+AA | 4.429 | 4.429 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | loro | primary | T | T+G | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | primary | T+AA | T+AA+G | 4.429 | 2.181 | 2.247 [1.520, 2.658] |
| R2 | B4-CrossAccount | S1b | loro | primary | T | T+AA+G | 4.429 | 2.181 | 2.247 [1.520, 2.658] |
| R2 | B4-CrossAccount | S1b | loro | primary | T+G | T+AA+G | 2.182 | 2.181 | 0.001 [-0.005, 0.008] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | G-minus-eq | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | T+G-minus-eq | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | primary | T | T+G-minus-eq | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | T+G-minus-timing | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | T+AA+G-minus-eq | 4.429 | 2.181 | 2.247 [1.520, 2.658] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | G-minus-eq-minus-timing | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| R2 | B4-CrossAccount | S1b | loro | primary | none | T+AA+G-minus-eq-minus-timing | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | none | T | 5.000 | 4.999 | 0.001 [-0.015, 0.015] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | none | G | 5.000 | 4.998 | 0.002 [-0.021, 0.028] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | T | T+AA | 4.999 | 4.998 | 0.001 [-0.004, 0.007] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | T | T+G | 4.999 | 5.003 | -0.003 [-0.023, 0.018] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | T+AA | T+AA+G | 4.998 | 5.003 | -0.005 [-0.023, 0.016] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | T | T+AA+G | 4.999 | 5.003 | -0.003 [-0.024, 0.020] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | T+G | T+AA+G | 5.003 | 5.003 | 0.000 [-0.003, 0.003] |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 4.998 | 0.002 [-0.027, 0.032] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | none | T | 4.429 | 4.423 | 0.005 [-0.029, 0.035] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | none | G | 4.429 | 4.440 | -0.011 [-0.067, 0.025] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | T | T+AA | 4.423 | 4.420 | 0.003 [-0.006, 0.013] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | T | T+G | 4.423 | 4.450 | -0.026 [-0.100, 0.014] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | T+AA | T+AA+G | 4.420 | 4.451 | -0.032 [-0.110, 0.010] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | T | T+AA+G | 4.423 | 4.451 | -0.028 [-0.105, 0.015] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | T+G | T+AA+G | 4.450 | 4.451 | -0.002 [-0.007, 0.001] |
| R3 | B3-PrivGas-v1 | S1b | loro | primary | none | T+AA+G-minus-eq | 4.429 | 4.447 | -0.019 [-0.101, 0.031] |
| R3 | B4-CrossAccount | S1b | holdout | primary | none | T | 5.000 | 4.999 | 0.001 [-0.015, 0.015] |
| R3 | B4-CrossAccount | S1b | holdout | primary | none | G | 5.000 | 5.002 | -0.002 [-0.016, 0.012] |
| R3 | B4-CrossAccount | S1b | holdout | primary | T | T+AA | 4.999 | 4.998 | 0.001 [-0.004, 0.007] |
| R3 | B4-CrossAccount | S1b | holdout | primary | T | T+G | 4.999 | 5.001 | -0.002 [-0.014, 0.010] |
| R3 | B4-CrossAccount | S1b | holdout | primary | T+AA | T+AA+G | 4.998 | 5.000 | -0.002 [-0.014, 0.010] |
| R3 | B4-CrossAccount | S1b | holdout | primary | T | T+AA+G | 4.999 | 5.000 | -0.000 [-0.014, 0.013] |
| R3 | B4-CrossAccount | S1b | holdout | primary | T+G | T+AA+G | 5.001 | 5.000 | 0.001 [-0.004, 0.007] |
| R3 | B4-CrossAccount | S1b | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 4.996 | 0.004 [-0.020, 0.028] |
| R3 | B4-CrossAccount | S1b | loro | primary | none | T | 4.429 | 4.423 | 0.005 [-0.029, 0.035] |
| R3 | B4-CrossAccount | S1b | loro | primary | none | G | 4.429 | 4.440 | -0.011 [-0.024, 0.001] |
| R3 | B4-CrossAccount | S1b | loro | primary | T | T+AA | 4.423 | 4.420 | 0.003 [-0.006, 0.013] |
| R3 | B4-CrossAccount | S1b | loro | primary | T | T+G | 4.423 | 4.431 | -0.008 [-0.026, 0.008] |
| R3 | B4-CrossAccount | S1b | loro | primary | T+AA | T+AA+G | 4.420 | 4.430 | -0.010 [-0.024, 0.003] |
| R3 | B4-CrossAccount | S1b | loro | primary | T | T+AA+G | 4.423 | 4.430 | -0.007 [-0.024, 0.007] |
| R3 | B4-CrossAccount | S1b | loro | primary | T+G | T+AA+G | 4.431 | 4.430 | 0.001 [-0.003, 0.005] |
| R3 | B4-CrossAccount | S1b | loro | primary | none | T+AA+G-minus-eq | 4.429 | 4.430 | -0.001 [-0.026, 0.021] |

#### Feature-family ablations of T+AA+G (positive = the removed family carried held-out information)

| relation | baseline | scen. | conv. | removed | CE full | CE without | delta_bits [CI] |
|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S1b | field_kind | timing | 0.000 | 0.000 | 0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | field_kind | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | field_kind | eq | 0.000 | 2.160 | 2.160 [1.836, 2.538] |
| R2 | B3-PrivGas-v1 | S1b | field_kind | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | field_kind | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | primary | timing | 0.000 | 0.000 | 0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | primary | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | primary | eq | 0.000 | 2.160 | 2.160 [1.836, 2.538] |
| R2 | B3-PrivGas-v1 | S1b | primary | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1b | primary | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | field_kind | timing | 2.181 | 4.427 | 2.245 [1.526, 2.660] |
| R2 | B4-CrossAccount | S1b | field_kind | gas | 2.181 | 2.166 | -0.015 [-0.055, 0.029] |
| R2 | B4-CrossAccount | S1b | field_kind | eq | 2.181 | 2.181 | -0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | field_kind | pm | 2.181 | 2.177 | -0.005 [-0.016, 0.004] |
| R2 | B4-CrossAccount | S1b | field_kind | app | 2.181 | 2.181 | -0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | primary | timing | 2.181 | 4.427 | 2.245 [1.526, 2.660] |
| R2 | B4-CrossAccount | S1b | primary | gas | 2.181 | 2.166 | -0.015 [-0.055, 0.029] |
| R2 | B4-CrossAccount | S1b | primary | eq | 2.181 | 2.181 | -0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1b | primary | pm | 2.181 | 2.177 | -0.005 [-0.016, 0.004] |
| R2 | B4-CrossAccount | S1b | primary | app | 2.181 | 2.181 | -0.000 [-0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S1b | primary | timing | 4.451 | 4.457 | 0.005 [-0.050, 0.044] |
| R3 | B3-PrivGas-v1 | S1b | primary | gas | 4.451 | 4.431 | -0.021 [-0.059, 0.002] |
| R3 | B3-PrivGas-v1 | S1b | primary | eq | 4.451 | 4.447 | -0.004 [-0.024, 0.012] |
| R3 | B3-PrivGas-v1 | S1b | primary | pm | 4.451 | 4.451 | 0.000 [0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S1b | primary | app | 4.451 | 4.457 | 0.005 [-0.015, 0.027] |
| R3 | B4-CrossAccount | S1b | primary | timing | 4.430 | 4.440 | 0.009 [-0.010, 0.027] |
| R3 | B4-CrossAccount | S1b | primary | gas | 4.430 | 4.420 | -0.010 [-0.024, 0.003] |
| R3 | B4-CrossAccount | S1b | primary | eq | 4.430 | 4.430 | -0.000 [-0.014, 0.011] |
| R3 | B4-CrossAccount | S1b | primary | pm | 4.430 | 4.430 | 0.000 [0.000, 0.000] |
| R3 | B4-CrossAccount | S1b | primary | app | 4.430 | 4.432 | 0.002 [-0.015, 0.018] |

#### Configuration and scenario holdouts (T+AA+G and T+G-minus-eq)

| relation | baseline | scen. | fold kind | conv. | feature set | subjects | top-1 | CE bits | chance bits |
|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | T+G-minus-eq | 96 | 0.333 [0.198, 0.469] | 2.516 [2.306, 2.723] | 5.000 |
| R2 | B3-PrivGas-v1 | S1b | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | T+G-minus-eq | 96 | 0.333 [0.198, 0.469] | 2.516 [2.306, 2.723] | 5.000 |
| R2 | B3-PrivGas-v1 | S1b | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T+AA+G | 96 | 0.312 [0.188, 0.427] | 2.572 [2.410, 2.785] | 5.000 |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | T+G-minus-eq | 96 | 0.323 [0.208, 0.438] | 2.576 [2.415, 2.785] | 5.000 |
| R2 | B4-CrossAccount | S1b | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B4-CrossAccount | S1b | holdout | primary | T+AA+G | 96 | 0.312 [0.188, 0.427] | 2.572 [2.410, 2.785] | 5.000 |
| R2 | B4-CrossAccount | S1b | holdout | primary | T+G-minus-eq | 96 | 0.323 [0.208, 0.438] | 2.576 [2.415, 2.785] | 5.000 |
| R2 | B4-CrossAccount | S1b | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | T+AA+G | 96 | 0.010 [0.000, 0.042] | 5.003 [4.971, 5.034] | 5.000 |
| R3 | B3-PrivGas-v1 | S1b | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B4-CrossAccount | S1b | holdout | primary | T+AA+G | 96 | 0.010 [0.000, 0.042] | 5.000 [4.977, 5.026] | 5.000 |
| R3 | B4-CrossAccount | S1b | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |

#### Audits and stop conditions

| check | result |
|---|---|
| leakage_selfcheck_ok | True |
| harness_public_order_equals_schedule | True |
| harness_order_leak_flags | 0 |
| split_audit_ok | True |
| split_learned_prediction_sets_checked | 1032 |
| r3_above_chance_flags | 0 |
| b3_clean_candidate_set_gt_1 | True |
| runs_failed | 0 |
| b4_account_separation_ok | True |
| r2_candidate_universe_identical_across_attacks | True |

Harness order audit (combined z over runs; |z| > 3.29 flags):

| baseline | scen. | pair | runs | mean rho | z |
|---|---|---|---|---|---|
| B3-PrivGas-v1 | S1b | deliver~act | 9 | -0.056 | -0.42 |
| B3-PrivGas-v1 | S1b | fund~act | 9 | -0.014 | 0.48 |
| B3-PrivGas-v1 | S1b | issue~act | 9 | 0.954 | 11.66 |
| B3-PrivGas-v1 | S1b | issue~prepare | 9 | -0.075 | -0.86 |
| B3-PrivGas-v1 | S1b | prepare~act | 9 | -0.085 | -0.86 |
| B3-PrivGas-v1 | S1b | slot~act | 9 | -0.105 | -1.29 |
| B3-PrivGas-v1 | S1b | slot~deliver | 9 | -0.108 | -0.82 |
| B3-PrivGas-v1 | S1b | slot~fund | 9 | 0.117 | 1.41 |
| B3-PrivGas-v1 | S1b | slot~issue | 9 | -0.066 | -1.09 |
| B3-PrivGas-v1 | S1b | slot~prepare | 9 | 0.184 | 2.29 |
| B3-PrivGas-v1 | S1b | slot~setup | 9 | 0.042 | 0.60 |
| B4-CrossAccount | S1b | deliver~act | 9 | -0.056 | -0.42 |
| B4-CrossAccount | S1b | fund~act | 9 | -0.014 | 0.48 |
| B4-CrossAccount | S1b | issue~act | 9 | 0.954 | 11.66 |
| B4-CrossAccount | S1b | issue~prepare | 9 | -0.075 | -0.86 |
| B4-CrossAccount | S1b | prepare~act | 9 | -0.085 | -0.86 |
| B4-CrossAccount | S1b | setup_issuer~act | 9 | -0.002 | 0.22 |
| B4-CrossAccount | S1b | setup_issuer~deliver | 9 | 0.082 | 0.22 |
| B4-CrossAccount | S1b | setup~setup_issuer | 9 | -0.009 | 0.28 |
| B4-CrossAccount | S1b | slot~act | 9 | -0.105 | -1.29 |
| B4-CrossAccount | S1b | slot~deliver | 9 | -0.108 | -0.82 |
| B4-CrossAccount | S1b | slot~fund | 9 | 0.117 | 1.41 |
| B4-CrossAccount | S1b | slot~issue | 9 | -0.066 | -1.09 |
| B4-CrossAccount | S1b | slot~prepare | 9 | 0.184 | 2.29 |
| B4-CrossAccount | S1b | slot~setup | 9 | 0.042 | 0.60 |
| B4-CrossAccount | S1b | slot~setup_issuer | 9 | -0.054 | -0.36 |

Figures: `figures/d1-pilot/20260915T212911Z/r2_timing_rules_s0_vs_s1.png`, `figures/d1-pilot/20260915T212911Z/r2_timing_rules_s0_vs_s1_b4.png`, `figures/d1-pilot/20260915T212911Z/learned_cross_entropy.png`, `figures/d1-pilot/20260915T212911Z/r3_negative_control.png`, `figures/d1-pilot/20260915T212911Z/delta_bits.png`

#### Paired B3-PrivGas-v1 vs B4-CrossAccount (run pairs matched on scenario, N, replicate; subject-weighted; 95% bootstrap CI over run pairs)

| scen. | comparison | run pairs | B3 | B4 | chance | B4 − B3 [CI] |
|---|---|---|---|---|---|---|
| S1b | exact: Bootstrap sender == Spend sender | 9 | 1.000 | 0.054 | 0.054 | -0.946 [-0.960, -0.920] |
| S1b | exact: CreditSpent sender == depositor | 9 | 1.000 | 0.054 | 0.054 | -0.946 [-0.960, -0.920] |
| S1b | exact: announcer == asset sender | 9 | 1.000 | 0.054 | 0.054 | -0.946 [-0.961, -0.920] |
| S1b | exact: shared-identifier scan | 9 | 1.000 | 0.054 | 0.054 | -0.946 [-0.961, -0.920] |
| S1b | timing: insertion-order FIFO | 9 | 0.417 | 0.417 | 0.054 | 0.000 [0.000, 0.000] |
| S1b | timing: common-delay window k=2 | 9 | 0.278 | 0.278 | 0.054 | 0.000 [0.000, 0.000] |
| S1b | learned full trace T+AA+G: top-1 | 9 | 1.000 | 0.369 | 0.054 | -0.631 [-0.696, -0.547] |
| S1b | learned full trace T+AA+G: CE bits | 9 | 0.000 | 2.181 | 4.429 | 2.181 [1.941, 2.441] |
| S1b | learned no-equality T+AA+G-minus-eq: top-1 | 9 | 0.387 | 0.369 | 0.054 | -0.018 [-0.045, 0.012] |
| S1b | learned no-equality T+AA+G-minus-eq: CE bits | 9 | 2.160 | 2.181 | 4.429 | 0.021 [-0.047, 0.085] |
| S1b | learned timing T+G-minus-eq: top-1 | 9 | 0.387 | 0.363 | 0.054 | -0.024 [-0.047, 0.007] |
| S1b | learned timing T+G-minus-eq: CE bits | 9 | 2.161 | 2.182 | 4.429 | 0.021 [-0.045, 0.085] |
| S1b | learned G-minus-eq (gas+proof+timing): CE bits | 9 | 2.160 | 2.182 | 4.429 | 0.022 [-0.045, 0.085] |
| S1b | learned gas/proof only G-minus-eq-minus-timing: top-1 | 9 | 0.065 | 0.065 | 0.054 | 0.000 [-0.028, 0.042] |
| S1b | learned gas/proof only G-minus-eq-minus-timing: CE bits | 9 | 4.394 | 4.427 | 4.429 | 0.033 [-0.025, 0.088] |
| S1b | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 9 | 4.394 | 4.427 | 4.429 | 0.033 [-0.025, 0.091] |
| S1b | learned no timing T+G-minus-timing: CE bits | 9 | 0.000 | 4.427 | 4.429 | 4.426 [3.790, 4.788] |

#### Paired comparison by pool size (mean over replicates)

| scen. | N | comparison | B3 | B4 | chance |
|---|---|---|---|---|---|
| S1b | 8 | exact: Bootstrap sender == Spend sender | 1.000 | 0.125 | 0.125 |
| S1b | 8 | exact: CreditSpent sender == depositor | 1.000 | 0.125 | 0.125 |
| S1b | 8 | exact: announcer == asset sender | 1.000 | 0.125 | 0.125 |
| S1b | 8 | exact: shared-identifier scan | 1.000 | 0.125 | 0.125 |
| S1b | 8 | timing: insertion-order FIFO | 0.583 | 0.583 | 0.125 |
| S1b | 8 | timing: common-delay window k=2 | 0.355 | 0.355 | 0.125 |
| S1b | 8 | learned full trace T+AA+G: top-1 | 1.000 | 0.500 | 0.125 |
| S1b | 8 | learned full trace T+AA+G: CE bits | 0.000 | 2.105 | 3.000 |
| S1b | 8 | learned no-equality T+AA+G-minus-eq: top-1 | 0.542 | 0.500 | 0.125 |
| S1b | 8 | learned no-equality T+AA+G-minus-eq: CE bits | 2.069 | 2.105 | 3.000 |
| S1b | 8 | learned timing T+G-minus-eq: top-1 | 0.542 | 0.500 | 0.125 |
| S1b | 8 | learned timing T+G-minus-eq: CE bits | 2.071 | 2.107 | 3.000 |
| S1b | 8 | learned G-minus-eq (gas+proof+timing): CE bits | 2.072 | 2.107 | 3.000 |
| S1b | 8 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.125 | 0.167 | 0.125 |
| S1b | 8 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 3.028 | 2.995 | 3.000 |
| S1b | 8 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 3.028 | 2.995 | 3.000 |
| S1b | 8 | learned no timing T+G-minus-timing: CE bits | 0.000 | 2.995 | 3.000 |
| S1b | 16 | exact: Bootstrap sender == Spend sender | 1.000 | 0.062 | 0.062 |
| S1b | 16 | exact: CreditSpent sender == depositor | 1.000 | 0.062 | 0.062 |
| S1b | 16 | exact: announcer == asset sender | 1.000 | 0.062 | 0.062 |
| S1b | 16 | exact: shared-identifier scan | 1.000 | 0.062 | 0.062 |
| S1b | 16 | timing: insertion-order FIFO | 0.396 | 0.396 | 0.062 |
| S1b | 16 | timing: common-delay window k=2 | 0.263 | 0.263 | 0.062 |
| S1b | 16 | learned full trace T+AA+G: top-1 | 1.000 | 0.354 | 0.062 |
| S1b | 16 | learned full trace T+AA+G: CE bits | 0.000 | 2.167 | 4.000 |
| S1b | 16 | learned no-equality T+AA+G-minus-eq: top-1 | 0.333 | 0.354 | 0.062 |
| S1b | 16 | learned no-equality T+AA+G-minus-eq: CE bits | 2.200 | 2.167 | 4.000 |
| S1b | 16 | learned timing T+G-minus-eq: top-1 | 0.312 | 0.333 | 0.062 |
| S1b | 16 | learned timing T+G-minus-eq: CE bits | 2.199 | 2.166 | 4.000 |
| S1b | 16 | learned G-minus-eq (gas+proof+timing): CE bits | 2.196 | 2.166 | 4.000 |
| S1b | 16 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.042 | 0.083 | 0.062 |
| S1b | 16 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 3.976 | 3.999 | 4.000 |
| S1b | 16 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 3.976 | 3.999 | 4.000 |
| S1b | 16 | learned no timing T+G-minus-timing: CE bits | 0.000 | 3.999 | 4.000 |
| S1b | 32 | exact: Bootstrap sender == Spend sender | 1.000 | 0.031 | 0.031 |
| S1b | 32 | exact: CreditSpent sender == depositor | 1.000 | 0.031 | 0.031 |
| S1b | 32 | exact: announcer == asset sender | 1.000 | 0.031 | 0.031 |
| S1b | 32 | exact: shared-identifier scan | 1.000 | 0.031 | 0.031 |
| S1b | 32 | timing: insertion-order FIFO | 0.385 | 0.385 | 0.031 |
| S1b | 32 | timing: common-delay window k=2 | 0.266 | 0.266 | 0.031 |
| S1b | 32 | learned full trace T+AA+G: top-1 | 1.000 | 0.344 | 0.031 |
| S1b | 32 | learned full trace T+AA+G: CE bits | 0.000 | 2.207 | 5.000 |
| S1b | 32 | learned no-equality T+AA+G-minus-eq: top-1 | 0.375 | 0.344 | 0.031 |
| S1b | 32 | learned no-equality T+AA+G-minus-eq: CE bits | 2.163 | 2.207 | 5.000 |
| S1b | 32 | learned timing T+G-minus-eq: top-1 | 0.385 | 0.344 | 0.031 |
| S1b | 32 | learned timing T+G-minus-eq: CE bits | 2.165 | 2.209 | 5.000 |
| S1b | 32 | learned G-minus-eq (gas+proof+timing): CE bits | 2.165 | 2.209 | 5.000 |
| S1b | 32 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.062 | 0.031 | 0.031 |
| S1b | 32 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 4.944 | 4.999 | 5.000 |
| S1b | 32 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 4.944 | 4.999 | 5.000 |
| S1b | 32 | learned no timing T+G-minus-timing: CE bits | 0.000 | 4.999 | 5.000 |

#### R2 candidate universe

| check | result |
|---|---|
| subjects | 336 |
| subjects_by_baseline_slug | {'b3-privgas-v1': 168, 'b4-crossaccount': 168} |
| subjects_with_differing_universe | 0 |
| truth_outside_universe | 0 |
| ok | True |

#### R2 predictive delta_bits against the uniform model over the SAME N issuances (leave-one-replicate-out, primary convention)

| baseline | scen. | to | subjects | CE uniform | CE model | delta_bits [CI] |
|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | S1b | G-minus-eq | 168 | 4.429 | 2.160 | 2.268 [1.518, 2.714] |
| B3-PrivGas-v1 | S1b | G-minus-eq-minus-timing | 168 | 4.429 | 4.394 | 0.035 [-0.037, 0.100] |
| B3-PrivGas-v1 | S1b | T+AA+G-minus-eq | 168 | 4.429 | 2.160 | 2.268 [1.527, 2.715] |
| B3-PrivGas-v1 | S1b | T+AA+G-minus-eq-minus-timing | 168 | 4.429 | 4.394 | 0.035 [-0.037, 0.100] |
| B3-PrivGas-v1 | S1b | T+G-minus-eq | 168 | 4.429 | 2.161 | 2.267 [1.524, 2.714] |
| B4-CrossAccount | S1b | G-minus-eq | 168 | 4.429 | 2.182 | 2.246 [1.523, 2.656] |
| B4-CrossAccount | S1b | G-minus-eq-minus-timing | 168 | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| B4-CrossAccount | S1b | T+AA+G-minus-eq | 168 | 4.429 | 2.181 | 2.247 [1.520, 2.658] |
| B4-CrossAccount | S1b | T+AA+G-minus-eq-minus-timing | 168 | 4.429 | 4.427 | 0.002 [-0.020, 0.021] |
| B4-CrossAccount | S1b | T+G-minus-eq | 168 | 4.429 | 2.182 | 2.246 [1.523, 2.656] |

#### B4 account-separation audit (every B4 run; from its private run record)

| scen. | N | run | b4 checks passed | issuer≠spender accounts | issuer≠spender keys | Bootstrap senders | Spend senders | sender overlap | issuer↔spender txs | W1T to issuer |
|---|---|---|---|---|---|---|---|---|---|---|
| S1b | 8 | 20260915T212911Z-r1 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S1b | 8 | 20260915T212911Z-r2 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S1b | 8 | 20260915T212911Z-r3 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S1b | 16 | 20260915T212911Z-r1 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S1b | 16 | 20260915T212911Z-r2 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S1b | 16 | 20260915T212911Z-r3 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S1b | 32 | 20260915T212911Z-r1 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |
| S1b | 32 | 20260915T212911Z-r2 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |
| S1b | 32 | 20260915T212911Z-r3 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |

All B4 runs pass the separation audit: **True**.

#### R2 timing summary and gas/proof negative control (pooled over N; leave-one-replicate-out, primary convention; 95% CIs)

| source | baseline | scen. | chance top-1 | FIFO top-1 | window k=2 precision | window k=2 coverage | timing model T+G-minus-eq top-1 | top-3 | top-5 | CE bits (chance) | timing delta_bits | gas/proof-only delta_bits |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| prior batch 20260915T201434Z | B3-PrivGas-v1 | S1 | 0.067 | 0.433 [0.294, 0.616] | 0.819 [0.754, 0.870] | 0.922 | 0.339 [0.239, 0.459] | 0.839 | 0.961 | 2.098 [1.720, 2.407] (4.267) | 2.169 [1.469, 2.523] | -0.003 [-0.015, 0.009] |
| prior batch 20260915T201434Z | B4-CrossAccount | S1 | 0.067 | 0.433 [0.294, 0.616] | 0.819 [0.754, 0.870] | 0.922 | 0.339 [0.236, 0.446] | 0.839 | 0.956 | 2.103 [1.727, 2.438] (4.267) | 2.163 [1.464, 2.528] | -0.001 [-0.018, 0.015] |
| this batch 20260915T212911Z | B3-PrivGas-v1 | S1b | 0.054 | 0.417 [0.316, 0.535] | 0.831 [0.766, 0.881] | 0.952 | 0.387 [0.300, 0.482] | 0.851 | 0.952 | 2.161 [1.839, 2.562] (4.429) | 2.267 [1.524, 2.714] | 0.035 [-0.037, 0.100] |
| this batch 20260915T212911Z | B4-CrossAccount | S1b | 0.054 | 0.417 [0.316, 0.535] | 0.831 [0.766, 0.881] | 0.952 | 0.363 [0.281, 0.469] | 0.839 | 0.958 | 2.182 [1.885, 2.553] (4.429) | 2.246 [1.523, 2.656] | 0.002 [-0.020, 0.021] |

<!-- END GENERATED: d1-s1b-results -->
