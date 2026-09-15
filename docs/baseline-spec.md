# Baseline specification

Status: **B0, B1, B2-Signature and auxiliary B2-Allowlist implemented, hardened and R1-refined (2026-09-14, `docs/w1-baselines.md`); workloads W1-cold (primary) and W1-warm (ablation); B3 frozen specimen, measured unmodified as `B3-PrivGas-v1` on the NON-PRODUCTION `b3_compat_local` evaluation profile (2026-09-15, `docs/b3-evaluation.md`); B4–B6 not implemented.**

`baselines/` holds reference implementations that experiments compare
against — e.g., an unmodified/standard flow with no privacy or gas
mechanism applied, or a well-known prior approach. Baselines exist so that
every measured effect (privacy, gas overhead, latency, ...) is reported
*relative to* something, never as a bare absolute number.

## What qualifies as a baseline

A baseline must:

1. Be runnable standalone via the same harness experiments use
   (`make run-local-experiment`), with no dependency on unfinished project
   code.
2. Pin its own dependency versions independently of the main project
   (recorded via `scripts/env-report.sh` at run time, per
   `docs/experiment-schema.md`).
3. Have a written description of what it represents and why it's a fair
   comparison point (added to this file when the baseline is added).
4. Not be modified to make later results look better — changes to a
   baseline after it's been used in a reported result require a new
   baseline ID and a decision-log entry, not an in-place edit.

## Registry of baselines

| ID | Directory | Represents | Added (commit) |
|----|-----------|------------|-----------------|
| B3 / **B3-PrivGas-v1** | `baselines/b3_privgas_v1` (git submodule, pinned `02a3f0ab...e43a3e`, unmodified); evaluation build `baselines/b3_eval` (compile-only) + runner `experiments/workloads/w1` | The accepted PrivGas v1 implementation, reproduced as faithfully as possible — evaluated as a specimen, not improved. See `docs/b3-reproduction.md` for test results, dependency/version provenance, and a documented ordinary-key deployment failure (PoseidonT3 exceeds EIP-170). Recorder baseline id `B3-PrivGas-v1` (schema 5.0.0): the unmodified contracts measured under W1-cold (Fund → Bootstrap deploying the same SimpleAccount → Spend with a real Semaphore/Groth16 proof performing the W1 application call) **only** on the `b3_compat_local` profile (anvil `--code-size-limit 32768`; NON-PRODUCTION, NON-EIP-170-DEPLOYABLE-AS-BUILT, PRIVACY-EVALUATION-ONLY). Paymasters unstaked; no ERC-7562 enforcement. Tiers: A0, A2. Honest: node, bundler, sponsor operator, prover. A changed protocol would need a new id. `docs/b3-evaluation.md`. | 02a3f0ab (import); B3-PrivGas-v1 uncommitted, 2026-09-15 |
| B0 | `baselines/w1_b0_b2` (shared project) + runner `experiments/workloads/w1` | Sender-funded fresh EOA: the asset sender sends the ERC-20 and exactly the action transaction's max fee in ETH; the EOA performs the ERC-20 transfer. Workload W1-cold only. Tiers: A0. Honest: local node. | (uncommitted, 2026-09-14) |
| B1 | same | Sender-funded eth-infinitism `SimpleAccount` v0.9.0 (EntryPoint v0.9.0, commit `b36a1ed5`); the sender sends the EntryPoint required prefund; no Paymaster. W1-cold (the op deploys the account) and W1-warm (ablation; account pre-deployed). Tiers: A0, A2 (no A1). Honest: node, bundler. | (uncommitted, 2026-09-14) |
| B2-Signature | same | **Primary ordinary-Paymaster baseline.** Same account, EntryPoint, bundler and application call as B1, plus `SignatureVerifyingPaymaster`: sponsors an op carrying the sponsor's ECDSA signature over the EntryPoint `userOpHash` (v0.9.0 paymaster-signature suffix); no on-chain authorization transaction. W1-cold. Tiers: A0, A2. Honest: node, bundler, sponsor. | (uncommitted, 2026-09-14) |
| B2-Allowlist | same | **Auxiliary.** Same as B1 plus `ObservablePaymaster` (`sponsored[userOp.sender] == true`, owner-managed public allowlist). Its `setSponsored(account,true)` transaction publicly links sponsor and account before the operation and may produce stronger linkage than other ordinary Paymasters; never the sole public-Paymaster baseline for a privacy claim. W1-cold. Tiers: A0, A2. Honest: node, bundler, sponsor operator. | (uncommitted, 2026-09-14) |
| B4-B6 | not yet implemented | Independent-issuance credit / prior-art prepaid Paymaster / shielded-pool reference — see `docs/research-plan.md` §5. | — |

`experiments/recorder/adapters/` holds one adapter per baseline and
`experiments/recorder/baselines.py` declares each baseline's structural
capabilities (does it use ERC-4337, a bundler, a Paymaster, a credit system,
publishable privacy artefacts), which the record validator enforces. That
recording infrastructure was built before B0-B2 existed; the B0-B2 capability
rows were confirmed unchanged against the real implementations, while several
event-structure assumptions were not and were corrected under schema 2.0.0
(`docs/w1-baselines.md` §14). Rows for B4-B6 still encode
`docs/research-plan.md` §5, not an implementation. The example runs under
`experiments/recorder/examples/` are synthetic fixtures for testing the
recorder and are not measurements — see `docs/experiment-schema.md` §10.

For every baseline, R1's hidden answer is the *economic funding source* (the
wallet that funded the gas-paying balance), while the *immediate gas payer*
(EOA balance, SimpleAccount deposit, Paymaster deposit) is public context; see
`docs/w1-baselines.md` §7 and `docs/experiment-schema.md` §5.0. For
B3-PrivGas-v1 both operations are charged to a B3 Paymaster deposit funded by the
sponsor wallet; R2 (issuance ↔ redemption) is defined only for it
(`docs/b3-evaluation.md` §8).

**Matched D1 comparisons that include B3 must use runs from the same evaluation
profile** (`experiment_id` prefix `baselines/b3-compat-local/`). On that profile
the setup of every baseline also deploys the B3 contracts; measured workflow
quantities of B0–B2 are identical to the `eip170_standard` runs.

B0/B1/B2-Allowlist/B2-Signature deviate from criterion 1 above in one respect: they run through
`make run-matched-baselines SEED=<seed>` (which records event streams and a
cost reconciliation) rather than the metadata-only `make run-local-experiment`.

## Directory convention

B0-B2 share one directory, `baselines/w1_b0_b2/`, instead of the
`b0_sender_eoa/`, `b1_sender_aa/`, `b2_public_paymaster/` split sketched in
`docs/research-plan.md` §16: the comparison requires one token, one
EntryPoint build, one account build and one parameter file, and three copies
would be three chances to drift.

```
baselines/<baseline-id>/
  README.md        # what this represents, why it's a fair comparison
  <implementation>  # the actual runnable baseline
```
