# D2 kill-condition test: bounded root history and gas-scaling decomposition

> **NON-PRODUCTION | NON-EIP-170-DEPLOYABLE-AS-BUILT | EXPERIMENTAL-MITIGATION | EVALUATION-ONLY**

Status: **complete (2026-09-16)**. Batch `20260916T055452Z`, namespace `d2-killcondition`.

This phase tests the D2 kill condition in `docs/research-plan.md` §3: *if ordinary historical-root
retention and routine staking eliminate the problem at realistic load with no significant tradeoff,
D2 is engineering rather than research.* It also decomposes the D2-B gas growth the pilot reported
but did not explain.

The D2 falsification pilot (`docs/d2-pilot-results.md`, batch `20260915T223607Z`) is **closed**
(`docs/decision-log.md`, 2026-09-16). Nothing here regenerates, recomputes or rewrites any number
in it; its harness, contention engine, state machine, record tiers and D2-B measurement helpers are
**imported unchanged**.

Narrative outside the generated block is labelled **FACT** (measured), **INFERENCE** (derived from
measurements plus stated assumptions), **HYPOTHESIS** (not tested here) or **NEGATIVE RESULT**.
Every number in the generated block is produced by
`python3 -m experiments.liveness.d2k analyze --batch 20260916T055452Z --write-doc` from the recorded
data.

Code: `contracts/d2k/` (the experimental variant and the benchmarks) and
`experiments/liveness/d2k/` (`mitigation.py`, `harness.py`, `engine.py`, `exp_hist.py`,
`exp_gas.py`, `analysis.py`, `records.py`, `config.json`, `tests/`). Run:
`make d2k-run BATCH=<stamp>` then `make d2k-analyze BATCH=<stamp>`; tests `make d2k-test` and
`make d2k-contract-test`.

Artefacts: attempt and arrival records in `data/private/d2-killcondition/20260916T055452Z/*.jsonl`
(they carry client-private proof timing), machine-readable tables in
`results/d2-killcondition/20260916T055452Z/tables/` (CSV + JSON), raw per-experiment measurements in
`.../raw/`, the config/environment manifest in `.../manifest.json`, and the figures in
`figures/d2-killcondition/20260916T055452Z/`.

---

## 1. The two questions

**A. Can bounded root history cheaply remove the D2-A race?** The frozen `CreditPaymaster` accepts
only the latest mirrored Merkle root, so any intervening `CreditPool.deposit` invalidates a pending
Spend proof. The obvious engineering answer is to keep the last K roots. If a small K removes the
contention at negligible cost, D2-A is engineering, not research.

**B. Why does `CreditPool.deposit` gas grow with the tree?** The pilot measured 121,763 gas at tree
size 0 and 562,428 at size 255, ≈ 61,183 per tree level, against a frozen sponsored `callGasLimit`
of 160,000 and a fixed 0.005 ETH sponsorship budget. Whether that is a fundamental scaling property
or a B3 parameter bug decides whether D2-B survives.

## 2. What was built, and why it does not modify frozen B3

**FACT.** The frozen `CreditPool` takes its root-mirror target and its registry as **constructor
arguments** and its only interaction with the Paymaster is `creditPaymaster.mirrorRoot(newRoot)`.
An experimental root-acceptance component is therefore reachable by deploying the **unmodified
frozen bytecode** with a different constructor argument. A D2K environment is a second, complete
frozen deployment — `CreditPool`, `BootstrapPaymaster`, `AnnouncementRegistry`, all unmodified —
whose single difference is the address the pool mirrors roots to. A live test compares the deployed
runtime code of all four against the compiled frozen artifacts (immutables and library links
masked) and they are identical.

Unchanged and re-used exactly: CreditPool semantics, the Bootstrap flow, the Semaphore verifier,
proof message binding, nullifier handling, the EntryPoint, the account implementation, Paymaster
sponsorship semantics, the W1 application call, the staged bundler, the preVerificationGas
calibration, the Semaphore prover and its pinned artifacts, and the `b3_compat_local` profile.

**`D2-History-K`** (`contracts/d2k/src/HistoryCreditPaymaster.sol`) is an experimental variant, not
a proposed protocol. Its only intended semantic difference is step 3 of validation:

| | frozen `CreditPaymaster` | `D2-History-K` |
|---|---|---|
| root check | `proof.merkleTreeRoot != _merkleRoot` → `RootMismatch` | `_count[proof.merkleTreeRoot] == 0` → `RootMismatch` |

Everything else is copied verbatim and is pinned by a static test that compares the two sources:
the gas / fee / cost caps, `CREDIT_NULLIFIER_SCOPE`, the `paymasterAndData` layout and
`PAYMASTER_SIG_MAGIC` convention, proof decoding, the message and scope binding, `_hashForCircuit`,
the nullifier read and write, `postOp`, the `onlyEntryPoint` modifier, the `mirrorRoot` caller
check, both events and every error type.

## 3. Bounded root history: exact semantics

The history is a **ring buffer**, never a map of every root ever seen.

| question | answer |
|---|---|
| how do roots enter | only through `mirrorRoot`, which only `CreditPool.deposit` can call |
| how do roots leave | the slot at the write cursor is evicted by the update that overwrites it: the K-th update after a root was mirrored |
| what does K mean | history **capacity in roots**; a proof's root survives exactly K − 1 subsequent root updates |
| does the current root count toward K | **yes**. K = 1 keeps only the current root and is therefore latest-root-only |
| lookup complexity | O(1) in K — one own-storage `SLOAD` of `_count[root]`, the same shape as the frozen single `_merkleRoot` `SLOAD` |
| update complexity | O(1) in K — one `SLOAD` of the evicted slot, one refcount decrement, one ring write, one refcount increment, one cursor write |
| storage consumed | steady state **2K + 1** non-zero slots (K ring slots, K refcounts, the cursor), independent of how many roots have ever existed |
| duplicate roots | `_count` is a **refcount**, so a root mirrored twice occupies two slots and stays valid until both are evicted; retention never depends on eviction order |
| root 0 | the empty-slot sentinel; never counted, never accepted. A LeanIMT root is a Poseidon output over a non-zero leaf and `_insert` rejects a zero leaf, so 0 is not a reachable root |

`contracts/d2k/test/HistoryRoots.t.sol` pins all of this without needing a proof: the eviction
boundary at every K ∈ {1, 2, 4, 8, 16, 32}, duplicate refcounting, the K = 1 reduction, the 2K + 1
storage bound after 200 updates, and that steady-state update gas does not depend on K.

## 4. Append-only membership — checked before interpreting old roots as safe

**FACT (from the frozen source, pinned by a static test).** `CreditPool` calls
`InternalLeanIMT._insert` and nothing else: the library's `_update`, `_remove` and `_insertMany`
never appear. `_eligible` and `_used` are only ever assigned `true`, as is
`AnnouncementRegistry.eligible`. There is no revocation, deletion or expiry entry point anywhere in
the frozen credit path.

**INFERENCE.** An older root is therefore a **prefix of later membership**: every commitment it
attests to is still a member now, and no state that "should no longer be spendable" can be
represented by an old root but not by the current one. Independently, the nullifier scope is the
**constant** `CREDIT_NULLIFIER_SCOPE`, not a function of the root, so one credit yields the same
nullifier whichever retained root it proves against — accepting an old root cannot create a second
spend. Both properties are re-established experimentally in §K2 rather than assumed. The stop
condition "older roots permit a revoked/invalid membership" therefore did **not** fire.

**HYPOTHESIS (not tested here, and a real cost of the mitigation).** Proving against an older root
narrows the prover's anonymity set to the members present at that root. A spender who deliberately
uses an old root to avoid contention is choosing a smaller anonymity set; an observer who sees which
retained root a proof names learns which prefix of the membership the prover was in. This is a
privacy/liveness tradeoff the present experiment does not measure — it measures only liveness and
cost.

## 5. Method

Contention experiments run on a **fan-out** deployment: the frozen `CreditPool`'s single immutable
mirror target is a `FanOutRootMirror` that forwards each new root to the frozen `CreditPaymaster`
and to one `HistoryCreditPaymaster` per tested K. Every variant therefore sees the same deposits,
the same roots and the same block order, and "K = 1 reproduces frozen behaviour" is measured side by
side rather than argued. The fan-out inflates the Bootstrap's own gas, so **no gas, storage,
code-size or overhead number is taken from a fan-out deployment**: every §K7–§K9 number comes from a
**dedicated** deployment (one frozen `CreditPool` → one Paymaster), exactly as B3 deploys.

The frozen contention engine is reused. `HistoryTrial` overrides exactly one method,
`_root_changes_between`, so that only the K-th and later root changes after a proof count as
invalidating; every call site in the frozen engine passes `lo = t0`, which a static test pins, and
`capacity = 1` makes the override the identity. Every attempt record also carries the analytical
model's prediction and whether the chain agreed; a single disagreement raises and stops the
experiment.

**Analytical baseline.** Under Poisson root updates with μ = λ·T,

```
P(valid | K) = Σ_{j=0}^{K-1} e^{-μ} μ^j / j!        P(stale | K) = 1 − P(valid | K)
```

which reduces to `1 − e^{-μ}` at K = 1 — the curve the pilot measured.

**Pre-registered thresholds** (`docs/decision-log.md`, 2026-09-16, recorded before the reported
batch). A capacity K "removes practical contention at negligible cost" iff all four hold: stale-root
failure Wilson 95 % upper bound **< 1 %** pooled over 0 < λ·T ≤ 1; Spend-validation overhead
**< 5 %** of the frozen UserOperation's `actualGasUsed`; root-update overhead **< 10 %** of the
frozen Bootstrap UserOperation's `actualGasUsed`, worst case over tested tree sizes; steady-state
history storage **≤ 128 slots**. The percentages were fixed before any D2K run; their denominators
were made explicit after a reduced smoke run showed "overhead < x %" is ambiguous without one (the
decision-log entry states this plainly).

---

## 6. Question A — findings

### 6.1 The retention rule is exact, and K = 1 is the frozen contract

**FACT (K1, 150 runs: 5 variants × 6 intervening-update counts × 5 seeds).** A Spend proven
against root R, simulated successfully, then hit by exactly *d* unrelated Bootstraps, is included
**iff d < K** — in every single run. At d ≥ K it fails on chain with `RootMismatch`, the nullifier
is not spent, the sender's nonce does not advance, the Paymaster is not charged and the bundler
pays ≈ 151–161 k gwei of reverted bundle gas. At d < K it is included and the on-chain `rootAge`
of the accepted proof is exactly *d*. The analytical rule and the chain agreed 150/150. The exact
boundary is therefore: **a proof survives K − 1 root updates and dies on the K-th.**

**FACT.** The frozen `CreditPaymaster` and `D2-History-K` at K = 1 behave identically in every cell
of every experiment on the same chain, against the same roots: 5/5 vs 5/5 inclusion at each *d* in
the deterministic test, 408/800 vs 408/800 stale in the stochastic matrix, 32/54 vs 32/54 successes
in the retry loop. The stop condition "K = 1 fails to reproduce frozen latest-root behaviour" did
**not** fire.

### 6.2 Every security invariant held

**FACT (K2, 55 live cases, K = 8, real Groth16 proofs verified on chain by the frozen
`SemaphoreVerifier`).** All eleven invariants held 5/5: the current root is accepted; a retained
historical root (age K − 1) is accepted; a root one update past the window is rejected
(`RootMismatch`); a fabricated root is rejected; a *real, well-formed* proof against the root the
next deposit will create — legitimate but not yet mirrored — is rejected; a proof over the wrong
message is rejected (`WrongMessage`); a proof under a different scope is rejected (`WrongScope`); a
proof with one mutated Groth16 point is rejected (`InvalidProof`); a second spend of the same credit
is rejected (`NullifierSpent`) **including when it proves against a different, still-retained root**;
and K = 1's acceptance decision and reported current root equal the frozen contract's at every root
state. All eight rejection cases are caught at bundler simulation, 5/5 each, so they cost the bundler nothing; the two acceptance cases and the K = 1 equivalence check are decided on chain.

**NEGATIVE RESULT.** Bounded history does **not** weaken any unrelated property that this
experiment could reach. It is not a formal security claim: no proof is offered, the adversary is the
same A2 bundler-observer as the pilot's, and the anonymity-set effect of §4 is not measured.

### 6.3 Stale-root failure collapses with K, exactly as the Poisson model predicts

**FACT (K3/K4, 7,000 single-attempt trials; 0 inconsistent classifications, 0 retention-model
mismatches).** Pooled over the λ > 0 cells:

| variant | frozen | K=1 | K=2 | K=4 | K=8 | K=16 | K=32 |
|---|---|---|---|---|---|---|---|
| stale rate | 0.510 | 0.510 | 0.323 | 0.155 | 0.045 | 0.000 | 0.000 |
| valid at simulation → stale at inclusion | 141 | 141 | 130 | 94 | 36 | 0 | 0 |
| bundler loss (gwei) | 21.4 M | 22.7 M | 20.9 M | 15.1 M | 5.8 M | 0 | 0 |
| max root updates a successful proof survived | 0 | 0 | 1 | 3 | 7 | 15 | 15 |

**FACT.** The measured curves follow `P(stale | K) = 1 − Σ_{j<K} e^{−μ} μ^j / j!` with μ = λ·T:
of 140 λ > 0 cells, 4 have a Wilson interval excluding the analytical value (≈ 7 expected by chance
at 140 cells and 95 % coverage); of the 66 pooled λT-groups, 5 lie outside, and all but one are
K = 1 groups, i.e. the same finite-sample scatter the pilot already reported on its own
`1 − e^{−μ}` curve. The model was not fitted — it is the prediction, and every attempt record
carries it.

**INFERENCE.** The agreement is close to tautological once the retention semantics are what the
implementation says they are, which is exactly why the implementation, not the curve, is the
experimental content: the boundary is exact, eviction never happens early or late, duplicates are
refcounted, and nothing else failed in 7,000 trials. The T_chain exposure the pilot identified — a
proof valid at simulation and invalid at inclusion — does not disappear, it is *rescaled*: it falls
from 141 to 36 occurrences at K = 8 and to 0 at K = 16 in this matrix, because the operation now
tolerates K − 1 updates inside that window instead of 0.

### 6.4 The mitigation's own cost

**FACT (K7, dedicated deployments, 6 real included Spends per variant at pool size 32, proof depth
5).** Spend validation costs **+114 gas**, *independently of K*: 253,517 vs 253,403 gas in the
`validatePaymasterUserOp` frame (+0.045 %), 364,035 vs 363,921 in the UserOperation's
`actualGasUsed` (+0.031 %), and +228 gwei of sponsor charge (728,070 vs 727,842 gwei). The `verifyProof` sub-frame is
identical (219,064 gas) and one Paymaster storage slot is written (the nullifier) in both. Lookup
cost does **not** change with K: a ring-buffer membership test is one `SLOAD`, the same shape as the
frozen single-root comparison.

**FACT (K8, dedicated deployments, tree sizes 0–31, 2 seeds, identical results per seed).** Once
the ring is full a root update costs **+29,830 gas at K = 1 and +32,630 gas at K = 2…16**
(`mirrorRoot` frame 6,511 → 36,341 / 39,141), and the delta is identical whether it is measured on
the `mirrorRoot` sub-frame or on the whole `CreditPool.deposit` frame — the mitigation adds nothing
outside the mirror call. While the ring is still filling the cost is higher and not monotone: over
the tested tree sizes the measured range is **+24,656 … +29,830 (K = 1)** and
**+32,630 … +49,738 (K = 2…16)**, with the maximum at the update that first fills the ring; K = 32
never reaches steady state within 32 insertions and sits at +44,556 … +44,564 throughout. (The
per-opcode reason for the transient's shape is not established here — no opcode-level trace was
taken — only its measured size.) Relative to what the sponsor actually pays for a Bootstrap that is
**3.7 %–5.5 % at tree size 31**
and at worst **5.03 % (K=1) to 8.39 % (K=2)** over all tested tree sizes; relative to the
`CreditPool.deposit` frame alone it is larger — up to 36.6 % at tree size 0, where the frozen frame
is smallest. Both denominators are in the table; the pre-registered threshold uses the first.
(Frozen-row deltas of 12–36 gas in the table are seed-level calldata noise: different commitments
have different zero-byte counts.)

**FACT (K9).** Deploying the variant costs **+258,337 gas** and **+1,196 runtime bytes**
(2,788 → 3,984, the same for every K because K is a constructor immutable), leaving 20,592 bytes of
EIP-170 headroom. Steady-state root-history storage is **2K + 1 slots**: 3, 5, 9, 17, 33, 65 for
K = 1…32. Nothing grows with the number of roots ever mirrored.

### 6.5 Retries, proofs and latency

**FACT (K5, 54 trials per variant with λ > 0, retry cap 10 attempts, bundler policy P0).**

| variant | successes / 54 | attempts (= proofs) / success | failures at simulation | failures on chain | bundler loss (gwei) | p95 time to success (s) |
|---|---|---|---|---|---|---|
| frozen | 32 | 9.72 | 216 | 63 | 9.57 M | 15.15 |
| K=1 | 32 | 9.72 | 216 | 63 | 10.12 M | 15.15 |
| K=2 | 42 | 5.57 | 122 | 70 | 11.25 M | 21.75 |
| K=4 | 49 | 2.65 | 31 | 50 | 8.03 M | 11.52 |
| K=8 | 52 | 1.77 | 4 | 36 | 5.79 M | 16.75 |
| K=16 | 54 | 1.02 | 0 | 1 | 0.16 M | 5.00 |
| K=32 | 54 | 1.00 | 0 | 0 | 0 | 5.00 |

**INFERENCE.** The client-side cost of contention — one fresh Groth16 proof per attempt — is what
bounded history actually buys down: 9.72 proofs per delivered Spend at latest-root, 1.00 at K = 32,
with total proving time falling from 83.2 s to 10.1 s over the same 54 trials. The bundler's loss is
not monotone in K at small K (K = 2 loses *more* than K = 1) because a larger K converts
cheap simulation rejections into operations that reach the chain and can still fail there; only from
K = 4 does the on-chain failure count fall enough to dominate. That is a genuine, non-obvious
tradeoff and the reason a *small* K is not automatically the right choice for the party paying.

### 6.6 Bundles

**FACT (K6, 95 configurations, bundle sizes 1/2/4/8, 0…K+1 intervening updates).** A bundle of *k*
Spends sharing one proof root survives **iff d < K**, at every bundle size — the boundary does not
depend on *k*, and when it is crossed **0 of k** operations are included, exactly as in the frozen
pilot. In the `one_stale_rest_fresh` variant — one operation past the window, the other k−1
re-proved against the current root — the whole bundle still reverts at index 0, at **every K**.

**INFERENCE.** Bounded history moves the cliff but does not remove it: `handleOps` is still
all-or-nothing, so one stale proof still destroys the valid operations bundled with it. That is an
EntryPoint property, not a root-policy property, and this phase deliberately did not redesign
bundling. A real bundler would drop the failing operation and re-bundle the rest, which this
harness does not do (§9).

### 6.7 Kill-condition verdict for D2-A

**FACT (K10).** Against the thresholds pre-registered in `docs/decision-log.md`:

| K | stale (0 < λT ≤ 1), Wilson upper | < 1 % | validation overhead | < 5 % | root-update overhead (worst size) | < 10 % | storage slots | ≤ 128 | meets all |
|---|---|---|---|---|---|---|---|---|---|
| frozen / 1 | 0.359 | no | 0.031 % | yes | 5.03 % | yes | 1 / 3 | yes | **no** |
| 2 | 0.139 | no | 0.031 % | yes | 8.39 % | yes | 5 | yes | **no** |
| 4 | 0.0168 | no (0/520 → 3/520 = 0.58 %, CI upper 1.68 %) | 0.031 % | yes | 8.32 % | yes | 9 | yes | **no** |
| 8 | 0.0073 | yes (0/520) | 0.031 % | yes | 8.26 % | yes | 17 | yes | **yes** |
| 16 | 0.0073 | yes (0/520) | 0.031 % | yes | 8.18 % | yes | 33 | yes | **yes** |
| 32 | 0.0073 | yes (0/520) | 0.031 % | yes | 8.03 % | yes | 65 | yes | **yes** |

**The smallest K meeting every pre-registered threshold is K = 8.** K = 4 misses only on the
interval upper bound (its point estimate, 0.58 %, is already below 1 %); more trials would settle
it, and the analytical value at the region boundary (μ = 1, K = 4) is 1.9 %, so K = 4 is genuinely
borderline rather than under-measured.

---

## 7. Question B — findings

### 7.1 The decomposition reproduces frozen behaviour exactly

**FACT (G1).** The frozen `CreditPool.deposit` frame measured here is **121,763 gas at tree size 0
and 562,428 at size 255** — identical to the frozen D2 pilot's D2-B table, on a different machine,
for both seeds. The LeanIMT-only benchmark, driven with the same 256 commitments in the same order,
ends with **the same root and the same size as the frozen pool** (checked on chain), so the
benchmark is the same Merkle primitive, not a re-implementation. The stop conditions "the
decomposition cannot reproduce frozen CreditPool behaviour" and "the benchmark uses a different
Merkle primitive" did **not** fire.

### 7.2 The ≈ 61 k per level is one Poseidon call

**FACT (G2).** One `PoseidonT3.hash` delegatecall, measured alone as a CALL sub-frame, costs
**61,337 gas** warm (78,437 on the first, cold call). From tree size 7 upward, each additional tree
level adds **61,183 gas** to `CreditPool.deposit` and 61,153 gas to the LeanIMT insertion, while the
number of `PoseidonT3` delegatecalls rises by exactly one. The **unexplained residual is −154 gas
per level (0.25 %)**, and it is constant — the same 154 gas at every level, which is the difference
between the isolated benchmark's own accounting and the call as it occurs inside the loop, not
drift. The first two levels are not on this line (size 1 → 3 adds only 24,111 gas for one extra
hash) because zero→non-zero slot initialisation of `depth` and `sideNodes` still dominates there.

**FACT.** `G0 = G1 + G3a` to within a **median of −119 gas and a worst case of 215 gas (0.135 % of
G0)** at every one of the 256 insertions. The parts are flat: the root mirror (G2) is 6,511 gas in
steady state (23,611 on the first write) and B3's surrounding logic (G3a — eligibility check, the
one-shot flag, the mirror call, the event) is 35,772 gas, neither of which depends on tree size. The
tree's non-hashing bookkeeping (G3b − G3a) is 27,152 gas. The external-call floor (G4) is 101 gas.

**INFERENCE — answering §16 directly.** The growth is cause **A**, the incremental Merkle-tree
insertion itself, and nothing else. Not B (B3-specific surrounding logic: flat, 35,772 gas), not C
(root mirroring: flat, 6,511 gas), not D (storage expansion: the new-slot cost is a one-off at the
first insertion and at each new level, not a per-level trend), not E. `CreditPool.deposit` is
`LeanIMT._insert` plus a constant, and `_insert` costs one Poseidon hash per set bit of the
insertion index — worst case ⌈log₂ n⌉ per insertion, ≈ 61.3 k gas each.

### 7.3 The frozen parameters

**FACT (G3).** At the frozen `callGasLimit` of 160,000 the Bootstrap **inserts only at tree size 0**
(margin +29,923 gas). At every tested size from 1 to 255 it is accepted by the Paymaster, included
on chain, and its execution runs out of gas; the minimal sufficient limit is 130,077 at size 0,
181,005 at size 1 and **584,667 at size 255** — a sawtooth, not a monotone curve (168,700 at size 2
is *lower* than at size 1), because the cost is set by the popcount of the insertion index, not by
the tree size. At size 255 the frozen attempt fails as a plain revert rather than an explicit
out-of-gas, because the Poseidon library call itself is starved.

**FACT (G4).** The advertised 10 gwei cap (`MAX_ACCEPTED_MAX_FEE_PER_GAS`) is **unreachable at every
tested tree size and every call-gas limit**. The binding constraint is the fixed wei budget
(`MAX_BOOTSTRAP_SPONSORSHIP_COST` = 0.005 ETH), refused as `MaxCostExceeded`: the highest feasible
gas price is 8 gwei at the frozen limit (analytic p_max = 8.80), 9 gwei at the minimal sufficient
limit at tree size 0 (9.29), 8 gwei from size 1 to 128, and **4 gwei at size 255** (5.04). The
analytic envelope `p_max = 0.005 ETH / Σ(gas limits)` matches every simulated verdict.

**INFERENCE.** Two separate things are true at once. The frozen 160,000 is an obviously wrong
parameter — it covers exactly one insertion, into an empty tree. But fixing it does not restore the
advertised envelope: the budget is a *fixed amount of wei* while the required gas grows
logarithmically with the pool, so each extra tree level costs ≈ 61 k gas and buys back a lower
maximum sponsorable gas price. At tree size 0 the protocol is already 12 % below its own advertised
cap; at 256 members it is 50 % below it. The sybil-resistance invariant `F > κ·c_credit·p_max` is
stated against a cap the protocol cannot reach.

### 7.4 A failed Bootstrap: what exactly is consumed

