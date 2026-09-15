# W1 matched baselines: B0, B1, B2-Allowlist, B2-Signature

Status: **implemented, hardened and measured on a local devnet (2026-09-14,
final pre-Prompt-4 cleanup; re-recorded under schema 5.0.0 on 2026-09-15 with
identical transactions and costs).** No privacy result is claimed anywhere in
this document; it defines the baselines, their costs and their remaining
differences. The frozen B3 specimen (`B3-PrivGas-v1`) and the evaluation-chain
profiles used to compare it with these baselines are in `docs/b3-evaluation.md`.

- Contracts and Foundry tests: `baselines/w1_b0_b2/`
- Live runner, bundler, calibration, accounting, recording, comparison:
  `experiments/workloads/w1/`
- Matched parameters (single source of truth): `baselines/w1_b0_b2/w1-config.json`
- Calibrate (environment-level, once): `make calibrate-pvg`
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
| Chain | anvil 1.4.1, chain id 31337, hardfork `prague`, automine; profile `eip170_standard` (EIP-170 enforced) or `b3_compat_local` (code-size limit 32,768, B3 contracts in the setup; identical B0–B2 workflow quantities, `docs/b3-evaluation.md` §2) |
| Setup | identical transaction sequence in every variant (both Paymasters deployed and funded everywhere; beneficiary pre-funded) → identical contract addresses |
| EntryPoint | eth-infinitism `EntryPoint`, commit `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` (tag `v0.9.0`), one deployment, same bytecode |
| Account | `SimpleAccount` v0.9.0 via `SimpleAccountFactory`, same implementation address and bytecode, same counterfactual account |
| Token / amount / destination | `W1Token` (OZ 5.6.1 ERC20) / 100 W1T / one seed-derived address, all baselines |
| Application call | byte-identical `transfer(destination, amount)`; B1/B2 wrap it in `SimpleAccount.execute(token, 0, call)` |
| Fee environment | base fee pinned to 1 gwei every block; priority 1 gwei; max fee 2 gwei → effective 2 gwei for every transaction and UserOperation |
| Account gas limits | verification 300,000; call 60,000 (no unused-gas penalty — tested) |
| Paymaster limits (both B2) | verification 60,000; postOp 0 |
| preVerificationGas | **not fixed**: one method for all variants — 21,000 + exact calldata gas + calibrated environment overhead (§5) |
| Deployment mode | `initCode` present in all W1-cold AA ops; absent in the W1-warm measured op |
| Bundler | the same in-repo instrumented bundler, same beneficiary |
| Keys | derived from (seed, role) only |

## 3. Architectures

**B0.** w1 sender `W1Token.transfer(EOA)`; w2 sender sends `65,000 × 2 gwei`;
w3 EOA `W1Token.transfer(destination)`.

**B1 W1-cold.** w1 token → counterfactual account; bundler prices
preVerificationGas (§5); w2 sender sends exactly the EntryPoint required prefund
`(300,000 + 60,000 + PVG) × 2 gwei`; w3 bundler `handleOps([op])`, op =
`initCode` + `execute(...)`, empty `paymasterAndData`. Unused prefund is
credited to the account's EntryPoint deposit.

**B1 W1-warm.** *Warm-up* (excluded): sender funds the deploy-only op's
prefund; bundler includes an op with `initCode` and empty `callData`.
*Workflow*: w1 token; PVG estimate (§5); w2 sender sends the full required prefund
of the measured op (a transfer into the now-deployed proxy, 60,000-gas limit);
w3 op without `initCode`, nonce 1.

**B2-Allowlist W1-cold.** w1 token; w2 sponsor operator
`ObservablePaymaster.setSponsored(account, true)`; PVG estimate (§5); w3 op =
B1's op + `paymasterAndData = paymaster ‖ uint128(60,000) ‖ uint128(0)`.
Rule: sponsor ⇔ `sponsored[userOp.sender] == true`; otherwise validation
reverts (`AA33`).

