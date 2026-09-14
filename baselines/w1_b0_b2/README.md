# baselines/w1_b0_b2 — matched W1 baselines B0, B1, B2-Signature, B2-Allowlist

One Foundry project shared by all four baselines, because the comparison is only
meaningful if they share the token, the EntryPoint, the account code and every
parameter. Full description, cost table and fairness notes:
**`docs/w1-baselines.md`**.

| Baseline | Recipient account | Gas funding | Contracts used |
|---|---|---|---|
| B0 | fresh EOA | sender sends ETH for the action tx | `W1Token` |
| B1 | eth-infinitism `SimpleAccount` v0.9.0 (counterfactual, deployed by the first UserOp) | sender sends the EntryPoint required prefund to the account | `W1Token`, `EntryPoint`, `SimpleAccountFactory` |
| B2-Signature (primary ordinary Paymaster) | same as B1 | `SignatureVerifyingPaymaster` deposit; authorization = sponsor ECDSA signature over `EntryPoint.getUserOpHash(op)` in the v0.9.0 paymaster-signature suffix | B1's + `SignatureVerifyingPaymaster` |
| B2-Allowlist (auxiliary) | same as B1 | `ObservablePaymaster` deposit; authorization `sponsored[userOp.sender] == true` via a public `setSponsored` transaction | B1's + `ObservablePaymaster` |

Workloads: W1-cold (primary; AA account deployed by the measured op) and
W1-warm (B1 ablation; account deployed by an earlier op).

## Files

```
w1-config.json            matched parameters (amount, fees, gas limits) — read by tests AND runner
dependency-pin.json       digests of the vendored AA / OZ trees compiled against
src/W1Token.sol           plain OpenZeppelin ERC20
src/ObservablePaymaster.sol   B2-Allowlist's public allowlist Paymaster (auxiliary)
src/SignatureVerifyingPaymaster.sol   B2-Signature's signature-verifying Paymaster
src/UpstreamArtifacts.sol compile-only import of unmodified EntryPoint / SimpleAccountFactory
test/*.t.sol              contract-semantics tests (NOT cost measurements)
```

## Provenance

`remappings.txt` points **read-only** into `../b3_privgas_v1/lib/`, whose
`account-abstraction` tree is byte-identical to eth-infinitism commit
`b36a1ed52ae00da6f8a4c8d50181e2877e4fa410` (tag `v0.9.0`; see
`docs/b3-reproduction.md`). Compiler settings copy B3's (solc 0.8.28, via-IR,
optimizer 200). The B3 submodule must be checked out to build this project.
Nothing under `baselines/b3_privgas_v1` is modified.

## Commands

```
make baselines-build                 # forge build
make baselines-test                  # forge test + live anvil tests
make run-matched-baselines SEED=<n>  # real runs for all five variants, recorded + comparison
```

Cost numbers come only from the live runner (`experiments/workloads/w1`), which
signs real transactions against anvil. The Forge tests use `vm.prank` and
exist to pin contract semantics.