**FACT (G5, frozen B3, 15 controlled attempts across 5 seeds and 3 starved call-gas limits).** In
every attempt validation passes, the bundle is included, and execution fails (out of gas at 160,000
and 40,000; a plain revert at 100,000). State before → after:

| | before | after |
|---|---|---|
| `BootstrapPaymaster.isUsed(account)` | false | **true** |
| `CreditPool.isEligible(account)` | true | true |
| `CreditPool.hasDeposited(account)` | false | false |
| tree size / root | s / R | s / R (**unchanged**) |
| account EntryPoint nonce | 0 | **1** |
| account code size | 0 bytes | **130 bytes** (deployed by initCode) |
| `BootstrapPaymaster` EntryPoint deposit | — | **−610,712 to −843,294 wei** |

**FACT.** The identical logical Bootstrap, rebuilt at the live nonce and with sufficient gas, is
refused by the Paymaster with **`AA34 signature error`** — `BootstrapPaymaster` returns
`SIG_VALIDATION_FAILED` because it marked the account used during the *first* validation. The
sponsored grant is therefore **permanently consumed by a failed execution**, and the sponsor paid
for it.

**FACT — and this refines the pilot's finding.** The credit itself is **not** lost. An
**unsponsored** UserOperation from the same account inserts the commitment successfully, paid from
the account's own balance through the EntryPoint's `missingAccountFunds` path, costing
**800,210–865,110 wei** out of the 0.01 ETH `vMin` the registry forwarded. No externally funded EOA
is needed. The frozen `BootstrapPaymaster`'s own source comment — "the user loses their free-gas
attempt but retains the ability to call `deposit()` self-funded" — is **correct**, and the pilot's
statement that the failure is "non-recoverable" is too strong: it is the *sponsorship* that is
non-recoverable, at a cost of ≈ 0.0008 ETH to the user and ≈ 0.0008 ETH to the sponsor per failure.

**INFERENCE.** This is a validation-state persistence property, not tree logic: the flag is written
in `validatePaymasterUserOp`, which the EntryPoint does not roll back when the execution phase
fails. Nothing about the Merkle tree causes it. It is not called a vulnerability here: it is a
documented consequence of marking a one-shot grant during validation, which is itself forced by
ERC-7562's storage rules, combined with a `callGasLimit` the wallet chose too small.

### 7.5 Could a bundler have caught it?

**FACT (G6, 8 probes over 2 seeds).** Validation-only simulation — the bundler's own
`eth_call handleOps`, the method the pilot used — **accepted all eight operations**, including the
three whose execution then failed on chain: the EntryPoint catches an execution failure and emits
`UserOperationEvent(success=false)` rather than reverting, so there is nothing for a validation-only
simulation to see. Two execution-aware probes separate them perfectly: `debug_traceCall` with
`callTracer` reports an out-of-gas frame in **6/6 starved** operations and **0/2 sufficient** ones,
and `eth_estimateGas` on the account's pool call returns 192,782–192,794 gas, above the frozen
160,000 in every starved case and below the sufficient limit in both others.

**INFERENCE.** Yes — a bundler could reasonably detect a too-low `callGasLimit` before submitting,
but only if it does execution-aware estimation, which ERC-4337 validation-rule simulation alone does
not give it. **Limitation:** this harness has no production bundler and no
`eth_estimateUserOperationGas` implementation, so what is shown is that the *information* is
available from an ordinary node before inclusion, not that any particular bundler implementation
would use it.

---

## 8. Decision

### D2-A — **CASE A**: bounded root history trivially solves it

A bounded ring buffer of **K = 8** roots removes stale-root failure from the whole tested
λ·T ≤ 1 region (0/520, Wilson upper 0.73 %) at a cost of **+114 gas per Spend validation
(+0.031 %), independent of K**, **+32.6 k gas per root update (≈ 8 % of a Bootstrap)**, **17
storage slots**, **+1,196 bytes of code** and **+258 k gas of deployment**. It needs no change to
`CreditPool`, the Bootstrap flow, Semaphore, proof binding, nullifier handling, the EntryPoint, the
account or the sponsorship semantics — only a different constructor argument — and it weakens no
security invariant this experiment could reach. **D2-A alone is engineering, not research.**

The honest qualifications: the root-update cost is not zero and is paid by the sponsor on every
deposit; the bundler's loss is *not* monotone in K at small K; one stale proof still destroys a whole
bundle at every K; and using an older root narrows the prover's anonymity set, which this phase did
not measure and which is the one part of the tradeoff that is not obviously engineering.

### D2-B — **CASE C + D**: a bad parameter on top of a real boundary

**C**: the frozen 160,000 `callGasLimit` covers exactly one insertion into an empty tree; the
decomposition shows no B3-specific overhead at all beyond a flat 35,772 gas. Choosing a sufficient
limit is a one-line wallet change.

**D**: the growth that remains after that fix is entirely intrinsic — `LeanIMT._insert` costs one
61,337-gas Poseidon call per set bit of the insertion index — and it runs against a **fixed wei**
sponsorship budget. The result is a feasibility boundary that is already binding at tree size 0
(8.8 gwei against an advertised 10) and tightens with every level (5.0 gwei at 256 members). A
protocol that sponsors privacy-state maintenance out of a fixed per-credit budget has a maximum gas
price that falls as its anonymity set grows. **That is the part of D2-B that is not a parameter
bug.**

**Do not generalise.** This is measured on one implementation of one primitive: `poseidon-solidity`
`PoseidonT3` as an external library, reached by delegatecall, compiled at optimizer 200 with via-IR.
A cheaper hash, an inlined library, a precompile, or a batched/epoch insertion would move every
number here. Nothing in this phase shows that all private Paymasters have this problem; it shows
that *this* one does, and why.

### Does D2 remain strong after the kill-condition test?

**D2-A: no.** Its kill condition fired. The pilot's contention result stands as a measurement, but
"retain the last K roots" is a small, cheap, standard fix, so D2-A cannot carry a paper.

**D2-B: partly.** Its immediate symptom is a parameter bug, but underneath it there is a real and
quantified statement: gas-sponsored privacy-state maintenance scales logarithmically while a fixed
sponsorship budget does not, so the sponsorable gas-price envelope shrinks as the anonymity set
grows, and the protocol's own sybil-resistance invariant is stated against a cap it never reaches.
That is a genuine systems boundary, but it is one finding, not a paper.

---

## 9. Assumptions and limitations

1. **Timing is modelled, not measured** (inherited from the pilot). λ and the segment durations are
   experimental controls; nothing here estimates the root-update rate of a deployed system. The
   pre-registered λ·T ≤ 1 region is a *stated* region, not an empirical claim about deployments.
2. **No production bundler, no staking, no ERC-7562.** This phase isolates protocol-state behaviour
   by design. `HistoryCreditPaymaster` reads only its own storage, but `_count` is keyed by a
   calldata value rather than by `msg.sender` — exactly as the frozen contract's
   `_nullifiers[proof.nullifier]` already is — and no ERC-7562 tracer, reputation system, public
   mempool or staked deployment was involved. **Nothing here establishes ERC-7562 or
   production-bundler compatibility for either the frozen contract or the variant.** If bounded
   history is pursued, that is the next thing to test.
3. **One bundler, ours**; it does not drop a failing operation and re-bundle the rest, which is why
   the whole-bundle failures in §6.6 are an upper bound on what a real bundler would lose.
4. **The fan-out is a harness device.** Contention numbers come from a deployment where one deposit
   mirrors to seven Paymasters. That inflates Bootstrap gas, so every gas, storage, code-size and
   overhead number comes from dedicated one-Paymaster deployments instead; the Spend path is
   untouched by the fan-out.
5. **Benchmark eligibility shortcut.** The gas-decomposition pool's registry is an EOA, so
   eligibility is granted directly instead of paying 256 × 0.021 ETH announcements. Both frozen
   contracts take the registry as a constructor argument, so neither their code nor their
   eligibility rule changes; the announcement path is measured separately, unchanged, in §7.3–§7.4.
6. **Experimental Bootstrap `callGasLimit`** is 1,200,000 in the contention experiments and
   1,500,000 in measurement mode. Neither is the frozen 160,000, neither is a proposed fix, and the
   frozen value is measured separately at every size.
7. **Single chain configuration**: `b3_compat_local`, automine, base fee pinned to 1 gwei, W1 gas
   limits — as in the pilot.
8. **Anonymity-set effect not measured.** §4 states the tradeoff; no experiment here quantifies it.
9. **`eth_estimateGas` is not `eth_estimateUserOperationGas`.** §7.5 shows the information exists
   before inclusion, not that a particular bundler would compute it.

## 10. Unexpected findings

1. **The ≈ 61 k per level *is* one Poseidon call.** 61,183 measured per level against 61,337 gas for
   one isolated `PoseidonT3.hash` — a 154-gas residual. The pilot's headline gas number has a
   one-line explanation.
2. **A failed Bootstrap does not destroy the credit.** The grant is consumed permanently, but an
   unsponsored UserOperation from the same account still inserts the commitment, paid from the
   `vMin` the registry already forwarded, with no externally funded EOA. The frozen contract's own
   comment was right; the pilot's "non-recoverable" was too strong.
3. **Validation-only simulation cannot see a too-low `callGasLimit` at all** — it accepted 8/8,
   including the three that then failed on chain — while `debug_traceCall` separates them perfectly.
4. **The bundler's loss is not monotone in K.** K = 2 loses *more* reverted-bundle gas than K = 1,
   because a bigger history converts free simulation rejections into operations that reach the chain.
5. **Even K = 1 costs more than the frozen contract per root update** (+29,830 gas): the ring
   machinery is heavier than a single `SSTORE` even when it holds one root.
6. **The minimal sufficient `callGasLimit` is a sawtooth**, not a curve — 181,005 at tree size 1 and
   168,700 at size 2 — because the cost tracks the popcount of the insertion index.
7. **The advertised 10 gwei cap is unreachable even at tree size 0 with the minimal sufficient
   limit** (9 gwei measured, 9.29 analytic).

## 11. Unresolved questions

1. What is a realistic λ? Every contention conclusion is stated per λ·T; no deployment-derived
   issuance rate exists.
2. Does bounded root history survive ERC-7562 validation rules and a staked, production bundler?
3. How much anonymity does an older root cost, and does an adversary learn anything from which
   retained root a proof names?
4. Is there a root-update scheme (batched insertion, epoch commitment, a cheaper hash, a precompile)
   that breaks the logarithmic-gas-against-fixed-budget boundary rather than pushing it out?
5. Would a real bundler's drop-and-re-bundle policy remove the whole-bundle failure that persists at
   every K?

---

<!-- BEGIN GENERATED: d2k tables -->
_Generated by `python3 -m experiments.liveness.d2k analyze --batch 20260916T055452Z --write-doc` from `results/d2-killcondition/20260916T055452Z/` and `data/private/d2-killcondition/20260916T055452Z/`. Do not edit by hand._

### K1. Deterministic retention boundary (Section 13)

| variant | K | intervening root updates | runs | included | model says valid | model = outcome | sim accepted | view accepts | root age | on-chain error | nullifier spent | nonce advanced | bundler net (gwei) | sponsor charge (gwei) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frozen | 1 | 0 | 5 | 5 | True | 5 | 5 | 5 | 0 | None | 5 | 5 | 787.200 | 744,910.800 |
| frozen | 1 | 1 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -151,919.600 | 0.000 |
| frozen | 1 | 2 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -151,919.600 | 0.000 |
| frozen | 1 | 3 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -151,919.600 | 0.000 |
| frozen | 1 | 4 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -151,919.600 | 0.000 |
| frozen | 1 | 8 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -151,919.600 | 0.000 |
| K1 | 1 | 0 | 5 | 5 | True | 5 | 5 | 5 | 0 | None | 5 | 5 | 9,387.600 | 719,570.400 |
| K1 | 1 | 1 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K1 | 1 | 2 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K1 | 1 | 3 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K1 | 1 | 4 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K1 | 1 | 8 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K2 | 2 | 0 | 5 | 5 | True | 5 | 5 | 5 | 0 | None | 5 | 5 | 9,368.400 | 719,551.200 |
| K2 | 2 | 1 | 5 | 5 | True | 5 | 5 | 5 | 1 | None | 5 | 5 | 782.400 | 745,129.200 |
| K2 | 2 | 2 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K2 | 2 | 3 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,714.800 | 0.000 |
| K2 | 2 | 4 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K2 | 2 | 8 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,700.800 | 0.000 |
| K4 | 4 | 0 | 5 | 5 | True | 5 | 5 | 5 | 0 | None | 5 | 5 | 9,382.800 | 719,541.600 |
| K4 | 4 | 1 | 5 | 5 | True | 5 | 5 | 5 | 1 | None | 5 | 5 | 9,382.800 | 719,541.600 |
| K4 | 4 | 2 | 5 | 5 | True | 5 | 5 | 5 | 2 | None | 5 | 5 | 796.800 | 745,119.600 |
| K4 | 4 | 3 | 5 | 5 | True | 5 | 5 | 5 | 3 | None | 5 | 5 | 796.800 | 745,119.600 |
| K4 | 4 | 4 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,676.800 | 0.000 |
| K4 | 4 | 8 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,676.800 | 0.000 |
| K8 | 8 | 0 | 5 | 5 | True | 5 | 5 | 5 | 0 | None | 5 | 5 | 9,358.800 | 719,560.800 |
| K8 | 8 | 1 | 5 | 5 | True | 5 | 5 | 5 | 1 | None | 5 | 5 | 9,358.800 | 719,560.800 |
| K8 | 8 | 2 | 5 | 5 | True | 5 | 5 | 5 | 2 | None | 5 | 5 | 9,358.800 | 719,560.800 |
| K8 | 8 | 3 | 5 | 5 | True | 5 | 5 | 5 | 3 | None | 5 | 5 | 9,358.800 | 719,560.800 |
| K8 | 8 | 4 | 5 | 5 | True | 5 | 5 | 5 | 4 | None | 5 | 5 | 772.800 | 745,138.800 |
| K8 | 8 | 8 | 5 | 0 | False | 5 | 5 | 0 | None | RootMismatch | 0 | 0 | -160,720.000 | 0.000 |

