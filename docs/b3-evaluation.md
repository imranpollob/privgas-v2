# B3-PrivGas-v1: the frozen PrivGas v1 specimen in the W1 measurement framework

> **NON-PRODUCTION | NON-EIP-170-DEPLOYABLE-AS-BUILT | PRIVACY-EVALUATION-ONLY**

Status: **integrated and measured on a local evaluation chain (2026-09-15).**
Schema 5.0.0. No privacy result is claimed anywhere in this document. It defines
how the unmodified B3 specimen is made observable under the same W1 workload as
B0/B1/B2, what its public trace and ground truth contain, and what it costs.

- Frozen specimen: `baselines/b3_privgas_v1` (submodule, commit
  `02a3f0abdb979446545aa87149080bfb44e43a3e`) — **not modified**.
- Evaluation build (compile-only, frozen sources by remapping): `baselines/b3_eval/`.
- Evaluation parameters and their provenance: `baselines/b3_eval/b3-eval-config.json`.
- Runner and recorder integration: `experiments/workloads/w1/{b3,runner,accounting_b3,recording,profiles,prover}.py`.
- Real prover: `experiments/workloads/w1/prover/` (`@semaphore-protocol/core` 4.14.2).
- Run: `make run-b3-evaluation SEED=<seed>`; test: `make baselines-test`.

## 1. Deployability: the finding is unchanged

`docs/b3-reproduction.md` stands as written: the frozen `PoseidonT3` library is
**29,315** runtime bytes against EIP-170's 24,576, so an ordinary-key deployment
of the credit path fails on an EIP-170-enforcing chain. Nothing here changes or
works around that for any real network. It is re-checked on every test run:

- `make b3-eip170-test` (the existing Forge regression) still passes;
- `test_b3_live.TestEip170Limitation` broadcasts the frozen `PoseidonT3` creation
  transaction to an anvil with default (EIP-170) limits and asserts that no
  code is created, and asserts the documented `29315 > 24576` statement is still
  in `docs/b3-reproduction.md`.

## 2. Evaluation-chain profile `b3_compat_local`

`experiments/workloads/w1/profiles.py`:

| | `eip170_standard` | `b3_compat_local` |
|---|---|---|
| anvil | 1.4.1, chain id 31337, `prague`, automine, base fee pinned | identical |
| code-size limit | anvil default 24,576 (EIP-170 enforced) | `--code-size-limit 32768` (initcode limit follows) |
| setup | W1 environment (EntryPoint, factory, token, both B2 Paymasters, deposits) | W1 environment, **then** the frozen B3 contracts, both B3 Paymaster deposits and 1 wei to `address(0)` |
| who runs on it | B0, B1 (cold/warm), B2-Allowlist, B2-Signature | the same five variants **and** B3-PrivGas-v1 |
| labels | — | NON-PRODUCTION, NON-EIP-170-DEPLOYABLE-AS-BUILT, PRIVACY-EVALUATION-ONLY |
| experiment ids | `baselines/<variant>` | `baselines/b3-compat-local/<variant>` |
| PVG artifact | `calibration/pvg-overhead.json` | `calibration/pvg-overhead.b3_compat_local.json` |

The B3 contracts are appended after the W1 setup, so every W1 contract keeps its
address, and the **whole setup is identical for every baseline on the profile**
(tested): B3 cannot be told apart merely by a different chain configuration or
contract set. The profile is part of the environment fingerprint, the
experiment id, every manifest and every chain dump.

**Why 1 wei to `address(0)`.** B3 burns its non-refundable fee to `address(0)`.
On a fresh devnet that account is empty, so the first burn pays a one-time
25,000-gas new-account charge (measured: `announceAndFund` 178,789 gas without
the pre-funding vs. 153,789 with it, test seed). On every public EVM chain
`address(0)` is non-empty. Same rationale as the pre-funded bundler beneficiary.

### Does raising the limit change B0/B1/B2?

Measured, not assumed. Same seed, both profiles, all five B0–B2 variants
(`results/w1-baselines/20260915T012357Z-profile-effect/profile_effect.json`,
`compare.profile_effect`, and `TestMatchedBaselinesOnCompatProfile`):

| Variant | workflow txs (gas, status, selector, value) | measured UserOp fields | calibrated O | cost-summary differences | setup gas std → compat |
|---|---|---|---|---|---|
| B0 W1-cold | identical | — | — | none | 7,295,025 → 20,359,827 |
| B1 W1-cold | identical | identical | identical | none | same |
| B1 W1-warm | identical | identical | identical | none | same |
| B2-Allowlist W1-cold | identical | identical | identical | none | same |
| B2-Signature W1-cold | identical | identical | identical | none | same |

