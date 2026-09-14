# W1 matched baselines: B0, B1, B2-Allowlist, B2-Signature

Status: **implemented, hardened and measured on a local devnet (2026-09-14,
pre-Prompt-4).** Schema 3.0.0. No privacy result is claimed anywhere in this
document; it defines the baselines, their costs and their remaining
differences.

- Contracts and Foundry tests: `baselines/w1_b0_b2/`
- Live runner, bundler, calibration, accounting, recording, comparison:
  `experiments/workloads/w1/`
- Matched parameters (single source of truth): `baselines/w1_b0_b2/w1-config.json`
- Run: `make run-matched-baselines SEED=<seed>`; test: `make baselines-test`

## 1. Baselines and workloads

| Baseline | Recipient account | Gas funding | Role |
|---|---|---|---|
| **B0** | fresh EOA | asset sender sends ETH for the action transaction | primary |
| **B1** | eth-infinitism `SimpleAccount` v0.9.0 | asset sender sends the EntryPoint required prefund | primary |
| **B2-Signature** | same as B1 | `SignatureVerifyingPaymaster`: sponsor ECDSA signature over the EntryPoint `userOpHash`, carried in `paymasterAndData`; no on-chain authorization transaction | **primary ordinary-Paymaster baseline** |
| **B2-Allowlist** | same as B1 | `ObservablePaymaster`: owner-managed public allowlist, `setSponsored(account, true)` before the operation | **auxiliary** |

B2-Allowlist's `setSponsored(account, true)` transaction creates an explicit,
public sponsor→account relationship on chain **before** the UserOperation. It
may therefore produce stronger linkage than other ordinary Paymaster designs.
It is kept as an intentionally public on-chain authorization baseline and
**must not be the sole public-Paymaster baseline for any later privacy
claim.** The two B2 designs have distinct `baseline_id`s and are never pooled.

| Workload | Meaning | Applies to |
|---|---|---|
| **W1-cold** (primary) | the recipient account is fresh; for AA baselines the counterfactual `SimpleAccount` is not deployed and the measured UserOperation deploys it via `initCode` | B0, B1, B2-Allowlist, B2-Signature |
| **W1-warm** (ablation) | the same `SimpleAccount` is deployed by an earlier warm-up UserOperation; the measured operation has no `initCode`; warm-up cost is excluded from the measured action and reported separately | B1 (B2 warm variants not implemented: optional, no new semantics) |

W1-warm exists only to separate first-use deployment overhead from recurring
execution overhead. B0 is unchanged (an EOA has nothing to pre-deploy; the
schema rejects `W1-warm` for non-AA baselines). For later privacy analysis:
deployment/account information belongs to the ordinary trace **T**;
Paymaster/gas-specific information belongs to **G**. That analysis is not
implemented.

## 2. What is held constant

Asserted by `compare.fairness_checks` (20 checks, all passing on the recorded
runs) and by the Foundry/live tests:

| Control | Value |
|---|---|
| Chain | anvil 1.4.1, chain id 31337, hardfork `prague`, EIP-170 enforced, automine |
| Setup | identical transaction sequence in every variant (both Paymasters deployed and funded everywhere; beneficiary pre-funded) → identical contract addresses |
| EntryPoint | eth-infinitism `EntryPoint`, commit `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` (tag `v0.9.0`), one deployment, same bytecode |
| Account | `SimpleAccount` v0.9.0 via `SimpleAccountFactory`, same implementation address and bytecode, same counterfactual account |
| Token / amount / destination | `W1Token` (OZ 5.6.1 ERC20) / 100 W1T / one seed-derived address, all baselines |
| Application call | byte-identical `transfer(destination, amount)`; B1/B2 wrap it in `SimpleAccount.execute(token, 0, call)` |
| Fee environment | base fee pinned to 1 gwei every block; priority 1 gwei; max fee 2 gwei → effective 2 gwei for every transaction and UserOperation |
| Account gas limits | verification 300,000; call 60,000 (no unused-gas penalty — tested) |
| Paymaster limits (both B2) | verification 60,000; postOp 0 |
| preVerificationGas | **not fixed**: calibrated per operation by one method (§5) |
| Deployment mode | `initCode` present in all W1-cold AA ops; absent in the W1-warm measured op |
| Bundler | the same in-repo instrumented bundler, same beneficiary |
| Keys | derived from (seed, role) only |

