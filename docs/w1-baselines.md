# W1 matched baselines B0, B1, B2

Status: **implemented and measured on a local devnet (2026-09-14).** One real
representative W1 run per baseline has been executed and recorded. No privacy
result is claimed anywhere in this document; it describes the baselines, their
costs, and what the first real runs taught us about the recorder.

- Contracts and Foundry tests: `baselines/w1_b0_b2/`
- Live runner, accounting, recording: `experiments/workloads/w1/`
- Matched parameters (single source of truth): `baselines/w1_b0_b2/w1-config.json`
- Run: `make run-matched-baselines SEED=<seed>`; test: `make baselines-test`

## 1. Workload W1 and what is held constant

1. The asset sender transfers 100 W1T (100 × 10^18 base units) of one ERC-20 to
   a fresh recipient-controlled account.
2. The recipient transfers the same 100 W1T to one fixed destination with
   `ERC20.transfer(destination, amount)`.

The three baselines differ only in account type and gas funding. Held constant
(each asserted by a test, see §9):

| Control | Value |
|---|---|
| Chain | anvil 1.4.1, chain id 31337, hardfork `prague`, EIP-170 enforced, automine |
| Setup phase | byte-identical transaction sequence in every baseline → identical contract addresses |
| ERC-20 | `W1Token` (plain OpenZeppelin 5.6.1 ERC20), same address |
| Amount / destination | 100 W1T / one seed-derived address |
| Application call | byte-identical `transfer(destination, amount)` calldata (B1/B2 wrap it in `SimpleAccount.execute(token, 0, call)`) |
| Fee policy | base fee pinned to 1 gwei every block; `maxPriorityFeePerGas` 1 gwei; `maxFeePerGas` 2 gwei → effective price 2 gwei for every transaction and every UserOperation |
| EntryPoint (B1/B2) | eth-infinitism `EntryPoint` v0.9.0, one deployment |
| Account code (B1/B2) | eth-infinitism `SimpleAccount` v0.9.0 via `SimpleAccountFactory`, same proxy and implementation code hash |
| UserOp limits (B1/B2) | verification 300,000; call 60,000; preVerification 50,000 (B2 adds paymaster verification 60,000, postOp 0) |
| Bundler (B1/B2) | the same in-repo instrumented bundler (§5) |
| Keys | derived from (seed, role) only — same sender, recipient key, destination, bundler for a given seed |
| Seed | secret; stored only in the private manifest |

## 2. B0 — sender-funded fresh EOA

| Step | Signer | Transaction |
|---|---|---|
| w1 | asset sender | `W1Token.transfer(freshEOA, 100 W1T)` |
| w2 | asset sender | send `65,000 × 2 gwei = 130,000 gwei` to the fresh EOA (exactly the action's max fee) |
| w3 | fresh EOA | `W1Token.transfer(destination, 100 W1T)`, gas limit 65,000 |

No contract account, EntryPoint, bundler or Paymaster is involved. The fresh
EOA's key is derived from the seed and never funded by anyone else.

## 3. B1 — sender-funded ERC-4337 smart account (no Paymaster)

| Step | Signer | Transaction |
|---|---|---|
| w1 | asset sender | `W1Token.transfer(account, 100 W1T)` to the **counterfactual** `SimpleAccountFactory.getAddress(owner, 0)` |
| w2 | asset sender | send exactly the EntryPoint required prefund `(300,000 + 60,000 + 50,000) × 2 gwei = 820,000 gwei` to the account address |
| w3 | bundler EOA | `EntryPoint.handleOps([op], beneficiary)` |

The UserOperation: `sender` = counterfactual account, `initCode` =
`factory ‖ createAccount(owner, 0)`, `callData` =
`execute(token, 0, transfer(destination, amount))`, empty `paymasterAndData`,
signature = owner's ECDSA signature over the hash returned by the deployed
EntryPoint's own `getUserOpHash` (v0.9.0 EIP-712 domain; no hash or domain is
constructed in this repository).