Workflow transaction hashes are identical as well. The only difference is setup
gas (the B3 infrastructure) and two extra accounting checks on the compat
profile (the two B3 Paymaster deposits stay unchanged). Both calibration
artifacts carry the same O for the shared shapes (14,985 / 13,708).

## 3. Exact protocol flow observed in the frozen source

Read from `src/*.sol`, `test/FunctionalCorrectnessFixture.sol`,
`test/BootstrapSponsorshipBound.t.sol` and `technical-report.md` §2/§6:

**Stage 1 — FUND** (`AnnouncementRegistry.announceAndFund(schemeId, stealthAddress,
ephemeralPubKey, metadata)`, payable): requires `msg.value ≥ vMin + F`; sends `F`
to `address(0)`; forwards `msg.value − F` to `stealthAddress`; calls
`announcer.announce(...)`; sets `eligible[stealth]`; pushes eligibility into
`BootstrapPaymaster` and `CreditPool` (`mirrorEligible`, each emitting
`EligibilityMirrored`); emits `Funded(stealth, forwarded, feeBurned)`.

**Stage 2 — BOOTSTRAP** (UserOperation from the stealth account, sponsored by
`BootstrapPaymaster`): the Paymaster requires `maxCost ≤ 0.005 ETH`,
`maxFeePerGas ≤ 10 gwei`, `_eligible[sender] && !_used[sender]`, and callData
exactly `execute(CreditPool, 0, deposit(uint256))` (196 bytes, every wrapper
field pinned); it sets `_used[sender]`, emits `BootstrapSponsored(sender)`, returns
empty context (no postOp). It does **not** inspect `initCode`. Execution:
`SimpleAccount.execute` → `CreditPool.deposit(commitment)` (eligible, not yet
deposited) inserts the leaf into the LeanIMT, calls
`CreditPaymaster.mirrorRoot(newRoot)` (`RootMirrored`) and emits
`Deposited(commitment, newRoot)`. With one leaf the LeanIMT depth stays 0 and
`PoseidonT3.hash` is never called; the library is deployed only because
`CreditPool` links against it.

**Stage 3 — SPEND** (UserOperation sponsored by `CreditPaymaster`): the proof
travels in the v0.9.0 paymaster-signature suffix
(`paymaster ‖ pmVerifGas ‖ postOpGas ‖ abi.encode(SemaphoreProof) ‖ uint16(len) ‖
PAYMASTER_SIG_MAGIC`), excluded from `userOpHash`. The Paymaster requires
`maxCost ≤ 0.005 ETH`, `callGas + verificationGas ≤ 500,000`,
`maxFeePerGas ≤ 10 gwei`, `proof.merkleTreeRoot == latest mirrored root`,
`proof.scope == keccak256("stealth-protocol.credit.v1")`,
`proof.message == userOpHash`, an unspent nullifier, and
`SemaphoreVerifier.verifyProof(...) == true`; it marks the nullifier spent,
emits `CreditSpent(nullifier, sender)`, returns empty context. **It accepts any
sender.**

Matching against the research record's description: it matches, with three
precisions the source adds. (a) The source lets *any* address spend; the
technical report describes the spender as possibly unrelated to the depositor.
(b) The artifact's own tests never use `initCode` (accounts are pre-deployed
proxies) although the paper models a counterfactual account deployed on first
use. (c) The Announcer in every B3 test is `test/mock/MockAnnouncer.sol`, which
emits `AnnounceCalled(schemeId, stealthAddress)` instead of the canonical
ERC-5564 `Announcement` event.

## 4. B3-PrivGas-v1 W1-cold workflow

