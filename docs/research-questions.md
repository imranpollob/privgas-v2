# Research questions

Status: **populated from `docs/research-plan.md` v1 (2026-09-13).**

The full decision tree, kill conditions, and schedule live in
`docs/research-plan.md` — this file is the short, stable index other docs
and experiments should link against. If the two ever disagree,
`research-plan.md` is canonical until this file is updated to match.

## Primary question (motivates D1)

> Under matched application behavior, how much incremental privacy does
> gas sponsorship provide or destroy for a fresh stealth account?

"Incremental" is load-bearing: a stealth account can already leak through
its public target, asset behavior, timing, account reuse, or recipient
actions. The experiments must isolate what the *gas mechanism specifically*
adds on top of that, not just measure end-to-end linkability.

## RQ1 (D1 — primary): Privacy limits of stealth-account gas sponsorship

- **Motivation**: existing literature covers sender-funded stealth
  addresses, generic anonymous gas tickets, shielded-pool relayer fees,
  and generic anonymity/deanonymization metrics — none isolate an
  ERC-4337-specific privacy effect. See `research-plan.md` §2.1.
- **Sub-relations** (must be reported separately, never collapsed into one
  "unlinkability" number — see `research-plan.md` §6):
  - R1: funding source / payer ↔ operation
  - R2: credit issuance ↔ credit redemption
  - R3: stealth account ↔ established recipient wallet / actor
- **Hypotheses**: H1-H4 in `research-plan.md` §8.
- **Relevant experiments**: `experiments/privacy/` (attack ladder, D1 in
  `research-plan.md` §12), run against baselines B0-B5.
- **Kill condition**: measured effects reduce entirely to known address
  reuse / trivial account equality / ordinary application leakage, with no
  ERC-4337-specific boundary (`research-plan.md` §3, D1).
- **Status**: open.

## RQ2 (D2 — fallback A): Validation-state contention and liveness

- **Motivation**: ZK-based anonymous sponsorship may trade privacy for
  inclusion latency or bounded sponsor/bundler exposure under concurrency,
  replacement, failure, and adversarial scheduling.
- **Hypotheses**: H5, H6 in `research-plan.md` §8.
- **Relevant experiments**: `experiments/liveness/` (root-churn stress
  tests, `research-plan.md` §13).
- **Kill condition**: routine historical-root retention / staking fixes
  eliminate the problem at realistic load with no significant tradeoff —
  then this is engineering, not research (`research-plan.md` §3, D2).
- **Status**: open, treated as fallback unless RQ1 is killed.

## RQ3 (D3 — fallback B): Private actual-cost gas settlement

- **Motivation**: can an independently purchased private gas credit pay
  the *actual* ERC-4337 cost (including failed execution) while
  preventing overspend and returning unlinkable change?
- **Hypothesis**: H7 in `research-plan.md` §8.
- **Relevant experiments**: `experiments/settlement/` (state-machine
  model first, no circuits — `research-plan.md` §14).
- **Kill condition**: a prior construction already matches the semantics,
  change is deterministically linkable, conservation fails under
  concurrency, or ERC-4337 semantics make it impractical
  (`research-plan.md` §3, D3).
- **Status**: open, treated as fallback unless RQ1 is killed.

## Decision gate

At the end of Week 3 (see `research-plan.md` §15, §19), at least one of
RQ1/RQ2/RQ3 must show a nontrivial, reproducible effect or the project
reassesses rather than mechanically extending PrivGas v1. See
`docs/decision-log.md` for when that gate is actually evaluated.
