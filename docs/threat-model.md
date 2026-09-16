# Threat model

Status: **populated from `docs/research-plan.md` v1 (2026-09-13).**

Full rationale lives in `docs/research-plan.md` §6-7; this file is the
short, stable index. If the two disagree, `research-plan.md` is canonical
until this file is updated to match.

## Assets (what we're tracking linkage of)

Per `research-plan.md` §6, using these symbols consistently across docs,
code, and data schemas:

| Symbol | Meaning |
|--------|---------|
| A | hidden actor / recipient identity in the controlled experiment |
| W | established wallet controlled by the actor |
| S | fresh stealth account |
| P | funding / payer account |
| I | gas-credit issuance event |
| C | hidden credit / note |
| O | sponsored UserOperation |
| T | ordinary public application trace |
| G | gas-sponsorship-specific observations |

## Relations under study (must be reported separately)

- **R1 — Payer-to-operation linkage**: can the observer infer which
  funding source P is associated with operation O?
  **Refined 2026-09-14** (`docs/decision-log.md`): R1 is **economic funding
  source ↔ operation**. Two concepts are kept distinct and recorded separately:
  - *immediate gas payer* — the balance the execution mechanism directly
    charges: the sender EOA's balance (B0), the SimpleAccount's EntryPoint
    deposit (B1), or the Paymaster's EntryPoint deposit (B2). This is normally
    **public context** (it is in the transaction or `UserOperationEvent`);
  - *economic funding source* — the wallet whose ETH supplied that balance:
    the wallet that sent ETH to the B0 recipient, the wallet that funded the
    B1 account / its deposit, the sponsor wallet that funded the B2
    Paymaster's deposit. **This is the hidden R1 answer.**

  "Which Paymaster contract paid" is intentionally public and usually trivial;
  it is never the R1 question. An EOA, a smart account, a Paymaster contract
  and an economic actor are never collapsed into one generic "payer".
- **R2 — Issuance-to-redemption linkage**: can the observer infer which
  issuance event I supplied the private authorization consumed by O?
- **R3 — Account-to-recipient linkage**: can the observer associate
  stealth account S with established wallet W or actor A?

A protocol can protect R2 while failing R3 (or vice versa). These are
never collapsed into one generic "unlinkability" claim anywhere in this
repository — code, docs, or paper.

## Adversary model (nested capability tiers)

- **A0 — Public-ledger observer**: blocks, transactions, logs, on-chain
  UserOperations, account addresses, targets, public calldata, gas/fee
  fields, timing, block position. Always in scope.
- **A1 — ERC-4337-aware observer**: A0 plus public bundler/RPC-visible
  UserOperation fields, replacement behavior, nonces, fee changes, and
  legitimately observable validation-state effects. In scope for D1/D2.
- **A2 — Bundler observer**: A1 plus submission time, retries, rejected
  operations, simulation/rejection reasons, replacement history. **Only
  usable with instrumented bundlers we operate or have permission to
  log** — see `bundler_private.jsonl` in `docs/experiment-schema.md`.
- **A3 — Service-collusion observer** (wallet RPC, witness/path service,
  bundler, relayer colluding): future extension only. **Do not make
  network-level claims without data supporting A3.**

## Trust assumptions

B3-PrivGas-v1 (2026-09-15, `docs/b3-evaluation.md`): evaluated at A0 (chain) and
A2 (in-repo bundler); assumed honest: local node, bundler, sponsor operator and
the recipient's local prover. Evaluated only on the NON-PRODUCTION
`b3_compat_local` chain profile.

D2 pilot (2026-09-15, `docs/d2-pilot-results.md`): liveness measurements at A0 (chain) and A2
(our instrumented staged bundler). The only targeted adversary modelled is **A2** — the bundler
operator or a party fed its simulation results — because the harness has no public mempool, so
no A0/A1 observer can see a pending Spend. Assumed honest: node, bundler, sponsor operator,
provers. `b3_compat_local` only.

D2 kill-condition test (2026-09-16, `docs/d2-killcondition-results.md`): the same tiers and the
same assumed-honest parties as the D2 pilot (A0 chain, A2 our instrumented staged bundler; honest
node, bundler, sponsor operator, provers; `b3_compat_local` only). The experimental
`D2-History-K` Paymaster is measured under exactly those tiers and **no privacy claim is made for
it**: whether an observer learns anything from *which* retained root a proof names, and how much
anonymity a prover gives up by proving against an older root, are recorded as untested hypotheses,
not results. No ERC-7562 tracer, no staking and no public mempool exist in this harness, so nothing
there establishes ERC-7562 or production-bundler compatibility for the frozen contract or for the
variant.

D1 pilot (2026-09-15, `docs/d1-pilot-results.md`): attacks at A0 only, with auxiliary
knowledge of the candidate wallet directory (R3) and a profiling attacker holding labelled
training runs; all baselines on `b3_compat_local`.

Otherwise not yet finalized per-baseline. Each baseline (`docs/baseline-spec.md`
registry) must state, when implemented, which of A0-A3 it is evaluated
under and which components are assumed honest for that evaluation. An
entry without an explicit adversary tier is incomplete.

## Non-goals / explicit scope boundaries

- Not designing a new cryptographic primitive as a starting point — see
  `docs/ai-coder-prompts.md` Prompt 8 and the AI-coder policy in
  `research-plan.md` §18.
- Not claiming novelty for constructs already covered by prior art (sender
  ETH funding, generic anonymous gas tickets, shielded-pool relayer fees,
  generic anonymity metrics, generic mixer-deanonymization graph
  learning) — `research-plan.md` §2.1.
- Not inferring production deployability from impersonated local tests
  (e.g. `vm.prank`) — see B3 reproduction rules in
  `docs/ai-coder-prompts.md` Prompt 1.
- PrivGas v1 (B3, see `docs/references.md`) is treated as an experimental
  specimen to be measured, not an architecture to preserve or improve in
  place. Any fix required to make it evaluable is recorded as a separate,
  explicit change — never a silent repair of the baseline
  (`docs/decision-log.md` tracks these).

## Process rule

Any change that asserts "this hides X from Y" or "this prevents Z" must
cite: which relation (R1/R2/R3), which adversary tier (A0-A3), and which
experiment in `experiments/privacy/` or `experiments/liveness/` attempted
to falsify it. Reviewers should reject protocol claims that don't cite
this file.