## 3. Architectures

**B0.** w1 sender `W1Token.transfer(EOA)`; w2 sender sends `65,000 × 2 gwei`;
w3 EOA `W1Token.transfer(destination)`.

**B1 W1-cold.** w1 token → counterfactual account; bundler calibrates
preVerificationGas; w2 sender sends exactly the EntryPoint required prefund
`(300,000 + 60,000 + PVG) × 2 gwei`; w3 bundler `handleOps([op])`, op =
`initCode` + `execute(...)`, empty `paymasterAndData`. Unused prefund is
credited to the account's EntryPoint deposit.

**B1 W1-warm.** *Warm-up* (excluded): sender funds the deploy-only op's
prefund; bundler includes an op with `initCode` and empty `callData`.
*Workflow*: w1 token; calibration; w2 sender sends the full required prefund
of the measured op (a transfer into the now-deployed proxy, 60,000-gas limit);
w3 op without `initCode`, nonce 1.

**B2-Allowlist W1-cold.** w1 token; w2 sponsor operator
`ObservablePaymaster.setSponsored(account, true)`; calibration; w3 op =
B1's op + `paymasterAndData = paymaster ‖ uint128(60,000) ‖ uint128(0)`.
Rule: sponsor ⇔ `sponsored[userOp.sender] == true`; otherwise validation
reverts (`AA33`).

**B2-Signature W1-cold.** w1 token; calibration; w3 op = B1's op +
`paymasterAndData = paymaster ‖ uint128(60,000) ‖ uint128(0) ‖
abi.encode(uint48 validUntil=0, uint48 validAfter=0) ‖ sponsorSig(65) ‖
uint16(65) ‖ PAYMASTER_SIG_MAGIC`. No sponsor transaction. The sponsor signer
key never transacts; its address is public (`verifyingSigner`, immutable).

## 4. B2-Signature: exactly what is signed, and what it binds

`SignatureVerifyingPaymaster` (`baselines/w1_b0_b2/src/`) is `BasePaymaster`
(unmodified v0.9.0) plus v0.9.0's own Paymaster-signature mechanism. **The
pinned tree contains no `VerifyingPaymaster` sample.** The construction reuses
only what the pinned tree defines: `UserOperationLib.getSignedPaymasterData`,
`getPaymasterSignature` and `encodePaymasterSignature` (exercised upstream by
`contracts/test/TestPaymasterWithSig.sol` with a toy check),
`_packValidationData`, and the same raw-digest ECDSA verification
`SimpleAccount` uses. No new message format or domain was designed.

**Signed message.** The 32-byte `userOpHash` passed by the EntryPoint to
`validatePaymasterUserOp`, i.e. `EntryPoint.getUserOpHash(userOp)`:

```
userOpHash = keccak256(0x19 0x01 ‖ domainSeparator ‖ structHash)
domainSeparator = EIP-712 {name: "ERC4337", version: "1",
                           chainId: block.chainid, verifyingContract: EntryPoint}
structHash = keccak256(abi.encode(
    PACKED_USEROP_TYPEHASH, sender, nonce, keccak256(initCode), keccak256(callData),
    accountGasLimits, preVerificationGas, gasFees,
    paymasterDataKeccak(paymasterAndData)))
paymasterDataKeccak(p) = keccak256(p[0 : len − sigLen − 10] ‖ PAYMASTER_SIG_MAGIC)
                         when the magic suffix is present
```

The sponsor signs the digest directly (no EIP-191 prefix); the Paymaster
recovers with OpenZeppelin `ECDSA.tryRecover` and compares with the immutable
`verifyingSigner`.