### K2. Security invariants with real proofs (Section 6)

| invariant | K | runs | held | expected included | included | expected error | observed error | rejected at simulation |
|---|---|---|---|---|---|---|---|---|
| current_root_accepted | 8 | 5 | 5 | True | 5 | None | – | 0 |
| retained_historical_root_accepted | 8 | 5 | 5 | True | 5 | None | – | 0 |
| root_older_than_window_rejected | 8 | 5 | 5 | False | 0 | RootMismatch | RootMismatch | 5 |
| fabricated_root_rejected | 8 | 5 | 5 | False | 0 | RootMismatch | RootMismatch | 5 |
| future_unknown_root_rejected | 8 | 5 | 5 | False | 0 | RootMismatch | RootMismatch | 5 |
| wrong_message_rejected | 8 | 5 | 5 | False | 0 | WrongMessage | WrongMessage | 5 |
| wrong_scope_rejected | 8 | 5 | 5 | False | 0 | WrongScope | WrongScope | 5 |
| invalid_groth16_rejected | 8 | 5 | 5 | False | 0 | InvalidProof | InvalidProof | 5 |
| nullifier_reuse_rejected | 8 | 5 | 5 | False | 0 | NullifierSpent | NullifierSpent | 5 |
| same_credit_twice_rejected | 8 | 5 | 5 | False | 0 | NullifierSpent | NullifierSpent | 5 |
| k1_matches_frozen | 8 | 5 | 5 | None | 0 | None | – | 0 |

### K3. Stochastic contention pooled by variant (Sections 9/10)

| variant | K | trials (λ>0) | stale | P̂(stale) | 95% CI | valid at sim → stale at inclusion | included (all cells) | other failures | inconsistent | model mismatch | bundler loss (gwei) | max root updates survived |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frozen | 1 | 800 | 408 | 0.510 | [0.475, 0.545] | 141 | 592 | 0 | 0 | 0 | 21,422,214.000 | 0 |
| K1 | 1 | 800 | 408 | 0.510 | [0.475, 0.545] | 141 | 592 | 0 | 0 | 0 | 22,663,560.000 | 0 |
| K2 | 2 | 800 | 258 | 0.323 | [0.291, 0.356] | 130 | 742 | 0 | 0 | 0 | 20,893,986.000 | 1 |
| K4 | 4 | 800 | 124 | 0.155 | [0.132, 0.182] | 94 | 876 | 0 | 0 | 0 | 15,105,762.000 | 3 |
| K8 | 8 | 800 | 36 | 0.045 | [0.033, 0.062] | 36 | 964 | 0 | 0 | 0 | 5,786,436.000 | 7 |
| K16 | 16 | 800 | 0 | 0.000 | [0.000, 0.005] | 0 | 1,000 | 0 | 0 | 0 | 0.000 | 15 |
| K32 | 32 | 800 | 0 | 0.000 | [0.000, 0.005] | 0 | 1,000 | 0 | 0 | 0 | 0.000 | 15 |

### K4. Analytical vs measured retention (Section 8)

| K | λT | trials | stale | P̂(stale) | 95% CI | analytic P(stale|K) | in CI | |error| |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.062 | 80 | 2 | 0.025 | [0.007, 0.087] | 0.061 | True | 0.036 |
| 1 | 0.125 | 160 | 18 | 0.113 | [0.072, 0.171] | 0.118 | True | 0.005 |
| 1 | 0.250 | 240 | 46 | 0.192 | [0.147, 0.246] | 0.221 | True | 0.030 |
| 1 | 0.500 | 320 | 102 | 0.319 | [0.270, 0.372] | 0.393 | False | 0.075 |
| 1 | 1.000 | 240 | 162 | 0.675 | [0.613, 0.731] | 0.632 | True | 0.043 |
| 1 | 1.250 | 80 | 44 | 0.550 | [0.441, 0.654] | 0.713 | False | 0.163 |
| 1 | 2.000 | 160 | 138 | 0.863 | [0.801, 0.907] | 0.865 | True | 0.002 |
| 1 | 2.500 | 80 | 68 | 0.850 | [0.756, 0.912] | 0.918 | False | 0.068 |
| 1 | 4.000 | 80 | 78 | 0.975 | [0.913, 0.993] | 0.982 | True | 0.007 |
| 1 | 5.000 | 80 | 78 | 0.975 | [0.913, 0.993] | 0.993 | False | 0.018 |
| 1 | 10.000 | 80 | 80 | 1.000 | [0.954, 1.000] | 1.000 | True | 0.000 |
| 2 | 0.062 | 40 | 1 | 0.025 | [0.004, 0.129] | 0.002 | False | 0.023 |
| 2 | 0.125 | 80 | 1 | 0.013 | [0.002, 0.067] | 0.007 | True | 0.005 |
| 2 | 0.250 | 120 | 4 | 0.033 | [0.013, 0.083] | 0.026 | True | 0.007 |
| 2 | 0.500 | 160 | 15 | 0.094 | [0.058, 0.149] | 0.090 | True | 0.004 |
| 2 | 1.000 | 120 | 36 | 0.300 | [0.225, 0.387] | 0.264 | True | 0.036 |
| 2 | 1.250 | 40 | 14 | 0.350 | [0.221, 0.505] | 0.355 | True | 0.005 |
| 2 | 2.000 | 80 | 46 | 0.575 | [0.466, 0.677] | 0.594 | True | 0.019 |
| 2 | 2.500 | 40 | 27 | 0.675 | [0.520, 0.799] | 0.713 | True | 0.038 |
| 2 | 4.000 | 40 | 35 | 0.875 | [0.739, 0.945] | 0.908 | True | 0.033 |
| 2 | 5.000 | 40 | 39 | 0.975 | [0.871, 0.996] | 0.960 | True | 0.015 |
| 2 | 10.000 | 40 | 40 | 1.000 | [0.912, 1.000] | 1.000 | True | 0.000 |
| 4 | 0.062 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 4 | 0.125 | 80 | 0 | 0.000 | [0.000, 0.046] | 0.000 | True | 0.000 |
| 4 | 0.250 | 120 | 0 | 0.000 | [0.000, 0.031] | 0.000 | True | 0.000 |
| 4 | 0.500 | 160 | 0 | 0.000 | [0.000, 0.023] | 0.002 | True | 0.002 |
| 4 | 1.000 | 120 | 3 | 0.025 | [0.009, 0.071] | 0.019 | True | 0.006 |
| 4 | 1.250 | 40 | 2 | 0.050 | [0.014, 0.165] | 0.038 | True | 0.012 |
| 4 | 2.000 | 80 | 17 | 0.212 | [0.137, 0.314] | 0.143 | True | 0.070 |
| 4 | 2.500 | 40 | 11 | 0.275 | [0.161, 0.428] | 0.242 | True | 0.033 |
| 4 | 4.000 | 40 | 20 | 0.500 | [0.352, 0.648] | 0.567 | True | 0.067 |
| 4 | 5.000 | 40 | 31 | 0.775 | [0.625, 0.877] | 0.735 | True | 0.040 |
| 4 | 10.000 | 40 | 40 | 1.000 | [0.912, 1.000] | 0.990 | True | 0.010 |
| 8 | 0.062 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 8 | 0.125 | 80 | 0 | 0.000 | [0.000, 0.046] | 0.000 | True | 0.000 |
| 8 | 0.250 | 120 | 0 | 0.000 | [0.000, 0.031] | 0.000 | True | 0.000 |
| 8 | 0.500 | 160 | 0 | 0.000 | [0.000, 0.023] | 0.000 | True | 0.000 |
| 8 | 1.000 | 120 | 0 | 0.000 | [0.000, 0.031] | 0.000 | True | 0.000 |
| 8 | 1.250 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 8 | 2.000 | 80 | 0 | 0.000 | [0.000, 0.046] | 0.001 | True | 0.001 |
| 8 | 2.500 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.004 | True | 0.004 |
| 8 | 4.000 | 40 | 3 | 0.075 | [0.026, 0.199] | 0.051 | True | 0.024 |
| 8 | 5.000 | 40 | 2 | 0.050 | [0.014, 0.165] | 0.133 | True | 0.083 |
| 8 | 10.000 | 40 | 31 | 0.775 | [0.625, 0.877] | 0.780 | True | 0.005 |
| 16 | 0.062 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 16 | 0.125 | 80 | 0 | 0.000 | [0.000, 0.046] | 0.000 | True | 0.000 |
| 16 | 0.250 | 120 | 0 | 0.000 | [0.000, 0.031] | 0.000 | True | 0.000 |
| 16 | 0.500 | 160 | 0 | 0.000 | [0.000, 0.023] | 0.000 | True | 0.000 |
| 16 | 1.000 | 120 | 0 | 0.000 | [0.000, 0.031] | 0.000 | True | 0.000 |
| 16 | 1.250 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 16 | 2.000 | 80 | 0 | 0.000 | [0.000, 0.046] | 0.000 | True | 0.000 |
| 16 | 2.500 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 16 | 4.000 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 16 | 5.000 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 16 | 10.000 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.049 | True | 0.049 |
| 32 | 0.062 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 32 | 0.125 | 80 | 0 | 0.000 | [0.000, 0.046] | 0.000 | True | 0.000 |
| 32 | 0.250 | 120 | 0 | 0.000 | [0.000, 0.031] | 0.000 | True | 0.000 |
| 32 | 0.500 | 160 | 0 | 0.000 | [0.000, 0.023] | 0.000 | True | 0.000 |
| 32 | 1.000 | 120 | 0 | 0.000 | [0.000, 0.031] | 0.000 | True | 0.000 |
| 32 | 1.250 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 32 | 2.000 | 80 | 0 | 0.000 | [0.000, 0.046] | 0.000 | True | 0.000 |
| 32 | 2.500 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 32 | 4.000 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 32 | 5.000 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |
| 32 | 10.000 | 40 | 0 | 0.000 | [0.000, 0.088] | 0.000 | True | 0.000 |

7000 attempts; 140 λ>0 cells, 4 whose Wilson interval excludes the analytical value; inconsistent classifications 0; retention-model mismatches 0. Outcome classes: {"VALID_PROOF_INCLUDED": 5766, "VALID_AT_SIMULATION_STALE_BEFORE_INCLUSION": 542, "STALE_BEFORE_SUBMISSION": 616, "STALE_BEFORE_SIMULATION": 76}.

### K5. Retries, proofs, simulations and latency by K (Section 10)

| variant | K | trials (λ>0) | successes | success rate | attempts (= proofs) / success | simulations / success | failures at simulation | failures on chain | bundler loss (gwei) | time to success p50 (s) | p95 (s) | proving ms (total) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frozen | 1 | 54 | 32 | 0.593 | 9.719 | 9.719 | 216 | 63 | 9,570,690.000 | 2.400 | 15.150 | 83,207.943 |
| K1 | 1 | 54 | 32 | 0.593 | 9.719 | 9.719 | 216 | 63 | 10,123,680.000 | 2.400 | 15.150 | 61,977.093 |
| K2 | 2 | 54 | 42 | 0.778 | 5.571 | 5.571 | 122 | 70 | 11,250,310.000 | 2.000 | 21.750 | 47,198.914 |
| K4 | 4 | 54 | 49 | 0.907 | 2.653 | 2.653 | 31 | 50 | 8,034,304.000 | 2.000 | 11.520 | 26,656.988 |
| K8 | 8 | 54 | 52 | 0.963 | 1.769 | 1.769 | 4 | 36 | 5,785,384.000 | 2.000 | 16.750 | 18,508.486 |
| K16 | 16 | 54 | 54 | 1.000 | 1.019 | 1.019 | 0 | 1 | 160,696.000 | 2.000 | 5.000 | 12,063.937 |
| K32 | 32 | 54 | 54 | 1.000 | 1.000 | 1.000 | 0 | 0 | 0.000 | 2.000 | 5.000 | 10,127.802 |