**B2-Signature W1-cold.** w1 token; PVG estimate (§5); w3 op = B1's op +
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

**This is not a new cryptographic construction.** B2-Signature is an ordinary
public signature-Paymaster baseline: the sponsor signs
`EntryPoint.getUserOpHash(op)` as a raw 32-byte digest (no EIP-191 wrapping);
the EntryPoint's ERC-4337 EIP-712 domain supplies the chain-id and EntryPoint
binding; the v0.9 Paymaster signature bytes are excluded from that hash exactly
as the pinned `UserOperationLib`/`paymasterDataKeccak` define; the EntryPoint
nonce provides inclusion replay protection; and the base configuration signs
`validUntil = validAfter = 0`, which the EntryPoint treats as **unbounded
validity**. The 0/0 window is kept deliberately for D1: a finite window would
add a timing feature and complicate the initial controlled comparison. Varying
it is a possible later ablation.

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
| Gas fields bound? | Yes, each isolated by a single-field mutation test (valid sponsor authorization → mutate one field → re-sign the account → `AA34`): `preVerificationGas`, `maxFeePerGas`, `maxPriorityFeePerGas`, `verificationGasLimit`, `callGasLimit`, `paymasterVerificationGasLimit`, `paymasterPostOpGasLimit` |
| initCode / factory data isolated? | Yes: a trailing byte appended to `createAccount(owner, salt)` (factory ignores it, same sender, account still deploys and validates) → `AA34`. Each mutation test first proves the unmutated op is accepted |
| Validity window bound? | Yes: `validUntil`/`validAfter` are signed Paymaster data enforced by the EntryPoint (tests: expired → `AA32`; window changed after signing → `AA34`) |
| Signature bytes bound? | No, by v0.9 design: excluded from the hash, but the suffix's presence is hashed (test: hash equal with placeholder vs real signature; differs without the suffix) |
| Replay prevention | EntryPoint nonce: an included op cannot be included again (`AA25`), and any other nonce changes the hash. The Paymaster keeps no replay state. W1 signs an unbounded window (0/0), so a signed, never-included op stays sponsorable until its nonce is consumed |
| Interaction with v0.9 hashing | Because signature bytes are excluded, sponsor and account sign **the same** `userOpHash`: the runner inserts a 65-byte placeholder, computes the hash, the sponsor signs, then the account signs the same hash |
| Wrong/missing signature | returns `SIG_VALIDATION_FAILED` → EntryPoint `AA34 signature error`; malformed signed data reverts (`AA33`) |
| Human review | still required for this binding (`docs/research-plan.md` §18) |

## 5. preVerificationGas: calibration phase vs. experiment phase

The first fixed preVerificationGas (50,000) left the bundler ~17,800 gas short
per operation; measurement showed that was dominated by a **one-time 25,000-gas
new-account charge** on an unfunded beneficiary. The beneficiary is pre-funded
in setup, and preVerificationGas is priced in two separate phases.

**Calibration phase** (`make calibrate-pvg` →
`python3 -m experiments.workloads.w1.calibrate --seed 910001 --seed 910002`,
method `break_even_calibration_v1`, `pvg.calibrate`). For every AA variant and
seed, dry-run the exact encoded `handleOps([op], beneficiary)` bundle inside an
`evm_snapshot` and revert, then decompose the gas the EntryPoint does not charge:
`O = G₀ − (A₀ − PVG₀) − 21,000 − calldataGas(bundle₀)` (EIP-2028: 4 / 16 gas per
zero / non-zero byte; the EIP-7623 floor is checked not to bind). The
calibration requires **one O per operation shape across every variant and
seed**, the same environment fingerprint in every run, and reconciliation with
no bundler subsidy; otherwise it fails. It writes the committable artifact
`baselines/w1_b0_b2/calibration/pvg-overhead.json`:

| Recorded | Value |
|---|---|
| O, shape `execute_call` (the W1 application call: every measured W1 op) | **14,985 gas** |
| O, shape `empty_calldata` (deploy-only warm-up op) | **13,708 gas** |
| O, shape `execute_pool_deposit` (B3 Bootstrap; `b3_compat_local` artifact only) | **19,776 gas** |
| samples | 10 (B1 cold, B1 warm measured + warm-up, B2-Allowlist, B2-Signature) × 2 seeds, all equal within shape |
| environment fingerprint | EntryPoint commit `b36a1ed5…`; deployed-bytecode sha256 of EntryPoint, SimpleAccountFactory, SimpleAccount, both Paymasters; bundler version `privgas-minibundler-v1`; bundle size 1; beneficiary pre-funded; chain id 31337; hardfork `prague`; anvil version |
| also | creation timestamp, method, matched-config sha256, provisional PVG, seed **commitments** only |

**Experiment phase** (default `pvg_mode="calibrated_overhead"`, method
`calibrated_overhead_v1`, `pvg.estimate`). For each research sample:

```
PVG = 21,000 + calldataGas(exact final encoded handleOps calldata) + O[shape]
```

iterated to the smallest covering fixed point, re-signing each step because PVG
changes the hash, the signatures and the calldata. **Nothing is executed to
price the operation**: every run records `environment.evm_snapshots_taken` (0
in every experiment run, tested), logs a `pvg_estimate` event (not
`pvg_calibration`), and records the artifact sha256 and the O it used.

**Recalibration is required** — the runner raises `RecalibrationRequired`
before sending any transaction — if the fingerprint changes (EntryPoint
version/bytecode, account/factory/Paymaster bytecode, bundler version, bundle
size, beneficiary funding, chain id, hardfork, anvil version) or the artifact is
missing. Bundler logic changes that affect the encoded bundle or EntryPoint call
must bump `BUNDLER_ID`. The exact-operation dry run remains available as
`pvg_mode="dry_run"` for calibration and diagnostics only.

Assumptions behind this separation: O is independent of the PVG value (PVG only
changes calldata bytes and prefund amounts, never EntryPoint execution paths);
O is constant within an op shape (verified across initCode present/absent,
Paymaster absent/allowlist/signature/B3 CreditPaymaster, and calldata 900–1,380
bytes); bundles contain one op. A multi-op bundle or a new op shape needs
recalibration.

**O is net of the executed call's gas refund (found 2026-09-15).** Measured O is
derived from the receipt, which is net of refunds. The W1 application call
transfers the account's whole token balance and earns the EIP-3529 4,800-gas
SSTORE-clear refund; transferring `amount − 1` instead raises O from 14,985 to
19,785, exactly 4,800 more. B3's Bootstrap call (`CreditPool.deposit`) clears
nothing and calibrates to 19,776. Shapes are therefore keyed by the executed
call (`calibration.op_shape`). One artifact exists per evaluation profile; the
profile id and code-size limit are part of the fingerprint, so the standard
artifact is refused on `b3_compat_local` and vice versa.

**Subsidy assertion.** Reconciliation fails if the bundler's net is worse than
−100 gas × price. A test re-injects the old 17.8k shortfall and confirms it is
caught.

Final representative runs (`20260915T012357Z`, experiment mode; identical to the
archived 4.0.0 runs `20260915T002323Z`):

| Variant | PVG | = 21,000 | + calldata gas (bytes) | + O | surplus | bundle gas | UserOp gas | **bundler net** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| B1 W1-cold | 42,813 | 21,000 | 6,828 (996) | 14,985 | 0 | 288,831 | 288,831 | **0** |
| B1 W1-warm | 41,901 | 21,000 | 5,904 (900) | 14,985 | 12 | 114,990 | 115,002 | **+12 gas** |
| B2-Allowlist W1-cold | 43,345 | 21,000 | 7,360 (1,060) | 14,985 | 0 | 271,121 | 271,121 | **0** |
| B2-Signature W1-cold | 44,733 | 21,000 | 8,748 (1,188) | 14,985 | 0 | 276,668 | 276,668 | **0** |

