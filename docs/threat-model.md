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

Not yet finalized per-baseline. Each baseline (`docs/baseline-spec.md`
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