### K6. Bundle behaviour (Section 14)

| mode | variant | K | bundle size | intervening root updates | runs | whole bundle included | ops included / ops | model says all included | on-chain error | failing op index | bundler net (gwei) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| one_stale_rest_fresh | frozen | 1 | 2 | 1 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -177,233.200 |
| one_stale_rest_fresh | frozen | 1 | 4 | 1 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,456.000 |
| one_stale_rest_fresh | frozen | 1 | 8 | 1 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,376.000 |
| one_stale_rest_fresh | K1 | 1 | 2 | 1 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,043.200 |
| one_stale_rest_fresh | K1 | 1 | 4 | 1 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,516.000 |
| one_stale_rest_fresh | K1 | 1 | 8 | 1 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,496.000 |
| one_stale_rest_fresh | K2 | 2 | 2 | 2 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,014.400 |
| one_stale_rest_fresh | K2 | 2 | 4 | 2 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,432.000 |
| one_stale_rest_fresh | K2 | 2 | 8 | 2 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,400.000 |
| one_stale_rest_fresh | K4 | 4 | 2 | 4 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,004.800 |
| one_stale_rest_fresh | K4 | 4 | 4 | 4 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,348.000 |
| one_stale_rest_fresh | K4 | 4 | 8 | 4 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,268.000 |
| one_stale_rest_fresh | K8 | 8 | 2 | 8 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,009.600 |
| one_stale_rest_fresh | K8 | 8 | 4 | 8 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,432.000 |
| one_stale_rest_fresh | K8 | 8 | 8 | 8 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,460.000 |
| shared_root | frozen | 1 | 1 | 0 | 5 | 5 | 5/5 | True | None | None | -8,808.000 |
| shared_root | frozen | 1 | 1 | 1 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -151,914.800 |
| shared_root | frozen | 1 | 1 | 2 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -151,914.800 |
| shared_root | frozen | 1 | 2 | 0 | 5 | 5 | 10/10 | True | None | None | 59,158.000 |
| shared_root | frozen | 1 | 2 | 1 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -177,233.200 |
| shared_root | frozen | 1 | 2 | 2 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -177,233.200 |
| shared_root | frozen | 1 | 4 | 0 | 5 | 5 | 20/20 | True | None | None | 195,120.400 |
| shared_root | frozen | 1 | 4 | 1 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,468.000 |
| shared_root | frozen | 1 | 4 | 2 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,468.000 |
| shared_root | frozen | 1 | 8 | 0 | 5 | 5 | 40/40 | True | None | None | 467,018.400 |
| shared_root | frozen | 1 | 8 | 1 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,448.000 |
| shared_root | frozen | 1 | 8 | 2 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,448.000 |
| shared_root | K1 | 1 | 1 | 0 | 5 | 5 | 5/5 | True | None | None | -8,827.200 |
| shared_root | K1 | 1 | 1 | 1 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,724.800 |
| shared_root | K1 | 1 | 1 | 2 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,724.800 |
| shared_root | K1 | 1 | 2 | 0 | 5 | 5 | 10/10 | True | None | None | 59,148.400 |
| shared_root | K1 | 1 | 2 | 1 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,033.600 |
| shared_root | K1 | 1 | 2 | 2 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,033.600 |
| shared_root | K1 | 1 | 4 | 0 | 5 | 5 | 20/20 | True | None | None | 195,130.000 |
| shared_root | K1 | 1 | 4 | 1 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,468.000 |
| shared_root | K1 | 1 | 4 | 2 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,468.000 |
| shared_root | K1 | 1 | 8 | 0 | 5 | 5 | 40/40 | True | None | None | 466,989.600 |
| shared_root | K1 | 1 | 8 | 1 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,472.000 |
| shared_root | K1 | 1 | 8 | 2 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,472.000 |
| shared_root | K2 | 2 | 1 | 0 | 5 | 5 | 5/5 | True | None | None | -8,822.400 |
| shared_root | K2 | 2 | 1 | 1 | 5 | 5 | 5/5 | True | None | None | -8,822.400 |
| shared_root | K2 | 2 | 1 | 2 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,720.000 |
| shared_root | K2 | 2 | 1 | 3 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,734.000 |
| shared_root | K2 | 2 | 2 | 0 | 5 | 5 | 10/10 | True | None | None | 59,153.200 |
| shared_root | K2 | 2 | 2 | 1 | 5 | 5 | 10/10 | True | None | None | 59,153.200 |
| shared_root | K2 | 2 | 2 | 2 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,014.400 |
| shared_root | K2 | 2 | 2 | 3 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,028.400 |
| shared_root | K2 | 2 | 4 | 0 | 5 | 5 | 20/20 | True | None | None | 195,082.000 |
| shared_root | K2 | 2 | 4 | 1 | 5 | 5 | 20/20 | True | None | None | 195,082.000 |
| shared_root | K2 | 2 | 4 | 2 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,504.000 |
| shared_root | K2 | 2 | 4 | 3 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,504.000 |
| shared_root | K2 | 2 | 8 | 0 | 5 | 5 | 40/40 | True | None | None | 466,936.800 |
| shared_root | K2 | 2 | 8 | 1 | 5 | 5 | 40/40 | True | None | None | 466,936.800 |
| shared_root | K2 | 2 | 8 | 2 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,544.000 |
| shared_root | K2 | 2 | 8 | 3 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,544.000 |
| shared_root | K4 | 4 | 1 | 0 | 5 | 5 | 5/5 | True | None | None | -8,817.600 |
| shared_root | K4 | 4 | 1 | 1 | 5 | 5 | 5/5 | True | None | None | -8,817.600 |
| shared_root | K4 | 4 | 1 | 3 | 5 | 5 | 5/5 | True | None | None | -8,817.600 |
| shared_root | K4 | 4 | 1 | 4 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,705.600 |
| shared_root | K4 | 4 | 1 | 5 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,719.600 |
| shared_root | K4 | 4 | 2 | 0 | 5 | 5 | 10/10 | True | None | None | 59,138.800 |
| shared_root | K4 | 4 | 2 | 1 | 5 | 5 | 10/10 | True | None | None | 59,138.800 |
| shared_root | K4 | 4 | 2 | 3 | 5 | 5 | 10/10 | True | None | None | 59,138.800 |
| shared_root | K4 | 4 | 2 | 4 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,028.800 |
| shared_root | K4 | 4 | 2 | 5 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,042.800 |
| shared_root | K4 | 4 | 4 | 0 | 5 | 5 | 20/20 | True | None | None | 195,091.600 |
| shared_root | K4 | 4 | 4 | 1 | 5 | 5 | 20/20 | True | None | None | 195,091.600 |
| shared_root | K4 | 4 | 4 | 3 | 5 | 5 | 20/20 | True | None | None | 195,091.600 |
| shared_root | K4 | 4 | 4 | 4 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,456.000 |
| shared_root | K4 | 4 | 4 | 5 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,456.000 |
| shared_root | K4 | 4 | 8 | 0 | 5 | 5 | 40/40 | True | None | None | 466,946.400 |
| shared_root | K4 | 4 | 8 | 1 | 5 | 5 | 40/40 | True | None | None | 466,946.400 |
| shared_root | K4 | 4 | 8 | 3 | 5 | 5 | 40/40 | True | None | None | 466,946.400 |
| shared_root | K4 | 4 | 8 | 4 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,472.000 |
| shared_root | K4 | 4 | 8 | 5 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,472.000 |
| shared_root | K8 | 8 | 1 | 0 | 5 | 5 | 5/5 | True | None | None | -8,803.200 |
| shared_root | K8 | 8 | 1 | 1 | 5 | 5 | 5/5 | True | None | None | -8,803.200 |
| shared_root | K8 | 8 | 1 | 7 | 5 | 5 | 5/5 | True | None | None | -8,803.200 |
| shared_root | K8 | 8 | 1 | 8 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,705.600 |
| shared_root | K8 | 8 | 1 | 9 | 5 | 0 | 0/5 | False | RootMismatch | 0 | -160,719.600 |
| shared_root | K8 | 8 | 2 | 0 | 5 | 5 | 10/10 | True | None | None | 59,186.800 |
| shared_root | K8 | 8 | 2 | 1 | 5 | 5 | 10/10 | True | None | None | 59,186.800 |
| shared_root | K8 | 8 | 2 | 7 | 5 | 5 | 10/10 | True | None | None | 59,186.800 |
| shared_root | K8 | 8 | 2 | 8 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,000.000 |
| shared_root | K8 | 8 | 2 | 9 | 5 | 0 | 0/10 | False | RootMismatch | 0 | -186,014.000 |
| shared_root | K8 | 8 | 4 | 0 | 5 | 5 | 20/20 | True | None | None | 195,154.000 |
| shared_root | K8 | 8 | 4 | 1 | 5 | 5 | 20/20 | True | None | None | 195,154.000 |
| shared_root | K8 | 8 | 4 | 7 | 5 | 5 | 20/20 | True | None | None | 195,154.000 |
| shared_root | K8 | 8 | 4 | 8 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,420.000 |
| shared_root | K8 | 8 | 4 | 9 | 5 | 0 | 0/20 | False | RootMismatch | 0 | -288,420.000 |
| shared_root | K8 | 8 | 8 | 0 | 5 | 5 | 40/40 | True | None | None | 467,037.600 |
| shared_root | K8 | 8 | 8 | 1 | 5 | 5 | 40/40 | True | None | None | 467,037.600 |
| shared_root | K8 | 8 | 8 | 7 | 5 | 5 | 40/40 | True | None | None | 467,037.600 |
| shared_root | K8 | 8 | 8 | 8 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,424.000 |
| shared_root | K8 | 8 | 8 | 9 | 5 | 0 | 0/40 | False | RootMismatch | 0 | -531,424.000 |

### K7. Spend-validation overhead by K (Section 11)

| variant | K | samples | validatePaymasterUserOp frame gas | Δ vs frozen (gas) | Δ vs frozen | verifyProof frame gas | UserOp actualGasUsed | Δ actual (gas) | Δ actual | Paymaster charge (wei) | Paymaster slots written |
|---|---|---|---|---|---|---|---|---|---|---|---|
| frozen | 1 | 6 | 253,403.000 | 0.000 | 0.000% | 219,064.000 | 363,921.000 | 0.000 | 0.000% | 727,842,000,000,000.000 | 1 |
| K1 | 1 | 6 | 253,517.000 | 114.000 | 0.045% | 219,064.000 | 364,035.000 | 114.000 | 0.031% | 728,070,000,000,000.000 | 1 |
| K2 | 2 | 6 | 253,517.000 | 114.000 | 0.045% | 219,064.000 | 364,035.000 | 114.000 | 0.031% | 728,070,000,000,000.000 | 1 |
| K4 | 4 | 6 | 253,517.000 | 114.000 | 0.045% | 219,064.000 | 364,035.000 | 114.000 | 0.031% | 728,070,000,000,000.000 | 1 |
| K8 | 8 | 6 | 253,517.000 | 114.000 | 0.045% | 219,064.000 | 364,035.000 | 114.000 | 0.031% | 728,070,000,000,000.000 | 1 |
| K16 | 16 | 6 | 253,517.000 | 114.000 | 0.045% | 219,064.000 | 364,035.000 | 114.000 | 0.031% | 728,070,000,000,000.000 | 1 |
| K32 | 32 | 6 | 253,517.000 | 114.000 | 0.045% | 219,064.000 | 364,035.000 | 114.000 | 0.031% | 728,070,000,000,000.000 | 1 |

### K8. Root-update overhead by K (Section 11)