| Step | Signer | Transaction / operation | Source of every parameter |
|---|---|---|---|
| setup | deployer, sponsor operator, faucet | W1 setup; frozen B3 contracts in the fixture's order (PoseidonT3, SemaphoreVerifier, MockAnnouncer, CreditPaymaster, CreditPool linked to PoseidonT3, BootstrapPaymaster, AnnouncementRegistry(vMin 0.01 ETH, F 0.021 ETH)); `EntryPoint.depositTo` 0.1 ETH for each B3 Paymaster; 1 wei to `address(0)` | frozen fixture / Demo / TestBase values; W1 deposit amount |
| w1 | asset sender | `W1Token.transfer(account, 100 W1T)` | identical to B0/B1/B2 |
| w2 FUND | asset sender | `announceAndFund{0.031 ETH}(1, account, ephemeralPubKey(33 bytes), "")` | scheme id and empty metadata as in B3's tests; the ephemeral key is seed-derived (B3 implements no ERC-5564 derivation) |
| w3 BOOTSTRAP | bundler | `handleOps([op])`: `initCode = factory ‖ createAccount(owner, 0)` (deploys the **same counterfactual SimpleAccount** as B1/B2), `callData = execute(CreditPool, 0, deposit(C))`, nonce 0, `BootstrapPaymaster` | account/fee limits shared with W1; bootstrap call gas 160,000 and Paymaster verification 60,000 from traces |
| w4 SPEND | bundler | `handleOps([op])` from the **same account**: `callData = execute(token, 0, transfer(destination, 100 W1T))` — byte-identical to B1/B2 — nonce 1, no initCode, `CreditPaymaster` + real proof | Spend Paymaster verification 400,000 = B3's `PM_VERIFICATION_GAS_LIMIT` |

`C` is the commitment of a Semaphore v4 identity whose secret is derived from
the (secret) run seed. Both operations' preVerificationGas is priced by the same
calibrated method as B1/B2 (§7). The account needs no ETH: both operations are
sponsored, so the forwarded `vMin` stays on the account.

**Protocol stages not removed.** Every stage runs. B3 cannot perform W1 without
Bootstrap, so the application call is the Spend stage; nothing was stripped to
improve matching.

**Account implementation.** The same pinned eth-infinitism `SimpleAccount` /
`SimpleAccountFactory` / `EntryPoint` v0.9.0 (commit
`b36a1ed52ae00da6f8a4c8d50181e2877e4fa410`), the same deployed addresses and
bytecode as B1/B2 on the profile (tested). The frozen B3 semantics did not
require a different account: `BootstrapPaymaster` pins only callData, and
`execute(address,uint256,bytes)` is `SimpleAccount`'s selector.

**Staking / ERC-7562.** The B3 Paymasters are not staked and no staking API was
added. The in-repo experimental bundler enforces no ERC-7562 rules, so the
operations execute; this establishes neither ERC-7562 nor production-bundler
compatibility.

## 5. Real proof generation and verification

- **Prover:** `prover/prove.mjs` calls exactly what B3's fixture generators call:
  `new Identity(secret)`, `new Group([commitment])`,
  `generateProof(identity, group, userOpHash, scope, 1)`, `verifyProof(proof)`
  (`@semaphore-protocol/core` 4.14.2, `package-lock.json` committed).
- **Circuit artifacts:** `semaphore-1.wasm` / `semaphore-1.zkey`, Semaphore
  artifact version 4.13.0 — the files the library itself resolves — downloaded
  once to `prover/.artifacts/` (gitignored) and refused unless their sha256
  matches `prover/artifacts-pin.json` (wasm
  `70289ef3…0dff9`, zkey `471a9788…46a08`).
- **Cross-check:** the prover reproduces the frozen fixture
  `test/fixtures/semaphore-valid-proof-depth1.json` exactly (commitment and
  nullifier; Groth16 points are randomised).
- **Binding order:** the wallet hashes the operation with a 416-byte placeholder
  proof (the suffix is excluded from `userOpHash`), proves over that hash,
  inserts the proof, checks the hash is unchanged, then the account signs the
  same hash. The mined proof's `message` equals the `UserOperationEvent` hash
  (tested).
- **On-chain verification:** B3's vendored `SemaphoreVerifier` (deployed
  bytecode equal to the compiled artifact; no `MockSemaphoreVerifier`, no
  `DemoVerifier`). A proof with one altered point is rejected by the real
  verifier (`AA33`, inner `InvalidProof()`); an unannounced account is refused by
  Bootstrap (`AA34`); a second, freshly generated real proof for the same credit
  is rejected (`AA33`, inner `NullifierSpent(uint256)`).
- **One witness only.** A single deterministic identity and a one-member group.
  §11 lists what independent multi-actor witnesses need.

## 6. Complete public trace (run `20260915T012357Z-b3cold`)

44 public rows (A0), 2 bundler rows (A2), 2 ground-truth rows. Every mined
transaction is present (tested). Trace phases: infrastructure 14, funding 17,
authorization 7, application 2, settlement 4; 17 rows fall in the private cost
window.