| Question | Answer |
|---|---|
| Chain id bound? | Yes — EIP-712 domain (test: signature made under chain id 31338 → `AA34`) |
| EntryPoint bound? | Yes — `verifyingContract` in the domain (test: hash from a second EntryPoint → `AA34`); the Paymaster also accepts calls only from its EntryPoint |
| Paymaster bound? | Yes — its address is the first 20 bytes of `paymasterAndData` (test: signature made for a twin Paymaster with the same signer → `AA34`) |
| Sender bound? | Yes (test: authorization of account A attached to account B's op → `AA34`) |
| Nonce bound? | Yes, the full 256-bit key‖sequence (test: reuse on nonce+1 → `AA34`) |
| initCode / callData bound? | Yes (test: amount changed after authorization, account re-signs → `AA34`) |
| Gas fields bound? | Yes: `accountGasLimits`, `preVerificationGas`, `gasFees`, both Paymaster gas limits (test: preVerificationGas+1 → `AA34`) |
| Validity window bound? | Yes: `validUntil`/`validAfter` are signed Paymaster data enforced by the EntryPoint (tests: expired → `AA32`; window changed after signing → `AA34`) |
| Signature bytes bound? | No, by v0.9 design: excluded from the hash, but the suffix's presence is hashed (test: hash equal with placeholder vs real signature; differs without the suffix) |
| Replay prevention | EntryPoint nonce: an included op cannot be included again (`AA25`), and any other nonce changes the hash. The Paymaster keeps no replay state. W1 signs an unbounded window (0/0), so a signed, never-included op stays sponsorable until its nonce is consumed |
| Interaction with v0.9 hashing | Because signature bytes are excluded, sponsor and account sign **the same** `userOpHash`: the runner inserts a 65-byte placeholder, computes the hash, the sponsor signs, then the account signs the same hash |
| Wrong/missing signature | returns `SIG_VALIDATION_FAILED` → EntryPoint `AA34 signature error`; malformed signed data reverts (`AA33`) |
| Human review | still required for this binding (`docs/research-plan.md` §18) |

## 5. preVerificationGas calibration (`break_even_calibration_v1`)

The earlier fixed preVerificationGas (50,000) left the bundler ~17,800 gas
short per operation. Measuring it showed the shortfall was dominated by a
**one-time 25,000-gas new-account charge**: the beneficiary was a fresh empty
address, so the EntryPoint's compensation transfer created it. With that
removed, a fixed 50,000 would have *over*-paid by ~7,000 gas. The beneficiary
is now pre-funded in setup (a production beneficiary already exists), and
preVerificationGas is calibrated per operation
(`experiments/workloads/w1/pvg.py`):

1. Build the op with provisional PVG₀ = 50,000 and real signatures; perform any
   state preparation it needs (B1: the prefund transfer).
2. In an `evm_snapshot`, broadcast the exact `handleOps([op], beneficiary)`
   bundle; read receipt `gasUsed` G₀ and `UserOperationEvent.actualGasUsed`
   A₀; `evm_revert`. Nothing from the dry run survives.
3. Gas the EntryPoint does not charge: `U = G₀ − (A₀ − PVG₀)`, decomposed as
   `U = 21,000 + calldataGas(bundle₀) + O`, where calldataGas is EIP-2028 over
   the exact encoded bytes (4 / 16 gas per zero / non-zero byte) and O is the
   EntryPoint's unmeasured overhead (ABI decoding, loop prologue,
   `BeforeExecution`, `UserOperationEvent`, `_compensate`, net of refunds).
4. Solve `PVG = 21,000 + calldataGas(bundle(PVG)) + O` for the final op,
   re-signing each iteration; iterate monotonically until the value covers its
   own calldata. Surplus is reported.
5. The EIP-7623 (Prague) calldata floor is checked and must not bind.

This is a zero-margin break-even value for this bundler, bundle size 1, this
devnet. Snapshot dry runs are a devnet facility; a production bundler must
estimate instead. The dry run is logged in the raw bundler log as a
`pvg_calibration` event, not as a `bundler_private` row.

**Subsidy assertion.** Reconciliation fails if the bundler's net is worse than
−100 gas × price (`SUBSIDY_TOLERANCE_GAS`); a test re-injects the old ~17.8k
shortfall and confirms it is caught.

| Variant | PVG | = 21,000 | + calldata gas (bytes) | + overhead O | surplus | bundle gas | UserOp gas | **bundler net** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B1 W1-cold | 42,813 | 21,000 | 6,828 (996) | 14,985 | 0 | 288,831 | 288,831 | **0** |
| B1 W1-warm (measured op) | 41,889 | 21,000 | 5,904 (900) | 14,985 | 0 | 114,990 | 114,990 | **0** |
| B1 W1-warm (warm-up op, excluded) | 39,816 | — | — | — | — | 257,649 | 257,649 | 0 |
| B2-Allowlist W1-cold | 43,345 | 21,000 | 7,360 (1,060) | 14,985 | 0 | 271,121 | 271,121 | **0** |
| B2-Signature W1-cold | 44,745 | 21,000 | 8,748 (1,188) | 14,985 | 12 | 276,668 | 276,680 | **+12 gas (+24 gwei)** |