| variant | K | tree size | mirrorRoot frame gas | Δ mirror (gas) | deposit frame gas | Δ deposit (gas) | Δ deposit | Bootstrap actualGasUsed | Δ Bootstrap (gas) | Δ Bootstrap | Paymaster slots written | new non-zero | history length |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frozen | 1 | 0 | 23,611 | 0 | 121,763 | 0 | 0.00% | 499,564 | 24 | 0.00% | 1 | 1 | 1 |
| frozen | 1 | 0 | 23,611 | 0 | 121,763 | 0 | 0.00% | 499,540 | 0 | 0.00% | 1 | 1 | 1 |
| frozen | 1 | 1 | 6,511 | 0 | 171,218 | 0 | 0.00% | 544,074 | 24 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 1 | 6,511 | 0 | 171,218 | 0 | 0.00% | 544,050 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 2 | 6,511 | 0 | 159,287 | 0 | 0.00% | 533,324 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 2 | 6,511 | 0 | 159,287 | 0 | 0.00% | 533,324 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 3 | 6,511 | 0 | 195,329 | 0 | 0.00% | 565,774 | 12 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 3 | 6,511 | 0 | 195,329 | 0 | 0.00% | 565,762 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 4 | 6,511 | 0 | 164,456 | 0 | 0.00% | 537,988 | 12 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 4 | 6,511 | 0 | 164,456 | 0 | 0.00% | 537,976 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 7 | 6,511 | 0 | 256,512 | 0 | 0.00% | 620,838 | 12 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 7 | 6,511 | 0 | 256,512 | 0 | 0.00% | 620,826 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 8 | 6,511 | 0 | 169,625 | 0 | 0.00% | 542,640 | 36 | 0.01% | 1 | 0 | 1 |
| frozen | 1 | 8 | 6,511 | 0 | 169,625 | 0 | 0.00% | 542,604 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 15 | 6,511 | 0 | 317,695 | 0 | 0.00% | 675,903 | 12 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 15 | 6,511 | 0 | 317,695 | 0 | 0.00% | 675,891 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 16 | 6,511 | 0 | 174,794 | 0 | 0.00% | 547,292 | 12 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 16 | 6,511 | 0 | 174,794 | 0 | 0.00% | 547,280 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 31 | 6,511 | 0 | 378,878 | 0 | 0.00% | 730,956 | 0 | 0.00% | 1 | 0 | 1 |
| frozen | 1 | 31 | 6,511 | 0 | 378,878 | 0 | 0.00% | 730,956 | 0 | 0.00% | 1 | 0 | 1 |
| K1 | 1 | 0 | 48,267 | 24,656 | 146,419 | 24,656 | 20.25% | 521,755 | 22,215 | 4.45% | 2 | 2 | 1 |
| K1 | 1 | 0 | 48,267 | 24,656 | 146,419 | 24,656 | 20.25% | 521,731 | 22,191 | 4.44% | 2 | 2 | 1 |
| K1 | 1 | 1 | 36,341 | 29,830 | 201,048 | 29,830 | 17.42% | 570,921 | 26,871 | 4.94% | 2 | 1 | 1 |
| K1 | 1 | 1 | 36,341 | 29,830 | 201,048 | 29,830 | 17.42% | 570,897 | 26,847 | 4.93% | 2 | 1 | 1 |
| K1 | 1 | 2 | 36,341 | 29,830 | 189,117 | 29,830 | 18.73% | 560,171 | 26,847 | 5.03% | 2 | 1 | 1 |
| K1 | 1 | 2 | 36,341 | 29,830 | 189,117 | 29,830 | 18.73% | 560,171 | 26,847 | 5.03% | 2 | 1 | 1 |
| K1 | 1 | 3 | 36,341 | 29,830 | 225,159 | 29,830 | 15.27% | 592,621 | 26,859 | 4.75% | 2 | 1 | 1 |
| K1 | 1 | 3 | 36,341 | 29,830 | 225,159 | 29,830 | 15.27% | 592,609 | 26,847 | 4.75% | 2 | 1 | 1 |
| K1 | 1 | 4 | 36,341 | 29,830 | 194,286 | 29,830 | 18.14% | 564,835 | 26,859 | 4.99% | 2 | 1 | 1 |
| K1 | 1 | 4 | 36,341 | 29,830 | 194,286 | 29,830 | 18.14% | 564,823 | 26,847 | 4.99% | 2 | 1 | 1 |
| K1 | 1 | 7 | 36,341 | 29,830 | 286,342 | 29,830 | 11.63% | 647,685 | 26,859 | 4.33% | 2 | 1 | 1 |
| K1 | 1 | 7 | 36,341 | 29,830 | 286,342 | 29,830 | 11.63% | 647,673 | 26,847 | 4.32% | 2 | 1 | 1 |
| K1 | 1 | 8 | 36,341 | 29,830 | 199,455 | 29,830 | 17.59% | 569,487 | 26,883 | 4.95% | 2 | 1 | 1 |
| K1 | 1 | 8 | 36,341 | 29,830 | 199,455 | 29,830 | 17.59% | 569,451 | 26,847 | 4.95% | 2 | 1 | 1 |
| K1 | 1 | 15 | 36,341 | 29,830 | 347,525 | 29,830 | 9.39% | 702,750 | 26,859 | 3.97% | 2 | 1 | 1 |
| K1 | 1 | 15 | 36,341 | 29,830 | 347,525 | 29,830 | 9.39% | 702,738 | 26,847 | 3.97% | 2 | 1 | 1 |
| K1 | 1 | 16 | 36,341 | 29,830 | 204,624 | 29,830 | 17.07% | 574,139 | 26,859 | 4.91% | 2 | 1 | 1 |
| K1 | 1 | 16 | 36,341 | 29,830 | 204,624 | 29,830 | 17.07% | 574,127 | 26,847 | 4.91% | 2 | 1 | 1 |
| K1 | 1 | 31 | 36,341 | 29,830 | 408,708 | 29,830 | 7.87% | 757,803 | 26,847 | 3.67% | 2 | 1 | 1 |
| K1 | 1 | 31 | 36,341 | 29,830 | 408,708 | 29,830 | 7.87% | 757,803 | 26,847 | 3.67% | 2 | 1 | 1 |
| K2 | 2 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,672 | 40,132 | 8.03% | 3 | 3 | 1 |
| K2 | 2 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,648 | 40,108 | 8.03% | 3 | 3 | 1 |
| K2 | 2 | 1 | 51,067 | 44,556 | 215,774 | 44,556 | 26.02% | 584,174 | 40,124 | 7.38% | 2 | 2 | 2 |
| K2 | 2 | 1 | 51,067 | 44,556 | 215,774 | 44,556 | 26.02% | 584,150 | 40,100 | 7.37% | 2 | 2 | 2 |
| K2 | 2 | 2 | 56,249 | 49,738 | 209,025 | 49,738 | 31.23% | 578,088 | 44,764 | 8.39% | 3 | 2 | 2 |
| K2 | 2 | 2 | 56,249 | 49,738 | 209,025 | 49,738 | 31.23% | 578,088 | 44,764 | 8.39% | 3 | 2 | 2 |
| K2 | 2 | 3 | 39,141 | 32,630 | 227,959 | 32,630 | 16.71% | 595,141 | 29,379 | 5.19% | 2 | 1 | 2 |
| K2 | 2 | 3 | 39,141 | 32,630 | 227,959 | 32,630 | 16.71% | 595,129 | 29,367 | 5.19% | 2 | 1 | 2 |
| K2 | 2 | 4 | 56,249 | 49,738 | 214,194 | 49,738 | 30.24% | 582,752 | 44,776 | 8.32% | 3 | 2 | 2 |
| K2 | 2 | 4 | 56,249 | 49,738 | 214,194 | 49,738 | 30.24% | 582,740 | 44,764 | 8.32% | 3 | 2 | 2 |
| K2 | 2 | 7 | 39,141 | 32,630 | 289,142 | 32,630 | 12.72% | 650,205 | 29,379 | 4.73% | 2 | 1 | 2 |
| K2 | 2 | 7 | 39,141 | 32,630 | 289,142 | 32,630 | 12.72% | 650,193 | 29,367 | 4.73% | 2 | 1 | 2 |
| K2 | 2 | 8 | 56,249 | 49,738 | 219,363 | 49,738 | 29.32% | 587,404 | 44,800 | 8.26% | 3 | 2 | 2 |
| K2 | 2 | 8 | 56,249 | 49,738 | 219,363 | 49,738 | 29.32% | 587,368 | 44,764 | 8.25% | 3 | 2 | 2 |
| K2 | 2 | 15 | 39,141 | 32,630 | 350,325 | 32,630 | 10.27% | 705,270 | 29,379 | 4.35% | 2 | 1 | 2 |
| K2 | 2 | 15 | 39,141 | 32,630 | 350,325 | 32,630 | 10.27% | 705,258 | 29,367 | 4.34% | 2 | 1 | 2 |
| K2 | 2 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,056 | 44,776 | 8.18% | 3 | 2 | 2 |
| K2 | 2 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,044 | 44,764 | 8.18% | 3 | 2 | 2 |
| K2 | 2 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 2 |
| K2 | 2 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 2 |
| K4 | 4 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,672 | 40,132 | 8.03% | 3 | 3 | 1 |
| K4 | 4 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,648 | 40,108 | 8.03% | 3 | 3 | 1 |
| K4 | 4 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,181 | 40,131 | 7.38% | 3 | 2 | 2 |
| K4 | 4 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,157 | 40,107 | 7.37% | 3 | 2 | 2 |
| K4 | 4 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K4 | 4 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K4 | 4 | 3 | 51,067 | 44,556 | 239,885 | 44,556 | 22.81% | 605,874 | 40,112 | 7.09% | 2 | 2 | 4 |
| K4 | 4 | 3 | 51,067 | 44,556 | 239,885 | 44,556 | 22.81% | 605,862 | 40,100 | 7.09% | 2 | 2 | 4 |
| K4 | 4 | 4 | 56,249 | 49,738 | 214,194 | 49,738 | 30.24% | 582,752 | 44,776 | 8.32% | 3 | 2 | 4 |
| K4 | 4 | 4 | 56,249 | 49,738 | 214,194 | 49,738 | 30.24% | 582,740 | 44,764 | 8.32% | 3 | 2 | 4 |
| K4 | 4 | 7 | 39,141 | 32,630 | 289,142 | 32,630 | 12.72% | 650,205 | 29,379 | 4.73% | 2 | 1 | 4 |
| K4 | 4 | 7 | 39,141 | 32,630 | 289,142 | 32,630 | 12.72% | 650,193 | 29,367 | 4.73% | 2 | 1 | 4 |
| K4 | 4 | 8 | 56,249 | 49,738 | 219,363 | 49,738 | 29.32% | 587,404 | 44,800 | 8.26% | 3 | 2 | 4 |
| K4 | 4 | 8 | 56,249 | 49,738 | 219,363 | 49,738 | 29.32% | 587,368 | 44,764 | 8.25% | 3 | 2 | 4 |
| K4 | 4 | 15 | 39,141 | 32,630 | 350,325 | 32,630 | 10.27% | 705,270 | 29,379 | 4.35% | 2 | 1 | 4 |
| K4 | 4 | 15 | 39,141 | 32,630 | 350,325 | 32,630 | 10.27% | 705,258 | 29,367 | 4.34% | 2 | 1 | 4 |
| K4 | 4 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,056 | 44,776 | 8.18% | 3 | 2 | 4 |
| K4 | 4 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,044 | 44,764 | 8.18% | 3 | 2 | 4 |
| K4 | 4 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 4 |
| K4 | 4 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 4 |
| K8 | 8 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,672 | 40,132 | 8.03% | 3 | 3 | 1 |
| K8 | 8 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,648 | 40,108 | 8.03% | 3 | 3 | 1 |
| K8 | 8 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,181 | 40,131 | 7.38% | 3 | 2 | 2 |
| K8 | 8 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,157 | 40,107 | 7.37% | 3 | 2 | 2 |
| K8 | 8 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K8 | 8 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K8 | 8 | 3 | 51,075 | 44,564 | 239,893 | 44,564 | 22.81% | 605,881 | 40,119 | 7.09% | 3 | 2 | 4 |
| K8 | 8 | 3 | 51,075 | 44,564 | 239,893 | 44,564 | 22.81% | 605,869 | 40,107 | 7.09% | 3 | 2 | 4 |
| K8 | 8 | 4 | 51,075 | 44,564 | 209,020 | 44,564 | 27.10% | 578,096 | 40,120 | 7.46% | 3 | 2 | 5 |
| K8 | 8 | 4 | 51,075 | 44,564 | 209,020 | 44,564 | 27.10% | 578,084 | 40,108 | 7.46% | 3 | 2 | 5 |
| K8 | 8 | 7 | 51,067 | 44,556 | 301,068 | 44,556 | 17.37% | 660,939 | 40,113 | 6.46% | 2 | 2 | 8 |
| K8 | 8 | 7 | 51,067 | 44,556 | 301,068 | 44,556 | 17.37% | 660,927 | 40,101 | 6.46% | 2 | 2 | 8 |
| K8 | 8 | 8 | 56,249 | 49,738 | 219,363 | 49,738 | 29.32% | 587,404 | 44,800 | 8.26% | 3 | 2 | 8 |
| K8 | 8 | 8 | 56,249 | 49,738 | 219,363 | 49,738 | 29.32% | 587,368 | 44,764 | 8.25% | 3 | 2 | 8 |
| K8 | 8 | 15 | 39,141 | 32,630 | 350,325 | 32,630 | 10.27% | 705,270 | 29,379 | 4.35% | 2 | 1 | 8 |
| K8 | 8 | 15 | 39,141 | 32,630 | 350,325 | 32,630 | 10.27% | 705,258 | 29,367 | 4.34% | 2 | 1 | 8 |
| K8 | 8 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,056 | 44,776 | 8.18% | 3 | 2 | 8 |
| K8 | 8 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,044 | 44,764 | 8.18% | 3 | 2 | 8 |
| K8 | 8 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 8 |
| K8 | 8 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 8 |
| K16 | 16 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,672 | 40,132 | 8.03% | 3 | 3 | 1 |
| K16 | 16 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,648 | 40,108 | 8.03% | 3 | 3 | 1 |
| K16 | 16 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,181 | 40,131 | 7.38% | 3 | 2 | 2 |
| K16 | 16 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,157 | 40,107 | 7.37% | 3 | 2 | 2 |
| K16 | 16 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K16 | 16 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K16 | 16 | 3 | 51,075 | 44,564 | 239,893 | 44,564 | 22.81% | 605,881 | 40,119 | 7.09% | 3 | 2 | 4 |
| K16 | 16 | 3 | 51,075 | 44,564 | 239,893 | 44,564 | 22.81% | 605,869 | 40,107 | 7.09% | 3 | 2 | 4 |
| K16 | 16 | 4 | 51,075 | 44,564 | 209,020 | 44,564 | 27.10% | 578,096 | 40,120 | 7.46% | 3 | 2 | 5 |
| K16 | 16 | 4 | 51,075 | 44,564 | 209,020 | 44,564 | 27.10% | 578,084 | 40,108 | 7.46% | 3 | 2 | 5 |
| K16 | 16 | 7 | 51,075 | 44,564 | 301,076 | 44,564 | 17.37% | 660,946 | 40,120 | 6.46% | 3 | 2 | 8 |
| K16 | 16 | 7 | 51,075 | 44,564 | 301,076 | 44,564 | 17.37% | 660,934 | 40,108 | 6.46% | 3 | 2 | 8 |
| K16 | 16 | 8 | 51,075 | 44,564 | 214,189 | 44,564 | 26.27% | 582,748 | 40,144 | 7.40% | 3 | 2 | 9 |
| K16 | 16 | 8 | 51,075 | 44,564 | 214,189 | 44,564 | 26.27% | 582,712 | 40,108 | 7.39% | 3 | 2 | 9 |
| K16 | 16 | 15 | 51,067 | 44,556 | 362,251 | 44,556 | 14.02% | 716,004 | 40,113 | 5.93% | 2 | 2 | 16 |
| K16 | 16 | 15 | 51,067 | 44,556 | 362,251 | 44,556 | 14.02% | 715,992 | 40,101 | 5.93% | 2 | 2 | 16 |
| K16 | 16 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,056 | 44,776 | 8.18% | 3 | 2 | 16 |
| K16 | 16 | 16 | 56,249 | 49,738 | 224,532 | 49,738 | 28.46% | 592,044 | 44,764 | 8.18% | 3 | 2 | 16 |
| K16 | 16 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 16 |
| K16 | 16 | 31 | 39,141 | 32,630 | 411,508 | 32,630 | 8.61% | 760,323 | 29,367 | 4.02% | 2 | 1 | 16 |
| K32 | 32 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,672 | 40,132 | 8.03% | 3 | 3 | 1 |
| K32 | 32 | 0 | 68,175 | 44,564 | 166,327 | 44,564 | 36.60% | 539,648 | 40,108 | 8.03% | 3 | 3 | 1 |
| K32 | 32 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,181 | 40,131 | 7.38% | 3 | 2 | 2 |
| K32 | 32 | 1 | 51,075 | 44,564 | 215,782 | 44,564 | 26.03% | 584,157 | 40,107 | 7.37% | 3 | 2 | 2 |
| K32 | 32 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K32 | 32 | 2 | 51,075 | 44,564 | 203,851 | 44,564 | 27.98% | 573,432 | 40,108 | 7.52% | 3 | 2 | 3 |
| K32 | 32 | 3 | 51,075 | 44,564 | 239,893 | 44,564 | 22.81% | 605,881 | 40,119 | 7.09% | 3 | 2 | 4 |
| K32 | 32 | 3 | 51,075 | 44,564 | 239,893 | 44,564 | 22.81% | 605,869 | 40,107 | 7.09% | 3 | 2 | 4 |
| K32 | 32 | 4 | 51,075 | 44,564 | 209,020 | 44,564 | 27.10% | 578,096 | 40,120 | 7.46% | 3 | 2 | 5 |
| K32 | 32 | 4 | 51,075 | 44,564 | 209,020 | 44,564 | 27.10% | 578,084 | 40,108 | 7.46% | 3 | 2 | 5 |
| K32 | 32 | 7 | 51,075 | 44,564 | 301,076 | 44,564 | 17.37% | 660,946 | 40,120 | 6.46% | 3 | 2 | 8 |
| K32 | 32 | 7 | 51,075 | 44,564 | 301,076 | 44,564 | 17.37% | 660,934 | 40,108 | 6.46% | 3 | 2 | 8 |
| K32 | 32 | 8 | 51,075 | 44,564 | 214,189 | 44,564 | 26.27% | 582,748 | 40,144 | 7.40% | 3 | 2 | 9 |
| K32 | 32 | 8 | 51,075 | 44,564 | 214,189 | 44,564 | 26.27% | 582,712 | 40,108 | 7.39% | 3 | 2 | 9 |
| K32 | 32 | 15 | 51,075 | 44,564 | 362,259 | 44,564 | 14.03% | 716,011 | 40,120 | 5.94% | 3 | 2 | 16 |
| K32 | 32 | 15 | 51,075 | 44,564 | 362,259 | 44,564 | 14.03% | 715,999 | 40,108 | 5.93% | 3 | 2 | 16 |
| K32 | 32 | 16 | 51,075 | 44,564 | 219,358 | 44,564 | 25.50% | 587,400 | 40,120 | 7.33% | 3 | 2 | 17 |
| K32 | 32 | 16 | 51,075 | 44,564 | 219,358 | 44,564 | 25.50% | 587,388 | 40,108 | 7.33% | 3 | 2 | 17 |
| K32 | 32 | 31 | 51,067 | 44,556 | 423,434 | 44,556 | 11.76% | 771,056 | 40,100 | 5.49% | 2 | 2 | 32 |
| K32 | 32 | 31 | 51,067 | 44,556 | 423,434 | 44,556 | 11.76% | 771,056 | 40,100 | 5.49% | 2 | 2 | 32 |