| Stage | Rows (event_type / calldata_class → trace_phase) | Public values |
|---|---|---|
| setup | 6 `native_transfer` faucet funding (5 roles + `address(0)`) [funding]; 12 `eoa_transaction/contract_creation` [infrastructure] + token mint [infrastructure]; 4 `paymaster_event/paymaster_deposit` + 4 `entrypoint_deposit` [funding] — the sponsor wallet funding both W1 and both B3 Paymasters | Paymaster addresses, sponsor wallet, deposit amounts |
| w1 | `asset_transfer/erc20_transfer` [application] | sender → account, 100 W1T |
| w2 FUND | `eoa_transaction/stealth_announce_and_fund` [funding]; `stealth_announcement` [authorization]; 2 × `sponsorship_eligibility` [authorization]; `native_transfer/native_value_only` registry→account 0.01 ETH [funding]; `native_transfer/fee_burn` registry→`address(0)` 0.021 ETH [authorization] | asset sender, account (`subject_account`), ephemeral key in calldata |
| w3 BOOTSTRAP | `eoa_transaction/entrypoint_handle_ops` [settlement]; `account_deployment` [infrastructure]; `paymaster_event/paymaster_sponsorship` [authorization]; `privacy_pool_event/pool_root_update` [authorization]; `privacy_pool_event/pool_deposit` [funding]; `user_operation_event` [settlement] | account as `sender`, BootstrapPaymaster, **commitment**, **root** |
| w4 SPEND | `eoa_transaction/entrypoint_handle_ops` [settlement]; `privacy_pool_event/pool_redeem` [authorization]; `asset_transfer/erc20_transfer` [application]; `user_operation_event` [settlement] | account as `sender`, CreditPaymaster, **nullifier**, proof **root**, proof metadata (groth16, verifier, 4 signals, 416 bytes, depth 1) |

No failures or retries occurred in the canonical run. Rejected operations in
negative-control runs are recorded in `bundler_private` only (no public mempool).
The recorder does not decode the MockAnnouncer's missing canonical fields and
does not infer anything.

**Bootstrap and Spend use the same public `UserOperation.sender`** — the account
that received the tokens and was announced. The source permits a different
spender, but in W1 the tokens and the Bootstrap eligibility both sit at the
announced account, so the application call can only come from it. This equality
is recorded as mined (both `user_operation_event` rows, both bundler rows, and
`bootstrap_and_spend_same_public_sender: true` in the private cost file) and is
not normalised away. It is a potential attack feature, not a result.

## 7. preVerificationGas for B3, and a calibration finding

Both B3 operations are priced as for B1/B2: `PVG = 21,000 + calldataGas(exact
final bundle) + O[shape]`, O from `pvg-overhead.b3_compat_local.json` (14
samples, 2 seeds; no snapshot in any experiment run). For Spend, every step of
the fixed-point search re-proves, because PVG changes `userOpHash` (3 proofs in
the recorded run).

**Finding: O absorbs the executed call's gas refund.** The Bootstrap op
calibrated to O = **19,776**, not 14,985. Replacing the W1 transfer of the whole
balance with `amount − 1` raises B2-Signature's O from 14,985 to **19,785** —
exactly the EIP-3529 4,800-gas SSTORE-clear refund the W1 transfer earns when it
empties the account's token balance. "O" is therefore EntryPoint unmeasured
overhead **net of the execution's refund**, and the shape key now names the
executed call: `execute_call` (the W1 application call, including B3 Spend:
14,985, now verified up to 1,380 calldata bytes), `execute_pool_deposit` (B3
Bootstrap: 19,776), `empty_calldata` (13,708). The standard-profile artifact is
unchanged in value.

## 8. Ground truth

Two rows per run, both `subject_kind = operation`:

| | Spend row (the W1 application op) | Bootstrap row |
|---|---|---|
| `immediate_gas_payer_kind` / address | `paymaster_entrypoint_deposit` / CreditPaymaster | `paymaster_entrypoint_deposit` / BootstrapPaymaster |
| R1 `economic_funding_source_id` | sponsor-operator wallet handle (funded CreditPaymaster via `depositTo`) | same wallet handle (funded BootstrapPaymaster) |
| R2 label | **observed**: `subject_ref` = Spend userop hash, `true_value` = issuance handle | **absent** (Bootstrap redeems no credit; the negative is kept) |
| R3 label | observed: account → actor handle | observed |
| `credit_id` / `issuance_id` | opaque handles | same handles |
| anchors (private) | stealth account, sponsor wallet, CreditPaymaster, spend tx/userop, `issuance_transaction_hash`/`issuance_userop_hash` (Bootstrap), `credit_commitment`, `credit_nullifier` | same, with BootstrapPaymaster and the Bootstrap tx/userop |

