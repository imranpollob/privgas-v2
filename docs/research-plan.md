# PrivGas v2 Research Plan v1

**Working project:** PrivGas v2  
**Time budget:** 10–12 weeks  
**Primary strategy:** D1 privacy limits and measurement  
**Fallback A:** D2 validation-state contention and liveness  
**Fallback B:** D3 private actual-cost settlement with unlinkable change

## 1. Research objective

The goal is not to build a larger version of PrivGas v1. The goal is to determine what privacy gas sponsorship actually adds to a stealth-account workflow, identify the boundary where that privacy is useful, and only then design a new mechanism if the experiments expose a meaningful unresolved problem.

The high-ceiling paper should aim for:

1. a precise privacy model for stealth-account gas sponsorship,
2. controlled matched baselines that isolate gas sponsorship from account abstraction and application behavior,
3. a reproducible ERC-4337 implementation and experiment harness,
4. empirical linkage attacks with controlled ground truth,
5. a formal or architecture-scoped limitation result,
6. a focused defense or protocol mechanism only where the evidence justifies it,
7. full cost, liveness, and failure analysis.

The project must remain publishable even if the initial protocol idea fails.

## 2. Literature constraints that shape the project

### 2.1 Claims we should not use as primary novelty

- “The sender can fund the stealth address with ETH” is already a recognized baseline.
- Anonymous/prepaid gas tickets are not new as a broad concept.
- Combining ZK membership with a gas sponsor is not enough by itself.
- Moving funds into a shielded UTXO pool and paying relayer fees from concealed native value is already explored by systems such as StealthHub.
- Generic entropy/anonymity metrics already exist.
- Generic graph-learning deanonymization of mixers is already mature.

Therefore the new paper must isolate an **ERC-4337-specific privacy, liveness, or settlement property**.

### 2.2 Most promising unresolved question

> Under matched application behavior, how much incremental privacy does gas sponsorship provide or destroy for a fresh stealth account?

The important word is **incremental**. A stealth account may already leak through its public target, asset behavior, timing, account reuse, wallet behavior, or recipient actions. The experiment must measure what the gas mechanism adds after conditioning on those features.

## 3. Research directions and decision tree

### D1 — Primary: End-to-end privacy limits of stealth-account gas sponsorship

**Question**

Under matched application behavior, how does the gas mechanism change linkage of:

- R1: funding source / payer ↔ operation
- R2: credit issuance ↔ credit redemption
- R3: stealth account ↔ established recipient wallet or actor

**Target contribution**

A formal separation of these relations plus a controlled empirical study showing where ERC-4337 sponsorship materially improves, worsens, or fails to change practical unlinkability.

**Kill condition**

Stop treating D1 as the main contribution if all measured effects reduce to already-known address reuse, trivial account equality, or ordinary application leakage and there is no meaningful ERC-4337-specific boundary.

### D2 — Fallback A: Validation-state contention and liveness

**Question**

Can ZK-based anonymous sponsorship provide useful inclusion latency and bounded sponsor/bundler exposure when proofs are prepared against changing roots and operations experience concurrency, replacement, failure, and adversarial scheduling?

**Target contribution**

A state-machine and empirical liveness study spanning proof generation, validation, bundler admission, root validity, inclusion, and settlement.

**Kill condition**

If ordinary historical-root retention and routine staking fixes eliminate the problem at realistic load with no significant tradeoff, D2 is engineering rather than research.

### D3 — Fallback B: Private actual-cost gas settlement

**Question**

Can an independently purchased private gas credit pay the **actual** ERC-4337 cost, including failed execution, while preventing overspending and returning unused value without linking later use?

**Target contribution**

A restricted reserve → charge → change protocol with formal value conservation and privacy properties.

**Kill condition**

Stop if:
- a prior construction already provides the same semantics and cost envelope,
- change is deterministically linkable,
- conservation fails under concurrency,
- ERC-4337 semantics make the mechanism impractical.

## 4. Canonical experimental workflow

The main experiment should use a **non-native asset** because this makes the gas-funding problem meaningful.

### Canonical workload W1

1. A sender transfers an ERC-20 token to a fresh stealth-controlled account.
2. The fresh account starts with no native ETH unless the baseline explicitly provides it.
3. The account performs one standardized action:
   - transfer the received ERC-20 token to a fixed test destination, or
   - approve and call a simple fixed test application.
4. All baselines execute the same logical application action.

### Secondary workloads

- W2: ERC-721 transfer and later transfer/approval.
- W3: native ETH only, used mainly to expose how strong the simple sender-ETH baseline is.
- W4: repeated actions from the same stealth smart account, only after W1 is stable.

Do not mix workloads in the first privacy result.

## 5. Baselines

### B0 — Sender-funded stealth EOA

