# B3 (PrivGas v1) reproduction report

Status: reproduces cleanly; ordinary-key deployment of the credit-issuance
path fails for a documented, verifiable reason. No baseline source was
modified to produce this report.

## Source

- Repository: https://github.com/imranpollob/stealth-protocol
- Pinned commit: `02a3f0abdb979446545aa87149080bfb44e43a3e`
- Imported as a git submodule at `baselines/b3_privgas_v1` (see
  `docs/decision-log.md`, 2026-09-13 entries). Verified via `git ls-remote`
  to match that repository's `HEAD` at import time.

## Recorded toolchain / dependency versions

Taken from the baseline's own `DEPENDENCIES.md` (vendored, offline build —
no `forge install`/npm/network required to build or test) and confirmed
locally:

| Component | Version |
|---|---|
| Foundry (`forge`) | `1.4.1-stable` (commit `cf77460`) — required a local upgrade, see below |
| Solidity | `0.8.28` (pinned in `foundry.toml`, `via_ir = true`, optimizer 200 runs) |
| `account-abstraction` (eth-infinitism EntryPoint) | commit `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` (tag `v0.9.0`) — see caveat below |
| `openzeppelin-contracts` | `5.6.1` |
| `semaphore-contracts` (Semaphore v4) | v4 |
| `@zk-kit/lean-imt.sol` | `2.0.1` |
| `poseidon-solidity` | `0.0.5` |
| Node.js | v22.20.0 (only needed to regenerate ZK proof fixtures; not needed to build/test) |

Full dependency provenance, including per-subtree SHA-256 hashes, is in
`baselines/b3_privgas_v1/DEPENDENCIES.md`.

### EntryPoint version — exact commit identified

`DEPENDENCIES.md` describes `lib/account-abstraction` as a "pre-release v0.9
development snapshot," chosen because the proof-binding construction depends
on v0.9-only machinery (`PAYMASTER_SIG_MAGIC`/`getPaymasterSignature()`,
transient `currentUserOpHash`, the `("ERC4337","1")` EIP-712 domain) absent
from published `0.8.0`/`0.9.0-rc.1`. That label alone isn't precise enough to
pin a comparison against, so the exact upstream commit was identified
directly rather than taken on the vendored README's word:

- Cloned `https://github.com/eth-infinitism/account-abstraction` (full
  history, `develop` default branch) and ran a byte-for-byte recursive diff
  (`diff -rq`) of its `contracts/` tree against the vendored
  `baselines/b3_privgas_v1/lib/account-abstraction/contracts/` tree.