Gas is paid by the standard non-Paymaster mechanism: during validation the
account forwards `missingAccountFunds` from its ETH balance to the EntryPoint
(`Deposited` event); after execution the EntryPoint pays `actualGasCost` to the
beneficiary and credits the unused prefund to the **account's EntryPoint
deposit**, not its ETH balance.

## 4. B2 — ordinary observable Paymaster

| Step | Signer | Transaction |
|---|---|---|
| w1 | asset sender | `W1Token.transfer(account, 100 W1T)` (same counterfactual account as B1) |
| w2 | sponsor operator | `ObservablePaymaster.setSponsored(account, true)` |
| w3 | bundler EOA | `EntryPoint.handleOps([op], beneficiary)` |

The UserOperation is identical to B1's except `paymasterAndData =
paymaster ‖ uint128(60,000) ‖ uint128(0)`. The recipient account holds **zero
native ETH and zero EntryPoint deposit** before and after.

**Paymaster authorization rule** (`baselines/w1_b0_b2/src/ObservablePaymaster.sol`),
complete:

> sponsor ⇔ `sponsored[userOp.sender] == true`, where `sponsored` is a public
> mapping written only by the owner through `setSponsored`, which emits
> `SponsorshipSet(account, flag)`.

No signatures, credentials, proofs, credits, hidden state, callData/target
restriction, rate limit or postOp. Unauthorized senders make validation revert
(`SenderNotSponsored`), surfaced by the EntryPoint as `AA33 reverted`. The
contract extends the unmodified v0.9.0 `BasePaymaster`; the sponsor operator
pre-funds its EntryPoint deposit (0.1 ETH) in the setup phase.

Why an allowlist rather than a signature-verifying Paymaster: a verifying
Paymaster requires designing a sponsor-signature domain (chain, EntryPoint,
Paymaster, UserOperation binding), which `docs/research-plan.md` §18 reserves
for human review. The allowlist has no such domain. It has a consequence that
matters for later D1 work and is recorded, not hidden: the sponsor operator
publicly names the sponsored account on chain before the operation
(§10 item 4; the choice is an open question in `docs/decision-log.md`).

## 5. The in-repo instrumented bundler (B1 and B2)

`experiments/workloads/w1/bundler.py`, bundler id `privgas-minibundler-v1`:
receive (wall-clock timestamp; hash from `getUserOpHash`) → simulate
(`eth_call handleOps([op], beneficiary)` from the bundler EOA against the
pending block; a revert is decoded and the op rejected) → sign the bundle
transaction and compute its hash **before** broadcasting (the pre-inclusion
association, A2) → broadcast → observe inclusion.

Not implemented, so not covered by any B1/B2 result: ERC-7562 tracing,
reputation/staking policy, a public alt-mempool (hence no A1 data), multi-op
bundles, fee replacement, calldata-based preVerificationGas estimation.

## 6. REAL W1 cost reconciliation

Representative runs `20260914T122736Z-b0/-b1/-b2`. All values in **gwei**
(1 gwei = 10^9 wei; raw wei values in
`data/private/baselines/b*-w1/<run>/w1_cost_reconciliation.json`). Start = last
setup block, end = last workflow block. Effective gas price is 2 gwei
everywhere (1 gwei burned, 1 gwei priority).

| Quantity | B0 | B1 | B2 |
|---|---:|---:|---:|
| Sender ETH start → end | 1,000,000,000 → 999,725,496 | 1,000,000,000 → 999,035,496 | 1,000,000,000 → 999,897,496 |
| Recipient ETH start → end | 0 → 37,096 | 0 → 0 | 0 → 0 |
| Recipient EntryPoint deposit start → end | 0 → 0 (unused) | 0 → 227,964 | 0 → 0 |
| Paymaster EntryPoint deposit start → end | not used | not used | 100,000,000 → 99,444,448 |
| Sponsor operator ETH Δ | — | — | −95,852 |
| Bundler EOA Δ / beneficiary Δ | — | −627,662 / +592,036 | −592,242 / +555,552 |
| ETH transferred directly to recipient | 130,000 | 820,000 | 0 |
| Action gas used | 46,452 (tx receipt) | 296,018 (UserOp) | 277,776 (UserOp) |
| Bundle transaction gas used | — | 313,831 | 296,121 |
| Other workflow tx gas used | w1 51,252; w2 21,000 | w1 51,252; w2 21,000 | w1 51,252; w2 (allowlist) 47,926 |
| Action gas charge | 92,904 | 592,036 | 555,552 |
| Action charge paid from | recipient EOA balance | recipient's EntryPoint prefund | Paymaster deposit |
| Unused recipient ETH | 37,096 (EOA balance) | 227,964 (EntryPoint deposit) | 0 |
| **Sender cost** | 274,504 | 964,504 | 102,504 |
| **Recipient cost from own funds** | 0 | 0 | 0 |
| **Sponsor cost** | 0 | 0 | 651,404 (555,552 deposit + 95,852 allowlist tx) |
| Bundler net (bundler + beneficiary) | — | −35,626 | −36,690 |
| **Total workflow ETH expenditure** (Σ tx fees) | 237,408 | 772,166 | 790,598 |
| of which burned / to block producer | 118,704 / 118,704 | 386,083 / 386,083 | 395,299 / 395,299 |
| Reconciliation checks passed | 12 / 12 | 18 / 18 | 20 / 20 |

Identities asserted on every run (`experiments/workloads/w1/accounting.py`;
any failure raises): Σ of all tracked ETH balance deltas = −burned base fee;
block-producer Δ = priority fees; EntryPoint ETH Δ = Σ deposit Δ; token moves
exactly `amount` from sender to destination; recipient starts with zero ETH,
zero deposit, zero tokens; UserOp `actualGasCost = actualGasUsed ×
min(maxFee, priority + basefee)`; bundler Δ = −bundle fee; beneficiary Δ =
`actualGasCost`; and per baseline — B0: sender Δ = −(fees + allowance),
recipient end = allowance − action fee; B1: sender Δ = −(fees + allowance),
account ETH + deposit = allowance − `actualGasCost`, Paymaster deposit
unchanged; B2: sender Δ = −w1 fee, sponsor Δ = −allowlist fee, Paymaster
deposit Δ = −`actualGasCost`, recipient ETH and deposit stay 0.

Reading the table (descriptive only): "unused" ETH is an artefact of fixed
limits in both B0 (65,000 limit vs 46,452 used) and B1 (verification limit);
B1's is locked in the EntryPoint deposit rather than an EOA balance; B2's
total expenditure exceeds B1's because the allowlist transaction (47,926 gas)
costs more than an ETH transfer (21,000). The in-repo bundler loses ETH on
every operation because the fixed preVerificationGas (50,000) does not cover
the bundle transaction's overhead over the UserOperation's own accounting.

## 7. Real records vs. the Prompt-3 synthetic fixtures

The synthetic fixtures (schema 1.0.0) were written before any baseline existed.
A structured comparison against the real 2.0.0 records (preserved 1.0.0 copies
were diffed before regeneration) found these assumptions to be wrong:

| # | Synthetic assumption | Real behaviour | Resolution |
|---|---|---|---|
| 1 | Mined `user_operation_event` rows are tier **A1**; the ERC-4337 fields are A1 fields | Every field of an included UserOperation is in the mined `handleOps` calldata and EntryPoint logs → **A0** (`research-plan.md` §7 lists on-chain UserOperations under A0) | Tier annotations and fixtures corrected (2.0.0) |
| 2 | `bundle_transaction_hash` is bundler-private | The mined bundle hash is public; the A2 knowledge is the pre-inclusion association | Field replaced by `submitted_bundle_transaction_hash` + `bundle_submission_timestamp_utc` (2.0.0) |
| 3 | B2 emits a per-operation `paymaster_event` "paymaster_deposit" row equal to the charge | EntryPoint v0.9.0 emits **no log** when it debits or refunds a deposit | Row removed; the movement is derivable from `actual_gas_cost` |
| 4 | A privately rejected B2 operation appears in `public_events` as `not_included` | The op went to a private bundler with no public mempool; no A0/A1 observer saw it | Public row removed; §3.5 of the schema doc corrected |
| 5 | B2 rejection `fee_too_low` followed by a fee replacement | The in-repo bundler has no fee policy or replacement; real rejections are `AA33` (unauthorized), `AA21` (insufficient prefund), `AA26` (verification limit) | Fixture uses a Paymaster rejection; new category `paymaster_validation_revert` |
| 6 | An AA action is two rows: UserOperationEvent + Transfer | Also the bundle transaction itself (its receipt gas differs from the UserOp's: 313,831 vs 296,018 in B1), `AccountDeployed` (first op deploys the account), B1's `Deposited` (prefund), B2's `SponsorshipSet` naming the account | Rows added; event type `entrypoint_deposit`, calldata classes `entrypoint_handle_ops`/`paymaster_policy`, field `subject_account` added |
| 7 | UserOperationEvent row precedes the Transfer row | Log order is AccountDeployed, (Deposited), Transfer, UserOperationEvent | Rows follow log order |
| 8 | Addresses in any case (fixture EntryPoint address checksummed) | RPC fields lowercase, decoded logs checksummed → the same account compared unequal | Lowercase address rule (2.0.0) |
| 9 | Fixture EntryPoint `0x0000000071727De2…` labelled `0.9.0` | That is the canonical **v0.7** EntryPoint address; the real one is deployed from v0.9.0 source | Placeholder replaced |
| 10 | Timestamps are whole seconds | Bundler timestamps carry microseconds; the validator rejected every fractional timestamp its own regex allowed | Validator bug fixed + regression test |
| 11 | B2 postOp limit 40,000, pm verification 80,000 | `ObservablePaymaster` has no postOp (0); 60,000 verification | Fixture aligned |
| 12 | B1 receives the same ETH top-up as B0 | B1 must supply the full required prefund (820,000 gwei vs B0's 130,000) | Recorded in cost table |
| 13 | B1 and B2 charge the same UserOp gas (268,000) | B2 is 18,242 gas cheaper than B1 (paymaster deposit debit vs account prefund transfer) | Recorded (fixture numbers remain fabricated) |
| 14 | `account_implementation.version: "fixture"` | Named implementation with source commit and bytecode digests; manifests also need bundler, fee policy, chain environment | Real manifests carry these |

Assumptions that **held**: the per-baseline capability flags (B0 no
ERC-4337/bundler/Paymaster; B1 ERC-4337 + bundler, null Paymaster; B2 public
Paymaster; none with credits or privacy artefacts); no `observer_a2/` directory
for B0; one A2 row per accepted operation; R2 `not_applicable` for B0–B2;
B2's `funding_address` anchor is the Paymaster.

## 8. Recorder and schema changes (2.0.0)

MAJOR: `bundler_private.bundle_transaction_hash` → `submitted_bundle_transaction_hash`
+ `bundle_submission_timestamp_utc`, with a rule that a rejected op carries
neither; address rule narrowed to lowercase; ERC-4337 field tier annotations
A1 → A0. Additive: `public_events.subject_account`; event type
`entrypoint_deposit`; calldata classes `entrypoint_handle_ops`,
`paymaster_policy`; rejection category `paymaster_validation_revert`. Fix:
fractional-second timestamps. Adapter: addresses canonicalised to lowercase;
`BundlerObservation`/`Observation` fields follow the schema. Capability table:
B0–B2 `implemented_in_repo=True`, flags unchanged. Doc: §3.5 (not_included
rows only when publicly observed), §6 row structure, §7 mined hashes public,
§8.2 boundary. Full list: `docs/experiment-schema.md` §9.0.

## 9. Tests

- Foundry (`baselines/w1_b0_b2/test`, 16 tests): contract semantics only — B1
  success/`AA21`/`AA24`, B2 sponsored success with zero ETH, `AA33` for
  unauthorized and revoked senders, deposit decrease = `actualGasCost`,
  owner-only allowlist, same factory/implementation/proxy code for B1/B2, same
  application calldata. Forge uses `vm.prank`; **no cost figure comes from
  Forge**.
- Live (`experiments/workloads/w1/tests`, 28 tests, real signed transactions on
  anvil): B0 success, node-rejected insufficient ETH, retained-ETH accounting,
  tampered-balance detection; B1 success, `AA21` simulation rejection, same
  semantics as B2; B2 sponsored success with zero native ETH, deposit decrease,
  `AA33` rejection, same account implementation as B1; shared token / amount /
  destination / byte-identical action, same fee policy, seed determinism, no
  unused-gas penalty; recording (measured origin, no fake UserOp for B0, A2
  separation, B2 public Paymaster, byte-identical regeneration from raw,
  rejected op A2-only, leakage self-check clean); dependency pin.

## 10. Fairness differences that remain

1. **Account deployment is inside the B1/B2 action.** The first UserOperation
   deploys the account via `initCode`; B0 deploys nothing.
2. **Bundler overhead is under-compensated.** Fixed preVerificationGas 50,000;
   the bundle transaction uses ~17.8k (B1) / ~18.3k (B2) more gas than the
   UserOperation is charged, so a production bundler would charge more.
3. **Validation work differs under identical limits.** B1 validation pays the
   prefund into the EntryPoint (needs 200k–250k gas); B2 validation calls the
   Paymaster instead (fits within 200k).
4. **B2's authorization needs an extra public per-account transaction** by a
   different signer (47,926 gas). A signature-based Paymaster would trade this
   for off-chain signing plus on-chain verification gas.
5. **Unused ETH is a limit artefact with different liquidity**: B0's stays in
   the EOA; B1's is locked in the EntryPoint deposit (withdrawable only by an
   owner-authorized call); B2 has none.
6. **Fee environment is idealised**: pinned base fee, constant priority fee,
   bundler tx price equal to UserOp price, no L1 data fee, no congestion.
7. **No ERC-7562 enforcement or staking.** `ObservablePaymaster` reads its own
   storage during validation; whether a production mempool would require it to
   stake was not checked.
8. **No public mempool** for B1/B2 (so no A1 observations), single-op bundles,
   no replacement.
9. **Environment contracts exist in every chain**: B0/B1 chains also contain a
   deployed, funded (unused) Paymaster because setup is identical.
10. **Fixed gas limits, not estimates**: B0 65,000 (~40% margin); B1/B2
    verification 300,000, call 60,000 (calibrated before any reported result; `docs/decision-log.md`).
11. **One scenario per run**: candidate sets have size one; no timing, actor
    or order randomisation yet.

## 11. Adversary tiers and trust assumptions (per `docs/threat-model.md`)

B0: A0 only (no bundler exists). B1/B2: A0 from chain data; A2 from the in-repo
bundler's log; **no A1 data exists** (no public mempool). Assumed honest for
these runs: the local node, the in-repo bundler (it logs truthfully and does
not censor), and the sponsor operator (B2). A3 is out of scope.

## 12. Provenance

EntryPoint, SimpleAccount, SimpleAccountFactory and BasePaymaster are compiled
unmodified from `baselines/b3_privgas_v1/lib/account-abstraction/contracts` —
byte-identical to eth-infinitism/account-abstraction commit
`b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` (tag `v0.9.0`,
`docs/b3-reproduction.md`) — with B3's compiler settings (solc 0.8.28, via-IR,
200 runs). The tree digests are pinned in `baselines/w1_b0_b2/dependency-pin.json`
and checked by a test. Nothing under `baselines/b3_privgas_v1` was modified.
Every manifest records deployed-bytecode sha256 digests, anvil version and
flags, Python dependency versions and `scripts/env-report.sh` output.