### K9. Deployment, code size and storage by K (Section 11)

| variant | K | contract | deployment gas | Δ gas | runtime code (bytes) | Δ bytes | steady-state storage slots | EIP-170 headroom (bytes) |
|---|---|---|---|---|---|---|---|---|
| frozen | 1 | CreditPaymaster | 657,890 | 0 | 2,788 | 0 | 1 | 21,788 |
| K1 | 1 | HistoryCreditPaymaster_K1 | 916,227 | 258,337 | 3,984 | 1,196 | 3 | 20,592 |
| K2 | 2 | HistoryCreditPaymaster_K2 | 916,227 | 258,337 | 3,984 | 1,196 | 5 | 20,592 |
| K4 | 4 | HistoryCreditPaymaster_K4 | 916,227 | 258,337 | 3,984 | 1,196 | 9 | 20,592 |
| K8 | 8 | HistoryCreditPaymaster_K8 | 916,227 | 258,337 | 3,984 | 1,196 | 17 | 20,592 |
| K16 | 16 | HistoryCreditPaymaster_K16 | 916,227 | 258,337 | 3,984 | 1,196 | 33 | 20,592 |
| K32 | 32 | HistoryCreditPaymaster_K32 | 916,227 | 258,337 | 3,984 | 1,196 | 65 | 20,592 |

### K10. Pre-registered kill-condition thresholds (Section 12)

| variant | K | region | trials | stale | stale rate | 95% CI upper | < 0.01 | validation overhead | < 0.05 | root-update overhead (worst size) | < 0.1 | storage slots | <= 128 | meets all |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| frozen | 1 | 0 < λT ≤ 1 | 520 | 165 | 0.317 | 0.359 | False | 0.000% | True | 0.01% | True | 1 | True | False |
| K1 | 1 | 0 < λT ≤ 1 | 520 | 165 | 0.317 | 0.359 | False | 0.031% | True | 5.03% | True | 3 | True | False |
| K2 | 2 | 0 < λT ≤ 1 | 520 | 57 | 0.110 | 0.139 | False | 0.031% | True | 8.39% | True | 5 | True | False |
| K4 | 4 | 0 < λT ≤ 1 | 520 | 3 | 0.006 | 0.017 | False | 0.031% | True | 8.32% | True | 9 | True | False |
| K8 | 8 | 0 < λT ≤ 1 | 520 | 0 | 0.000 | 0.007 | True | 0.031% | True | 8.26% | True | 17 | True | True |
| K16 | 16 | 0 < λT ≤ 1 | 520 | 0 | 0.000 | 0.007 | True | 0.031% | True | 8.18% | True | 33 | True | True |
| K32 | 32 | 0 < λT ≤ 1 | 520 | 0 | 0.000 | 0.007 | True | 0.031% | True | 8.03% | True | 65 | True | True |

Smallest K meeting every pre-registered threshold: **8**.

### G1. CreditPool.deposit gas decomposition (Sections 16-18)

| tree size before | after | depth | index set bits | G0 deposit | G1 insert | G0 − G1 | G2 mirror | G3a | Poseidon calls (G0/G1) | pool slots (written/new) | G1 slots (written/new) | Bootstrap actualGasUsed | predicted G0 = G1 + G3a | residual |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 1 | 0 | 0 | 121,763 | 69,121 | 52,642 | 23,611 | 52,872 | 0/0 | 4/4 | 3/3 | 529,564 | – | – |
| 1 | 2 | 1 | 1 | 171,218 | 135,661 | 35,557 | 6,511 | 35,772 | 1/1 | 5/4 | 4/3 | 574,074 | 171,433.000 | -215.000 |
| 2 | 3 | 2 | 1 | 159,287 | 123,730 | 35,557 | 6,511 | 35,772 | 1/1 | 6/3 | 5/2 | 563,336 | 159,502.000 | -215.000 |
| 3 | 4 | 2 | 2 | 195,329 | 159,736 | 35,593 | 6,511 | 35,772 | 2/2 | 4/2 | 3/1 | 595,774 | 195,508.000 | -179.000 |
| 7 | 8 | 3 | 3 | 256,512 | 220,889 | 35,623 | 6,511 | 35,772 | 3/3 | 4/2 | 3/1 | 650,838 | 256,661.000 | -149.000 |
| 8 | 9 | 4 | 1 | 169,625 | 134,068 | 35,557 | 6,511 | – | 1/1 | 8/3 | 7/2 | 572,640 | 169,840.000 | -215.000 |
| 15 | 16 | 4 | 4 | 317,695 | 282,042 | 35,653 | 6,511 | – | 4/4 | 4/2 | 3/1 | 705,903 | 317,814.000 | -119.000 |
| 16 | 17 | 5 | 1 | 174,794 | 139,237 | 35,557 | 6,511 | – | 1/1 | 9/3 | 8/2 | 577,280 | 175,009.000 | -215.000 |
| 31 | 32 | 5 | 5 | 378,878 | 343,195 | 35,683 | 6,511 | – | 5/5 | 4/2 | 3/1 | 760,968 | 378,967.000 | -89.000 |
| 32 | 33 | 6 | 1 | 179,963 | 144,406 | 35,557 | 6,511 | – | 1/1 | 10/3 | 9/2 | 581,944 | 180,178.000 | -215.000 |
| 63 | 64 | 6 | 6 | 440,062 | 404,349 | 35,713 | 6,511 | – | 6/6 | 4/2 | 3/1 | 816,033 | 440,121.000 | -59.000 |
| 64 | 65 | 7 | 1 | 185,132 | 149,575 | 35,557 | – | – | 1/1 | 11/3 | 10/2 | 586,596 | 185,347.000 | -215.000 |
| 127 | 128 | 7 | 7 | 501,245 | 465,502 | 35,743 | 6,511 | – | 7/7 | 4/2 | 3/1 | 871,098 | 501,274.000 | -29.000 |
| 128 | 129 | 8 | 1 | 190,301 | 154,744 | 35,557 | – | – | 1/1 | 12/3 | 11/2 | 591,249 | 190,516.000 | -215.000 |
| 255 | 256 | 8 | 8 | 562,428 | 526,655 | 35,773 | 6,511 | – | 8/8 | 4/2 | 3/1 | 926,163 | 562,427.000 | 1.000 |