The +12 gas is deterministic rounding from a signature zero-byte flip during the
fixed-point search; which variant gets it depends on the search's starting
value (the earlier dry-run mode put it on B2-Signature instead).

## 6. REAL cost table

Representative runs `20260915T012357Z-*` (experiment-mode PVG, schema 5.0.0,
profile `eip170_standard`; seed held privately; every transaction hash and cost
summary value identical to the archived 4.0.0 runs `20260915T002323Z-*`). All values in **gwei**; raw wei in
`data/private/baselines/<experiment>/<run>/w1_cost_reconciliation.json`;
summary in `results/w1-baselines/20260915T012357Z/comparison.json`. Effective
gas price 2 gwei everywhere (1 burned, 1 priority). Balances are compared from
the start of the measured workflow (after warm-up for W1-warm).

| Quantity | B0 | B1 cold | B1 warm | B2-Allowlist cold | B2-Signature cold |
|---|---:|---:|---:|---:|---:|
| Setup gas (identical, excluded from cost; public trace) | 7,295,025 | 7,295,025 | 7,295,025 | 7,295,025 | 7,295,025 |
| Warm-up gas / ETH consumed (excluded from cost; public trace) | — | — | 278,649 / 557,298 | — | — |
| Asset-transfer tx gas (w1) | 51,252 | 51,252 | 51,252 | 51,252 | 51,252 |
| ETH-allowance tx gas (w2) | 21,000 | 21,000 | 25,868 | — | — |
| ETH sent directly to recipient | 130,000 | 805,626 | 803,802 | 0 | 0 |
| Recipient action gas | 46,452 (tx) | 288,831 (UserOp) | 115,002 (UserOp) | 271,121 (UserOp) | 276,668 (UserOp) |
| of which preVerificationGas | — | 42,813 | 41,901 | 43,345 | 44,733 |
| UserOperation charge | — | 577,662 | 230,004 | 542,242 | 553,336 |
| Paymaster charge (= deposit decrease) | — | 0 | 0 | 542,242 | 553,336 |
| Paymaster deposit start → end | — | — | — | 100,000,000 → 99,457,758 | 100,000,000 → 99,446,664 |
| Account deployment in measured action | no | yes | no | yes | yes |
| Unused recipient ETH | 37,096 (EOA) | 227,964 | 573,798 ¹ | 0 | 0 |
| Remaining recipient EntryPoint deposit | 0 | 227,964 | 573,798 ¹ | 0 | 0 |
| Bundle tx gas | — | 288,831 | 114,990 | 271,121 | 276,668 |
| Bundler reimbursement (beneficiary Δ) | — | 577,662 | 230,004 | 542,242 | 553,336 |
| **Bundler net** | — | **0** | **+24** | **0** | **0** |
| Sponsor authorization cost | — | — | — | 95,852 (`setSponsored`, 47,926 gas) | 0 (off-chain signature) |
| **Sender cost** | 274,504 | 950,130 | 958,042 | 102,504 | 102,504 |
| **Recipient cost (own funds)** | 0 | 0 | 0 | 0 | 0 |
| **Sponsor cost** | 0 | 0 | 0 | 638,094 | 553,336 |
| **Total ETH consumed by workflow** (Σ tx fees) | 237,408 | 722,166 | 384,220 | 740,598 | 655,840 |
| Accounting checks | 13/13 | 22/22 | 23/23 | 22/22 | 22/22 |

¹ B1 warm starts the measured workflow with the warm-up op's leftover deposit
(284,334); "unused" is the workflow-window delta `allowance − charge`.

Transferred-but-unspent ETH is never counted as consumed.

