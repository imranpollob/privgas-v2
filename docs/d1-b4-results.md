# D1 B4 causal ablation: cross-account (independent) credit redemption

Status: **ablation complete (2026-09-15); not scaled.** An experimental counterfactual of
the frozen B3 specimen, not a protocol proposal. No novelty or production claim.

Labels: **FACT** (directly observed implementation or measurement result), **INFERENCE**
(interpretation supported by a result), **HYPOTHESIS** (not established), **NEGATIVE
RESULT** (a tested effect was absent / at chance). Every number below the "Generated
results" marker is produced by `python3 -m experiments.privacy.d1.evaluate score --doc b4
--write-doc` from frozen predictions; the narrative cites those tables.

- Workload: `experiments/workloads/d1/` (`b4-config.json`, `actors.py`, `schedule.py`,
  `runner.py` incl. `b4_account_separation_checks`, `recording.py`, `regeneration.py`)
- Attacks / evaluation: `experiments/privacy/d1/` (unchanged family + pre-registered
  additions, `evaluate/paired.py`)
- Tests: `experiments/workloads/d1/tests/test_b4_static.py`, `test_b4_live.py`,
  `experiments/privacy/d1/tests/test_static.py` (`TestB4CrossAccountReuse`),
  `experiments/tests/test_schema_validation.py` (`TestB4CrossAccountSchema`)
- Run: `make d1-b4-run SEED_FILE=data/private/d1-pilot/master_seed.txt BATCH=...`;
  `make d1-b4-attack BATCH=... ROUND=...`
- Decisions and pre-registration: `docs/decision-log.md` (2026-09-15, "B4-CrossAccount" and
  "B4 analysis pre-registration")

## 1. Question

The D1 pilot (`docs/d1-pilot-results.md`) found B3's issuance ↔ redemption relation (R2)
recovered exactly by account equality, because Bootstrap and Spend share one public
`UserOperation.sender`; at chance once equality features are removed in the clean schedule;
and substantially degraded by correlated timing. This experiment asks one causal question:

> Does R2 remain unlinkable when the credit is issued by one public account but redeemed
> by a different public account, holding the frozen credit mechanism constant?

The causal contrast is limited to **changing account coupling while holding the frozen
credit mechanism constant**. It does not establish that B4-CrossAccount is private in
general.

## 2. Frozen B3 permits cross-account redemption (verified before relying on it)

- FACT (source, `baselines/b3_privgas_v1/src/CreditPaymaster.sol` @ `02a3f0ab`):
  `validatePaymasterUserOp` checks `maxCost`, the call+verification gas cap, the fee cap, the
  proof root against the mirrored root, `scope`, `message == uint256(userOpHash)`, nullifier
  freshness and the Groth16 proof. `userOp.sender` is read only to emit
  `CreditSpent(nullifier, sender)`. `CreditPool.deposit` requires only that `msg.sender` is
  eligible and has not deposited.
- FACT (live, frozen contracts, `test_b4_live.py`): a Spend from an account that was never
  announced, eligible or a depositor, carrying a proof generated for its own `userOpHash`,
  is accepted and executes the W1 transfer. No contract change, no public handoff and no
  new proof system were needed. None of the §23 stop conditions on protocol semantics
  triggered.

## 3. B4-CrossAccount workflow

Per hidden actor *i* (independent draws from (secret seed, N, slot, kind); no identifier
derived from another): actor handle, established wallet, asset sender, **issuer key →
issuer account**, **issuer funder**, recipient key → **spender account** (the same account
B3 uses), Semaphore identity and commitment.

| step | B3-PrivGas-v1 | B4-CrossAccount |
|---|---|---|
| setup | faucet → asset sender ETH; treasury → asset sender W1T | same, plus faucet → issuer funder ETH (same value, its own shuffled order) |
| deliver | asset sender → W1T to account | asset sender → W1T to **spender** account |
| fund | asset sender: `announceAndFund(account)` | **issuer funder**: `announceAndFund(issuer account)` |
| issue | account: Bootstrap (initCode + `deposit(C_i)`) | **issuer account**: Bootstrap (initCode + `deposit(C_i)`) |
| prepare (off chain) | proof, final root, message = account's userOpHash | private handoff: spender wallet holds identity *i*; proof, final root, message = **spender's** userOpHash |
| act | account: Spend (no initCode, nonce 1), CreditPaymaster | **spender**: Spend (initCode, nonce 0), CreditPaymaster |

**Handoff.** The credit witness moves from issuer to spender only in the private run
record (`d1_private_run.json` → `actors[*].issuer_account / recipient_account`,
`b4.handoff`) and in ground truth (the Spend row's R2 label names the issuance made by the
same actor's issuer account). No transaction, event or public field carries it.

**Account-separation gate** (`runner.b4_account_separation_checks`; a failure aborts the
run): per actor the issuer and spender keys, accounts and funding wallets differ; the
mined Bootstrap sender equals the issuer account and differs from the mined Spend sender;
the sets of Bootstrap and Spend senders are disjoint; no transaction, ERC-20 transfer, ETH
edge or announcement joins any issuer-side address (issuer key, issuer funder, issuer
account) with any spender-side address (recipient key, asset sender, spender account); the
issuer never held W1T; the spender was never eligible, used or a depositor. A test
(`TestB4RunGate`) confirms a run with issuer = spender fails.

**Scheduling.** B4 uses B3's schedule streams verbatim, so B3 and B4 at one (replicate, N,
scenario) have identical event orders and times (tested). S0: all issuances, then the final
root is verified, then every proof against it in an independent order, then spends in an
independent order with delays independent of the hidden pairing. S1: one arrival order drives
delivery, admission (+300 s) and issuance (+900 s); actions follow the arrival order up to
±900 s jitter. The issuer-funder setup order is its own permutation in both scenarios.
Direct scheduler audit (`test_b4_static.py`): over 400 schedules, every issuer-side public
order (`setup_issuer`, `fund`, `issue`) rank-matched against every spender-side order
(`setup`, `deliver`, `prepare`, `act`) recovers the true pairing at 1/N, and every pair of
orders is uncorrelated with the slot and with each other (S0).

### 3.1 Matched with B3 / unavoidable differences

Identical: frozen contracts (masked runtime equals the frozen artifacts; source trees equal
their pin), EntryPoint v0.9.0, SimpleAccount/factory, CreditPool, both B3 Paymasters, the
real SemaphoreVerifier and circuit artifacts, W1 token, amount, destination and application
call, fee environment, experimental bundler, `b3_compat_local`, pool sizes, proof depth,
commitment construction, single-final-root handling, proof generation, Bootstrap gas
limits, feature extraction and every pilot attack.

Differences, all constant within a run and forced by removing the coupling: (1) the
admission is paid by a dedicated issuer funder (else one wallet would fund both sides);
(2) the Spend deploys the spender account (initCode, nonce 0), since nothing deployed it
earlier; (3) one extra faucet transfer per actor in setup; (4) the issuer account keeps the
forwarded vMin and holds no W1T.

## 4. Attacks (unchanged family; additions pre-registered)

All pilot attacks, rules and learned configurations run unchanged on both baselines, on the
public A0 trace only, in a process that cannot import ground truth. For B4, R3 drops
`r3_dir_vs_issuance_rank_g` (defined through spender == depositor, which does not exist).
Pre-registered before the B4 dataset was recorded (`docs/decision-log.md`), for B3 and B4 alike:

- exact rules `r2-announcer-eq-asset-sender` (funding-address equality),
  `r2-shared-eth-funder` (a wallet sent plain ETH to both sides), and
  `r2-shared-identifier-scan` (any address / identifier shared by the Spend account's and the
  depositor's transactions but not by every candidate; roots excluded because root equality is
  its own rule);
- learned selections of existing features `G-minus-eq-minus-timing` and
  `T+AA+G-minus-eq-minus-timing` (R2 timing features are family G, so `G-minus-eq` does not
  isolate gas / proof metadata).

**Two analyses** (Prompt §18). *A. Full public trace*: `T+AA+G` and every exact rule.
*B. No direct equality*: `*-minus-eq` models; predictive delta_bits is reported only
against the uniform model over the **same** N issuances (the candidate universe is checked
identical for every subject across every attack). `delta_bits(T → T+G) = log2 N` is not
reported as leakage: R2 candidates exist only through G.

**Paired comparison.** Run pairs share (scenario, N, replicate), hence actors, spender
accounts, identities and schedule; B4 − B3 differences are subject-weighted over run pairs
with a bootstrap CI over run pairs (`evaluate/paired.py`).

## 5. Dataset, integrity and audits

All statements refer to batch `20260915T201434Z`, attack round `a1`, tier A0. Numbers in
§5–§7 are quoted from the generated tables below (or from the named result files).

- FACT: 48/48 runs recorded (B3-PrivGas-v1 and B4-CrossAccount × S0/S1 × N = 4, 8, 16, 32 ×
  3 replicates); none failed, none retried. Every run passed all its end-of-run checks; every
  B4 run passed every account-separation check (44 / 80 / 152 / 296 per run at N = 4 / 8 / 16 / 32): no
  Bootstrap sender is a Spend sender, no issuer↔spender transaction or transfer, no W1T to
  any issuer.
- FACT (B3 regeneration, `results/d1-pilot/20260915T201434Z/b3_regeneration_check.json`):
  all 24 B3 runs reproduce the pilot's B3 runs. Every non-Spend transaction hash and every
  Bootstrap op is identical, and so is each Spend's sender, nonce, initCode, callData, gas
  limits, root and nullifier. Only Groth16 proof points differ (fresh proving randomness).
  Through the calldata zero-byte count this changes preVerificationGas, and with it the
  userOpHash, in some Spends. The code added for B4 did not change what B3 runs.
- FACT: frozen B3 sources are byte-identical to a pre-change snapshot (558 files) and to
  `baselines/b3_eval/dependency-pin.json`; deployed runtimes equal the frozen artifacts
  (immutables masked).
- FACT: leakage self-check clean (192 files); split audit: 28 folds, no shared actor address
  (issuer keys, issuer accounts and issuer funders included), 4,644 learned prediction sets'
  label provenance verified; the public order of every phase equals the private schedule; R2
  candidate universe identical for all 720 subjects across every rule and model; R3
  above-chance flags: 0.
- FACT (flag, investigated): the harness audit raised two flags. They are one statistic,
  `setup~fund` in S0 (mean ρ 0.31, z 3.35), identical for B3 and B4 because they share
  permutations, and the same flag the pilot investigated (z ≈ 0 over 400 fresh seeds,
  separate SHA-256 streams; `test_b4_static.py` passes that pair over 400 schedules). For B4
  the pair is issuer-side (admission) vs spender-side (asset-sender setup), so its
  exploitability was quantified post hoc (evaluation side, not part of the attack family):
  rank-matching the two orders hits 19/180 true pairs in S0 against 12 expected (N = 4:
  0.42 vs 0.25; N = 32: 0.03 vs 0.03). INFERENCE: a dataset-level chance fluctuation, not a
  harness leak. The flag criterion was not relaxed.

## 6. Findings

### 6.1 Frozen B3 — the pilot result is confirmed

- FACT: every account-equality rule (`Bootstrap sender == Spend sender`,
  `CreditSpent sender == depositor`, `transfer account == depositor`,
  `deployed account == spender`) and both pre-registered equality rules that B3's shared
  account satisfies (`announcer == asset sender`, `shared-identifier scan`) select the true
  issuance for every redemption: coverage 1.000, precision 1.000 [0.979, 1.000], in S0 and S1.
- FACT: with equality removed, B3 S0 is at chance (delta_bits none → T+AA+G-minus-eq
  −0.002 [−0.058, 0.042]); B3 S1 recovers about half the entropy (none → T+G-minus-eq
  2.169 [1.469, 2.523] of 4.267 bits).

### 6.2 B4-CrossAccount — exact rules (full public trace, analysis A)

- FACT: in B4, none of the seven equality rules fires in either scenario (coverage 0; top-1
  = chance 0.067). `shared-eth-funder` selects every candidate in both baselines (one shared
  faucet: no reduction). `root-match` selects the last-inserted issuance for every Spend and
  is at chance (precision 0.067) in both baselines.
- FACT: the learned full-trace model `T+AA+G` falls from top-1 1.000 / CE 0.000 bits (B3) to
  top-1 0.072 [0.033, 0.129] / CE 4.265 bits (B4 S0; chance 0.067 / 4.267).
- **NEGATIVE RESULT**: no deterministic public relation (address, funding wallet, asset
  account, deployment, Paymaster, nonce, commitment / nullifier / userop / tx identifier)
  links a B4 issuance to its redemption.

### 6.3 B4 S0 — no-direct-equality (analysis B)

- FACT: `T+AA+G-minus-eq` top-1 0.072 [0.033, 0.129], CE 4.265 bits; delta_bits
  none → T+AA+G-minus-eq 0.001 [−0.024, 0.024]; `T+G-minus-eq` 0.002 [−0.021, 0.023]; timing
  rules at chance (FIFO 0.067 [0.017, 0.157], window k=2 0.081 [0.050, 0.141]); every
  delta_bits by N has a CI containing 0.
- **NEGATIVE RESULT**: in the clean schedule, once the accounts are decoupled, R2 is at
  chance on every measure.

### 6.4 Gas / proof / Paymaster metadata

- FACT: `G-minus-eq-minus-timing` (root match, nullifier/commitment bit agreement, gas-used
  and PVG ranks and z-scores) has delta_bits vs uniform 0.001 [−0.019, 0.019] (B4 S0),
  −0.001 [−0.018, 0.015] (B4 S1), −0.001 / −0.003 (B3 S0 / S1, CIs containing 0);
  `T+AA+G-minus-eq-minus-timing` is identical. Ablating `gas` or `pm` from T+AA+G changes
  B4's CE by ≤ 0.021 bits with CIs containing 0.
- **NEGATIVE RESULT**: commitment/root, nullifier/proof metadata, Paymaster fields, gas
  limits, actual gas, PVG and fees carry no held-out R2 information in either baseline or
  scenario.

### 6.5 B4 S1 — correlated timing

- FACT: `T+G-minus-eq` top-1 0.339 [0.236, 0.446], top-3 0.839, top-5 0.956, CE 2.103 bits
  (chance 4.267); delta_bits none → T+G-minus-eq 2.163 [1.464, 2.528]; by N 1.312
  [0.022, 2.356] (N = 8), 2.221 (N = 16), 2.672 [2.368, 2.937] (N = 32), not significant at
  N = 4. FIFO top-1 0.433 [0.294, 0.616]; window k=2 top-1 0.286, coverage 0.922, precision
  0.819, reduction 0.819.
- FACT: in B4, removing `timing` from T+AA+G removes all of it (2.163 [1.457, 2.528]);
  removing `eq` removes nothing.
- FACT (paired): B4 S1 minus B3 S1 for the no-equality and timing models: CE +0.006
  [−0.031, 0.044] bits, top-1 0.000 [−0.029, 0.025]. The timing rules are identical in B3 and
  B4 by construction (same schedule, rules read only issuance/redemption order).
- FACT (unexpected, post hoc, not part of the attack family): the pilot's S1 model drives
  delivery (+0 s), admission (+300 s) and issuance (+900 s) from one arrival order. In B4
  that ties the SPENDER's asset delivery to the ISSUER's admission. Rank-matching those two
  public orders recovers the true pairing for 100% of subjects at every N (evaluation-side
  diagnostic from the verified public orders). The pre-registered family never reads
  delivery-vs-admission (`r2_delivery_rank_gap_tg` is defined through the depositor's own
  delivery, which B4 does not have), so **B4 S1 figures are a lower bound on timing
  linkage under this timing model**.
- INFERENCE: account decoupling removes the deterministic linkage but leaves ordinary
  timing linkage unchanged. Correlated workflow timing re-links the two accounts, through
  issuance → redemption timing and, more strongly, through issuer-admission ↔
  spender-delivery timing.

### 6.6 T / AA / G conditional results (R2)

- FACT (primary convention): T and T+AA carry no R2 feature (uniform, CE 4.267) in both
  baselines. In B3, G, T+G and T+AA+G are exact; in B4 they are at chance in S0 and at the
  timing level in S1 (CE ≈ 2.10). Under the `field_kind` convention, B4 S1 T+AA reaches top-1
  0.433 / CE 2.658: the Bootstrap op's block order counts as AA there, so it carries FIFO
  timing. B4 S0 T+AA stays at chance under both conventions.
- INFERENCE: delta_bits(T → T+G) = log2 N in B3 is a property of the relation (R2
  candidates exist only through G), not leakage, and is not reported as such. The
  informative contrasts are equality removal (B3 → B4, same universe) and S0 → S1.

### 6.7 Transfer and holdout

- FACT: configuration holdout (train N ≤ 16, test N = 32) transfers within a scenario (B4 S1
  T+G-minus-eq CE 2.346 vs chance 5.000; B4 S0 5.013 ≈ chance). Scenario transfer S1 → S0 is
  confidently wrong (B4 S0 CE 9.22 [6.30, 10.91] vs 4.27) as in the pilot; S0 → S1 gains
  little (B4 S1 CE 4.19).

### 6.8 R3 negative control

- FACT: every learned R3 model for B3 and B4 in both scenarios has top-1 CIs containing
  chance (e.g. B4 S0 T+AA+G 0.067 [0.019, 0.158]; B4 S1 0.044 [0.014, 0.080]) and CE at or
  slightly above uniform; no R3 flag. **NEGATIVE RESULT** (as designed): no label leakage.

### 6.9 R1

- FACT: in both baselines every operation has exactly one public candidate economic funder
  (the sponsor wallet funding both Paymaster deposits); R1 classification is not run,
  unchanged from the pilot.

### 6.10 Direct paired B3 / B4 summary (pooled over N; B4 − B3 with 95% CI over 12 run pairs)

| scen. | measure | B3 | B4 | chance | B4 − B3 |
|---|---|---|---|---|---|
| S0 | exact: Bootstrap sender == Spend sender (top-1) | 1.000 | 0.067 | 0.067 | −0.933 [−0.953, −0.893] |
| S0 | exact: shared-identifier scan (top-1) | 1.000 | 0.067 | 0.067 | −0.933 [−0.953, −0.889] |
| S0 | full trace T+AA+G (CE bits) | 0.000 | 4.265 | 4.267 | +4.265 [3.558, 4.654] |
| S0 | no-equality T+AA+G-minus-eq (top-1) | 0.056 | 0.072 | 0.067 | +0.017 [−0.025, 0.052] |
| S0 | no-equality T+AA+G-minus-eq (CE bits) | 4.269 | 4.265 | 4.267 | −0.003 [−0.045, 0.032] |
| S0 | gas/proof only G-minus-eq-minus-timing (CE bits) | 4.268 | 4.266 | 4.267 | −0.002 [−0.021, 0.013] |
| S1 | exact: Bootstrap sender == Spend sender (top-1) | 1.000 | 0.067 | 0.067 | −0.933 [−0.953, −0.893] |
| S1 | full trace T+AA+G (CE bits) | 0.000 | 2.104 | 4.267 | +2.104 [1.743, 2.382] |
| S1 | timing T+G-minus-eq (top-1) | 0.339 | 0.339 | 0.067 | 0.000 [−0.029, 0.025] |
| S1 | timing T+G-minus-eq (CE bits) | 2.098 | 2.103 | 4.267 | +0.006 [−0.031, 0.041] |
| S1 | timing rule FIFO (top-1) | 0.433 | 0.433 | 0.067 | 0.000 |
| S1 | gas/proof only G-minus-eq-minus-timing (CE bits) | 4.270 | 4.267 | 4.267 | −0.002 [−0.014, 0.009] |

INFERENCE (causal, limited): holding the frozen credit mechanism and schedule constant,
changing only account coupling moves R2 from exact linkage to chance in the clean schedule,
and from exact to the timing-only level in the correlated schedule. The whole B3 → B4
difference equals the equality family; nothing else differs between the paired runs.

## 7. Decision rule (pre-registered criteria, `docs/decision-log.md`)

- B4 S0 near chance: best exact rule top-1 CI contains chance ✓; delta_bits
  none → T+AA+G-minus-eq 0.001 [−0.024, 0.024] ✓.
- B4 S1 meaningfully linkable through timing: delta_bits none → T+G-minus-eq 2.163
  [1.464, 2.528], 0.51 × log2 N ✓; FIFO top-1 CI [0.294, 0.616] above chance ✓.
- No Case B trigger: no exact rule fires in B4 S0; metadata-only models have CIs containing 0.

**Applicable case: A.** The dominant B3 R2 failure is public-account coupling; the residual
boundary is timing.

INFERENCE on the D1 falsification criterion (`docs/research-plan.md` §3: stop treating D1 as
the main contribution if all effects reduce to known address reuse, trivial account
equality or ordinary application leakage with no meaningful ERC-4337-specific boundary):
Case A does not rescue D1 on that criterion. The two effects this ablation isolates are
(a) account equality, removable by an account workflow the frozen contracts already
permit, and (b) ordinary timing correlation, identical with or without the gas mechanism's
account coupling. Across pilot and ablation, no ERC-4337- or sponsorship-specific
observable (Paymaster fields, PVG, gas, proof metadata, roots, nullifiers) added held-out
information. **The kill condition remains met for the questions tested.** What survives is
a measurement / negative result, not a main-paper ERC-4337-specific boundary.

## 8. Assumptions

- Tier A0 only; profiling attacker trained on labelled runs of the same configuration.
- The off-chain witness handoff is perfect and leaves no trace (controlled ground truth). A
  real handoff channel is not modelled.
- The issuer funder is an independent, faucet-funded wallet. In practice the actor must
  fund the admission from some wallet with no public relation to the spender's asset source.
- Honest actors only; no attacker-controlled commitments; single final root (no contention).
- One shared destination, token and amount (minimal T variation); unstaked Paymasters;
  experimental bundler; `b3_compat_local`.

## 9. Limitations

- 3 replicates, N ≤ 32; per-N CIs are wide (N = 4 S1 not significant).
- One S1 timing family, reused from the pilot. It correlates admission with delivery as
  well as issuance with redemption (§6.5), so S1 linkage is understated by the pre-registered
  attacks and depends strongly on this one model.
- The spender's Spend deploys the account (initCode, nonce 0), unlike B3's Spend; constant
  within a run, but it changes the Spend's gas profile relative to B3 (no cross-baseline
  feature reads it).
- B4's extra issuer funder adds N public faucet transfers; a real deployment would have a
  richer funding graph, which could create or destroy linkage.
- Not tested: cross-run joins, A1 mempool data, realistic application variation.

## 10. Unresolved questions

- How strong timing linkage is under realistic, heterogeneous delays, and how much delay a
  user must add. This is ordinary mixing-latency territory, not ERC-4337-specific.
- Whether any ERC-4337-specific signal appears under root contention, when proofs go stale
  and are regenerated, or when bundles are replaced or fail (D2).
- Whether a practical off-chain handoff and independent admission funding are usable by a
  stealth recipient without creating a new public edge (not measured here).

## Generated results

<!-- BEGIN GENERATED: d1-b4-results -->

Batch `20260915T201434Z`, attack round `a1`. Generated by `python3 -m experiments.privacy.d1.evaluate score`; machine-readable tables in `results/d1-pilot/20260915T201434Z/evaluation-a1/`.

#### Dataset

| baseline | scenario | N | runs recorded | runs failed |
|---|---|---|---|---|
| B3-PrivGas-v1 | S0 | 4 | 3 | 0 |
| B3-PrivGas-v1 | S0 | 8 | 3 | 0 |
| B3-PrivGas-v1 | S0 | 16 | 3 | 0 |
| B3-PrivGas-v1 | S0 | 32 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 4 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 8 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 16 | 3 | 0 |
| B3-PrivGas-v1 | S1 | 32 | 3 | 0 |
| B4-CrossAccount | S0 | 4 | 3 | 0 |
| B4-CrossAccount | S0 | 8 | 3 | 0 |
| B4-CrossAccount | S0 | 16 | 3 | 0 |
| B4-CrossAccount | S0 | 32 | 3 | 0 |
| B4-CrossAccount | S1 | 4 | 3 | 0 |
| B4-CrossAccount | S1 | 8 | 3 | 0 |
| B4-CrossAccount | S1 | 16 | 3 | 0 |
| B4-CrossAccount | S1 | 32 | 3 | 0 |

#### Candidate sets (per run; identical across replicates)

| baseline | N | R1 public candidates | R1 true funders | R2 candidates | R3 candidates | total commitments | honest commitments | attacker commitments |
|---|---|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | 4 | 1 | 1 | 4 | 4 | 4 | 4 | 0 |
| B3-PrivGas-v1 | 8 | 1 | 1 | 8 | 8 | 8 | 8 | 0 |
| B3-PrivGas-v1 | 16 | 1 | 1 | 16 | 16 | 16 | 16 | 0 |
| B3-PrivGas-v1 | 32 | 1 | 1 | 32 | 32 | 32 | 32 | 0 |
| B4-CrossAccount | 4 | 1 | 1 | 4 | 4 | 4 | 4 | 0 |
| B4-CrossAccount | 8 | 1 | 1 | 8 | 8 | 8 | 8 | 0 |
| B4-CrossAccount | 16 | 1 | 1 | 16 | 16 | 16 | 16 | 0 |
| B4-CrossAccount | 32 | 1 | 1 | 32 | 32 | 32 | 32 | 0 |

#### R1 structure (public trace)

| baseline | N | immediate payer | distinct immediate payers | public candidate funders / op | ops with direct account edge | funding shared across ops | R1 classification run |
|---|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | 4 | paymaster_entrypoint_deposit | 1 | 1 | 0/4 | True | False |
| B3-PrivGas-v1 | 8 | paymaster_entrypoint_deposit | 1 | 1 | 0/8 | True | False |
| B3-PrivGas-v1 | 16 | paymaster_entrypoint_deposit | 1 | 1 | 0/16 | True | False |
| B3-PrivGas-v1 | 32 | paymaster_entrypoint_deposit | 1 | 1 | 0/32 | True | False |
| B4-CrossAccount | 4 | paymaster_entrypoint_deposit | 1 | 1 | 0/4 | True | False |
| B4-CrossAccount | 8 | paymaster_entrypoint_deposit | 1 | 1 | 0/8 | True | False |
| B4-CrossAccount | 16 | paymaster_entrypoint_deposit | 1 | 1 | 0/16 | True | False |
| B4-CrossAccount | 32 | paymaster_entrypoint_deposit | 1 | 1 | 0/32 | True | False |

#### Exact / deterministic rules (pooled over N; 95% CIs)

| relation | baseline | scen. | rule | families | tier | coverage | precision | top-1 | chance top-1 | mean |C| | reduction |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S0 | r2-announcer-eq-asset-sender | T+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-creditspent-sender-eq-depositor | G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-deployed-account-eq-spender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-root-match | G | A0 | 1.000 | 0.067 [0.039, 0.113] | 0.067 [0.031, 0.132] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-shared-eth-funder | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B3-PrivGas-v1 | S0 | r2-shared-identifier-scan | T+AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.072 [0.043, 0.120] | 0.072 [0.029, 0.136] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-transfer-account-eq-depositor | T+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S0 | r2-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B3-PrivGas-v1 | S1 | r2-announcer-eq-asset-sender | T+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-creditspent-sender-eq-depositor | G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-deployed-account-eq-spender | AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-root-match | G | A0 | 1.000 | 0.067 [0.039, 0.113] | 0.067 [0.032, 0.135] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-shared-eth-funder | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B3-PrivGas-v1 | S1 | r2-shared-identifier-scan | T+AA+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.061 [0.034, 0.106] | 0.061 [0.021, 0.139] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-transfer-account-eq-depositor | T+G | A0 | 1.000 | 1.000 [0.979, 1.000] | 1.000 [1.000, 1.000] | 0.067 | 22.7 | 0.933 |
| R2 | B3-PrivGas-v1 | S1 | r2-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-announcer-eq-asset-sender | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-creditspent-sender-eq-depositor | G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-deployed-account-eq-spender | AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-root-match | G | A0 | 1.000 | 0.067 [0.039, 0.113] | 0.067 [0.031, 0.132] | 0.067 | 22.7 | 0.933 |
| R2 | B4-CrossAccount | S0 | r2-shared-eth-funder | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-shared-identifier-scan | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.072 [0.043, 0.120] | 0.072 [0.011, 0.169] | 0.067 | 22.7 | 0.933 |
| R2 | B4-CrossAccount | S0 | r2-transfer-account-eq-depositor | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S0 | r2-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-announcer-eq-asset-sender | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-bootstrap-sender-eq-spend-sender | AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-creditspent-sender-eq-depositor | G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-deployed-account-eq-spender | AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-root-match | G | A0 | 1.000 | 0.067 [0.039, 0.113] | 0.067 [0.032, 0.135] | 0.067 | 22.7 | 0.933 |
| R2 | B4-CrossAccount | S1 | r2-shared-eth-funder | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-shared-identifier-scan | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-shuffled-fifo-control | G | A0 | 1.000 | 0.056 [0.030, 0.099] | 0.056 [0.021, 0.129] | 0.067 | 22.7 | 0.933 |
| R2 | B4-CrossAccount | S1 | r2-transfer-account-eq-depositor | T+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R2 | B4-CrossAccount | S1 | r2-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S0 | r3-order-match-action | T | A0 | 1.000 | 0.100 [0.064, 0.153] | 0.100 [0.037, 0.205] | 0.067 | 22.7 | 0.933 |
| R3 | B3-PrivGas-v1 | S0 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S0 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S1 | r3-order-match-action | T | A0 | 1.000 | 0.078 [0.047, 0.126] | 0.078 [0.024, 0.160] | 0.067 | 22.7 | 0.933 |
| R3 | B3-PrivGas-v1 | S1 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B3-PrivGas-v1 | S1 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B4-CrossAccount | S0 | r3-order-match-action | T | A0 | 1.000 | 0.100 [0.064, 0.153] | 0.100 [0.037, 0.205] | 0.067 | 22.7 | 0.933 |
| R3 | B4-CrossAccount | S0 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B4-CrossAccount | S0 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B4-CrossAccount | S1 | r3-order-match-action | T | A0 | 1.000 | 0.078 [0.047, 0.126] | 0.078 [0.024, 0.160] | 0.067 | 22.7 | 0.933 |
| R3 | B4-CrossAccount | S1 | r3-uniform | none | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |
| R3 | B4-CrossAccount | S1 | r3-wallet-appears-on-chain | T+AA+G | A0 | 0.000 | – | 0.067 [0.048, 0.111] | 0.067 | 22.7 | – |

#### R2 timing rules by pool size

| baseline | scen. | rule | N | top-1 | top-3 | top-5 | coverage | precision | reduction | chance top-1 |
|---|---|---|---|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | S0 | insertion-order-fifo | 16 | 0.062 | 0.250 | 0.354 | 1.000 | 0.062 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S0 | insertion-order-fifo | 32 | 0.021 | 0.094 | 0.156 | 1.000 | 0.021 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S0 | insertion-order-fifo | 4 | 0.333 | 0.833 | 1.000 | 1.000 | 0.333 | 0.750 | 0.250 |
| B3-PrivGas-v1 | S0 | insertion-order-fifo | 8 | 0.125 | 0.333 | 0.583 | 1.000 | 0.125 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S0 | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S0 | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S0 | nearest-prior-issuance | 4 | 0.250 | 0.750 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| B3-PrivGas-v1 | S0 | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S0 | shuffled-fifo-control | 16 | 0.042 | 0.125 | 0.312 | 1.000 | 0.042 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S0 | shuffled-fifo-control | 32 | 0.062 | 0.167 | 0.250 | 1.000 | 0.062 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S0 | shuffled-fifo-control | 4 | 0.250 | 0.667 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| B3-PrivGas-v1 | S0 | shuffled-fifo-control | 8 | 0.083 | 0.333 | 0.625 | 1.000 | 0.083 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S0 | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| B3-PrivGas-v1 | S0 | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| B3-PrivGas-v1 | S0 | uniform | 4 | 0.250 | 0.750 | 1.000 | 0.000 | – | – | 0.250 |
| B3-PrivGas-v1 | S0 | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| B3-PrivGas-v1 | S0 | window-k1 | 16 | 0.080 | 0.271 | 0.417 | 0.583 | 0.143 | 0.879 | 0.062 |
| B3-PrivGas-v1 | S0 | window-k1 | 32 | 0.043 | 0.156 | 0.229 | 0.708 | 0.074 | 0.943 | 0.031 |
| B3-PrivGas-v1 | S0 | window-k1 | 4 | 0.222 | 0.917 | 1.000 | 0.500 | 0.500 | 0.417 | 0.250 |
| B3-PrivGas-v1 | S0 | window-k1 | 8 | 0.082 | 0.292 | 0.583 | 0.625 | 0.133 | 0.792 | 0.125 |
| B3-PrivGas-v1 | S0 | window-k2 | 16 | 0.107 | 0.271 | 0.417 | 0.708 | 0.294 | 0.805 | 0.062 |
| B3-PrivGas-v1 | S0 | window-k2 | 32 | 0.042 | 0.156 | 0.229 | 0.906 | 0.138 | 0.909 | 0.031 |
| B3-PrivGas-v1 | S0 | window-k2 | 4 | 0.312 | 0.917 | 1.000 | 0.417 | 0.800 | 0.400 | 0.250 |
| B3-PrivGas-v1 | S0 | window-k2 | 8 | 0.071 | 0.292 | 0.583 | 0.875 | 0.190 | 0.667 | 0.125 |
| B3-PrivGas-v1 | S0 | window-k4 | 16 | 0.079 | 0.271 | 0.417 | 0.812 | 0.462 | 0.638 | 0.062 |
| B3-PrivGas-v1 | S0 | window-k4 | 32 | 0.032 | 0.156 | 0.229 | 0.990 | 0.189 | 0.830 | 0.031 |
| B3-PrivGas-v1 | S0 | window-k4 | 4 | 0.306 | 0.917 | 1.000 | 0.333 | 0.750 | 0.438 | 0.250 |
| B3-PrivGas-v1 | S0 | window-k4 | 8 | 0.111 | 0.292 | 0.583 | 0.917 | 0.545 | 0.449 | 0.125 |
| B3-PrivGas-v1 | S1 | insertion-order-fifo | 16 | 0.500 | 0.833 | 0.979 | 1.000 | 0.500 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S1 | insertion-order-fifo | 32 | 0.344 | 0.760 | 0.958 | 1.000 | 0.344 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S1 | insertion-order-fifo | 4 | 0.417 | 0.750 | 1.000 | 1.000 | 0.417 | 0.750 | 0.250 |
| B3-PrivGas-v1 | S1 | insertion-order-fifo | 8 | 0.667 | 0.917 | 1.000 | 1.000 | 0.667 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S1 | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S1 | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S1 | nearest-prior-issuance | 4 | 0.250 | 0.750 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| B3-PrivGas-v1 | S1 | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S1 | shuffled-fifo-control | 16 | 0.042 | 0.125 | 0.312 | 1.000 | 0.042 | 0.938 | 0.062 |
| B3-PrivGas-v1 | S1 | shuffled-fifo-control | 32 | 0.010 | 0.062 | 0.094 | 1.000 | 0.010 | 0.969 | 0.031 |
| B3-PrivGas-v1 | S1 | shuffled-fifo-control | 4 | 0.417 | 0.833 | 1.000 | 1.000 | 0.417 | 0.750 | 0.250 |
| B3-PrivGas-v1 | S1 | shuffled-fifo-control | 8 | 0.125 | 0.333 | 0.583 | 1.000 | 0.125 | 0.875 | 0.125 |
| B3-PrivGas-v1 | S1 | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| B3-PrivGas-v1 | S1 | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| B3-PrivGas-v1 | S1 | uniform | 4 | 0.250 | 0.750 | 1.000 | 0.000 | – | – | 0.250 |
| B3-PrivGas-v1 | S1 | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| B3-PrivGas-v1 | S1 | window-k1 | 16 | 0.367 | 0.875 | 0.979 | 0.771 | 0.649 | 0.899 | 0.062 |
| B3-PrivGas-v1 | S1 | window-k1 | 32 | 0.288 | 0.802 | 0.948 | 0.875 | 0.643 | 0.930 | 0.031 |
| B3-PrivGas-v1 | S1 | window-k1 | 4 | 0.347 | 0.833 | 1.000 | 0.833 | 0.600 | 0.525 | 0.250 |
| B3-PrivGas-v1 | S1 | window-k1 | 8 | 0.368 | 0.958 | 1.000 | 0.667 | 0.812 | 0.781 | 0.125 |
| B3-PrivGas-v1 | S1 | window-k2 | 16 | 0.294 | 0.875 | 0.979 | 0.896 | 0.791 | 0.840 | 0.062 |
| B3-PrivGas-v1 | S1 | window-k2 | 32 | 0.265 | 0.802 | 0.948 | 0.969 | 0.817 | 0.887 | 0.031 |
| B3-PrivGas-v1 | S1 | window-k2 | 4 | 0.250 | 0.833 | 1.000 | 0.833 | 0.700 | 0.375 | 0.250 |
| B3-PrivGas-v1 | S1 | window-k2 | 8 | 0.375 | 0.958 | 1.000 | 0.833 | 0.950 | 0.681 | 0.125 |
| B3-PrivGas-v1 | S1 | window-k4 | 16 | 0.251 | 0.875 | 0.979 | 1.000 | 0.917 | 0.737 | 0.062 |
| B3-PrivGas-v1 | S1 | window-k4 | 32 | 0.190 | 0.802 | 0.948 | 1.000 | 1.000 | 0.804 | 0.031 |
| B3-PrivGas-v1 | S1 | window-k4 | 4 | 0.250 | 0.833 | 1.000 | 0.167 | 0.500 | 0.375 | 0.250 |
| B3-PrivGas-v1 | S1 | window-k4 | 8 | 0.311 | 0.958 | 1.000 | 0.875 | 0.952 | 0.536 | 0.125 |
| B4-CrossAccount | S0 | insertion-order-fifo | 16 | 0.062 | 0.250 | 0.354 | 1.000 | 0.062 | 0.938 | 0.062 |
| B4-CrossAccount | S0 | insertion-order-fifo | 32 | 0.021 | 0.094 | 0.156 | 1.000 | 0.021 | 0.969 | 0.031 |
| B4-CrossAccount | S0 | insertion-order-fifo | 4 | 0.333 | 0.833 | 1.000 | 1.000 | 0.333 | 0.750 | 0.250 |
| B4-CrossAccount | S0 | insertion-order-fifo | 8 | 0.125 | 0.333 | 0.583 | 1.000 | 0.125 | 0.875 | 0.125 |
| B4-CrossAccount | S0 | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| B4-CrossAccount | S0 | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| B4-CrossAccount | S0 | nearest-prior-issuance | 4 | 0.250 | 0.750 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| B4-CrossAccount | S0 | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| B4-CrossAccount | S0 | shuffled-fifo-control | 16 | 0.062 | 0.229 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| B4-CrossAccount | S0 | shuffled-fifo-control | 32 | 0.042 | 0.104 | 0.188 | 1.000 | 0.042 | 0.969 | 0.031 |
| B4-CrossAccount | S0 | shuffled-fifo-control | 4 | 0.500 | 0.833 | 1.000 | 1.000 | 0.500 | 0.750 | 0.250 |
| B4-CrossAccount | S0 | shuffled-fifo-control | 8 | 0.000 | 0.167 | 0.542 | 1.000 | 0.000 | 0.875 | 0.125 |
| B4-CrossAccount | S0 | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| B4-CrossAccount | S0 | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| B4-CrossAccount | S0 | uniform | 4 | 0.250 | 0.750 | 1.000 | 0.000 | – | – | 0.250 |
| B4-CrossAccount | S0 | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| B4-CrossAccount | S0 | window-k1 | 16 | 0.080 | 0.271 | 0.417 | 0.583 | 0.143 | 0.879 | 0.062 |
| B4-CrossAccount | S0 | window-k1 | 32 | 0.043 | 0.156 | 0.229 | 0.708 | 0.074 | 0.943 | 0.031 |
| B4-CrossAccount | S0 | window-k1 | 4 | 0.222 | 0.917 | 1.000 | 0.500 | 0.500 | 0.417 | 0.250 |
| B4-CrossAccount | S0 | window-k1 | 8 | 0.082 | 0.292 | 0.583 | 0.625 | 0.133 | 0.792 | 0.125 |
| B4-CrossAccount | S0 | window-k2 | 16 | 0.107 | 0.271 | 0.417 | 0.708 | 0.294 | 0.805 | 0.062 |
| B4-CrossAccount | S0 | window-k2 | 32 | 0.042 | 0.156 | 0.229 | 0.906 | 0.138 | 0.909 | 0.031 |
| B4-CrossAccount | S0 | window-k2 | 4 | 0.312 | 0.917 | 1.000 | 0.417 | 0.800 | 0.400 | 0.250 |
| B4-CrossAccount | S0 | window-k2 | 8 | 0.071 | 0.292 | 0.583 | 0.875 | 0.190 | 0.667 | 0.125 |
| B4-CrossAccount | S0 | window-k4 | 16 | 0.079 | 0.271 | 0.417 | 0.812 | 0.462 | 0.638 | 0.062 |
| B4-CrossAccount | S0 | window-k4 | 32 | 0.032 | 0.156 | 0.229 | 0.990 | 0.189 | 0.830 | 0.031 |
| B4-CrossAccount | S0 | window-k4 | 4 | 0.306 | 0.917 | 1.000 | 0.333 | 0.750 | 0.438 | 0.250 |
| B4-CrossAccount | S0 | window-k4 | 8 | 0.111 | 0.292 | 0.583 | 0.917 | 0.545 | 0.449 | 0.125 |
| B4-CrossAccount | S1 | insertion-order-fifo | 16 | 0.500 | 0.833 | 0.979 | 1.000 | 0.500 | 0.938 | 0.062 |
| B4-CrossAccount | S1 | insertion-order-fifo | 32 | 0.344 | 0.760 | 0.958 | 1.000 | 0.344 | 0.969 | 0.031 |
| B4-CrossAccount | S1 | insertion-order-fifo | 4 | 0.417 | 0.750 | 1.000 | 1.000 | 0.417 | 0.750 | 0.250 |
| B4-CrossAccount | S1 | insertion-order-fifo | 8 | 0.667 | 0.917 | 1.000 | 1.000 | 0.667 | 0.875 | 0.125 |
| B4-CrossAccount | S1 | nearest-prior-issuance | 16 | 0.062 | 0.188 | 0.312 | 1.000 | 0.062 | 0.938 | 0.062 |
| B4-CrossAccount | S1 | nearest-prior-issuance | 32 | 0.031 | 0.094 | 0.156 | 1.000 | 0.031 | 0.969 | 0.031 |
| B4-CrossAccount | S1 | nearest-prior-issuance | 4 | 0.250 | 0.750 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| B4-CrossAccount | S1 | nearest-prior-issuance | 8 | 0.125 | 0.375 | 0.625 | 1.000 | 0.125 | 0.875 | 0.125 |
| B4-CrossAccount | S1 | shuffled-fifo-control | 16 | 0.042 | 0.146 | 0.292 | 1.000 | 0.042 | 0.938 | 0.062 |
| B4-CrossAccount | S1 | shuffled-fifo-control | 32 | 0.031 | 0.094 | 0.177 | 1.000 | 0.031 | 0.969 | 0.031 |
| B4-CrossAccount | S1 | shuffled-fifo-control | 4 | 0.250 | 0.917 | 1.000 | 1.000 | 0.250 | 0.750 | 0.250 |
| B4-CrossAccount | S1 | shuffled-fifo-control | 8 | 0.083 | 0.250 | 0.625 | 1.000 | 0.083 | 0.875 | 0.125 |
| B4-CrossAccount | S1 | uniform | 16 | 0.062 | 0.188 | 0.312 | 0.000 | – | – | 0.062 |
| B4-CrossAccount | S1 | uniform | 32 | 0.031 | 0.094 | 0.156 | 0.000 | – | – | 0.031 |
| B4-CrossAccount | S1 | uniform | 4 | 0.250 | 0.750 | 1.000 | 0.000 | – | – | 0.250 |
| B4-CrossAccount | S1 | uniform | 8 | 0.125 | 0.375 | 0.625 | 0.000 | – | – | 0.125 |
| B4-CrossAccount | S1 | window-k1 | 16 | 0.367 | 0.875 | 0.979 | 0.771 | 0.649 | 0.899 | 0.062 |
| B4-CrossAccount | S1 | window-k1 | 32 | 0.288 | 0.802 | 0.948 | 0.875 | 0.643 | 0.930 | 0.031 |
| B4-CrossAccount | S1 | window-k1 | 4 | 0.347 | 0.833 | 1.000 | 0.833 | 0.600 | 0.525 | 0.250 |
| B4-CrossAccount | S1 | window-k1 | 8 | 0.368 | 0.958 | 1.000 | 0.667 | 0.812 | 0.781 | 0.125 |
| B4-CrossAccount | S1 | window-k2 | 16 | 0.294 | 0.875 | 0.979 | 0.896 | 0.791 | 0.840 | 0.062 |
| B4-CrossAccount | S1 | window-k2 | 32 | 0.265 | 0.802 | 0.948 | 0.969 | 0.817 | 0.887 | 0.031 |
| B4-CrossAccount | S1 | window-k2 | 4 | 0.250 | 0.833 | 1.000 | 0.833 | 0.700 | 0.375 | 0.250 |
| B4-CrossAccount | S1 | window-k2 | 8 | 0.375 | 0.958 | 1.000 | 0.833 | 0.950 | 0.681 | 0.125 |
| B4-CrossAccount | S1 | window-k4 | 16 | 0.251 | 0.875 | 0.979 | 1.000 | 0.917 | 0.737 | 0.062 |
| B4-CrossAccount | S1 | window-k4 | 32 | 0.190 | 0.802 | 0.948 | 1.000 | 1.000 | 0.804 | 0.031 |
| B4-CrossAccount | S1 | window-k4 | 4 | 0.250 | 0.833 | 1.000 | 0.167 | 0.500 | 0.375 | 0.250 |
| B4-CrossAccount | S1 | window-k4 | 8 | 0.311 | 0.958 | 1.000 | 0.875 | 0.952 | 0.536 | 0.125 |

#### Learned models (conditional logit; L2 chosen by inner CV on training runs; leave-one-replicate-out, pooled N)

| relation | baseline | scen. | conv. | feature set | subjects | top-1 | top-3 | CE bits | chance bits | Brier | ECE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S0 | field_kind | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | G-minus-eq | 180 | 0.039 [0.006, 0.087] | 0.178 | 4.267 [3.531, 4.644] | 4.267 | 0.935 | 0.036 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | G-minus-eq-minus-timing | 180 | 0.050 [0.015, 0.095] | 0.144 | 4.268 [3.528, 4.644] | 4.267 | 0.935 | 0.023 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-eq | 180 | 0.056 [0.014, 0.113] | 0.217 | 4.269 [3.537, 4.652] | 4.267 | 0.935 | 0.028 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-eq-minus-timing | 180 | 0.050 [0.015, 0.095] | 0.144 | 4.268 [3.528, 4.644] | 4.267 | 0.935 | 0.023 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+G-minus-eq | 180 | 0.050 [0.012, 0.113] | 0.222 | 4.268 [3.537, 4.652] | 4.267 | 0.935 | 0.033 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | field_kind | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | G-minus-eq | 180 | 0.039 [0.006, 0.087] | 0.178 | 4.267 [3.531, 4.644] | 4.267 | 0.935 | 0.036 |
| R2 | B3-PrivGas-v1 | S0 | primary | G-minus-eq-minus-timing | 180 | 0.050 [0.015, 0.095] | 0.144 | 4.268 [3.528, 4.644] | 4.267 | 0.935 | 0.023 |
| R2 | B3-PrivGas-v1 | S0 | primary | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-eq | 180 | 0.056 [0.014, 0.113] | 0.217 | 4.269 [3.537, 4.652] | 4.267 | 0.935 | 0.028 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-eq-minus-timing | 180 | 0.050 [0.015, 0.095] | 0.144 | 4.268 [3.528, 4.644] | 4.267 | 0.935 | 0.023 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+G-minus-eq | 180 | 0.050 [0.012, 0.113] | 0.222 | 4.268 [3.537, 4.652] | 4.267 | 0.935 | 0.033 |
| R2 | B3-PrivGas-v1 | S0 | primary | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | G-minus-eq | 180 | 0.339 [0.239, 0.459] | 0.839 | 2.097 [1.720, 2.406] | 4.267 | 0.724 | 0.132 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | G-minus-eq-minus-timing | 180 | 0.078 [0.031, 0.158] | 0.178 | 4.270 [3.520, 4.651] | 4.267 | 0.934 | 0.007 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-eq | 180 | 0.339 [0.239, 0.459] | 0.839 | 2.098 [1.720, 2.407] | 4.267 | 0.725 | 0.132 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-eq-minus-timing | 180 | 0.078 [0.031, 0.158] | 0.178 | 4.270 [3.520, 4.651] | 4.267 | 0.934 | 0.007 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+G-minus-eq | 180 | 0.339 [0.239, 0.459] | 0.839 | 2.098 [1.720, 2.407] | 4.267 | 0.725 | 0.132 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | field_kind | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.001 [0.000, 0.001] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | G-minus-eq | 180 | 0.339 [0.239, 0.459] | 0.839 | 2.097 [1.720, 2.406] | 4.267 | 0.724 | 0.132 |
| R2 | B3-PrivGas-v1 | S1 | primary | G-minus-eq-minus-timing | 180 | 0.078 [0.031, 0.158] | 0.178 | 4.270 [3.520, 4.651] | 4.267 | 0.934 | 0.007 |
| R2 | B3-PrivGas-v1 | S1 | primary | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-app | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-eq | 180 | 0.339 [0.239, 0.459] | 0.839 | 2.098 [1.720, 2.407] | 4.267 | 0.725 | 0.132 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-eq-minus-timing | 180 | 0.078 [0.031, 0.158] | 0.178 | 4.270 [3.520, 4.651] | 4.267 | 0.934 | 0.007 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-gas | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-pm | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+G | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+G-minus-eq | 180 | 0.339 [0.239, 0.459] | 0.839 | 2.098 [1.720, 2.407] | 4.267 | 0.725 | 0.132 |
| R2 | B3-PrivGas-v1 | S1 | primary | T+G-minus-timing | 180 | 1.000 [1.000, 1.000] | 1.000 | 0.000 [0.000, 0.000] | 4.267 | 0.000 | 0.000 |
| R2 | B3-PrivGas-v1 | S1 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S0 | field_kind | G | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | field_kind | G-minus-eq | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | field_kind | G-minus-eq-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | field_kind | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA | 180 | 0.067 [0.017, 0.157] | 0.217 | 4.267 [3.510, 4.648] | 4.267 | 0.934 | 0.013 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA+G | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.512, 4.647] | 4.267 | 0.934 | 0.022 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA+G-minus-app | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.512, 4.647] | 4.267 | 0.934 | 0.022 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA+G-minus-eq | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.512, 4.647] | 4.267 | 0.934 | 0.022 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA+G-minus-eq-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA+G-minus-gas | 180 | 0.061 [0.015, 0.140] | 0.183 | 4.268 [3.510, 4.648] | 4.267 | 0.934 | 0.020 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA+G-minus-pm | 180 | 0.078 [0.034, 0.147] | 0.244 | 4.266 [3.518, 4.648] | 4.267 | 0.935 | 0.039 |
| R2 | B4-CrossAccount | S0 | field_kind | T+AA+G-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | field_kind | T+G | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | field_kind | T+G-minus-eq | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | field_kind | T+G-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | field_kind | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S0 | primary | G | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | primary | G-minus-eq | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | primary | G-minus-eq-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | primary | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S0 | primary | T+AA | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S0 | primary | T+AA+G | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.512, 4.647] | 4.267 | 0.934 | 0.022 |
| R2 | B4-CrossAccount | S0 | primary | T+AA+G-minus-app | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.512, 4.647] | 4.267 | 0.934 | 0.022 |
| R2 | B4-CrossAccount | S0 | primary | T+AA+G-minus-eq | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.512, 4.647] | 4.267 | 0.934 | 0.022 |
| R2 | B4-CrossAccount | S0 | primary | T+AA+G-minus-eq-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | primary | T+AA+G-minus-gas | 180 | 0.061 [0.015, 0.140] | 0.183 | 4.268 [3.510, 4.648] | 4.267 | 0.934 | 0.020 |
| R2 | B4-CrossAccount | S0 | primary | T+AA+G-minus-pm | 180 | 0.078 [0.034, 0.147] | 0.244 | 4.266 [3.518, 4.648] | 4.267 | 0.935 | 0.039 |
| R2 | B4-CrossAccount | S0 | primary | T+AA+G-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | primary | T+G | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | primary | T+G-minus-eq | 180 | 0.072 [0.033, 0.129] | 0.239 | 4.265 [3.514, 4.647] | 4.267 | 0.934 | 0.023 |
| R2 | B4-CrossAccount | S0 | primary | T+G-minus-timing | 180 | 0.081 [0.032, 0.156] | 0.244 | 4.266 [3.517, 4.648] | 4.267 | 0.934 | 0.010 |
| R2 | B4-CrossAccount | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S1 | field_kind | G | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | field_kind | G-minus-eq | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | field_kind | G-minus-eq-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | field_kind | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA | 180 | 0.433 [0.294, 0.616] | 0.800 | 2.658 [2.064, 3.294] | 4.267 | 0.772 | 0.178 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA+G | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.104 [1.727, 2.439] | 4.267 | 0.727 | 0.131 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA+G-minus-app | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.104 [1.727, 2.439] | 4.267 | 0.727 | 0.131 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA+G-minus-eq | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.104 [1.727, 2.439] | 4.267 | 0.727 | 0.131 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA+G-minus-eq-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA+G-minus-gas | 180 | 0.322 [0.224, 0.449] | 0.839 | 2.083 [1.708, 2.391] | 4.267 | 0.719 | 0.128 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA+G-minus-pm | 180 | 0.344 [0.250, 0.457] | 0.844 | 2.101 [1.716, 2.437] | 4.267 | 0.725 | 0.119 |
| R2 | B4-CrossAccount | S1 | field_kind | T+AA+G-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | field_kind | T+G | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | field_kind | T+G-minus-eq | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | field_kind | T+G-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | field_kind | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S1 | primary | G | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | primary | G-minus-eq | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | primary | G-minus-eq-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | primary | T | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S1 | primary | T+AA | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R2 | B4-CrossAccount | S1 | primary | T+AA+G | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.104 [1.727, 2.439] | 4.267 | 0.727 | 0.131 |
| R2 | B4-CrossAccount | S1 | primary | T+AA+G-minus-app | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.104 [1.727, 2.439] | 4.267 | 0.727 | 0.131 |
| R2 | B4-CrossAccount | S1 | primary | T+AA+G-minus-eq | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.104 [1.727, 2.439] | 4.267 | 0.727 | 0.131 |
| R2 | B4-CrossAccount | S1 | primary | T+AA+G-minus-eq-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | primary | T+AA+G-minus-gas | 180 | 0.322 [0.224, 0.449] | 0.839 | 2.083 [1.708, 2.391] | 4.267 | 0.719 | 0.128 |
| R2 | B4-CrossAccount | S1 | primary | T+AA+G-minus-pm | 180 | 0.344 [0.250, 0.457] | 0.844 | 2.101 [1.716, 2.437] | 4.267 | 0.725 | 0.119 |
| R2 | B4-CrossAccount | S1 | primary | T+AA+G-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | primary | T+G | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | primary | T+G-minus-eq | 180 | 0.339 [0.236, 0.446] | 0.839 | 2.103 [1.727, 2.438] | 4.267 | 0.727 | 0.130 |
| R2 | B4-CrossAccount | S1 | primary | T+G-minus-timing | 180 | 0.072 [0.026, 0.158] | 0.239 | 4.267 [3.527, 4.646] | 4.267 | 0.933 | 0.021 |
| R2 | B4-CrossAccount | S1 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B3-PrivGas-v1 | S0 | primary | G | 180 | 0.067 [0.022, 0.144] | 0.161 | 4.310 [3.596, 4.672] | 4.267 | 0.942 | 0.025 |
| R3 | B3-PrivGas-v1 | S0 | primary | T | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.634] | 4.267 | 0.933 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G | 180 | 0.083 [0.034, 0.176] | 0.211 | 4.303 [3.610, 4.656] | 4.267 | 0.941 | 0.036 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-app | 180 | 0.067 [0.027, 0.129] | 0.183 | 4.275 [3.528, 4.657] | 4.267 | 0.935 | 0.010 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-eq | 180 | 0.056 [0.008, 0.157] | 0.211 | 4.299 [3.597, 4.654] | 4.267 | 0.940 | 0.061 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-gas | 180 | 0.078 [0.027, 0.169] | 0.217 | 4.262 [3.532, 4.640] | 4.267 | 0.933 | 0.031 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-pm | 180 | 0.083 [0.034, 0.176] | 0.211 | 4.303 [3.610, 4.656] | 4.267 | 0.941 | 0.036 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+AA+G-minus-timing | 180 | 0.039 [0.007, 0.083] | 0.150 | 4.320 [3.638, 4.678] | 4.267 | 0.943 | 0.043 |
| R3 | B3-PrivGas-v1 | S0 | primary | T+G | 180 | 0.078 [0.027, 0.167] | 0.217 | 4.302 [3.610, 4.656] | 4.267 | 0.941 | 0.042 |
| R3 | B3-PrivGas-v1 | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B3-PrivGas-v1 | S1 | primary | G | 180 | 0.083 [0.039, 0.150] | 0.200 | 4.289 [3.520, 4.667] | 4.267 | 0.936 | 0.013 |
| R3 | B3-PrivGas-v1 | S1 | primary | T | 180 | 0.056 [0.019, 0.098] | 0.200 | 4.345 [3.650, 4.706] | 4.267 | 0.950 | 0.031 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA | 180 | 0.050 [0.016, 0.090] | 0.178 | 4.351 [3.665, 4.709] | 4.267 | 0.951 | 0.037 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G | 180 | 0.050 [0.016, 0.101] | 0.189 | 4.296 [3.561, 4.665] | 4.267 | 0.939 | 0.031 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-app | 180 | 0.050 [0.015, 0.107] | 0.194 | 4.289 [3.544, 4.663] | 4.267 | 0.937 | 0.026 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-eq | 180 | 0.044 [0.012, 0.100] | 0.189 | 4.295 [3.562, 4.667] | 4.267 | 0.939 | 0.033 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-gas | 180 | 0.061 [0.021, 0.103] | 0.189 | 4.354 [3.684, 4.716] | 4.267 | 0.951 | 0.027 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-pm | 180 | 0.050 [0.016, 0.101] | 0.189 | 4.296 [3.561, 4.665] | 4.267 | 0.939 | 0.031 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+AA+G-minus-timing | 180 | 0.072 [0.024, 0.148] | 0.211 | 4.275 [3.520, 4.653] | 4.267 | 0.934 | 0.010 |
| R3 | B3-PrivGas-v1 | S1 | primary | T+G | 180 | 0.072 [0.029, 0.134] | 0.200 | 4.289 [3.544, 4.660] | 4.267 | 0.938 | 0.021 |
| R3 | B3-PrivGas-v1 | S1 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B4-CrossAccount | S0 | primary | G | 180 | 0.056 [0.022, 0.104] | 0.219 | 4.302 [3.569, 4.670] | 4.267 | 0.940 | 0.018 |
| R3 | B4-CrossAccount | S0 | primary | T | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.634] | 4.267 | 0.933 | 0.042 |
| R3 | B4-CrossAccount | S0 | primary | T+AA | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B4-CrossAccount | S0 | primary | T+AA+G | 180 | 0.067 [0.019, 0.158] | 0.228 | 4.295 [3.597, 4.653] | 4.267 | 0.939 | 0.034 |
| R3 | B4-CrossAccount | S0 | primary | T+AA+G-minus-app | 180 | 0.078 [0.037, 0.143] | 0.200 | 4.303 [3.571, 4.675] | 4.267 | 0.939 | 0.012 |
| R3 | B4-CrossAccount | S0 | primary | T+AA+G-minus-eq | 180 | 0.056 [0.008, 0.158] | 0.217 | 4.294 [3.587, 4.652] | 4.267 | 0.939 | 0.053 |
| R3 | B4-CrossAccount | S0 | primary | T+AA+G-minus-gas | 180 | 0.067 [0.016, 0.155] | 0.217 | 4.260 [3.528, 4.635] | 4.267 | 0.933 | 0.042 |
| R3 | B4-CrossAccount | S0 | primary | T+AA+G-minus-pm | 180 | 0.067 [0.019, 0.158] | 0.228 | 4.295 [3.597, 4.653] | 4.267 | 0.939 | 0.034 |
| R3 | B4-CrossAccount | S0 | primary | T+AA+G-minus-timing | 180 | 0.061 [0.024, 0.108] | 0.178 | 4.303 [3.581, 4.672] | 4.267 | 0.940 | 0.018 |
| R3 | B4-CrossAccount | S0 | primary | T+G | 180 | 0.067 [0.019, 0.158] | 0.222 | 4.295 [3.597, 4.653] | 4.267 | 0.939 | 0.034 |
| R3 | B4-CrossAccount | S0 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |
| R3 | B4-CrossAccount | S1 | primary | G | 180 | 0.064 [0.019, 0.135] | 0.211 | 4.280 [3.530, 4.653] | 4.267 | 0.936 | 0.028 |
| R3 | B4-CrossAccount | S1 | primary | T | 180 | 0.056 [0.019, 0.098] | 0.200 | 4.345 [3.650, 4.706] | 4.267 | 0.950 | 0.031 |
| R3 | B4-CrossAccount | S1 | primary | T+AA | 180 | 0.050 [0.016, 0.090] | 0.178 | 4.351 [3.665, 4.709] | 4.267 | 0.951 | 0.037 |
| R3 | B4-CrossAccount | S1 | primary | T+AA+G | 180 | 0.044 [0.014, 0.080] | 0.167 | 4.375 [3.700, 4.735] | 4.267 | 0.954 | 0.046 |
| R3 | B4-CrossAccount | S1 | primary | T+AA+G-minus-app | 180 | 0.028 [0.000, 0.071] | 0.139 | 4.297 [3.575, 4.664] | 4.267 | 0.939 | 0.048 |
| R3 | B4-CrossAccount | S1 | primary | T+AA+G-minus-eq | 180 | 0.033 [0.000, 0.085] | 0.144 | 4.372 [3.685, 4.738] | 4.267 | 0.954 | 0.052 |
| R3 | B4-CrossAccount | S1 | primary | T+AA+G-minus-gas | 180 | 0.050 [0.016, 0.090] | 0.178 | 4.351 [3.665, 4.709] | 4.267 | 0.951 | 0.037 |
| R3 | B4-CrossAccount | S1 | primary | T+AA+G-minus-pm | 180 | 0.044 [0.014, 0.080] | 0.167 | 4.375 [3.700, 4.735] | 4.267 | 0.954 | 0.046 |
| R3 | B4-CrossAccount | S1 | primary | T+AA+G-minus-timing | 180 | 0.056 [0.020, 0.103] | 0.200 | 4.280 [3.540, 4.652] | 4.267 | 0.936 | 0.022 |
| R3 | B4-CrossAccount | S1 | primary | T+G | 180 | 0.044 [0.014, 0.080] | 0.167 | 4.368 [3.686, 4.726] | 4.267 | 0.953 | 0.045 |
| R3 | B4-CrossAccount | S1 | primary | none | 180 | 0.067 [0.048, 0.111] | 0.200 | 4.267 [3.517, 4.645] | 4.267 | 0.933 | 0.000 |

#### delta_bits (held-out CE difference in bits; paired cluster bootstrap 95% CI)

| relation | baseline | scen. | fold | conv. | from | to | CE from | CE to | delta_bits [CI] |
|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | G | 5.000 | 0.004 | 4.996 [4.996, 4.996] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+AA | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+AA | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | G-minus-eq | 5.000 | 5.020 | -0.020 [-0.057, 0.017] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T+G-minus-eq | 5.000 | 5.011 | -0.011 [-0.058, 0.032] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T | T+G-minus-eq | 5.000 | 5.011 | -0.011 [-0.058, 0.032] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T+AA+G-minus-eq | 5.000 | 5.013 | -0.013 [-0.061, 0.033] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | G-minus-eq-minus-timing | 5.000 | 5.015 | -0.015 [-0.032, 0.003] |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.015 | -0.015 [-0.032, 0.003] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | G | 5.000 | 0.004 | 4.996 [4.996, 4.996] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | G-minus-eq | 5.000 | 5.020 | -0.020 [-0.057, 0.017] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T+G-minus-eq | 5.000 | 5.011 | -0.011 [-0.058, 0.032] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+G-minus-eq | 5.000 | 5.011 | -0.011 [-0.058, 0.032] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 5.013 | -0.013 [-0.061, 0.033] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | G-minus-eq-minus-timing | 5.000 | 5.015 | -0.015 [-0.032, 0.003] |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.015 | -0.015 [-0.032, 0.003] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | G-minus-eq | 4.267 | 4.267 | -0.000 [-0.026, 0.021] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T+G-minus-eq | 4.267 | 4.268 | -0.001 [-0.056, 0.041] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | T | T+G-minus-eq | 4.267 | 4.268 | -0.001 [-0.056, 0.041] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T+AA+G-minus-eq | 4.267 | 4.269 | -0.002 [-0.058, 0.042] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.268 | -0.001 [-0.024, 0.016] |
| R2 | B3-PrivGas-v1 | S0 | loro | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.268 | -0.001 [-0.024, 0.016] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | G-minus-eq | 4.267 | 4.267 | -0.000 [-0.026, 0.021] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T+G-minus-eq | 4.267 | 4.268 | -0.001 [-0.056, 0.041] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | T | T+G-minus-eq | 4.267 | 4.268 | -0.001 [-0.056, 0.041] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 4.269 | -0.002 [-0.058, 0.042] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | G-minus-eq-minus-timing | 4.267 | 4.268 | -0.001 [-0.024, 0.016] |
| R2 | B3-PrivGas-v1 | S0 | loro | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.268 | -0.001 [-0.024, 0.016] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | G | 4.267 | 0.001 | 4.265 [3.517, 4.646] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+G | T+AA+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | G-minus-eq | 4.267 | 9.172 | -4.906 [-6.396, -2.731] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T+G-minus-eq | 4.267 | 8.736 | -4.469 [-5.873, -2.299] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T | T+G-minus-eq | 4.267 | 8.736 | -4.469 [-5.873, -2.299] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T+AA+G-minus-eq | 4.267 | 8.863 | -4.597 [-6.021, -2.445] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.263 | 0.004 [-0.010, 0.017] |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.263 | 0.004 [-0.010, 0.017] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | G | 4.267 | 0.001 | 4.265 [3.517, 4.646] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+G | T+AA+G | 0.001 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | G-minus-eq | 4.267 | 9.172 | -4.906 [-6.396, -2.731] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T+G-minus-eq | 4.267 | 8.736 | -4.469 [-5.873, -2.299] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+G-minus-eq | 4.267 | 8.736 | -4.469 [-5.873, -2.299] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 8.863 | -4.597 [-6.021, -2.445] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | G-minus-eq-minus-timing | 4.267 | 4.263 | 0.004 [-0.010, 0.017] |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.263 | 0.004 [-0.010, 0.017] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | G | 5.000 | 0.003 | 4.997 [4.997, 4.997] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+AA | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+AA | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T+G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T | T+G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T+AA+G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | G-minus-eq-minus-timing | 5.000 | 5.014 | -0.014 [-0.033, 0.004] |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.014 | -0.014 [-0.033, 0.004] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | G | 5.000 | 0.003 | 4.997 [4.997, 4.997] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+G | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA+G | 5.000 | 0.001 | 4.999 [4.999, 4.999] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+G | T+AA+G | 0.002 | 0.001 | 0.001 [0.001, 0.001] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T+G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T+G-minus-timing | 5.000 | 0.002 | 4.998 [4.998, 4.998] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 2.361 | 2.639 [2.402, 2.850] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | G-minus-eq-minus-timing | 5.000 | 5.014 | -0.014 [-0.033, 0.004] |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.014 | -0.014 [-0.033, 0.004] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | G-minus-eq | 4.267 | 2.097 | 2.170 [1.471, 2.524] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T+G-minus-eq | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | T | T+G-minus-eq | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T+AA+G-minus-eq | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.270 | -0.003 [-0.015, 0.009] |
| R2 | B3-PrivGas-v1 | S1 | loro | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.270 | -0.003 [-0.015, 0.009] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | G-minus-eq | 4.267 | 2.097 | 2.170 [1.471, 2.524] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T+G-minus-eq | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | T | T+G-minus-eq | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | G-minus-eq-minus-timing | 4.267 | 4.270 | -0.003 [-0.015, 0.009] |
| R2 | B3-PrivGas-v1 | S1 | loro | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.270 | -0.003 [-0.015, 0.009] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+AA | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+AA | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | G-minus-eq | 4.267 | 4.180 | 0.087 [0.057, 0.107] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T+G-minus-eq | 4.267 | 3.978 | 0.288 [0.183, 0.396] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T | T+G-minus-eq | 4.267 | 3.978 | 0.288 [0.183, 0.396] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T+AA+G-minus-eq | 4.267 | 3.972 | 0.294 [0.190, 0.401] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.264 | 0.003 [-0.018, 0.020] |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.264 | 0.003 [-0.018, 0.020] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | G | 4.267 | 0.001 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+G | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA+G | 4.267 | 0.000 | 4.267 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+G | T+AA+G | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | G-minus-eq | 4.267 | 4.180 | 0.087 [0.057, 0.107] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T+G-minus-eq | 4.267 | 3.978 | 0.288 [0.183, 0.396] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+G-minus-eq | 4.267 | 3.978 | 0.288 [0.183, 0.396] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T+G-minus-timing | 4.267 | 0.000 | 4.266 [3.517, 4.647] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 3.972 | 0.294 [0.190, 0.401] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | G-minus-eq-minus-timing | 4.267 | 4.264 | 0.003 [-0.018, 0.020] |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.264 | 0.003 [-0.018, 0.020] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | G | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T | T+AA | 5.000 | 5.003 | -0.003 [-0.019, 0.012] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T | T+G | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T+AA | T+AA+G | 5.003 | 5.014 | -0.012 [-0.044, 0.017] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T | T+AA+G | 5.000 | 5.014 | -0.014 [-0.056, 0.025] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T+G | T+AA+G | 5.013 | 5.014 | -0.002 [-0.006, 0.002] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | G-minus-eq | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | T+G-minus-eq | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T | T+G-minus-eq | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | T+G-minus-timing | 5.000 | 5.008 | -0.008 [-0.032, 0.015] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | T+AA+G-minus-eq | 5.000 | 5.014 | -0.014 [-0.056, 0.025] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.032, 0.015] |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.032, 0.015] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | G | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | holdout | primary | T | T+G | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | primary | T+AA | T+AA+G | 5.000 | 5.014 | -0.014 [-0.056, 0.025] |
| R2 | B4-CrossAccount | S0 | holdout | primary | T | T+AA+G | 5.000 | 5.014 | -0.014 [-0.056, 0.025] |
| R2 | B4-CrossAccount | S0 | holdout | primary | T+G | T+AA+G | 5.013 | 5.014 | -0.002 [-0.006, 0.002] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | G-minus-eq | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | T+G-minus-eq | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | primary | T | T+G-minus-eq | 5.000 | 5.013 | -0.013 [-0.051, 0.024] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | T+G-minus-timing | 5.000 | 5.008 | -0.008 [-0.032, 0.015] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 5.014 | -0.014 [-0.056, 0.025] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.032, 0.015] |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.032, 0.015] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | G | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | T | T+AA | 4.267 | 4.267 | 0.000 [-0.014, 0.014] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | T | T+G | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | T+AA | T+AA+G | 4.267 | 4.265 | 0.001 [-0.021, 0.021] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | T | T+AA+G | 4.267 | 4.265 | 0.001 [-0.024, 0.024] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | T+G | T+AA+G | 4.265 | 4.265 | -0.000 [-0.004, 0.002] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | G-minus-eq | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | T+G-minus-eq | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | T | T+G-minus-eq | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | T+G-minus-timing | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | T+AA+G-minus-eq | 4.267 | 4.265 | 0.001 [-0.024, 0.024] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| R2 | B4-CrossAccount | S0 | loro | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | G | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | loro | primary | T | T+G | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | primary | T+AA | T+AA+G | 4.267 | 4.265 | 0.001 [-0.024, 0.024] |
| R2 | B4-CrossAccount | S0 | loro | primary | T | T+AA+G | 4.267 | 4.265 | 0.001 [-0.024, 0.024] |
| R2 | B4-CrossAccount | S0 | loro | primary | T+G | T+AA+G | 4.265 | 4.265 | -0.000 [-0.004, 0.002] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | G-minus-eq | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | T+G-minus-eq | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | primary | T | T+G-minus-eq | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | T+G-minus-timing | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 4.265 | 0.001 [-0.024, 0.024] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | G-minus-eq-minus-timing | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| R2 | B4-CrossAccount | S0 | loro | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | G | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T | T+AA | 4.267 | 7.875 | -3.609 [-4.759, -2.647] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T | T+G | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T+AA | T+AA+G | 7.875 | 9.220 | -1.345 [-2.632, 0.800] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T | T+AA+G | 4.267 | 9.220 | -4.954 [-6.448, -2.761] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T+G | T+AA+G | 9.217 | 9.220 | -0.004 [-0.008, -0.001] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | G-minus-eq | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | T+G-minus-eq | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T | T+G-minus-eq | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | T+G-minus-timing | 4.267 | 4.278 | -0.012 [-0.032, 0.006] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | T+AA+G-minus-eq | 4.267 | 9.220 | -4.954 [-6.448, -2.761] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.278 | -0.012 [-0.032, 0.006] |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.278 | -0.012 [-0.032, 0.006] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | G | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | transfer | primary | T | T+G | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | primary | T+AA | T+AA+G | 4.267 | 9.220 | -4.954 [-6.448, -2.761] |
| R2 | B4-CrossAccount | S0 | transfer | primary | T | T+AA+G | 4.267 | 9.220 | -4.954 [-6.448, -2.761] |
| R2 | B4-CrossAccount | S0 | transfer | primary | T+G | T+AA+G | 9.217 | 9.220 | -0.004 [-0.008, -0.001] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | G-minus-eq | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | T+G-minus-eq | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | primary | T | T+G-minus-eq | 4.267 | 9.217 | -4.950 [-6.443, -2.756] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | T+G-minus-timing | 4.267 | 4.278 | -0.012 [-0.032, 0.006] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 9.220 | -4.954 [-6.448, -2.761] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | G-minus-eq-minus-timing | 4.267 | 4.278 | -0.012 [-0.032, 0.006] |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.278 | -0.012 [-0.032, 0.006] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | G | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T | T+AA | 5.000 | 3.168 | 1.832 [1.723, 1.943] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T | T+G | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T+AA | T+AA+G | 3.168 | 2.346 | 0.822 [0.565, 1.016] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T | T+AA+G | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T+G | T+AA+G | 2.346 | 2.346 | 0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | T+G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T | T+G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | T+G-minus-timing | 5.000 | 5.008 | -0.008 [-0.031, 0.013] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | T+AA+G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.031, 0.013] |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.031, 0.013] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | T | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | G | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | T | T+AA | 5.000 | 5.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | holdout | primary | T | T+G | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | T+AA | T+AA+G | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | T | T+AA+G | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | T+G | T+AA+G | 2.346 | 2.346 | 0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | T+G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | T | T+G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | T+G-minus-timing | 5.000 | 5.008 | -0.008 [-0.031, 0.013] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 2.346 | 2.654 [2.392, 2.872] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.031, 0.013] |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | T+AA+G-minus-eq-minus-timing | 5.000 | 5.008 | -0.008 [-0.031, 0.013] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | G | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | T | T+AA | 4.267 | 2.658 | 1.609 [0.480, 2.118] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | T | T+G | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | T+AA | T+AA+G | 2.658 | 2.104 | 0.554 [0.222, 1.044] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | T | T+AA+G | 4.267 | 2.104 | 2.162 [1.463, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | T+G | T+AA+G | 2.103 | 2.104 | -0.001 [-0.002, 0.000] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | G-minus-eq | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | T+G-minus-eq | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | T | T+G-minus-eq | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | T+G-minus-timing | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | T+AA+G-minus-eq | 4.267 | 2.104 | 2.162 [1.463, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| R2 | B4-CrossAccount | S1 | loro | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | G | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | loro | primary | T | T+G | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | T+AA | T+AA+G | 4.267 | 2.104 | 2.162 [1.463, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | T | T+AA+G | 4.267 | 2.104 | 2.162 [1.463, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | T+G | T+AA+G | 2.103 | 2.104 | -0.001 [-0.002, 0.000] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | G-minus-eq | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | T+G-minus-eq | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | T | T+G-minus-eq | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | T+G-minus-timing | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 2.104 | 2.162 [1.463, 2.528] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | G-minus-eq-minus-timing | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| R2 | B4-CrossAccount | S1 | loro | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | G | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T | T+AA | 4.267 | 4.193 | 0.074 [0.039, 0.111] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T | T+G | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T+AA | T+AA+G | 4.193 | 4.185 | 0.008 [-0.038, 0.046] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T | T+AA+G | 4.267 | 4.185 | 0.082 [0.048, 0.106] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T+G | T+AA+G | 4.193 | 4.185 | 0.008 [0.004, 0.012] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | G-minus-eq | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | T+G-minus-eq | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T | T+G-minus-eq | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | T+G-minus-timing | 4.267 | 4.280 | -0.014 [-0.039, 0.009] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | T+AA+G-minus-eq | 4.267 | 4.185 | 0.082 [0.048, 0.106] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | G-minus-eq-minus-timing | 4.267 | 4.280 | -0.014 [-0.039, 0.009] |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.280 | -0.014 [-0.039, 0.009] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | T | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | G | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | primary | T | T+AA | 4.267 | 4.267 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | transfer | primary | T | T+G | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | primary | T+AA | T+AA+G | 4.267 | 4.185 | 0.082 [0.048, 0.106] |
| R2 | B4-CrossAccount | S1 | transfer | primary | T | T+AA+G | 4.267 | 4.185 | 0.082 [0.048, 0.106] |
| R2 | B4-CrossAccount | S1 | transfer | primary | T+G | T+AA+G | 4.193 | 4.185 | 0.008 [0.004, 0.012] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | G-minus-eq | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | T+G-minus-eq | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | primary | T | T+G-minus-eq | 4.267 | 4.193 | 0.074 [0.040, 0.098] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | T+G-minus-timing | 4.267 | 4.280 | -0.014 [-0.039, 0.009] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 4.185 | 0.082 [0.048, 0.106] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | G-minus-eq-minus-timing | 4.267 | 4.280 | -0.014 [-0.039, 0.009] |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | T+AA+G-minus-eq-minus-timing | 4.267 | 4.280 | -0.014 [-0.039, 0.009] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | none | T | 5.000 | 4.997 | 0.003 [-0.010, 0.014] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | none | G | 5.000 | 5.000 | -0.000 [-0.003, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA | 4.997 | 4.997 | -0.000 [-0.002, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+G | 4.997 | 4.998 | -0.001 [-0.003, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA | T+AA+G | 4.997 | 4.998 | -0.001 [-0.003, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T | T+AA+G | 4.997 | 4.998 | -0.001 [-0.004, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T+G | T+AA+G | 4.998 | 4.998 | -0.000 [-0.002, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 4.994 | 0.006 [-0.004, 0.016] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | none | T | 4.267 | 4.260 | 0.007 [-0.036, 0.043] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | none | G | 4.267 | 4.310 | -0.044 [-0.155, 0.002] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA | 4.260 | 4.260 | -0.000 [-0.001, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T | T+G | 4.260 | 4.302 | -0.043 [-0.154, 0.002] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T+AA | T+AA+G | 4.260 | 4.303 | -0.043 [-0.154, 0.002] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T | T+AA+G | 4.260 | 4.303 | -0.043 [-0.154, 0.002] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | T+G | T+AA+G | 4.302 | 4.303 | -0.000 [-0.001, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 4.299 | -0.033 [-0.160, 0.030] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | none | T | 4.267 | 4.345 | -0.078 [-0.352, 0.076] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | none | G | 4.267 | 4.289 | -0.022 [-0.068, 0.024] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA | 4.345 | 4.354 | -0.009 [-0.026, 0.001] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+G | 4.345 | 4.267 | 0.078 [-0.076, 0.344] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA | T+AA+G | 4.354 | 4.266 | 0.088 [-0.067, 0.363] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T | T+AA+G | 4.345 | 4.266 | 0.078 [-0.069, 0.341] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T+G | T+AA+G | 4.267 | 4.266 | 0.001 [-0.009, 0.008] |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 4.265 | 0.001 [-0.028, 0.030] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | none | T | 5.000 | 5.004 | -0.004 [-0.023, 0.014] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | none | G | 5.000 | 5.000 | 0.000 [-0.025, 0.024] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA | 5.004 | 5.004 | -0.000 [-0.001, 0.001] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+G | 5.004 | 5.005 | -0.001 [-0.025, 0.022] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA | T+AA+G | 5.004 | 5.005 | -0.001 [-0.026, 0.022] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T | T+AA+G | 5.004 | 5.005 | -0.001 [-0.025, 0.022] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T+G | T+AA+G | 5.005 | 5.005 | -0.000 [-0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 5.000 | -0.000 [-0.028, 0.027] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | none | T | 4.267 | 4.345 | -0.078 [-0.280, -0.003] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | none | G | 4.267 | 4.289 | -0.022 [-0.059, 0.009] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA | 4.345 | 4.351 | -0.007 [-0.019, -0.001] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T | T+G | 4.345 | 4.289 | 0.055 [-0.014, 0.244] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T+AA | T+AA+G | 4.351 | 4.296 | 0.056 [-0.014, 0.248] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T | T+AA+G | 4.345 | 4.296 | 0.049 [-0.019, 0.231] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | T+G | T+AA+G | 4.289 | 4.296 | -0.006 [-0.015, -0.002] |
| R3 | B3-PrivGas-v1 | S1 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 4.295 | -0.028 [-0.066, -0.000] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | none | T | 4.267 | 4.257 | 0.010 [-0.028, 0.054] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | none | G | 4.267 | 4.287 | -0.021 [-0.055, 0.002] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA | 4.257 | 4.256 | 0.000 [-0.000, 0.001] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+G | 4.257 | 4.279 | -0.022 [-0.058, 0.002] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA | T+AA+G | 4.256 | 4.279 | -0.023 [-0.058, 0.001] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T | T+AA+G | 4.257 | 4.279 | -0.022 [-0.058, 0.002] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T+G | T+AA+G | 4.279 | 4.279 | 0.000 [-0.000, 0.001] |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 4.275 | -0.008 [-0.057, 0.039] |
| R3 | B4-CrossAccount | S0 | holdout | primary | none | T | 5.000 | 4.997 | 0.003 [-0.010, 0.014] |
| R3 | B4-CrossAccount | S0 | holdout | primary | none | G | 5.000 | 5.000 | -0.000 [-0.011, 0.010] |
| R3 | B4-CrossAccount | S0 | holdout | primary | T | T+AA | 4.997 | 4.997 | -0.000 [-0.002, 0.001] |
| R3 | B4-CrossAccount | S0 | holdout | primary | T | T+G | 4.997 | 4.997 | 0.000 [-0.010, 0.010] |
| R3 | B4-CrossAccount | S0 | holdout | primary | T+AA | T+AA+G | 4.997 | 4.997 | 0.000 [-0.010, 0.010] |
| R3 | B4-CrossAccount | S0 | holdout | primary | T | T+AA+G | 4.997 | 4.997 | -0.000 [-0.010, 0.009] |
| R3 | B4-CrossAccount | S0 | holdout | primary | T+G | T+AA+G | 4.997 | 4.997 | -0.000 [-0.002, 0.001] |
| R3 | B4-CrossAccount | S0 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 4.994 | 0.006 [-0.009, 0.020] |
| R3 | B4-CrossAccount | S0 | loro | primary | none | T | 4.267 | 4.260 | 0.007 [-0.036, 0.043] |
| R3 | B4-CrossAccount | S0 | loro | primary | none | G | 4.267 | 4.302 | -0.035 [-0.149, 0.011] |
| R3 | B4-CrossAccount | S0 | loro | primary | T | T+AA | 4.260 | 4.260 | -0.000 [-0.001, 0.001] |
| R3 | B4-CrossAccount | S0 | loro | primary | T | T+G | 4.260 | 4.295 | -0.035 [-0.143, 0.009] |
| R3 | B4-CrossAccount | S0 | loro | primary | T+AA | T+AA+G | 4.260 | 4.295 | -0.035 [-0.142, 0.009] |
| R3 | B4-CrossAccount | S0 | loro | primary | T | T+AA+G | 4.260 | 4.295 | -0.035 [-0.143, 0.009] |
| R3 | B4-CrossAccount | S0 | loro | primary | T+G | T+AA+G | 4.295 | 4.295 | -0.000 [-0.001, 0.001] |
| R3 | B4-CrossAccount | S0 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 4.294 | -0.027 [-0.150, 0.035] |
| R3 | B4-CrossAccount | S0 | transfer | primary | none | T | 4.267 | 4.345 | -0.078 [-0.352, 0.076] |
| R3 | B4-CrossAccount | S0 | transfer | primary | none | G | 4.267 | 4.266 | 0.000 [-0.020, 0.019] |
| R3 | B4-CrossAccount | S0 | transfer | primary | T | T+AA | 4.345 | 4.354 | -0.009 [-0.026, 0.001] |
| R3 | B4-CrossAccount | S0 | transfer | primary | T | T+G | 4.345 | 4.340 | 0.004 [-0.018, 0.030] |
| R3 | B4-CrossAccount | S0 | transfer | primary | T+AA | T+AA+G | 4.354 | 4.350 | 0.004 [-0.018, 0.031] |
| R3 | B4-CrossAccount | S0 | transfer | primary | T | T+AA+G | 4.345 | 4.350 | -0.005 [-0.031, 0.020] |
| R3 | B4-CrossAccount | S0 | transfer | primary | T+G | T+AA+G | 4.340 | 4.350 | -0.009 [-0.026, 0.001] |
| R3 | B4-CrossAccount | S0 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 4.349 | -0.082 [-0.367, 0.084] |
| R3 | B4-CrossAccount | S1 | holdout | primary | none | T | 5.000 | 5.004 | -0.004 [-0.023, 0.014] |
| R3 | B4-CrossAccount | S1 | holdout | primary | none | G | 5.000 | 5.007 | -0.007 [-0.034, 0.019] |
| R3 | B4-CrossAccount | S1 | holdout | primary | T | T+AA | 5.004 | 5.004 | -0.000 [-0.001, 0.001] |
| R3 | B4-CrossAccount | S1 | holdout | primary | T | T+G | 5.004 | 5.010 | -0.006 [-0.033, 0.020] |
| R3 | B4-CrossAccount | S1 | holdout | primary | T+AA | T+AA+G | 5.004 | 5.010 | -0.006 [-0.033, 0.020] |
| R3 | B4-CrossAccount | S1 | holdout | primary | T | T+AA+G | 5.004 | 5.010 | -0.006 [-0.033, 0.020] |
| R3 | B4-CrossAccount | S1 | holdout | primary | T+G | T+AA+G | 5.010 | 5.010 | -0.000 [-0.001, 0.001] |
| R3 | B4-CrossAccount | S1 | holdout | primary | none | T+AA+G-minus-eq | 5.000 | 5.006 | -0.006 [-0.038, 0.023] |
| R3 | B4-CrossAccount | S1 | loro | primary | none | T | 4.267 | 4.345 | -0.078 [-0.280, -0.003] |
| R3 | B4-CrossAccount | S1 | loro | primary | none | G | 4.267 | 4.280 | -0.014 [-0.036, 0.002] |
| R3 | B4-CrossAccount | S1 | loro | primary | T | T+AA | 4.345 | 4.351 | -0.007 [-0.019, -0.001] |
| R3 | B4-CrossAccount | S1 | loro | primary | T | T+G | 4.345 | 4.368 | -0.024 [-0.074, 0.002] |
| R3 | B4-CrossAccount | S1 | loro | primary | T+AA | T+AA+G | 4.351 | 4.375 | -0.024 [-0.073, 0.002] |
| R3 | B4-CrossAccount | S1 | loro | primary | T | T+AA+G | 4.345 | 4.375 | -0.030 [-0.088, -0.003] |
| R3 | B4-CrossAccount | S1 | loro | primary | T+G | T+AA+G | 4.368 | 4.375 | -0.007 [-0.018, -0.001] |
| R3 | B4-CrossAccount | S1 | loro | primary | none | T+AA+G-minus-eq | 4.267 | 4.372 | -0.106 [-0.352, -0.017] |
| R3 | B4-CrossAccount | S1 | transfer | primary | none | T | 4.267 | 4.257 | 0.010 [-0.028, 0.054] |
| R3 | B4-CrossAccount | S1 | transfer | primary | none | G | 4.267 | 4.241 | 0.026 [-0.003, 0.096] |
| R3 | B4-CrossAccount | S1 | transfer | primary | T | T+AA | 4.257 | 4.256 | 0.000 [-0.000, 0.001] |
| R3 | B4-CrossAccount | S1 | transfer | primary | T | T+G | 4.257 | 4.236 | 0.021 [-0.005, 0.082] |
| R3 | B4-CrossAccount | S1 | transfer | primary | T+AA | T+AA+G | 4.256 | 4.235 | 0.021 [-0.006, 0.081] |
| R3 | B4-CrossAccount | S1 | transfer | primary | T | T+AA+G | 4.257 | 4.235 | 0.021 [-0.006, 0.082] |
| R3 | B4-CrossAccount | S1 | transfer | primary | T+G | T+AA+G | 4.236 | 4.235 | 0.000 [-0.001, 0.001] |
| R3 | B4-CrossAccount | S1 | transfer | primary | none | T+AA+G-minus-eq | 4.267 | 4.232 | 0.035 [-0.014, 0.126] |

#### Feature-family ablations of T+AA+G (positive = the removed family carried held-out information)

| relation | baseline | scen. | conv. | removed | CE full | CE without | delta_bits [CI] |
|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S0 | field_kind | timing | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | eq | 0.000 | 4.269 | 4.269 [3.540, 4.654] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | field_kind | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | timing | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | eq | 0.000 | 4.269 | 4.269 [3.540, 4.654] |
| R2 | B3-PrivGas-v1 | S0 | primary | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S0 | primary | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | timing | 0.000 | 0.000 | 0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | eq | 0.000 | 2.098 | 2.098 [1.708, 2.411] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | field_kind | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | timing | 0.000 | 0.000 | 0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | gas | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | eq | 0.000 | 2.098 | 2.098 [1.708, 2.411] |
| R2 | B3-PrivGas-v1 | S1 | primary | pm | 0.000 | 0.000 | -0.000 [-0.000, 0.000] |
| R2 | B3-PrivGas-v1 | S1 | primary | app | 0.000 | 0.000 | 0.000 [0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | field_kind | timing | 4.265 | 4.266 | 0.000 [-0.013, 0.014] |
| R2 | B4-CrossAccount | S0 | field_kind | gas | 4.265 | 4.268 | 0.003 [-0.016, 0.023] |
| R2 | B4-CrossAccount | S0 | field_kind | eq | 4.265 | 4.265 | 0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | field_kind | pm | 4.265 | 4.266 | 0.001 [-0.010, 0.012] |
| R2 | B4-CrossAccount | S0 | field_kind | app | 4.265 | 4.265 | -0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | primary | timing | 4.265 | 4.266 | 0.000 [-0.013, 0.014] |
| R2 | B4-CrossAccount | S0 | primary | gas | 4.265 | 4.268 | 0.003 [-0.016, 0.023] |
| R2 | B4-CrossAccount | S0 | primary | eq | 4.265 | 4.265 | 0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S0 | primary | pm | 4.265 | 4.266 | 0.001 [-0.010, 0.012] |
| R2 | B4-CrossAccount | S0 | primary | app | 4.265 | 4.265 | -0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | field_kind | timing | 2.104 | 4.267 | 2.163 [1.457, 2.528] |
| R2 | B4-CrossAccount | S1 | field_kind | gas | 2.104 | 2.083 | -0.021 [-0.079, 0.023] |
| R2 | B4-CrossAccount | S1 | field_kind | eq | 2.104 | 2.104 | 0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | field_kind | pm | 2.104 | 2.101 | -0.003 [-0.032, 0.019] |
| R2 | B4-CrossAccount | S1 | field_kind | app | 2.104 | 2.104 | 0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | primary | timing | 2.104 | 4.267 | 2.163 [1.457, 2.528] |
| R2 | B4-CrossAccount | S1 | primary | gas | 2.104 | 2.083 | -0.021 [-0.079, 0.023] |
| R2 | B4-CrossAccount | S1 | primary | eq | 2.104 | 2.104 | 0.000 [-0.000, 0.000] |
| R2 | B4-CrossAccount | S1 | primary | pm | 2.104 | 2.101 | -0.003 [-0.032, 0.019] |
| R2 | B4-CrossAccount | S1 | primary | app | 2.104 | 2.104 | 0.000 [-0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S0 | primary | timing | 4.303 | 4.320 | 0.017 [-0.023, 0.065] |
| R3 | B3-PrivGas-v1 | S0 | primary | gas | 4.303 | 4.262 | -0.041 [-0.152, 0.004] |
| R3 | B3-PrivGas-v1 | S0 | primary | eq | 4.303 | 4.299 | -0.003 [-0.026, 0.016] |
| R3 | B3-PrivGas-v1 | S0 | primary | pm | 4.303 | 4.303 | 0.000 [0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S0 | primary | app | 4.303 | 4.275 | -0.028 [-0.150, 0.031] |
| R3 | B3-PrivGas-v1 | S1 | primary | timing | 4.296 | 4.275 | -0.021 [-0.055, 0.003] |
| R3 | B3-PrivGas-v1 | S1 | primary | gas | 4.296 | 4.354 | 0.059 [-0.014, 0.263] |
| R3 | B3-PrivGas-v1 | S1 | primary | eq | 4.296 | 4.295 | -0.001 [-0.015, 0.011] |
| R3 | B3-PrivGas-v1 | S1 | primary | pm | 4.296 | 4.296 | 0.000 [0.000, 0.000] |
| R3 | B3-PrivGas-v1 | S1 | primary | app | 4.296 | 4.289 | -0.007 [-0.026, 0.007] |
| R3 | B4-CrossAccount | S0 | primary | timing | 4.295 | 4.303 | 0.008 [-0.044, 0.052] |
| R3 | B4-CrossAccount | S0 | primary | gas | 4.295 | 4.260 | -0.035 [-0.142, 0.009] |
| R3 | B4-CrossAccount | S0 | primary | eq | 4.295 | 4.294 | -0.001 [-0.020, 0.017] |
| R3 | B4-CrossAccount | S0 | primary | pm | 4.295 | 4.295 | 0.000 [0.000, 0.000] |
| R3 | B4-CrossAccount | S0 | primary | app | 4.295 | 4.303 | 0.008 [-0.046, 0.050] |
| R3 | B4-CrossAccount | S1 | primary | timing | 4.375 | 4.280 | -0.095 [-0.333, -0.009] |
| R3 | B4-CrossAccount | S1 | primary | gas | 4.375 | 4.351 | -0.024 [-0.073, 0.002] |
| R3 | B4-CrossAccount | S1 | primary | eq | 4.375 | 4.372 | -0.003 [-0.023, 0.014] |
| R3 | B4-CrossAccount | S1 | primary | pm | 4.375 | 4.375 | 0.000 [0.000, 0.000] |
| R3 | B4-CrossAccount | S1 | primary | app | 4.375 | 4.297 | -0.078 [-0.310, 0.004] |

#### Configuration and scenario holdouts (T+AA+G and T+G-minus-eq)

| relation | baseline | scen. | fold kind | conv. | feature set | subjects | top-1 | CE bits | chance bits |
|---|---|---|---|---|---|---|---|---|---|
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | T+G-minus-eq | 96 | 0.010 [0.000, 0.042] | 5.011 [4.967, 5.057] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | T+G-minus-eq | 96 | 0.010 [0.000, 0.042] | 5.011 [4.967, 5.057] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | T+G-minus-eq | 180 | 0.089 [0.037, 0.179] | 8.736 [5.833, 10.419] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | field_kind | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | T+G-minus-eq | 180 | 0.089 [0.037, 0.179] | 8.736 [5.833, 10.419] | 4.267 |
| R2 | B3-PrivGas-v1 | S0 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | T+G-minus-eq | 96 | 0.271 [0.146, 0.406] | 2.361 [2.155, 2.593] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA+G | 96 | 1.000 [1.000, 1.000] | 0.001 [0.001, 0.001] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | T+G-minus-eq | 96 | 0.271 [0.146, 0.406] | 2.361 [2.155, 2.593] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | T+G-minus-eq | 180 | 0.311 [0.202, 0.460] | 3.978 [3.259, 4.355] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | field_kind | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA+G | 180 | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | T+G-minus-eq | 180 | 0.311 [0.202, 0.460] | 3.978 [3.259, 4.355] | 4.267 |
| R2 | B3-PrivGas-v1 | S1 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T+AA+G | 96 | 0.042 [0.010, 0.094] | 5.014 [4.975, 5.057] | 5.000 |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | T+G-minus-eq | 96 | 0.042 [0.010, 0.084] | 5.013 [4.976, 5.051] | 5.000 |
| R2 | B4-CrossAccount | S0 | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B4-CrossAccount | S0 | holdout | primary | T+AA+G | 96 | 0.042 [0.010, 0.094] | 5.014 [4.975, 5.057] | 5.000 |
| R2 | B4-CrossAccount | S0 | holdout | primary | T+G-minus-eq | 96 | 0.042 [0.010, 0.084] | 5.013 [4.976, 5.051] | 5.000 |
| R2 | B4-CrossAccount | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T+AA+G | 180 | 0.094 [0.047, 0.162] | 9.220 [6.310, 10.915] | 4.267 |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | T+G-minus-eq | 180 | 0.094 [0.047, 0.162] | 9.217 [6.301, 10.912] | 4.267 |
| R2 | B4-CrossAccount | S0 | transfer | field_kind | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B4-CrossAccount | S0 | transfer | primary | T+AA+G | 180 | 0.094 [0.047, 0.162] | 9.220 [6.310, 10.915] | 4.267 |
| R2 | B4-CrossAccount | S0 | transfer | primary | T+G-minus-eq | 180 | 0.094 [0.047, 0.162] | 9.217 [6.301, 10.912] | 4.267 |
| R2 | B4-CrossAccount | S0 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T+AA+G | 96 | 0.271 [0.156, 0.406] | 2.346 [2.136, 2.605] | 5.000 |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | T+G-minus-eq | 96 | 0.271 [0.156, 0.406] | 2.346 [2.136, 2.605] | 5.000 |
| R2 | B4-CrossAccount | S1 | holdout | field_kind | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B4-CrossAccount | S1 | holdout | primary | T+AA+G | 96 | 0.271 [0.156, 0.406] | 2.346 [2.136, 2.605] | 5.000 |
| R2 | B4-CrossAccount | S1 | holdout | primary | T+G-minus-eq | 96 | 0.271 [0.156, 0.406] | 2.346 [2.136, 2.605] | 5.000 |
| R2 | B4-CrossAccount | S1 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T+AA+G | 180 | 0.250 [0.165, 0.371] | 4.185 [3.447, 4.563] | 4.267 |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | T+G-minus-eq | 180 | 0.233 [0.136, 0.362] | 4.193 [3.456, 4.570] | 4.267 |
| R2 | B4-CrossAccount | S1 | transfer | field_kind | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R2 | B4-CrossAccount | S1 | transfer | primary | T+AA+G | 180 | 0.250 [0.165, 0.371] | 4.185 [3.447, 4.563] | 4.267 |
| R2 | B4-CrossAccount | S1 | transfer | primary | T+G-minus-eq | 180 | 0.233 [0.136, 0.362] | 4.193 [3.456, 4.570] | 4.267 |
| R2 | B4-CrossAccount | S1 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | T+AA+G | 96 | 0.042 [0.000, 0.094] | 4.998 [4.986, 5.011] | 5.000 |
| R3 | B3-PrivGas-v1 | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | T+AA+G | 180 | 0.072 [0.025, 0.156] | 4.266 [3.512, 4.644] | 4.267 |
| R3 | B3-PrivGas-v1 | S0 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | T+AA+G | 96 | 0.031 [0.000, 0.083] | 5.005 [4.977, 5.035] | 5.000 |
| R3 | B3-PrivGas-v1 | S1 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | T+AA+G | 180 | 0.078 [0.030, 0.146] | 4.279 [3.507, 4.671] | 4.267 |
| R3 | B3-PrivGas-v1 | S1 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R3 | B4-CrossAccount | S0 | holdout | primary | T+AA+G | 96 | 0.052 [0.000, 0.146] | 4.997 [4.980, 5.016] | 5.000 |
| R3 | B4-CrossAccount | S0 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B4-CrossAccount | S0 | transfer | primary | T+AA+G | 180 | 0.094 [0.036, 0.198] | 4.350 [3.647, 4.724] | 4.267 |
| R3 | B4-CrossAccount | S0 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |
| R3 | B4-CrossAccount | S1 | holdout | primary | T+AA+G | 96 | 0.010 [0.000, 0.042] | 5.010 [4.977, 5.045] | 5.000 |
| R3 | B4-CrossAccount | S1 | holdout | primary | none | 96 | 0.031 [0.031, 0.031] | 5.000 [5.000, 5.000] | 5.000 |
| R3 | B4-CrossAccount | S1 | transfer | primary | T+AA+G | 180 | 0.089 [0.040, 0.169] | 4.235 [3.404, 4.640] | 4.267 |
| R3 | B4-CrossAccount | S1 | transfer | primary | none | 180 | 0.067 [0.048, 0.111] | 4.267 [3.517, 4.645] | 4.267 |

#### Audits and stop conditions

| check | result |
|---|---|
| leakage_selfcheck_ok | True |
| harness_public_order_equals_schedule | True |
| harness_order_leak_flags | 2 |
| split_audit_ok | True |
| split_learned_prediction_sets_checked | 4644 |
| r3_above_chance_flags | 0 |
| b3_clean_candidate_set_gt_1 | True |
| runs_failed | 0 |
| b4_account_separation_ok | True |
| r2_candidate_universe_identical_across_attacks | True |

Harness order audit (combined z over runs; |z| > 3.29 flags):

| baseline | scen. | pair | runs | mean rho | z |
|---|---|---|---|---|---|
| B3-PrivGas-v1 | S0 | deliver~act | 12 | 0.173 | 1.90 |
| B3-PrivGas-v1 | S0 | fund~act | 12 | 0.018 | -0.25 |
| B3-PrivGas-v1 | S0 | issue~act | 12 | 0.087 | 0.79 |
| B3-PrivGas-v1 | S0 | issue~prepare | 12 | 0.053 | 0.44 |
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
| B3-PrivGas-v1 | S1 | issue~prepare | 12 | 1.000 | 11.97 |
| B3-PrivGas-v1 | S1 | prepare~act | 12 | 0.841 | 10.87 |
| B3-PrivGas-v1 | S1 | slot~act | 12 | 0.017 | -0.41 |
| B3-PrivGas-v1 | S1 | slot~deliver | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~fund | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~issue | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~prepare | 12 | 0.004 | -0.56 |
| B3-PrivGas-v1 | S1 | slot~setup | 12 | 0.004 | -0.56 |
| B4-CrossAccount | S0 | deliver~act | 12 | 0.173 | 1.90 |
| B4-CrossAccount | S0 | fund~act | 12 | 0.018 | -0.25 |
| B4-CrossAccount | S0 | issue~act | 12 | 0.087 | 0.79 |
| B4-CrossAccount | S0 | issue~prepare | 12 | 0.053 | 0.44 |
| B4-CrossAccount | S0 | prepare~act | 12 | 0.001 | 0.03 |
| B4-CrossAccount | S0 | setup_issuer~act | 12 | -0.024 | 0.22 |
| B4-CrossAccount | S0 | setup_issuer~deliver | 12 | -0.075 | -0.61 |
| B4-CrossAccount | S0 | setup~setup_issuer | 12 | -0.066 | -0.70 |
| B4-CrossAccount | S0 | slot~act | 12 | 0.064 | 0.98 |
| B4-CrossAccount | S0 | slot~deliver | 12 | 0.009 | 0.88 |
| B4-CrossAccount | S0 | slot~fund | 12 | 0.143 | 0.60 |
| B4-CrossAccount | S0 | slot~issue | 12 | -0.025 | -0.16 |
| B4-CrossAccount | S0 | slot~prepare | 12 | -0.040 | -0.00 |
| B4-CrossAccount | S0 | slot~setup | 12 | 0.065 | 0.21 |
| B4-CrossAccount | S0 | slot~setup_issuer | 12 | 0.134 | 0.39 |
| B4-CrossAccount | S1 | deliver~act | 12 | 0.841 | 10.87 |
| B4-CrossAccount | S1 | fund~act | 12 | 0.841 | 10.87 |
| B4-CrossAccount | S1 | issue~act | 12 | 0.841 | 10.87 |
| B4-CrossAccount | S1 | issue~prepare | 12 | 1.000 | 11.97 |
| B4-CrossAccount | S1 | prepare~act | 12 | 0.841 | 10.87 |
| B4-CrossAccount | S1 | setup_issuer~act | 12 | 0.181 | 1.29 |
| B4-CrossAccount | S1 | setup_issuer~deliver | 12 | 0.092 | 0.69 |
| B4-CrossAccount | S1 | setup~setup_issuer | 12 | 0.092 | 0.69 |
| B4-CrossAccount | S1 | slot~act | 12 | 0.017 | -0.41 |
| B4-CrossAccount | S1 | slot~deliver | 12 | 0.004 | -0.56 |
| B4-CrossAccount | S1 | slot~fund | 12 | 0.004 | -0.56 |
| B4-CrossAccount | S1 | slot~issue | 12 | 0.004 | -0.56 |
| B4-CrossAccount | S1 | slot~prepare | 12 | 0.004 | -0.56 |
| B4-CrossAccount | S1 | slot~setup | 12 | 0.004 | -0.56 |
| B4-CrossAccount | S1 | slot~setup_issuer | 12 | -0.004 | 0.15 |

Figures: `figures/d1-pilot/20260915T201434Z/r2_timing_rules_s0_vs_s1.png`, `figures/d1-pilot/20260915T201434Z/r2_timing_rules_s0_vs_s1_b4.png`, `figures/d1-pilot/20260915T201434Z/learned_cross_entropy.png`, `figures/d1-pilot/20260915T201434Z/r3_negative_control.png`, `figures/d1-pilot/20260915T201434Z/delta_bits.png`

#### Paired B3-PrivGas-v1 vs B4-CrossAccount (run pairs matched on scenario, N, replicate; subject-weighted; 95% bootstrap CI over run pairs)

| scen. | comparison | run pairs | B3 | B4 | chance | B4 − B3 [CI] |
|---|---|---|---|---|---|---|
| S0 | exact: Bootstrap sender == Spend sender | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.893] |
| S0 | exact: CreditSpent sender == depositor | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.893] |
| S0 | exact: announcer == asset sender | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.893] |
| S0 | exact: shared-identifier scan | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.889] |
| S0 | timing: insertion-order FIFO | 12 | 0.067 | 0.067 | 0.067 | 0.000 [0.000, 0.000] |
| S0 | timing: common-delay window k=2 | 12 | 0.081 | 0.081 | 0.067 | 0.000 [0.000, 0.000] |
| S0 | learned full trace T+AA+G: top-1 | 12 | 1.000 | 0.072 | 0.067 | -0.928 [-0.952, -0.895] |
| S0 | learned full trace T+AA+G: CE bits | 12 | 0.000 | 4.265 | 4.267 | 4.265 [3.558, 4.654] |
| S0 | learned no-equality T+AA+G-minus-eq: top-1 | 12 | 0.056 | 0.072 | 0.067 | 0.017 [-0.025, 0.052] |
| S0 | learned no-equality T+AA+G-minus-eq: CE bits | 12 | 4.269 | 4.265 | 4.267 | -0.003 [-0.045, 0.032] |
| S0 | learned timing T+G-minus-eq: top-1 | 12 | 0.050 | 0.072 | 0.067 | 0.022 [-0.030, 0.057] |
| S0 | learned timing T+G-minus-eq: CE bits | 12 | 4.268 | 4.265 | 4.267 | -0.003 [-0.044, 0.031] |
| S0 | learned G-minus-eq (gas+proof+timing): CE bits | 12 | 4.267 | 4.265 | 4.267 | -0.002 [-0.023, 0.014] |
| S0 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 12 | 0.050 | 0.081 | 0.067 | 0.031 [-0.022, 0.095] |
| S0 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 12 | 4.268 | 4.266 | 4.267 | -0.002 [-0.021, 0.013] |
| S0 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 12 | 4.268 | 4.266 | 4.267 | -0.002 [-0.022, 0.013] |
| S0 | learned no timing T+G-minus-timing: CE bits | 12 | 0.000 | 4.266 | 4.267 | 4.265 [3.531, 4.653] |
| S1 | exact: Bootstrap sender == Spend sender | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.893] |
| S1 | exact: CreditSpent sender == depositor | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.893] |
| S1 | exact: announcer == asset sender | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.897] |
| S1 | exact: shared-identifier scan | 12 | 1.000 | 0.067 | 0.067 | -0.933 [-0.953, -0.893] |
| S1 | timing: insertion-order FIFO | 12 | 0.433 | 0.433 | 0.067 | 0.000 [0.000, 0.000] |
| S1 | timing: common-delay window k=2 | 12 | 0.286 | 0.286 | 0.067 | 0.000 [0.000, 0.000] |
| S1 | learned full trace T+AA+G: top-1 | 12 | 1.000 | 0.339 | 0.067 | -0.661 [-0.742, -0.579] |
| S1 | learned full trace T+AA+G: CE bits | 12 | 0.000 | 2.104 | 4.267 | 2.104 [1.743, 2.382] |
| S1 | learned no-equality T+AA+G-minus-eq: top-1 | 12 | 0.339 | 0.339 | 0.067 | 0.000 [-0.030, 0.026] |
| S1 | learned no-equality T+AA+G-minus-eq: CE bits | 12 | 2.098 | 2.104 | 4.267 | 0.006 [-0.031, 0.044] |
| S1 | learned timing T+G-minus-eq: top-1 | 12 | 0.339 | 0.339 | 0.067 | 0.000 [-0.029, 0.025] |
| S1 | learned timing T+G-minus-eq: CE bits | 12 | 2.098 | 2.103 | 4.267 | 0.006 [-0.031, 0.041] |
| S1 | learned G-minus-eq (gas+proof+timing): CE bits | 12 | 2.097 | 2.103 | 4.267 | 0.006 [-0.030, 0.042] |
| S1 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 12 | 0.078 | 0.072 | 0.067 | -0.006 [-0.040, 0.033] |
| S1 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 12 | 4.270 | 4.267 | 4.267 | -0.002 [-0.014, 0.009] |
| S1 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 12 | 4.270 | 4.267 | 4.267 | -0.002 [-0.014, 0.009] |
| S1 | learned no timing T+G-minus-timing: CE bits | 12 | 0.000 | 4.267 | 4.267 | 4.267 [3.521, 4.654] |

#### Paired comparison by pool size (mean over replicates)

| scen. | N | comparison | B3 | B4 | chance |
|---|---|---|---|---|---|
| S0 | 4 | exact: Bootstrap sender == Spend sender | 1.000 | 0.250 | 0.250 |
| S0 | 4 | exact: CreditSpent sender == depositor | 1.000 | 0.250 | 0.250 |
| S0 | 4 | exact: announcer == asset sender | 1.000 | 0.250 | 0.250 |
| S0 | 4 | exact: shared-identifier scan | 1.000 | 0.250 | 0.250 |
| S0 | 4 | timing: insertion-order FIFO | 0.333 | 0.333 | 0.250 |
| S0 | 4 | timing: common-delay window k=2 | 0.312 | 0.312 | 0.250 |
| S0 | 4 | learned full trace T+AA+G: top-1 | 1.000 | 0.083 | 0.250 |
| S0 | 4 | learned full trace T+AA+G: CE bits | 0.000 | 2.078 | 2.000 |
| S0 | 4 | learned no-equality T+AA+G-minus-eq: top-1 | 0.167 | 0.083 | 0.250 |
| S0 | 4 | learned no-equality T+AA+G-minus-eq: CE bits | 2.093 | 2.078 | 2.000 |
| S0 | 4 | learned timing T+G-minus-eq: top-1 | 0.167 | 0.083 | 0.250 |
| S0 | 4 | learned timing T+G-minus-eq: CE bits | 2.076 | 2.066 | 2.000 |
| S0 | 4 | learned G-minus-eq (gas+proof+timing): CE bits | 2.065 | 2.066 | 2.000 |
| S0 | 4 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.083 | 0.250 | 0.250 |
| S0 | 4 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 2.041 | 2.041 | 2.000 |
| S0 | 4 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 2.041 | 2.041 | 2.000 |
| S0 | 4 | learned no timing T+G-minus-timing: CE bits | 0.000 | 2.041 | 2.000 |
| S0 | 8 | exact: Bootstrap sender == Spend sender | 1.000 | 0.125 | 0.125 |
| S0 | 8 | exact: CreditSpent sender == depositor | 1.000 | 0.125 | 0.125 |
| S0 | 8 | exact: announcer == asset sender | 1.000 | 0.125 | 0.125 |
| S0 | 8 | exact: shared-identifier scan | 1.000 | 0.125 | 0.125 |
| S0 | 8 | timing: insertion-order FIFO | 0.125 | 0.125 | 0.125 |
| S0 | 8 | timing: common-delay window k=2 | 0.071 | 0.071 | 0.125 |
| S0 | 8 | learned full trace T+AA+G: top-1 | 1.000 | 0.125 | 0.125 |
| S0 | 8 | learned full trace T+AA+G: CE bits | 0.000 | 2.989 | 3.000 |
| S0 | 8 | learned no-equality T+AA+G-minus-eq: top-1 | 0.083 | 0.125 | 0.125 |
| S0 | 8 | learned no-equality T+AA+G-minus-eq: CE bits | 3.026 | 2.989 | 3.000 |
| S0 | 8 | learned timing T+G-minus-eq: top-1 | 0.125 | 0.125 | 0.125 |
| S0 | 8 | learned timing T+G-minus-eq: CE bits | 3.025 | 2.989 | 3.000 |
| S0 | 8 | learned G-minus-eq (gas+proof+timing): CE bits | 3.021 | 2.989 | 3.000 |
| S0 | 8 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.083 | 0.125 | 0.125 |
| S0 | 8 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 3.020 | 2.991 | 3.000 |
| S0 | 8 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 3.020 | 2.991 | 3.000 |
| S0 | 8 | learned no timing T+G-minus-timing: CE bits | 0.000 | 2.991 | 3.000 |
| S0 | 16 | exact: Bootstrap sender == Spend sender | 1.000 | 0.062 | 0.062 |
| S0 | 16 | exact: CreditSpent sender == depositor | 1.000 | 0.062 | 0.062 |
| S0 | 16 | exact: announcer == asset sender | 1.000 | 0.062 | 0.062 |
| S0 | 16 | exact: shared-identifier scan | 1.000 | 0.062 | 0.062 |
| S0 | 16 | timing: insertion-order FIFO | 0.062 | 0.062 | 0.062 |
| S0 | 16 | timing: common-delay window k=2 | 0.107 | 0.107 | 0.062 |
| S0 | 16 | learned full trace T+AA+G: top-1 | 1.000 | 0.062 | 0.062 |
| S0 | 16 | learned full trace T+AA+G: CE bits | 0.000 | 3.983 | 4.000 |
| S0 | 16 | learned no-equality T+AA+G-minus-eq: top-1 | 0.062 | 0.062 | 0.062 |
| S0 | 16 | learned no-equality T+AA+G-minus-eq: CE bits | 3.974 | 3.983 | 4.000 |
| S0 | 16 | learned timing T+G-minus-eq: top-1 | 0.062 | 0.062 | 0.062 |
| S0 | 16 | learned timing T+G-minus-eq: CE bits | 3.976 | 3.986 | 4.000 |
| S0 | 16 | learned G-minus-eq (gas+proof+timing): CE bits | 3.995 | 3.986 | 4.000 |
| S0 | 16 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.042 | 0.073 | 0.062 |
| S0 | 16 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 4.008 | 3.999 | 4.000 |
| S0 | 16 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 4.008 | 3.999 | 4.000 |
| S0 | 16 | learned no timing T+G-minus-timing: CE bits | 0.000 | 3.999 | 4.000 |
| S0 | 32 | exact: Bootstrap sender == Spend sender | 1.000 | 0.031 | 0.031 |
| S0 | 32 | exact: CreditSpent sender == depositor | 1.000 | 0.031 | 0.031 |
| S0 | 32 | exact: announcer == asset sender | 1.000 | 0.031 | 0.031 |
| S0 | 32 | exact: shared-identifier scan | 1.000 | 0.031 | 0.031 |
| S0 | 32 | timing: insertion-order FIFO | 0.021 | 0.021 | 0.031 |
| S0 | 32 | timing: common-delay window k=2 | 0.042 | 0.042 | 0.031 |
| S0 | 32 | learned full trace T+AA+G: top-1 | 1.000 | 0.062 | 0.031 |
| S0 | 32 | learned full trace T+AA+G: CE bits | 0.000 | 4.999 | 5.000 |
| S0 | 32 | learned no-equality T+AA+G-minus-eq: top-1 | 0.031 | 0.062 | 0.031 |
| S0 | 32 | learned no-equality T+AA+G-minus-eq: CE bits | 4.999 | 4.999 | 5.000 |
| S0 | 32 | learned timing T+G-minus-eq: top-1 | 0.010 | 0.062 | 0.031 |
| S0 | 32 | learned timing T+G-minus-eq: CE bits | 4.998 | 4.998 | 5.000 |
| S0 | 32 | learned G-minus-eq (gas+proof+timing): CE bits | 4.990 | 4.998 | 5.000 |
| S0 | 32 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.042 | 0.052 | 0.031 |
| S0 | 32 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 4.988 | 4.995 | 5.000 |
| S0 | 32 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 4.988 | 4.995 | 5.000 |
| S0 | 32 | learned no timing T+G-minus-timing: CE bits | 0.000 | 4.995 | 5.000 |
| S1 | 4 | exact: Bootstrap sender == Spend sender | 1.000 | 0.250 | 0.250 |
| S1 | 4 | exact: CreditSpent sender == depositor | 1.000 | 0.250 | 0.250 |
| S1 | 4 | exact: announcer == asset sender | 1.000 | 0.250 | 0.250 |
| S1 | 4 | exact: shared-identifier scan | 1.000 | 0.250 | 0.250 |
| S1 | 4 | timing: insertion-order FIFO | 0.417 | 0.417 | 0.250 |
| S1 | 4 | timing: common-delay window k=2 | 0.250 | 0.250 | 0.250 |
| S1 | 4 | learned full trace T+AA+G: top-1 | 1.000 | 0.250 | 0.250 |
| S1 | 4 | learned full trace T+AA+G: CE bits | 0.000 | 2.439 | 2.000 |
| S1 | 4 | learned no-equality T+AA+G-minus-eq: top-1 | 0.250 | 0.250 | 0.250 |
| S1 | 4 | learned no-equality T+AA+G-minus-eq: CE bits | 2.376 | 2.439 | 2.000 |
| S1 | 4 | learned timing T+G-minus-eq: top-1 | 0.250 | 0.250 | 0.250 |
| S1 | 4 | learned timing T+G-minus-eq: CE bits | 2.374 | 2.434 | 2.000 |
| S1 | 4 | learned G-minus-eq (gas+proof+timing): CE bits | 2.370 | 2.434 | 2.000 |
| S1 | 4 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.333 | 0.417 | 0.250 |
| S1 | 4 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 2.013 | 1.977 | 2.000 |
| S1 | 4 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 2.013 | 1.977 | 2.000 |
| S1 | 4 | learned no timing T+G-minus-timing: CE bits | 0.000 | 1.977 | 2.000 |
| S1 | 8 | exact: Bootstrap sender == Spend sender | 1.000 | 0.125 | 0.125 |
| S1 | 8 | exact: CreditSpent sender == depositor | 1.000 | 0.125 | 0.125 |
| S1 | 8 | exact: announcer == asset sender | 1.000 | 0.125 | 0.125 |
| S1 | 8 | exact: shared-identifier scan | 1.000 | 0.125 | 0.125 |
| S1 | 8 | timing: insertion-order FIFO | 0.667 | 0.667 | 0.125 |
| S1 | 8 | timing: common-delay window k=2 | 0.375 | 0.375 | 0.125 |
| S1 | 8 | learned full trace T+AA+G: top-1 | 1.000 | 0.417 | 0.125 |
| S1 | 8 | learned full trace T+AA+G: CE bits | 0.000 | 1.691 | 3.000 |
| S1 | 8 | learned no-equality T+AA+G-minus-eq: top-1 | 0.458 | 0.417 | 0.125 |
| S1 | 8 | learned no-equality T+AA+G-minus-eq: CE bits | 1.612 | 1.691 | 3.000 |
| S1 | 8 | learned timing T+G-minus-eq: top-1 | 0.458 | 0.417 | 0.125 |
| S1 | 8 | learned timing T+G-minus-eq: CE bits | 1.611 | 1.688 | 3.000 |
| S1 | 8 | learned G-minus-eq (gas+proof+timing): CE bits | 1.609 | 1.688 | 3.000 |
| S1 | 8 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.125 | 0.083 | 0.125 |
| S1 | 8 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 3.003 | 3.005 | 3.000 |
| S1 | 8 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 3.003 | 3.005 | 3.000 |
| S1 | 8 | learned no timing T+G-minus-timing: CE bits | 0.000 | 3.005 | 3.000 |
| S1 | 16 | exact: Bootstrap sender == Spend sender | 1.000 | 0.062 | 0.062 |
| S1 | 16 | exact: CreditSpent sender == depositor | 1.000 | 0.062 | 0.062 |
| S1 | 16 | exact: announcer == asset sender | 1.000 | 0.062 | 0.062 |
| S1 | 16 | exact: shared-identifier scan | 1.000 | 0.062 | 0.062 |
| S1 | 16 | timing: insertion-order FIFO | 0.500 | 0.500 | 0.062 |
| S1 | 16 | timing: common-delay window k=2 | 0.294 | 0.294 | 0.062 |
| S1 | 16 | learned full trace T+AA+G: top-1 | 1.000 | 0.354 | 0.062 |
| S1 | 16 | learned full trace T+AA+G: CE bits | 0.000 | 1.779 | 4.000 |
| S1 | 16 | learned no-equality T+AA+G-minus-eq: top-1 | 0.375 | 0.354 | 0.062 |
| S1 | 16 | learned no-equality T+AA+G-minus-eq: CE bits | 1.836 | 1.779 | 4.000 |
| S1 | 16 | learned timing T+G-minus-eq: top-1 | 0.375 | 0.354 | 0.062 |
| S1 | 16 | learned timing T+G-minus-eq: CE bits | 1.836 | 1.779 | 4.000 |
| S1 | 16 | learned G-minus-eq (gas+proof+timing): CE bits | 1.836 | 1.779 | 4.000 |
| S1 | 16 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.062 | 0.083 | 0.062 |
| S1 | 16 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 4.007 | 4.008 | 4.000 |
| S1 | 16 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 4.007 | 4.008 | 4.000 |
| S1 | 16 | learned no timing T+G-minus-timing: CE bits | 0.000 | 4.008 | 4.000 |
| S1 | 32 | exact: Bootstrap sender == Spend sender | 1.000 | 0.031 | 0.031 |
| S1 | 32 | exact: CreditSpent sender == depositor | 1.000 | 0.031 | 0.031 |
| S1 | 32 | exact: announcer == asset sender | 1.000 | 0.031 | 0.031 |
| S1 | 32 | exact: shared-identifier scan | 1.000 | 0.031 | 0.031 |
| S1 | 32 | timing: insertion-order FIFO | 0.344 | 0.344 | 0.031 |
| S1 | 32 | timing: common-delay window k=2 | 0.265 | 0.265 | 0.031 |
| S1 | 32 | learned full trace T+AA+G: top-1 | 1.000 | 0.323 | 0.031 |
| S1 | 32 | learned full trace T+AA+G: CE bits | 0.000 | 2.328 | 5.000 |
| S1 | 32 | learned no-equality T+AA+G-minus-eq: top-1 | 0.302 | 0.323 | 0.031 |
| S1 | 32 | learned no-equality T+AA+G-minus-eq: CE bits | 2.315 | 2.328 | 5.000 |
| S1 | 32 | learned timing T+G-minus-eq: top-1 | 0.302 | 0.323 | 0.031 |
| S1 | 32 | learned timing T+G-minus-eq: CE bits | 2.315 | 2.328 | 5.000 |
| S1 | 32 | learned G-minus-eq (gas+proof+timing): CE bits | 2.315 | 2.328 | 5.000 |
| S1 | 32 | learned gas/proof only G-minus-eq-minus-timing: top-1 | 0.042 | 0.021 | 0.031 |
| S1 | 32 | learned gas/proof only G-minus-eq-minus-timing: CE bits | 5.000 | 4.999 | 5.000 |
| S1 | 32 | learned all metadata T+AA+G-minus-eq-minus-timing: CE bits | 5.000 | 4.999 | 5.000 |
| S1 | 32 | learned no timing T+G-minus-timing: CE bits | 0.000 | 4.999 | 5.000 |

#### R2 candidate universe

| check | result |
|---|---|
| subjects | 720 |
| subjects_by_baseline_slug | {'b3-privgas-v1': 360, 'b4-crossaccount': 360} |
| subjects_with_differing_universe | 0 |
| truth_outside_universe | 0 |
| ok | True |

#### R2 predictive delta_bits against the uniform model over the SAME N issuances (leave-one-replicate-out, primary convention)

| baseline | scen. | to | subjects | CE uniform | CE model | delta_bits [CI] |
|---|---|---|---|---|---|---|
| B3-PrivGas-v1 | S0 | G-minus-eq | 180 | 4.267 | 4.267 | -0.000 [-0.026, 0.021] |
| B3-PrivGas-v1 | S0 | G-minus-eq-minus-timing | 180 | 4.267 | 4.268 | -0.001 [-0.024, 0.016] |
| B3-PrivGas-v1 | S0 | T+AA+G-minus-eq | 180 | 4.267 | 4.269 | -0.002 [-0.058, 0.042] |
| B3-PrivGas-v1 | S0 | T+AA+G-minus-eq-minus-timing | 180 | 4.267 | 4.268 | -0.001 [-0.024, 0.016] |
| B3-PrivGas-v1 | S0 | T+G-minus-eq | 180 | 4.267 | 4.268 | -0.001 [-0.056, 0.041] |
| B3-PrivGas-v1 | S1 | G-minus-eq | 180 | 4.267 | 2.097 | 2.170 [1.471, 2.524] |
| B3-PrivGas-v1 | S1 | G-minus-eq-minus-timing | 180 | 4.267 | 4.270 | -0.003 [-0.015, 0.009] |
| B3-PrivGas-v1 | S1 | T+AA+G-minus-eq | 180 | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| B3-PrivGas-v1 | S1 | T+AA+G-minus-eq-minus-timing | 180 | 4.267 | 4.270 | -0.003 [-0.015, 0.009] |
| B3-PrivGas-v1 | S1 | T+G-minus-eq | 180 | 4.267 | 2.098 | 2.169 [1.469, 2.523] |
| B4-CrossAccount | S0 | G-minus-eq | 180 | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| B4-CrossAccount | S0 | G-minus-eq-minus-timing | 180 | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| B4-CrossAccount | S0 | T+AA+G-minus-eq | 180 | 4.267 | 4.265 | 0.001 [-0.024, 0.024] |
| B4-CrossAccount | S0 | T+AA+G-minus-eq-minus-timing | 180 | 4.267 | 4.266 | 0.001 [-0.019, 0.019] |
| B4-CrossAccount | S0 | T+G-minus-eq | 180 | 4.267 | 4.265 | 0.002 [-0.021, 0.023] |
| B4-CrossAccount | S1 | G-minus-eq | 180 | 4.267 | 2.103 | 2.163 [1.464, 2.528] |
| B4-CrossAccount | S1 | G-minus-eq-minus-timing | 180 | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| B4-CrossAccount | S1 | T+AA+G-minus-eq | 180 | 4.267 | 2.104 | 2.162 [1.463, 2.528] |
| B4-CrossAccount | S1 | T+AA+G-minus-eq-minus-timing | 180 | 4.267 | 4.267 | -0.001 [-0.018, 0.015] |
| B4-CrossAccount | S1 | T+G-minus-eq | 180 | 4.267 | 2.103 | 2.163 [1.464, 2.528] |

#### B4 account-separation audit (every B4 run; from its private run record)

| scen. | N | run | b4 checks passed | issuer≠spender accounts | issuer≠spender keys | Bootstrap senders | Spend senders | sender overlap | issuer↔spender txs | W1T to issuer |
|---|---|---|---|---|---|---|---|---|---|---|
| S0 | 4 | 20260915T201434Z-r1 | 44/44 | 4 | 4 | 4 | 4 | 0 | 0 | 0 |
| S0 | 4 | 20260915T201434Z-r2 | 44/44 | 4 | 4 | 4 | 4 | 0 | 0 | 0 |
| S0 | 4 | 20260915T201434Z-r3 | 44/44 | 4 | 4 | 4 | 4 | 0 | 0 | 0 |
| S0 | 8 | 20260915T201434Z-r1 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S0 | 8 | 20260915T201434Z-r2 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S0 | 8 | 20260915T201434Z-r3 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S0 | 16 | 20260915T201434Z-r1 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S0 | 16 | 20260915T201434Z-r2 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S0 | 16 | 20260915T201434Z-r3 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S0 | 32 | 20260915T201434Z-r1 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |
| S0 | 32 | 20260915T201434Z-r2 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |
| S0 | 32 | 20260915T201434Z-r3 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |
| S1 | 4 | 20260915T201434Z-r1 | 44/44 | 4 | 4 | 4 | 4 | 0 | 0 | 0 |
| S1 | 4 | 20260915T201434Z-r2 | 44/44 | 4 | 4 | 4 | 4 | 0 | 0 | 0 |
| S1 | 4 | 20260915T201434Z-r3 | 44/44 | 4 | 4 | 4 | 4 | 0 | 0 | 0 |
| S1 | 8 | 20260915T201434Z-r1 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S1 | 8 | 20260915T201434Z-r2 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S1 | 8 | 20260915T201434Z-r3 | 80/80 | 8 | 8 | 8 | 8 | 0 | 0 | 0 |
| S1 | 16 | 20260915T201434Z-r1 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S1 | 16 | 20260915T201434Z-r2 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S1 | 16 | 20260915T201434Z-r3 | 152/152 | 16 | 16 | 16 | 16 | 0 | 0 | 0 |
| S1 | 32 | 20260915T201434Z-r1 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |
| S1 | 32 | 20260915T201434Z-r2 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |
| S1 | 32 | 20260915T201434Z-r3 | 296/296 | 32 | 32 | 32 | 32 | 0 | 0 | 0 |

All B4 runs pass the separation audit: **True**.

<!-- END GENERATED: d1-b4-results -->
