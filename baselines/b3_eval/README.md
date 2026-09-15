# baselines/b3_eval — evaluation build of the frozen B3 specimen

> **NON-PRODUCTION | NON-EIP-170-DEPLOYABLE-AS-BUILT | PRIVACY-EVALUATION-ONLY**

This directory contains **no protocol code**. It is a compile-only Foundry
project that builds the unmodified PrivGas v1 contracts from the pinned
submodule `baselines/b3_privgas_v1` (commit
`02a3f0abdb979446545aa87149080bfb44e43a3e`) by read-only remappings, with the
submodule's own compiler settings (solc 0.8.28, via-IR, optimizer 200), so the
W1 runner can deploy them on the `b3_compat_local` evaluation profile.

| File | Purpose |
|---|---|
| `src/FrozenB3Artifacts.sol` | seven `import` lines, nothing else: AnnouncementRegistry, BootstrapPaymaster, CreditPool, CreditPaymaster, MockAnnouncer (B3's own test announcer), SemaphoreVerifier (real Groth16), PoseidonT3 |
| `b3-eval-config.json` | evaluation parameters with their source-file provenance (vMin, fee, scheme id, gas limits, deposits) |
| `dependency-pin.json` | tree digests of every compiled frozen source tree (checked by the live tests) |

Executable bytecode equals the submodule's own `forge build` (metadata and
library-link placeholders excluded; tested). `PoseidonT3` is 29,315 runtime
bytes and still cannot be deployed on an EIP-170 chain
(`docs/b3-reproduction.md`, unchanged). Nothing here is a deployment, a fix or
a production configuration. See `docs/b3-evaluation.md`.

```
make b3-eval-build        # forge build here
make b3-eip170-test       # the frozen PoseidonT3 still exceeds EIP-170
make run-b3-evaluation SEED=<seed>
```