**Derived by difference** (`compare.derived`, with confounds): account
deployment component (B1 cold − B1 warm) **173,829 gas** of UserOp gas (912 of
it PVG; confounded by the nonce's first write, initCode calldata and warm's
starting deposit); signature-authorization overhead (B2-Signature −
B2-Allowlist) **5,547 gas** = 1,388 PVG + 4,159 validation/execution, while
B2-Allowlist instead pays a 47,926-gas `setSponsored` transaction.

## 7. R1 instantiation and the complete public trace

R1 is **economic funding source ↔ operation** (`docs/threat-model.md`). The
immediate gas payer is public context and is recorded separately.

| | Immediate gas payer (`immediate_gas_payer_kind`, public) | Economic funding source (hidden R1 answer) | Subject operation |
|---|---|---|---|
| B0 | `eoa_balance` — the recipient EOA | the wallet that sent ETH to the EOA (the asset sender) | action tx hash |
| B1 cold / warm | `smart_account_entrypoint_deposit` — the SimpleAccount | the wallet that sent ETH to the account, which the account forwarded into its EntryPoint deposit (the asset sender; in W1-warm also the warm-up funding) | measured userop hash |
| B2-Allowlist | `paymaster_entrypoint_deposit` — `ObservablePaymaster` | the sponsor-operator wallet that called `deposit()` for the Paymaster | measured userop hash |
| B2-Signature | `paymaster_entrypoint_deposit` — `SignatureVerifyingPaymaster` | the sponsor-operator wallet that called `deposit()` for the Paymaster | measured userop hash |

In B0/B1 the economic funder coincides in value with the asset sender; the two
remain separate fields. The sponsor *signer* of B2-Signature is an authorization
key, not a funding source.

**Complete public trace.** Every mined transaction is recorded, including
setup and warm-up, each row with a content-derived `trace_phase`. The cost
window is private (`w1_cost_window.json`).

| Run | public rows | infrastructure | funding | authorization | application | settlement | in cost window |
|---|---:|---:|---:|---:|---:|---:|---:|
| B0 | 18 | 6 | 10 | 0 | 2 | 0 | 3 |
| B1 cold | 22 | 7 | 11 | 0 | 2 | 2 | 7 |
| B1 warm | 26 | 7 | 13 | 0 | 2 | 4 | 6 |
| B2-Allowlist | 21 | 7 | 9 | 1 | 2 | 2 | 6 |
| B2-Signature | 20 | 7 | 9 | 0 | 2 | 2 | 5 |

Public but **excluded from cost**: faucet funding of deployer / asset sender /
bundler / sponsor operator / beneficiary (`funding`); the five contract
deployments and the token mint (`infrastructure`); the sponsor operator's two
Paymaster `deposit()` calls and their `Deposited` events (`funding`); for
W1-warm, the warm-up ETH transfer, bundle, `AccountDeployed`, `Deposited` and
`UserOperationEvent`. Included in both: asset delivery, B0/B1 ETH allowance,
`setSponsored` (B2-Allowlist), the measured bundle and its events.

Evidence present (tested, `TestR1PublicTrace`): B0 — the funder→EOA ETH edge
precedes the action; B1 — funder→account ETH edge, the account's `Deposited`
event, and the unsponsored op; B2-Allowlist — sponsor-wallet→Paymaster
`deposit()` with `Deposited`, the `setSponsored(account, true)` authorization
row (sent by the same wallet) before the op, and the op naming the Paymaster;
B2-Signature — the same funding evidence and op, and **no** authorization row.
No inference is implemented.

## 7a. Recorder integration (schema 5.0.0)