### G2. Per-level growth explained (Section 19)

| tree size (2^d − 1) | Poseidon calls | G0 deposit | G1 insert | Δ G0 / level | Δ G1 / level | Δ Poseidon calls | measured PoseidonT3.hash gas | unexplained per level |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | 171,218 | 135,661 | – | – | – | 61,337.000 | – |
| 3 | 2 | 195,329 | 159,736 | 24,111 | 24,075 | 1 | 61,337.000 | -37,226.000 |
| 7 | 3 | 256,512 | 220,889 | 61,183 | 61,153 | 1 | 61,337.000 | -154.000 |
| 15 | 4 | 317,695 | 282,042 | 61,183 | 61,153 | 1 | 61,337.000 | -154.000 |
| 31 | 5 | 378,878 | 343,195 | 61,183 | 61,153 | 1 | 61,337.000 | -154.000 |
| 63 | 6 | 440,062 | 404,349 | 61,184 | 61,154 | 1 | 61,337.000 | -153.000 |
| 127 | 7 | 501,245 | 465,502 | 61,183 | 61,153 | 1 | 61,337.000 | -154.000 |
| 255 | 8 | 562,428 | 526,655 | 61,183 | 61,153 | 1 | 61,337.000 | -154.000 |

Measured cost of one `PoseidonT3.hash` delegatecall (G5, warm): 61,337.000 gas (78,437 on the first, cold call). External-call floor (G4): 101.000 gas. Root mirror only (G2, steady state): 6,511.000 gas. B3 surrounding logic without tree work (G3a): 35,772.000 gas; with the tree's size/leaf bookkeeping (G3b): 62,924.000 gas (difference 27,152.000). Residual of G0 − (G1 + G3a): median -119.000 gas, worst 215.000 gas (0.135% of G0). Identical across seeds: True. Reproduction checks: {"2026091601": {"final_tree_size": 256, "offchain_group_root_matches": true, "leanimt_bench_root_matches_pool": true, "leanimt_bench_size": 256, "frozen_call_gas_limit": 160000}, "2026091602": {"final_tree_size": 256, "offchain_group_root_matches": true, "leanimt_bench_root_matches_pool": true, "leanimt_bench_size": 256, "frozen_call_gas_limit": 160000}}.

### G3. Frozen-parameter feasibility (Section 20)

| tree size | frozen callGasLimit | frozen: included | execution success | commitment inserted | failure class | grant consumed | sponsor charged (wei) | minimal sufficient callGasLimit | frozen margin (gas) | actualGasUsed at minimal limit |
|---|---|---|---|---|---|---|---|---|---|---|
| 0 | 160,000 | True | True | True | None | True | 784,332,000,000,000 | 130,077 | 29,923 | 392,178 |
| 1 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 181,005 | -21,005 | 441,633 |
| 2 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 168,700 | -8,700 | 429,702 |
| 4 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 174,168 | -14,168 | 434,871 |
| 8 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 179,296 | -19,296 | 440,040 |
| 16 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 184,765 | -24,765 | 445,209 |
| 32 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 190,234 | -30,234 | 450,378 |
| 64 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 195,360 | -35,360 | 455,547 |
| 128 | 160,000 | True | False | False | EXECUTION_REVERT_OUT_OF_GAS | True | 843,294,000,000,000 | 200,829 | -40,829 | 460,716 |
| 255 | 160,000 | True | False | False | EXECUTION_REVERT_EXECUTION_REVERTED | True | 841,716,000,000,000 | 584,667 | -424,667 | 832,843 |

### G4. Gas-price / budget envelope (Section 23)

| tree size | limit kind | callGasLimit | Σ gas limits | max feasible gas price (gwei) | analytic p_max = 0.005 ETH / Σ (gwei) | nominal cap (gwei) | nominal cap reachable | refusal |
|---|---|---|---|---|---|---|---|---|
| 0 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 0 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 0 | min_required | 130,077 | 538,145 | 9.000 | 9.291 | 10.000 | False | MaxCostExceeded |
| 1 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 1 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 1 | min_required | 181,005 | 589,073 | 8.000 | 8.488 | 10.000 | False | MaxCostExceeded |
| 2 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 2 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 2 | min_required | 168,700 | 576,768 | 8.000 | 8.669 | 10.000 | False | MaxCostExceeded |
| 4 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 4 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 4 | min_required | 174,168 | 582,236 | 8.000 | 8.588 | 10.000 | False | MaxCostExceeded |
| 8 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 8 | high | 1,500,000 | 1,908,056 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 8 | min_required | 179,296 | 587,364 | 8.000 | 8.513 | 10.000 | False | MaxCostExceeded |
| 16 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 16 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 16 | min_required | 184,765 | 592,833 | 8.000 | 8.434 | 10.000 | False | MaxCostExceeded |
| 32 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 32 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 32 | min_required | 190,234 | 598,302 | 8.000 | 8.357 | 10.000 | False | MaxCostExceeded |
| 64 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 64 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 64 | min_required | 195,360 | 603,428 | 8.000 | 8.286 | 10.000 | False | MaxCostExceeded |
| 128 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 128 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 128 | min_required | 200,829 | 608,897 | 8.000 | 8.212 | 10.000 | False | MaxCostExceeded |
| 255 | frozen | 160,000 | 568,056 | 8.000 | 8.802 | 10.000 | False | MaxCostExceeded |
| 255 | high | 1,500,000 | 1,908,068 | 2.000 | 2.620 | 10.000 | False | MaxCostExceeded |
| 255 | min_required | 584,667 | 992,735 | 4.000 | 5.037 | 10.000 | False | MaxCostExceeded |

### G5. Failed-Bootstrap state transition (Section 21)

| starved callGasLimit | failure class | validation passed | bundle included | execution success | grant before → after | pool eligible after | hasDeposited after | Paymaster deposit before → after (wei) | sponsor loss (wei) | nonce before → after | account code before → after (bytes) | tree size before → after | root changed | sponsored retry | grant permanently consumed | self-funded UserOp included | self-funded cost (wei) | credit recoverable without external funding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 160,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,098,940,872,000,000,000 → 20,098,097,578,000,000,000 | 843,294,000,000,000 | 0 → 1 | 0 → 130 | 1 → 1 | False | AA34 signature error | True | True | 821,710,000,000,000 | True |
| 100,000 | EXECUTION_REVERT_EXECUTION_REVERTED | True | True | False | False → True | True | False | 20,098,097,578,000,000,000 → 20,097,371,960,000,000,000 | 725,618,000,000,000 | 0 → 1 | 0 → 130 | 2 → 2 | False | AA34 signature error | True | True | 800,234,000,000,000 | True |
| 40,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,097,371,960,000,000,000 → 20,096,761,224,000,000,000 | 610,736,000,000,000 | 0 → 1 | 0 → 130 | 3 → 3 | False | AA34 signature error | True | True | 865,110,000,000,000 | True |
| 160,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,098,940,896,000,000,000 → 20,098,097,626,000,000,000 | 843,270,000,000,000 | 0 → 1 | 0 → 130 | 1 → 1 | False | AA34 signature error | True | True | 821,710,000,000,000 | True |
| 100,000 | EXECUTION_REVERT_EXECUTION_REVERTED | True | True | False | False → True | True | False | 20,098,097,626,000,000,000 → 20,097,372,032,000,000,000 | 725,594,000,000,000 | 0 → 1 | 0 → 130 | 2 → 2 | False | AA34 signature error | True | True | 800,234,000,000,000 | True |
| 40,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,097,372,032,000,000,000 → 20,096,761,320,000,000,000 | 610,712,000,000,000 | 0 → 1 | 0 → 130 | 3 → 3 | False | AA34 signature error | True | True | 865,110,000,000,000 | True |
| 160,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,098,940,872,000,000,000 → 20,098,097,578,000,000,000 | 843,294,000,000,000 | 0 → 1 | 0 → 130 | 1 → 1 | False | AA34 signature error | True | True | 821,710,000,000,000 | True |
| 100,000 | EXECUTION_REVERT_EXECUTION_REVERTED | True | True | False | False → True | True | False | 20,098,097,578,000,000,000 → 20,097,371,960,000,000,000 | 725,618,000,000,000 | 0 → 1 | 0 → 130 | 2 → 2 | False | AA34 signature error | True | True | 800,234,000,000,000 | True |
| 40,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,097,371,960,000,000,000 → 20,096,761,224,000,000,000 | 610,736,000,000,000 | 0 → 1 | 0 → 130 | 3 → 3 | False | AA34 signature error | True | True | 865,110,000,000,000 | True |
| 160,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,098,940,872,000,000,000 → 20,098,097,578,000,000,000 | 843,294,000,000,000 | 0 → 1 | 0 → 130 | 1 → 1 | False | AA34 signature error | True | True | 821,710,000,000,000 | True |
| 100,000 | EXECUTION_REVERT_EXECUTION_REVERTED | True | True | False | False → True | True | False | 20,098,097,578,000,000,000 → 20,097,371,984,000,000,000 | 725,594,000,000,000 | 0 → 1 | 0 → 130 | 2 → 2 | False | AA34 signature error | True | True | 800,210,000,000,000 | True |
| 40,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,097,371,984,000,000,000 → 20,096,761,272,000,000,000 | 610,712,000,000,000 | 0 → 1 | 0 → 130 | 3 → 3 | False | AA34 signature error | True | True | 865,086,000,000,000 | True |
| 160,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,098,940,872,000,000,000 → 20,098,097,578,000,000,000 | 843,294,000,000,000 | 0 → 1 | 0 → 130 | 1 → 1 | False | AA34 signature error | True | True | 821,710,000,000,000 | True |
| 100,000 | EXECUTION_REVERT_EXECUTION_REVERTED | True | True | False | False → True | True | False | 20,098,097,578,000,000,000 → 20,097,371,984,000,000,000 | 725,594,000,000,000 | 0 → 1 | 0 → 130 | 2 → 2 | False | AA34 signature error | True | True | 800,210,000,000,000 | True |
| 40,000 | EXECUTION_REVERT_OUT_OF_GAS | True | True | False | False → True | True | False | 20,097,371,984,000,000,000 → 20,096,761,248,000,000,000 | 610,736,000,000,000 | 0 → 1 | 0 → 130 | 3 → 3 | False | AA34 signature error | True | True | 865,110,000,000,000 | True |

### G6. Bundler-side detection before inclusion (Section 22)

| seed | callGasLimit | is frozen value | validation-only eth_call handleOps | debug_traceCall sees OOG | eth_estimateGas(deposit) | estimate > callGasLimit | on-chain UserOp success | actualGasUsed | grant consumed |
|---|---|---|---|---|---|---|---|---|---|
| 2,026,091,601 | 160,000 | True | accepted | True | 192,794 | True | False | 421,647 | True |
| 2,026,091,601 | 100,000 | False | accepted | True | 192,782 | True | False | 362,984 | True |
| 2,026,091,601 | 40,000 | False | accepted | True | 192,782 | True | False | 305,356 | True |
| 2,026,091,601 | 1,500,000 | False | accepted | False | 192,794 | False | True | 574,074 | True |
| 2,026,091,602 | 160,000 | True | accepted | True | 192,794 | True | False | 421,635 | True |
| 2,026,091,602 | 100,000 | False | accepted | True | 192,782 | True | False | 362,972 | True |
| 2,026,091,602 | 40,000 | False | accepted | True | 192,794 | True | False | 305,356 | True |
| 2,026,091,602 | 1,500,000 | False | accepted | False | 192,794 | False | True | 574,050 | True |

### Figures

- `figures/d2-killcondition/20260916T055452Z/stale_probability_vs_lambdaT_by_K.png` (`.svg`)
- `figures/d2-killcondition/20260916T055452Z/analytic_vs_measured_by_K.png` (`.svg`)
- `figures/d2-killcondition/20260916T055452Z/failure_rate_vs_history_size.png` (`.svg`)
- `figures/d2-killcondition/20260916T055452Z/overhead_vs_history_size.png` (`.svg`)
- `figures/d2-killcondition/20260916T055452Z/gas_decomposition_vs_tree_size.png` (`.svg`)
- `figures/d2-killcondition/20260916T055452Z/deposit_gas_vs_poseidon_calls.png` (`.svg`)
- `figures/d2-killcondition/20260916T055452Z/frozen_feasibility_envelope.png` (`.svg`)
- `figures/d2-killcondition/20260916T055452Z/failed_bootstrap_state_transition.png` (`.svg`)
<!-- END GENERATED: d2k tables -->