Sender transfers the non-native asset plus enough ETH for the recipient's subsequent transaction.

Purpose: simplest direct-funding baseline.

Fairness requirements:
- record ETH allowance separately from actual gas consumed,
- record retained ETH/change,
- use the same asset action and fee environment.

### B1 — Sender-funded stealth smart account

Same logical workflow as B0, but executed through the same ERC-4337 smart-account code used by later baselines.

Purpose: isolate the effect of account abstraction from Paymaster effects.

### B2 — Ordinary observable Paymaster

A standard non-private Paymaster sponsors the same operation.

Purpose: isolate ZK/private authorization overhead and leakage from ordinary sponsorship.

### B3 — PrivGas v1

Reproduce the accepted architecture as faithfully as possible.

Purpose: evaluate the published design as a specimen, not silently “improve” it.

Any fixes needed for deployment must be recorded separately.

### B4 — Independently issued anonymous credit

A minimal prototype where issuance is not performed by the stealth account itself.

Purpose: test whether decoupling issuance from the stealth-account lifecycle materially changes linkage.

This is an experimental baseline, not yet a novelty claim.

### B5 — Existing/reconstructed prepaid ZK Paymaster

Reproduce or adapt the closest available prior prepaid/Semaphore Paymaster.

Purpose: prevent claiming novelty for functionality already available in prior implementations.

### Optional B6 — Shielded-pool/relayer reference

Use only for actions that can be compared fairly.

Purpose: establish the boundary between preserving ordinary smart-account execution and moving assets into shared private state.

## 6. Formal privacy relations

Let:

- A = hidden actor / recipient identity in the controlled experiment
- W = established wallet controlled by the actor
- S = fresh stealth account
- P = funding/payer account
- I = gas-credit issuance event
- C = hidden credit/note
- O = sponsored UserOperation
- T = ordinary public application trace
- G = gas-sponsorship-specific observations

We analyze three relations separately:

### R1 — Payer-to-operation linkage

Can the observer infer which funding source P is associated with operation O?

### R2 — Issuance-to-redemption linkage

Can the observer infer which issuance event I supplied the private authorization consumed by O?

### R3 — Account-to-recipient linkage

Can the observer associate stealth account S with established wallet W or actor A?

A protocol can protect R2 while failing R3. These must never be collapsed into one generic “unlinkability” claim.

## 7. Threat models

### A0 — Public-ledger observer

Observes blocks, transactions, logs, on-chain UserOperations, account addresses, targets, public calldata, gas/fee fields, timing, and block position.

### A1 — ERC-4337-aware observer

A0 plus public bundler/RPC-visible UserOperation fields, replacement behavior, nonces, fee changes, and validation-state effects that are legitimately observable.

### A2 — Bundler observer

A1 plus submission time, retries, rejected operations, simulation/rejection reasons, and replacement history.

Use A2 only with instrumented bundlers we operate or have permission to log.

### A3 — Service-collusion observer

Future extension only: wallet RPC, witness/path service, bundler, relayer.

Do not make network-level claims without data supporting A3.

## 8. Core hypotheses

- **H1:** PrivGas v1 may protect only a narrower credit relation while exposing account-level Bootstrap ↔ Spend linkage.
- **H2:** Independent issuance materially improves R2 under matched workload.
- **H3:** Application traces dominate some privacy questions, so gas-specific incremental information for R3 may be small.
- **H4:** ERC-4337 replacement, validation, fee, or bundler-visible features create additional leakage in some settings.
- **H5:** Latest-root state causes measurable liveness loss under concurrency.
- **H6:** Routine historical roots may neutralize H5, in which case D2 is not a main contribution.
- **H7:** Actual-cost private settlement is materially harder than one-time credit redemption because of failure, concurrency, public cost, and change.

## 9. Experimental metrics

### 9.1 Linkage metrics

Report:
- top-1 accuracy,
- top-k recall,
- precision at stated coverage,
- AUROC/AUPRC where appropriate,
- calibration / Brier score,
- anonymity posterior entropy,
- effective candidate-set size.

Do not report only classification accuracy.

### 9.2 Incremental privacy value

The theoretical framing is:

`I(U ; G | T)`

where U is the hidden relation being inferred.

In experiments, prefer an operational estimate based on held-out predictive log-loss:

`ΔL = CE(model using T) - CE(model using T + G)`

Convert natural-log loss to bits when needed.

Interpretation:
- positive ΔL: gas-specific features give the attacker additional information,
- near-zero ΔL: sponsorship-specific metadata adds little beyond the application trace,
- negative apparent values should be treated as estimation noise/model instability unless robustly replicated.

### 9.3 Liveness metrics