**R1 (one hop, unchanged definition).** Neither Paymaster contract is the
economic funder (validator rule `payer_conflation`). The asset sender's `vMin`
reaches the account but pays no gas, and `F` is burned, so neither is a one-hop
funding source of either operation.

**R2.** The commitment, root and nullifier are public in `public_events`; which
issuance a redemption consumed exists only in `ground_truth.jsonl` and the
private anchors. Tested: no hidden handle, label key, identity commitment field
or proof timing appears in any public file; the attacker-side reader loads the
B3 run (A2 tier) without ground truth and refuses the ground-truth file; the
leakage self-check finds nothing.

**R3.** The stealth account → actor mapping is secret, as for B0–B2.

## 9. Cost reconciliation (run `20260915T012357Z-b3cold`)

42/42 conservation checks (every tracked ETH delta including `address(0)`,
both Paymaster deposits, beneficiary and bundler, token, sender identity, tree
size, root, nullifier, single-use grant). Gwei; effective gas price 2 gwei.

| Quantity | Value |
|---|---:|
| ERC-20 asset transfer (w1) | 51,252 gas · 102,504 gwei |
| AnnouncementRegistry `announceAndFund` (w2) | 153,801 gas · 307,602 gwei |
| ETH forwarded to the stealth account (`vMin`) | 10,000,000 gwei — **transferred, retained, not a gas cost** |
| Non-refundable admission fee `F` (burned to `address(0)`) | 21,000,000 gwei — irrecoverable, not gas |
| Bootstrap UserOperation gas (PVG) | 392,166 (48,056) |
| Bootstrap bundle tx gas · bundler net | 392,166 · 0 |
| BootstrapPaymaster charge (= deposit decrease) | 784,332 gwei |
| Spend UserOperation gas (PVG) | 372,069 (48,837) |
| Spend bundle tx gas · bundler net | 372,045 · +24 gas |
| CreditPaymaster charge (= deposit decrease) | 744,138 gwei |
| Sponsor deposits start → end | 100,000,000 → 99,215,668 (Bootstrap); 100,000,000 → 99,255,862 (Credit) |
| Unused ETH on the stealth account | 10,000,000 gwei (`vMin`) |
| **Sender cost** (fees w1 + w2 + `vMin` + `F`) | 31,410,106 gwei |
| **Sponsor cost** (both Paymaster charges) | 1,528,470 gwei |
| Recipient cost (own funds) | 0 |
| **Total ETH consumed by the workflow** (Σ tx fees) | 1,938,528 gwei |
| Total irrecoverable incl. burned `F` | 22,938,528 gwei |
| Transferred-but-retained ETH | 10,000,000 gwei |
| Proof generation (mined proof / all 3 Spend pricing proofs) | 169.6 ms / 728.3 ms (depth 1, off-chain verify ≈ 11 ms) |
| B3 infrastructure deployment (setup; **not a production cost**) | 13,043,802 gas: PoseidonT3 6,394,160; SemaphoreVerifier 4,423,140; CreditPaymaster 657,890; AnnouncementRegistry 544,073; BootstrapPaymaster 428,024; CreditPool 390,230; MockAnnouncer 114,843; + 2 × `depositTo` 45,721 |

For comparison on the same profile and seed: B2-Signature total 655,840 gwei,
sponsor cost 553,336, application UserOp gas 276,668. The B3 Spend op is 95,401
gas more than B2-Signature's op (4,104 of it PVG), **confounded** by account
deployment (inside B2-Signature's op, inside B3's Bootstrap), Groth16 vs
ecrecover and the nullifier write. The PoseidonT3 deployment figure describes
this local chain only.

## 10. Matched fairness (B1, B2-Signature, B3 on `b3_compat_local`)

`compare.fairness_checks`: 25/25 pass for the six compat-profile variants.