The +12 gas is deterministic rounding: re-signing changed the zero-byte count
of a fresh signature, and the monotone iteration keeps the covering value.
Residuals observed in development runs with other seeds were 0–24 gas, always
in the bundler's favour. O was identical (14,985) for every measured op.

## 6. REAL cost table

Representative runs `20260914T160148Z-*` (seed held privately). All values in
**gwei**; raw wei in `data/private/baselines/<experiment>/<run>/w1_cost_reconciliation.json`;
cross-variant summary in `results/w1-baselines/20260914T160148Z/comparison.json`.
Effective gas price 2 gwei everywhere (1 burned, 1 priority). Balances are
compared from the start of the measured workflow (after warm-up for W1-warm).

| Quantity | B0 | B1 cold | B1 warm | B2-Allowlist cold | B2-Signature cold |
|---|---:|---:|---:|---:|---:|
| Setup gas (identical, excluded) | 7,295,025 | 7,295,025 | 7,295,025 | 7,295,025 | 7,295,025 |
| Warm-up gas / ETH consumed (excluded) | — | — | 278,649 / 557,298 | — | — |
| Asset-transfer tx gas (w1) | 51,252 | 51,252 | 51,252 | 51,252 | 51,252 |
| ETH-allowance tx gas (w2) | 21,000 | 21,000 | 25,868 | — | — |
| ETH sent directly to recipient | 130,000 | 805,626 | 803,778 | 0 | 0 |
| Recipient action gas | 46,452 (tx) | 288,831 (UserOp) | 114,990 (UserOp) | 271,121 (UserOp) | 276,680 (UserOp) |
| of which preVerificationGas | — | 42,813 | 41,889 | 43,345 | 44,745 |
| UserOperation charge | — | 577,662 | 229,980 | 542,242 | 553,360 |
| Paymaster charge (= deposit decrease) | — | 0 | 0 | 542,242 | 553,360 |
| Paymaster deposit start → end | — | — | — | 100,000,000 → 99,457,758 | 100,000,000 → 99,446,640 |
| Account deployment in measured action | no | yes | no | yes | yes |
| Unused recipient ETH | 37,096 (EOA) | 227,964 | 573,798 ¹ | 0 | 0 |
| Remaining recipient EntryPoint deposit | 0 | 227,964 | 573,798 ¹ | 0 | 0 |
| Bundle tx gas | — | 288,831 | 114,990 | 271,121 | 276,668 |
| Bundler reimbursement (beneficiary Δ) | — | 577,662 | 229,980 | 542,242 | 553,360 |
| **Bundler net** | — | **0** | **0** | **0** | **+24** |
| Sponsor authorization cost | — | — | — | 95,852 (`setSponsored`, 47,926 gas) | 0 (off-chain signature) |
| **Sender cost** | 274,504 | 950,130 | 958,018 | 102,504 | 102,504 |
| **Recipient cost (own funds)** | 0 | 0 | 0 | 0 | 0 |
| **Sponsor cost** | 0 | 0 | 0 | 638,094 | 553,360 |
| **Total ETH consumed by workflow** (Σ tx fees) | 237,408 | 722,166 | 384,220 | 740,598 | 655,840 |
| Accounting checks | 13/13 | 22/22 | 23/23 | 22/22 | 22/22 |

¹ B1 warm: the measured workflow starts with the warm-up op's leftover deposit
(284,334). Reported "unused" is the workflow-window delta `allowance − charge`;
the account's end state is 284,334 ETH + 573,798 deposit.

Transferred-but-unspent ETH is never counted as consumed: it appears only as
unused recipient ETH / remaining deposit.

**Derived by difference** (`compare.derived`, with confounds):

- *Account deployment component* (B1 cold − B1 warm): **173,841 gas** of
  UserOperation gas (924 of it preVerificationGas). Confounds: the EntryPoint
  nonce's first write (0→1, zero→non-zero) in cold vs 1→2 in warm; initCode
  calldata; warm's non-empty starting deposit.
- *Signature-authorization overhead* (B2-Signature − B2-Allowlist UserOp gas):
  **5,559 gas** = 1,400 preVerificationGas (128 more encoded calldata bytes)
  + 4,159 validation/execution (ecrecover, decoding; net of the allowlist's
  storage read). B2-Allowlist instead pays a separate 47,926-gas `setSponsored`
  transaction per account.