- admission success rate,
- rejection reason distribution,
- proof re-generation rate,
- inclusion latency p50/p95,
- replacement count,
- accepted-root age,
- gas paid per completed action,
- sponsor deposit depletion,
- bundler reputation/state changes where observable.

### 9.4 Cost metrics

Report the full workflow:
- sender cost,
- user cost,
- sponsor cost,
- Paymaster deposit movement,
- admission/burn fee,
- retained ETH,
- failed-operation cost,
- proving time,
- memory,
- RPC/bundler calls.

Never compare only verifier gas.

## 10. Dataset and event schema

Store secret ground truth separately from attacker-visible data.

### ground_truth.jsonl

Fields:
- experiment_id
- seed
- actor_id
- established_wallet_id
- funding_wallet_id
- asset_sender_id
- stealth_account_id
- credit_id
- issuance_id
- intended_relation_labels
- scenario_id

### public_events.jsonl

Fields:
- experiment_id
- chain_id
- block_number
- tx_hash
- userop_hash
- sender
- paymaster
- target
- method_selector
- public calldata class
- nonce
- asset type
- asset amount bucket if publicly visible
- max_fee_per_gas
- max_priority_fee_per_gas
- verification_gas_limit
- call_gas_limit
- pre_verification_gas
- gas_used
- timestamp
- block position
- event type
- commitment/root if public
- nullifier if public
- outcome

### bundler_private.jsonl

Only for instrumented experiments:
- receive timestamp
- simulation timestamp
- simulation result
- rejection category
- replacement lineage
- inclusion timestamp
- RPC endpoint/bundler identifier

Never expose actor IDs to attack scripts.

## 11. Experimental controls

Each comparison must hold constant as much as possible:
- chain/network,
- account implementation,
- target contract,
- calldata semantics,
- asset type and amount distribution,
- operation timing distribution,
- bundler,
- fee policy,
- number of honest actors,
- number of attacker-controlled actors,
- software version.

Randomize actor assignment, issuance-to-use delay, operation order, candidate-set membership, and experiment seed.

Hold out by actors/accounts, time window, and software configuration. A random row split is insufficient for linkage research.

## 12. D1 attack ladder

Do not begin with a GNN.

1. **Exact/equality rules:** same account, direct funding edge, obvious issuance/account reuse.
2. **Timing/candidate filtering:** issuance-to-use delay, block distance, root age, candidate pool occupancy.
3. **Gas and fee metadata:** fee caps, priority fee, gas limits, actual gas used, replacement pattern.
4. **Application behavior:** target, method selector, asset, amount bucket, transaction neighborhood.
5. **Conditional model:** compare T only, G only, T+G. This is the main D1 experiment.
6. **Graph/learned model:** only if simpler attacks leave meaningful residual signal.

## 13. D2 experiment design

Reproduce PrivGas before changing it.

Test:
- latest-root-only,
- bounded root history,
- epoch/snapshot roots,
- concurrent deposits,
- simultaneous redemptions,
- proof-generation delay,
- fee replacement,
- failed execution,
- two compatible bundlers,
- adversarial deposit bursts.

Initial analytical sanity check:

`P(valid) ≈ exp(-λT)`

for deposit arrival rate λ and proof-to-inclusion interval T under a Poisson model.

This is only a starting model. Experiments must test bursty and adversarial arrivals.

## 14. D3 minimal accounting model

Do not write a circuit first.

Create a state-machine prototype with:
- credit value q,
- reserve amount r,
- actual charge c,
- returned change q' = q - c,
- failure cost cf,
- concurrent reservation,
- cancellation/expiry,
- double-spend attempts.

Required invariants:

1. Conservation
2. No overspend
3. Failure safety
4. Change unlinkability
5. Sponsor solvency

Only after the state machine survives adversarial tests should a ZK design begin.

## 15. 10–12 week schedule and decision gates

### Days 1–5

Deliverables:
- freeze PrivGas v1 commit and dependencies,
- reproduce all existing tests,
- identify/deal with staking/deployment blocker,
- ordinary-key deployment,
- implement B0–B3,
- finalize event schema,
- write formal definitions of R1/R2/R3.

Gate: if PrivGas v1 cannot deploy normally, make the smallest explicit fix required for evaluation. Preserve the unfixed specimen.

### Week 2

Deliverables:
- B4 prototype,
- B5 prior-art baseline,
- root-churn stress test,
- concurrent-redemption test,
- first simple linkage attacks,
- initial result dashboard.

Gate: do not claim “anonymous gas credits” as novelty unless a precise missing property survives B4/B5 comparison.

### Week 3

Deliverables:
- matched D1 T-only vs G-only vs T+G experiment,
- two-bundler D2 pilot,
- D3 state-machine prototype,
- first go/no-go memo.

Gate: select one primary direction and at most two fallbacks.