Measured runs (`data_origin: "measured"`, gitignored):
`data/public/baselines/{b0-w1-cold, b1-w1-cold, b1-w1-warm,
b2-allowlist-w1-cold, b2-signature-w1-cold}/20260915T012357Z-*/` with 18 / 22 /
26 / 21 / 20 public rows and 0 / 1 / 2 / 1 / 1 bundler rows. The same variants
on `b3_compat_local` (`data/public/baselines/b3-compat-local/...`) have 30 / 34 /
38 / 33 / 32 public rows: the 12 extra rows are the B3 setup (7 deployments, 2
`depositTo` + 2 `Deposited`, 1 wei to `address(0)`). B0 has no
`observer_a2/`; B1 rows carry no Paymaster; B2 variants carry distinct
`baseline_id`s and Paymaster addresses; bundler data stays in its own
directory. Leakage self-check: 0 findings over 15 runs (11 measured, 4
synthetic). The 4.0.0 measured runs were moved to
`data/private/archive/schema-4.0.0/` and the 3.0.0 runs to
`data/private/archive/schema-3.0.0/`. Attacker-side readers now
refuse `data/raw/` as well as `data/private/`, and raw chain dumps no longer
carry role-naming step labels.

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

- Foundry (`baselines/w1_b0_b2/test`, 43): B0 token semantics; B1 success /
  `AA21` / `AA24`; B2-Allowlist success, `AA33`, revocation, owner-only;
  **B2-Signature (25)**: valid authorization; wrong signer; missing signature;
  wrong sender; modified call; replay (`AA25`); next-nonce reuse; other
  EntryPoint; other chain id; other Paymaster; expired window (`AA32`); window
  tampering; hash excludes signature bytes but not suffix presence; suffix
  matches upstream encoding; no allowlist state; EntryPoint-only validation;
  and single-field mutations of initCode/factory data, `maxFeePerGas`,
  `maxPriorityFeePerGas`, `verificationGasLimit`, `callGasLimit`,
  `preVerificationGas`, `paymasterVerificationGasLimit`,
  `paymasterPostOpGasLimit` (each with an accepted control), plus a helper
  sanity test; matching of B1 / B2 ops and account code. No cost figure comes
  from Forge.
- Live and static (`experiments/workloads/w1/tests`, 93 = 51 B0–B2 + 42 B3 in
  `test_b3_live.py`, listed in `docs/b3-evaluation.md` §12): all variants' success
  and rejection paths; warm-up excluded from cost; bundler subsidy within
  tolerance; PVG decomposition equals the mined bytes; subsidy assertion
  catches a re-injected shortfall; no unused-gas penalty; **experiment runs take
  no snapshots and use the artifact's O; dry-run mode still agrees within 24
  gas; a changed fingerprint raises `RecalibrationRequired`; calibration with a
  fresh seed reproduces the artifact**; **R1 trace completeness (every mined tx
  recorded) and per-baseline funding evidence; ground truth separates economic
  funder, immediate payer and operation; cost window private**; fairness checks
  (23 on `eip170_standard`, 25 with B3 on `b3_compat_local`); determinism;
  recording, regeneration, A2-only rejection, leakage self-check; calibration
  artifact consistency for both profiles; dependency pin.
- Recorder (`experiments/tests`, 125): schema 5.0.0 incl. payer-kind rule,
  `payer_conflation`, pre-5.0.0 version rejection, content-derived `trace_phase`
  (including the B3 classes), R2 anchor rules, retired `B3` id, raw-path reader
  guard.

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
11. **B2 warm variants not implemented** (deliberately: B1 warm is the
    account-deployment ablation before Prompt 4).

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

Schema 4.0.0 runs (identical transactions and costs; B3 not yet measurable,
no evaluation profile, no R2 anchors) are archived under
`data/private/archive/schema-4.0.0/`. Schema 3.0.0 runs (per-sample exact-bundle
PVG dry runs; R1 anchored on the Paymaster contract; no setup-time public
events) are archived under `data/private/archive/schema-3.0.0/`. The first version of these baselines
(schema 2.0.0: a single `B2` allowlist baseline, fixed preVerificationGas,
unfunded beneficiary) and the
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