## 7. Recorder integration (schema 3.0.0)

Measured runs (`data_origin: "measured"`, gitignored):
`data/public/baselines/{b0-w1-cold, b1-w1-cold, b1-w1-warm,
b2-allowlist-w1-cold, b2-signature-w1-cold}/20260914T160148Z-*/`.

| Run | public rows | bundler rows | notes |
|---|---:|---:|---|
| B0 W1-cold | 3 | none (no `observer_a2/`) | no UserOperation fields, no Paymaster |
| B1 W1-cold | 7 | 1 | `paymaster` null on every row |
| B1 W1-warm | 11 | 2 | includes the warm-up rows (on chain, part of T); manifest `components.workload.role` = ablation |
| B2-Allowlist W1-cold | 6 | 1 | `paymaster_event` / `paymaster_policy` row with `subject_account` |
| B2-Signature W1-cold | 5 | 1 | no authorization row; different Paymaster address |

Schema 3.0.0 changes: `baseline_id` `B2` → `B2-Allowlist`, `B2-Signature`;
`workload_id` `W1` → `W1-cold`, `W1-warm` (with a rule rejecting `W1-warm` for
non-AA baselines). Leakage self-check: 0 findings over 9 runs (5 measured, 4
synthetic examples). The schema-2.0.0 measured runs were moved to
`data/private/archive/schema-2.0.0/` (not deleted).

## 8. The in-repo bundler is experimental