### Weeks 4–5

Deliverables:
- main controlled runs,
- public-load calibration,
- source/label audit,
- formal model/counterexamples.

Gate:
- D1 must show more than trivial equality.
- D2 must show more than “add root history”.
- D3 must show more than renamed e-cash.

### Week 6

Deliverables:
- independent configurations,
- negative controls,
- adversarial schedules,
- first complete results narrative.

Gate: if the strongest claim is only “our implementation works,” change direction.

### Weeks 7–8

Deliverables:
- focused defense or final protocol variant,
- full cost/limitation analysis,
- draft proofs,
- threats-to-validity section.

Gate: stop adding features. Finish the supported contribution.

### Weeks 9–10

Deliverables:
- reproduction scripts,
- complete ablations,
- full paper draft,
- hostile internal review.

Gate: every headline claim must map to a result, theorem/argument, assumption, or explicitly labeled hypothesis.

### Weeks 11–12 if available

Deliverables:
- external reproduction,
- remaining full-text comparisons,
- artifact packaging,
- journal revision.

Gate: submit only after the conference-to-journal contribution delta is explicit.

## 16. Repository structure

```text
privgas-v2/
├── README.md
├── docs/
│   ├── research-plan.md
│   ├── research-questions.md
│   ├── threat-model.md
│   ├── literature-matrix.md
│   ├── baseline-spec.md
│   ├── experiment-schema.md
│   ├── decision-log.md
│   └── reference/              # no copyrighted PDFs in a public repo
├── baselines/
│   ├── b0_sender_eoa/
│   ├── b1_sender_aa/
│   ├── b2_public_paymaster/
│   ├── b3_privgas_v1/
│   ├── b4_independent_credit/
│   └── b5_prepaid_prior/
├── contracts/
├── circuits/
├── test/
├── scripts/
├── experiments/
│   ├── workloads/
│   ├── privacy/
│   ├── liveness/
│   ├── settlement/
│   └── analysis/
├── data/
│   ├── raw/
│   ├── public/
│   └── private/                # gitignored
├── results/
├── figures/
└── paper/
```

## 17. Branching / evidence policy

Suggested branches:
- `main`
- `baseline/privgas-v1`
- `baseline/b0-b2`
- `experiment/d1-privacy`
- `experiment/d2-liveness`
- `experiment/d3-settlement`
- `fix/<explicit-fix-name>`

Rules:

1. Never silently repair B3.
2. Every fix must have a test demonstrating the original failure.
3. Benchmark outputs must be generated by scripts, not copied manually.
4. Record commit, chain, EntryPoint version, compiler, Foundry/Node versions, circuit artifacts, and seed.
5. Do not commit secret ground-truth mappings to a public repository.
6. Do not put licensed IEEE PDFs in the public repository.

## 18. AI-coder policy

AI can accelerate deployment scripts, adapters, workload generators, data recorders, parsers, tests, plotting, and baseline reproduction.

AI must not independently design cryptographic security assumptions, proof domains, nullifier semantics, refund accounting, authorization invariants, or the adversary model.

Human review is mandatory for signature domains, UserOperation hash binding, chain/EntryPoint binding, nullifier timing, validation/postOp state transitions, integer/value accounting, rollback semantics, and concurrent state changes.

Every AI-coder task should include explicit invariants and acceptance tests.

## 19. Immediate definition of success

At the end of Week 3, this project is on track only if at least one of the following is true:

- **D1 survives:** reproducible, nontrivial ERC-4337/gas-specific privacy effect after conditioning on application behavior.
- **D2 survives:** meaningful liveness/privacy/capital tradeoff not removed by routine root retention.
- **D3 survives:** toy actual-cost private-settlement model satisfies conservation and concurrency safety and still has a plausible unlinkable-change design not already subsumed by prior work.

If none survives, do not extend PrivGas mechanically. Reassess the research question.

## 20. First paper narrative if D1 succeeds

1. Stealth addresses solve recipient-address reuse but create a practical gas-funding problem.
2. Existing approaches include sender ETH, privacy tools, blinded tickets, relayers, shielded pools, and Paymasters.
3. These mechanisms protect different relations, but “privacy” is often discussed without isolating gas-specific leakage.
4. We formalize three linkage relations for stealth-account gas sponsorship.
5. We build matched ERC-4337 baselines that change only the gas mechanism.
6. We measure the incremental attack value of gas-specific observations after conditioning on public application behavior.
7. We identify the conditions under which sponsorship adds meaningful privacy, adds leakage, or is irrelevant.
8. We introduce only the minimal defense/protocol change justified by the observed boundary.
9. We evaluate privacy, liveness, cost, and limitations end to end.

This is a stronger journal direction than “PrivGas with more tests.”