- **Zero differences** against upstream commit
  `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` ("Fixing salt (#611)",
  2025-11-16T13:48:21-03:00) — also zero differences against `develop`'s
  current tip `1c6b669d0eea734e09a87e095ba15e076151718a` ("Add audit for
  release v0.9 (#612)", 2025-12-17), which only adds an audit document on
  top of `b36a1ed` and touches no contract source.
- `b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` **is the exact commit the
  upstream repo tags `v0.9.0`**, and is also present on
  `origin/releases/v0.9`.
- Package self-identification, read directly from the vendored tree (not
  restated from `DEPENDENCIES.md`): `lib/account-abstraction/package.json`
  → `"name": "accountabstraction", "version": "0.9.0"`;
  `lib/account-abstraction/contracts/package.json` → `"name":
  "@account-abstraction/contracts", "version": "0.9.0",` repository
  `https://github.com/eth-infinitism/account-abstraction`.

**Factual statement**: B3 uses `account-abstraction` commit
`b36a1ed52ae00da6f8a4c8d50181e2877e4fa410`, whose vendored code identifies
itself as `@account-abstraction/contracts` version `0.9.0` (`package.json`),
and which upstream now tags as the `v0.9.0` release. Whether that tag existed
at the time B3's author vendored these sources is unknown — `DEPENDENCIES.md`
was written as if only an `0.9.0-rc.1` existed on npm, and an npm-published
`@account-abstraction/contracts@0.9.0` was not checked here (the exact match
was established against the upstream git commit and tag directly, which is
stronger evidence than an npm version string either way). Either way, this is
no longer usefully described as merely "a pre-release snapshot with no stable
identity" — it has one: the commit hash and tag above.

**This means**: any comparison against other baselines (B0-B2, B4-B6) must
either match `account-abstraction@b36a1ed` exactly or explicitly record the
EntryPoint version divergence per `docs/experiment-schema.md`'s
`entrypoint_version` field — e.g. `entrypoint_version:
"account-abstraction@b36a1ed52ae00da6f8a4c8d50181e2877e4fa410 (v0.9.0)"`
rather than the ambiguous string `"0.9"`.

### Local Foundry version mismatch (fixed)

This machine's global Foundry install was `forge 0.2.0` (built 2024-08-13),
old enough that it did not know Solidity 0.8.28 defaults to the Cancun EVM,
so `forge build` failed on `EntryPoint.sol`'s `transient` storage variable
("Transient storage is not supported by EVM versions older than cancun").
Fixed by installing the exact pinned version by hash:

```sh
foundryup -i 1.4.1
```

Attestation and binary hash verified by `foundryup` itself (see terminal
output at time of run). This is a local-machine toolchain fix, not a
change to the baseline source, and is reversible with `foundryup -u
<prior-version>` (Foundry keeps every installed version switchable).

## Test suite reproduction

Reproduced verbatim with `scripts/run_b3_original.sh`, which `cd`s into the
submodule and runs `forge test`, without editing any baseline file:

```
Ran 13 test suites: 65 tests passed, 0 failed, 0 skipped (65 total tests)
```

Matches `DEPENDENCIES.md`'s own claim ("`forge test` # 65 passing, no
network access required"). Raw output: `results/b3/forge-test.log`,
`results/b3/forge-test.json`; summary: `results/b3/reproduction.json`.

## Ordinary-key deployment attempt

Prompt 1's rule: attempt deployment using ordinary authorized keys only —
no `vm.prank`/`vm.etch` impersonation standing in for a real deploy.

The repository's own `script/Demo.s.sol` does **not** satisfy this: it uses
`vm.prank(ENTRY_POINT)` to simulate EntryPoint calling the paymasters, and a
mock `DemoVerifier` that unconditionally returns `true` for proof
verification, plus placeholder (non-real) Semaphore proof points. It
demonstrates the protocol's control flow, not its deployability or its
real proof verification. It is not evidence of ordinary-key deployability.

### What was actually attempted

`test/b3_ordinary_deploy/` (this repo, not the submodule) contains a
minimal Foundry project that imports the vendored B3 source by remapping
and attempts a real, signed deployment:

- `script/OrdinaryDeploy.s.sol` — `forge script --broadcast` using Anvil's
  well-known default dev private key for account (0): a real ECDSA key
  producing a real signed transaction, not a cheatcode impersonation.
- Target chain: a plain `anvil` instance with **no** `--code-size-limit`
  override — i.e. an ordinary, EIP-170-enforcing EVM (this is Anvil's
  default; matches mainnet and most L2s in this respect).
- Target contract: `CreditPool` (the credit-issuance / Merkle-tree
  contract that the bootstrap-sponsored deposit step, and thus the whole
  R2/R3 credit flow, depends on).

Reproducible via `scripts/run_b3_ordinary_deploy.sh` (starts its own
throwaway Anvil, runs the broadcast attempt, tears Anvil down, writes
`results/b3/ordinary-deploy-result.json` and `results/b3/ordinary-deploy.log`).

### Result: fails

```
Error: `PoseidonT3` is above the contract size limit (29315 > 24576).
```

Root cause, confirmed directly (not inferred from the error message alone):

- `CreditPool` imports `@zk-kit/lean-imt.sol/InternalLeanIMT.sol`, whose
  Merkle-tree hashing calls `PoseidonT3.hash(...)`.
- `PoseidonT3.hash` is declared `public` (not `internal`) in
  `lib/poseidon-solidity/PoseidonT3.sol`, so Solidity compiles it as a
  **separately deployed library contract** reached via `DELEGATECALL`,
  rather than inlining it into callers.
- Measured directly with `forge inspect PoseidonT3 deployedBytecode`:
  **29,315 bytes** of runtime code, against EIP-170's **24,576-byte**
  contract-size limit — 4,739 bytes (~19%) over.
- Foundry's own broadcaster refuses to submit the deployment transaction
  once it detects this client-side (no `eth_sendRawTransaction` appears in
  the Anvil request log for this run) — the same refusal any
  EIP-170-conforming node would eventually enforce on-chain.

This confirms the exact blocker the baseline's own `Demo.s.sol` comment
already flags ("PoseidonT3 (29 KB) exceeds EIP-170's 24 KB mainnet limit
... For broadcast to a real network use a pre-deployed PoseidonT3 at its
canonical address"). We did not previously take that comment on faith —
this report is the independent confirmation, with exact byte counts and a
real broadcast attempt.

### What this does and doesn't mean

- It does **not** mean B3 is undeployable in every configuration: if
  `PoseidonT3` is already deployed at a canonical, deterministic
  (CREATE2/"Nick's method"-style) address on a given chain — as is common
  practice for shared libraries like this in the Semaphore/zk-kit
  ecosystem — `CreditPool` could link against that pre-existing address
  instead of deploying its own copy. That was not tested here: doing so
  would require confirming such a canonical deployment actually exists and
  linking against it, which is a design decision for B3's evaluation, not
  a "fix" to silently apply to the vendored source.
- It does mean: a naive, ordinary-key, single-transaction deployment of
  the credit-issuance path, from a clean chain state, is not possible on
  an EIP-170-enforcing chain.
- Per `docs/decision-log.md`'s standing rule, this is recorded as a
  finding, not repaired in `baselines/b3_privgas_v1`. Any workaround
  (linking to a pre-deployed canonical `PoseidonT3`, or otherwise) is a
  separate, explicitly labeled change if and when the project needs
  `CreditPool` actually deployed for an experiment.
- A regression test encoding this fact (independent of any live network)
  lives at `test/b3_ordinary_deploy/test/OrdinaryDeploy.t.sol` and
  currently **fails by design** — it documents the unresolved defect
  rather than working around it.

## Acceptance criteria check (against `docs/ai-coder-prompts.md` Prompt 1)

- [x] Existing tests reproduce: 65/65 passing, unmodified.
- [x] Original code remains hash-identical: submodule pinned at the exact
      commit; nothing in `baselines/b3_privgas_v1` was edited.
- [x] Ordinary-key deployment status is explicitly known: **fails**, for
      `CreditPool` / the credit-issuance path, with an exact, reproduced
      reason (PoseidonT3 exceeds EIP-170 by 4,739 bytes).
- [x] No deployment success is inferred from impersonated local tests:
      `Demo.s.sol`'s `vm.prank`-based flow was explicitly excluded as
      evidence; a real signed-broadcast attempt was made instead.

## No novelty or security claims

This report characterizes the vendored B3 specimen as found. It makes no
claim about PrivGas v1's privacy or security properties, and introduces no
protocol changes — see `docs/threat-model.md`'s process rule.