| Control | B1 | B2-Signature | B3 |
|---|---|---|---|
| ERC-20, amount, destination | same | same | same |
| Final application call (execute calldata) | same | same | **same** (Spend) |
| EntryPoint / SimpleAccount / factory / account address | same | same | same |
| Account verification / call gas limits, fee fields | same | same | same (Spend) |
| Fee environment, bundler, PVG method, beneficiary | same | same | same |
| Evaluation chain configuration, deployed contract set | same | same | same |
| Account deployment | measured op (initCode) | measured op (initCode) | **Bootstrap op** (initCode), Spend has none |

**Unavoidable differences** (recorded in `comparison.json`, not forced equal):

1. Two sponsored operations (Bootstrap, Spend) plus an announcement transaction,
   against one operation; account deployment happens in Bootstrap.
2. `paymasterAndData` 478 bytes (416-byte proof) vs 191 (B2-Signature) vs 0 (B1);
   PVG 48,837 vs 44,733 vs 42,813.
3. Spend Paymaster verification limit 400,000 (Groth16 ≈ 219k gas) vs 60,000;
   Bootstrap call gas limit 160,000 (CreditPool deposit) vs the shared 60,000.
4. The asset sender also pays `vMin` (retained on the account) and a burned fee.
5. B3 Paymaster validation writes storage and emits events; B2-Signature's
   does not.
6. The public trace carries commitment, root and nullifier.
7. Latest-root-only proofs (no root history) — irrelevant with one deposit,
   material with concurrency.
8. One-member group: anonymity set 1 (the proof hides nothing among peers yet).
9. `MockAnnouncer` instead of a canonical ERC-5564 Announcer.
10. Unstaked Paymasters on an experimental bundler without ERC-7562.

## 11. What independent multi-actor witnesses need (Prompt 4, not built)

- one Semaphore identity per actor/credit, derived from per-actor secrets, with
  the insertion order of commitments recorded privately so the off-chain group
  matches the on-chain LeanIMT (`Group(commitments_in_deposit_order)`);
- proofs against the **latest** mirrored root at proof time: with concurrent
  deposits, a proof generated before another deposit is rejected
  (`RootMismatch`) and must be regenerated — a scheduling and liveness variable
  that has to be recorded, not hidden;
- tree depth > 1 as the group grows (artifacts `semaphore-<depth>` pinned the
  same way); PoseidonT3 is then actually exercised on chain;
- one announced account per credit (`CreditPool` allows one deposit per
  address), so multi-credit actors need multiple announced accounts;
- the candidate sets for R2 (`b3-credit-issuances`) populated with real
  alternatives, and timing/order randomisation per `docs/research-plan.md` §11;
- per-proof timings kept private; proof generation for PVG pricing scales with
  the number of fixed-point steps.

## 12. Tests

`experiments/workloads/w1/tests/test_b3_live.py` (42): frozen submodule at the
pinned commit and clean, source-tree pin, compile-only eval project, bytecode
equal to the submodule's own build; B3 refused on the standard profile; EIP-170
finding documented and re-reproduced live; deployed runtime equals the frozen
artifacts (immutables and link masked), CreditPool linked to the deployed
PoseidonT3, real verifier, same EntryPoint/account as B1; Bootstrap success;
unannounced account rejected; real proof verifies and is bound to the
operation; tampered proof rejected by the verifier; Spend success; replay
rejected by the nullifier set; W1 transfer success; same public sender recorded;
schema-5 manifest provenance (source commit, profile, EntryPoint commit, circuit
identifiers, fingerprint, measured); every B3 stage in the public trace; R1/R2/R3
ground truth; R2 answer absent from attacker-visible data; attacker reader works
and cannot read ground truth; leakage self-check; private cost window; cost
reconciliation and a tampered balance caught; PVG from the compat artifact;
standard artifact refused on the compat profile; B0/B1/B2-Signature reconcile on
both profiles; identical compat setup for every baseline; matched fairness with
B3; no B0/B1/B2 workflow difference between profiles; artifact shapes; parameter
provenance; proof codec.

## 13. Assumptions and limits of this integration

- The profile raises one limit; nothing about real-network deployability follows.
- A single witness and a single credit: no anonymity set, no root contention.
- The Spend sender equals the Bootstrap sender because W1 places the tokens at
  the announced account; a workload where a different account spends is
  possible in the source and is not evaluated.
- `MockAnnouncer` is the frozen artifact's announcer; a canonical ERC-5564
  Announcer would additionally publish `caller`, `ephemeralPubKey` and
  `metadata` in a log (they are already public in calldata).
- No claim about privacy, security, ERC-7562 compliance, production-bundler
  compatibility or novelty is made.