`privgas-minibundler-v1` is an **instrumented experimental bundler**. It
simulates with `eth_call handleOps`, enforces no ERC-7562 rules, has no
reputation, staking or public mempool, bundles one op, never replaces, and
calibrates a zero-margin preVerificationGas using devnet snapshots. It **does
not establish ERC-7562 or production compatibility**. A real, independent
compatible bundler is required later for: any D2 liveness claim; any
production-compatibility claim; replication of D1 results under an independent
bundler. Staking requirements (e.g. for `ObservablePaymaster`'s storage read)
were **not tested and are not inferred**. No external bundler has been
integrated.

## 9. Tests

- Foundry (`baselines/w1_b0_b2/test`, 35): B1 success / `AA21` / `AA24`;
  B2-Allowlist success, `AA33`, revocation, owner-only; **B2-Signature (17)**:
  valid authorization with zero ETH and no allowlist, wrong signer, missing
  signature, wrong sender, modified call, modified gas field, replay (`AA25`),
  next-nonce reuse, other EntryPoint domain, other chain id, other Paymaster,
  expired window (`AA32`), window tampering, hash excludes signature bytes but
  not suffix presence, suffix matches upstream `encodePaymasterSignature`,
  no allowlist state, EntryPoint-only validation; matching of B1 / B2-Allowlist
  / B2-Signature ops and account code. No cost figure comes from Forge.
- Live (`experiments/workloads/w1/tests`, 39): all variants' success paths,
  node-rejected B0 underfunding, `AA21`/`AA33`/`AA34` rejections, warm-up
  excluded from cost, deployment component, bundler subsidy within tolerance,
  calibration decomposition equals the mined bytes, subsidy assertion catches
  a re-injected shortfall, no unused-gas penalty, 20 fairness checks,
  byte-identical application call, fee policy, seed determinism, recording
  (distinct baseline ids, warm ablation labelling, A2 separation,
  byte-identical regeneration, rejected op A2-only, leakage self-check),
  dependency pin.

## 10. Remaining fairness differences

1. **Deployment inside the measured cold action** (all AA cold); isolated only
   by the W1-warm ablation, and only by difference.
2. **preVerificationGas differs per variant** (41,889–44,745) because it
   follows each op's calldata; it is calibrated by one method, not held equal.
3. **Validation work differs**: B1 pays the prefund into the EntryPoint;
   B2-Allowlist reads a storage slot; B2-Signature decodes and runs ecrecover.
4. **Authorization differs structurally**: B2-Allowlist needs a public
   per-account transaction by the sponsor operator; B2-Signature needs none but
   carries a larger `paymasterAndData` (128 more encoded calldata bytes); B1
   needs a sender ETH transfer.
5. **Unused ETH is a limit artefact with different liquidity**: B0's stays in
   the EOA; B1's sits in the EntryPoint deposit.
6. **B1 warm's funding transfer costs 25,868 gas** (into a deployed proxy) vs
   21,000 in cold, and starts from a non-zero deposit.
7. **Idealised fee environment and zero-margin bundler**: pinned base fee,
   bundler tx price equal to UserOp price, no profit margin, no L1 data fee.
8. **Experimental bundler** (§8): no ERC-7562, no public mempool (no A1 data),
   single-op bundles, no replacement.
9. **Identical setup includes unused contracts**: every chain has both
   Paymasters deployed and funded.
10. **One scenario per run**; candidate sets of size one; no timing or actor
    randomisation.
11. **B2 warm variants not implemented.**

## 11. Adversary tiers and trust assumptions

B0: A0 only. B1/B2: A0 from chain data, A2 from the in-repo bundler; no A1 data.
Assumed honest: local node, in-repo bundler, sponsor operator and sponsor
signer. A3 out of scope.

## 12. Provenance

EntryPoint, SimpleAccount, SimpleAccountFactory, BasePaymaster and
UserOperationLib come unmodified from
`baselines/b3_privgas_v1/lib/account-abstraction/contracts`, byte-identical to
commit `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` (`docs/b3-reproduction.md`),
compiled with B3's settings; digests pinned in
`baselines/w1_b0_b2/dependency-pin.json`. Nothing under
`baselines/b3_privgas_v1` was modified. Manifests record deployed-bytecode
digests, anvil version and flags, Python dependency versions, calibration
details and `scripts/env-report.sh` output.

## 13. History

The first version of these baselines (schema 2.0.0: a single `B2` allowlist
baseline, fixed preVerificationGas, unfunded beneficiary) and the
synthetic-fixture corrections it forced are recorded in `docs/decision-log.md`
(2026-09-14 entries). Its measured runs are archived, not deleted.

## 14. Schema 2.0.0: synthetic-fixture assumptions corrected by the first real runs

Kept verbatim in substance from the first implementation (the recorder and its
synthetic fixtures predated any real baseline). Numbers in the "real" column
are from those schema-2.0.0 runs (now archived); "B2" there is today's
B2-Allowlist.

| # | Synthetic assumption | Real behaviour | Resolution |
|---|---|---|---|
| 1 | Mined `user_operation_event` rows are tier A1 | Every field of an included UserOperation is in the mined `handleOps` calldata and EntryPoint logs → A0 | Tier annotations and fixtures corrected |
| 2 | `bundle_transaction_hash` is bundler-private | The mined bundle hash is public; the A2 knowledge is the pre-inclusion association | Replaced by `submitted_bundle_transaction_hash` + `bundle_submission_timestamp_utc` |
| 3 | B2 emits a per-operation deposit-decrease `paymaster_event` | EntryPoint v0.9.0 emits no log when it debits or refunds a deposit | Row removed |
| 4 | A privately rejected B2 op appears publicly as `not_included` | Private bundler, no public mempool: no A0/A1 observer saw it | Public row removed; schema §3.5 corrected |
| 5 | B2 rejection `fee_too_low` + replacement | The in-repo bundler has no fee policy or replacement; real rejections are `AA33`, `AA21`, `AA26` (and now `AA34`) | `paymaster_validation_revert` category |
| 6 | An AA action is two rows | Also the bundle transaction, `AccountDeployed`, B1's `Deposited`, B2's `SponsorshipSet` naming the account | Rows, event type, calldata classes and `subject_account` added |
| 7 | UserOperationEvent row precedes Transfer | Log order: AccountDeployed, (Deposited), Transfer, UserOperationEvent | Rows follow log order |
| 8 | Mixed-case addresses accepted | Same account compared unequal across rows | Lowercase address rule |
| 9 | Fixture EntryPoint `0x0000000071727De2…` labelled 0.9.0 | That is the canonical v0.7 address | Placeholder replaced |
| 10 | Whole-second timestamps | Bundler timestamps carry microseconds; the validator rejected them | Validator bug fixed |
| 11 | B2 postOp limit 40,000, pm verification 80,000 | No postOp (0); 60,000 | Fixture aligned |
| 12 | B1 top-up equals B0's | B1 must supply the full required prefund | Cost table |
| 13 | B1 and B2 charge equal UserOp gas | They differ (validation paths differ) | Recorded |
| 14 | `account_implementation.version: "fixture"` | Named implementation with source commit and bytecode digests | Real manifests carry these |

Capability flags held.
