# contracts/d2k — D2 kill-condition experimental contracts

> **NON-PRODUCTION | EXPERIMENTAL-MITIGATION | EVALUATION-ONLY**

Nothing in this directory modifies `baselines/b3_privgas_v1` (pinned submodule,
`02a3f0abdb979446545aa87149080bfb44e43a3e`) or `baselines/b3_eval`. The frozen
sources are compiled read-only through remappings, exactly as `b3_eval` does,
with the submodule's own compiler settings (solc 0.8.28, via-IR, optimizer 200)
so gas numbers are comparable like-for-like.

These contracts exist only to answer the two D2 kill-condition questions in
`docs/d2-killcondition-results.md`. **None of them is a proposed protocol.**

| File | Role |
|---|---|
| `src/HistoryCreditPaymaster.sol` | **D2-History-K.** The single-difference experimental variant of the frozen `CreditPaymaster`: accepts the current root and the previous K−1 roots instead of the current root only. Everything else — caps, scope, proof decoding, message/scope binding, nullifier handling, `postOp`, events, errors — is copied verbatim. K is a constructor immutable; K = 1 must reproduce frozen latest-root behaviour. |
| `src/FanOutRootMirror.sol` | **Harness only.** A frozen `CreditPool`'s mirror target is immutable, so this fan-out lets one real deposit stream drive the frozen Paymaster and every K variant at once (a paired comparison under one arrival realisation). It inflates the Bootstrap's own gas, so no overhead number is ever taken from a fan-out deployment. |
| `src/bench/GasDecomposition.sol` | **D2-B benchmarks.** `LeanIMTBench` (G1, insertion alone, same `InternalLeanIMT` + same deployed `PoseidonT3` as the frozen pool, same storage slots), `RootMirrorPusher`/`MinimalRootMirror` (G2, publish a changing root with no Merkle work), `PoolSurroundBench` (G3, `CreditPool.deposit`'s surrounding logic with the insertion replaced, in two modes), `NoopBench` (G4, external-call floor), `PoseidonCallBench` (G5, one `PoseidonT3.hash` delegatecall). |
| `test/HistoryRoots.t.sol` | Ring-buffer retention mechanics that need no proof: entry, eviction boundary, duplicate refcounting, K = 1 reduction, bounded storage, O(1) update, frozen constants unchanged. Proof-path security invariants are tested live with real Groth16 proofs in `experiments/liveness/d2k/tests/test_live.py`. |

How the experimental Paymaster is wired without touching frozen code: the frozen
`CreditPool` takes its mirror target and its registry as **constructor
arguments**, so the D2K environment deploys a second, unmodified frozen
`CreditPool` / `BootstrapPaymaster` / `AnnouncementRegistry` set whose only
difference is the address the pool pushes roots to. The pool's bytecode,
eligibility rules, Bootstrap flow, Semaphore verifier, proof binding, nullifier
handling, EntryPoint, account implementation, Paymaster sponsorship semantics
and the W1 application call are all unchanged.

```
make d2k-build       # forge build here
make d2k-contract-test
```
