# Experiment schema

Canonical definition of **what an experiment run records and who is allowed
to see it**. Two things live here:

1. **§1–§2** the per-run metadata contract, unchanged from the original
   scaffold — the reproducibility record every run must emit.
2. **§3 onward** the three-stream event schema: `ground_truth.jsonl`,
   `public_events.jsonl`, `bundler_private.jsonl`, their field definitions,
   their public/private classification, and how the separation is enforced.

`docs/research-plan.md` §10 sketches the three streams; this file is the
authoritative, implemented version. Where the two differ in detail, this
file is canonical for the schema and §9 below records the differences.
Relation definitions (R1/R2/R3) and adversary tiers (A0–A3) are defined in
`docs/threat-model.md` and are referenced, not redefined, here.

Implementation: `experiments/recorder/`. The field tables in §5–§7 are
generated from the code (`python3 -m experiments.recorder.docgen --write`)
and a test fails if they drift.

---

## 1. Per-run metadata record

Every experiment run emits a `metadata.json` (or, for runs that produce event
streams, the run manifests in §4) alongside its raw output, with at minimum:

| Field                 | Type     | Meaning                                                                 |
|------------------------|----------|--------------------------------------------------------------------------|
| `experiment_id`        | string   | Identifier matching a definition under `experiments/<category>/`        |
| `git_commit`           | string   | Full commit SHA the run executed at (`git rev-parse HEAD`)              |
| `git_dirty`            | boolean  | Whether the worktree had uncommitted changes at run time                |
| `seed`                 | integer  | RNG seed used for the run                                                |
| `chain_id`             | integer  | Chain/network ID targeted (including local devnets, e.g. anvil default) |
| `entrypoint_version`   | string   | ERC-4337 EntryPoint (or equivalent AA entrypoint) version targeted      |
| `tool_versions`        | object   | Output of `scripts/env-report.sh`, captured at run time                 |
| `started_at_utc`       | string   | ISO-8601 UTC timestamp                                                  |
| `finished_at_utc`      | string   | ISO-8601 UTC timestamp                                                  |
| `parameters`           | object   | All experiment-specific inputs (workload size, config, etc.)             |
| `outputs`              | object or path | The measured result(s), or a path to where they're stored          |

`make run-local-experiment ID=<id> SEED=<seed>` still produces exactly this
shape and remains the contract for runs that record no event streams (the B3
reproduction in `docs/b3-reproduction.md` is one). Runs that do record event
streams emit the two run manifests in §4 instead, which carry the same
information with one deliberate change: **`seed` moves to the private
manifest** (§8.3).

### Why each field is required

- **experiment_id**: makes results discoverable and links them back to a
  research question in `docs/research-questions.md`.
- **git_commit** + **git_dirty**: without this, "which code produced this
  number" is unanswerable. A dirty worktree at run time should be treated
  as non-reproducible and flagged, not silently accepted.
- **seed**: required for any randomized workload or sampling; without it,
  variance can't be distinguished from a real effect.
- **chain_id**: gas costs, block gas limits, and opcode pricing are
  chain-specific; a result without this is not comparable across networks.
- **entrypoint_version**: ERC-4337 EntryPoint semantics and gas accounting
  have changed across versions; mixing versions silently invalidates
  comparisons.
- **tool_versions**: compiler and library versions can change measured gas
  costs and correctness even with identical source code.

## 2. Storage convention for metadata-only runs

```
results/<experiment_id>/<run_timestamp>/
  metadata.json     # §1
  raw/              # raw output referenced by `outputs`, if not inline
```

---

## 3. The three streams

The project measures how much a **gas-payment mechanism** changes three
linkage relations (`docs/threat-model.md`). That only means anything if the
answer key is kept away from the code trying to guess it. Hence three
logically separate streams, each with one owner and one audience:

| Stream | Holds | Who may read it | On disk |
|--------|-------|-----------------|---------|
| `ground_truth.jsonl` | secret experiment labels: hidden identities and the true R1/R2/R3 answers | evaluation only, after predictions are frozen | `data/private/` (gitignored) |
| `public_events.jsonl` | what the declared public observer can see | tiers **A0** and **A1** | `data/public/.../observer_a0a1/` |
| `bundler_private.jsonl` | what an instrumented bundler we operate can see | tier **A2** | `data/public/.../observer_a2/` |

Tier **A3** (service collusion) is deliberately not implemented. No stream
here supports a network-level claim.

A note on the name: `bundler_private.jsonl` is *private with respect to the
public ledger*, not secret with respect to the attacker. It is an attacker
input at tier A2. Only `ground_truth.jsonl` is secret.

### 3.1 Directory layout

```
data/public/<experiment_id>/<run_id>/
  run_manifest.public.json
  observer_a0a1/public_events.jsonl        # tiers A0, A1
  observer_a2/bundler_private.jsonl        # tier A2 (absent if no bundler)
  predictions/<attack_id>/<relation>/      # frozen attack output (§8.4)

data/private/<experiment_id>/<run_id>/
  run_manifest.private.json                # SECRET: holds the seed
  ground_truth.jsonl                       # SECRET

data/raw/<experiment_id>/<run_id>/         # raw chain / bundler dumps
```

The tiers are separate **directories**, not just separate files, so an A0/A1
dataset is assembled by naming `observer_a0a1/` and cannot pick up bundler
data from a glob. Including A2 data requires naming the other directory,
which is a visible, deliberate act — as `docs/threat-model.md` requires,
since A2 is only usable with bundlers we operate or have permission to log.

### 3.2 Shared record envelope

Every row in every stream carries the same envelope, so any row can be traced
to (which schema, which experiment, which run, which code revision, which
baseline, measured or synthetic) without consulting anything outside the row:
`schema_version`, `stream`, `experiment_id`, `run_id`, `record_id`, `seq`,
`baseline_id`, `workload_id`, `scenario_id`, `software_revision`,
`data_origin`, `recorded_at_utc`.

`record_id` is `<run_id>/<stream>/<seq:06d>` and is the stable identity a
frozen prediction can refer to.

### 3.3 Numeric and format conventions

- **uint256-domain values** — wei amounts, gas limits, gas prices, ERC-4337
  nonces, token amounts in base units — are **decimal strings**
  (`"1000000000"`). JSON numbers are IEEE-754 doubles in most parsers and
  lose precision above 2^53, which would silently corrupt fee and amount
  comparisons.
- **Small bounded counters** — `chain_id`, `block_number`,
  `transaction_index`, `log_index`, `replacement_count`, `seq` — are JSON
  integers. A string `chain_id` is rejected: mixed representations break
  cross-run joins.
- **32-byte hashes and field elements** are `0x`-prefixed lowercase hex of
  exactly 32 bytes. **Addresses are `0x`-prefixed lowercase 20-byte hex**
  (2.0.0; adapters canonicalise). 1.0.0 accepted EIP-55 checksummed and
  lowercase spellings side by side, and the first real runs produced both —
  RPC transaction fields are lowercase, decoded logs checksummed — so the same
  account compared unequal across rows.
- **Fractional seconds** in timestamps (1–6 digits) are valid. (A 1.0.0
  validator bug rejected them despite the documented pattern; found by the
  first real bundler timestamps and fixed with a regression test.)
- **Timestamps** are ISO-8601 UTC with a trailing `Z`. Offsets and local time
  are rejected. `block_timestamp_utc` is chain time; `recorded_at_utc` is the
  harness wall clock; they are never conflated.

### 3.4 Null and not-applicable semantics

The schema is *required-key, explicit-value*:

- **Every field defined by a stream's schema must be present as a key.**
  Absence-by-omission is never valid. This is what makes validation
  deterministic and stops "the field is missing" and "the field is empty"
  from being indistinguishable.
- **`null`** — the field is meaningful for this baseline and this row, but the
  value is genuinely unknown or did not occur. Example: `block_number` for an
  operation that was never included.
- **`"not_applicable"`** (the literal string) — the concept does not exist for
  this baseline at all. Example: `credit_id` under B0, which has no credit
  system, and the R2 label's `status` for the same reason.
- **A field not in the schema** — rejected. The schema is a strict allow-list.

The two empty values are not interchangeable and the validator will not
accept one where the schema allows only the other. Concretely: `credit_id:
null` under B0 is a validation error, because it would claim a credit exists
whose identity we failed to record.

### 3.5 Failed and rejected operations are data

Nothing is dropped for being a negative result:

- A UserOperation that was never included is recorded in `public_events` with
  `outcome: "not_included"` and every inclusion field `null` **only if a
  public observer could actually see it** — i.e. it was exposed by a public
  UserOperation mempool or RPC (tier A1). An operation submitted to a private
  bundler and never included was seen by no A0/A1 observer and appears only
  in `bundler_private`. (Corrected in 2.0.0: the 1.0.0 fixtures recorded a
  public row for a privately rejected operation; the real B2 runs showed no
  such observation exists.)
- A rejected operation is recorded in `bundler_private` with its
  `rejection_category`; the rejection-reason distribution is a reported
  liveness metric (`docs/research-plan.md` §9.3).
- A relation with no link for a given subject is recorded with label
  `status: "absent"` and `true_value: null` — a true negative, not an absence
  of data.

---

## 4. Reproducibility metadata

### 4.1 `software_revision` — never a manufactured commit

Every row carries a `software_revision` object. There are exactly two honest
shapes:

```json
{"kind": "git_commit", "git_commit": "<40 hex>", "git_dirty": false,
 "worktree_id": null, "describe": "clean worktree at d641d306e763"}
```

```json
{"kind": "git_worktree", "git_commit": "<40 hex or null>", "git_dirty": true,
 "worktree_id": "<sha256>", "describe": "uncommitted worktree (...)"}
```

`git_commit` is used only when git actually reports a HEAD **and** the
worktree is clean. Otherwise — uncommitted changes, or a repository with no
commits yet — the row says `git_worktree` and carries a sha256 over the real
working-tree state (`git status --porcelain` plus the staged and unstaged
diffs). A commit hash is never invented, and the validator rejects
inconsistent combinations (e.g. `kind: "git_commit"` with `git_dirty: true`).
Every git call is read-only and passes `--no-optional-locks`.

### 4.2 Run manifests

`run_manifest.public.json` carries: `experiment_id`, `run_id`, `baseline_id`
and its description, `workload_id`, `chain_id`, `data_origin`,
`software_revision`, `started_at_utc`, `finished_at_utc`, `tool_versions` and
the full raw text of `scripts/env-report.sh`, `seed_commitment_sha256`,
`streams`, `notes`, and `components`:

```json
"components": {
  "entrypoint": {"address": "0x...", "version": "0.9.0"},
  "account_implementation": {"kind": "erc4337_smart_account", "version": "..."},
  "paymaster": {"kind": "observable_paymaster", "address": "0x...",
                "version": "...", "privacy_mechanism": null},
  "asset": {"kind": "erc20", "address": "0x...", "decimals": 18},
  "destination": "0x..."
}
```

Tool versions come from `scripts/env-report.sh` — the repository's existing
single source of version truth — not from a competing implementation.

`components` is not schema-validated. Measured W1 runs add `bundler`,
`fee_policy`, `chain_environment`, `transfer_amount`, `matched_config_sha256`
and deployed-bytecode digests (`experiments/workloads/w1/recording.py`);
addresses inside it follow the lowercase rule.

`run_manifest.private.json` carries the same run identity plus the **seed**.

### 4.3 `data_origin`

Every row declares `"measured"` or `"synthetic_fixture"`, and the validator
requires a `synthetic-` run_id prefix for the latter and forbids it for the
former. A fixture can therefore never be read as a measurement, and the check
is mechanical rather than a naming convention.

---

## 5. `ground_truth.jsonl` — SECRET

The answer key. Written to `data/private/` (gitignored). Never an attacker
input; the only sanctioned consumer is `experiments.labels`.

**Hidden identifiers are opaque handles, never on-chain values.** An id like
`actor_a17f3c` is accepted; anything address- or hex-shaped is rejected. Two
reasons: a hidden id that *was* an address would legitimately appear in
public output, making the value-leak scan (§8.5) unable to tell leakage from
normal recording; and it keeps "who this is" structurally distinct from
"which address this is". The bridge from a handle to its on-chain values is
`public_anchors`, inside this private stream — public data may live in the
private stream, never the reverse.

**Multiple accounts are not multiple people.** `actor_id` is the identity;
`stealth_account_id`, `established_wallet_id`, `funding_wallet_id` and
`asset_sender_id` are accounts. Many rows may share one `actor_id`, and that
is the normal case. `experiments.labels.loader` exposes `accounts_by_actor`
and `credits_by_actor` and deliberately offers no single-valued inverse that
would imply account↔actor uniqueness. The same holds for credits: several
`credit_id` values per actor is expected, and distinct commitments are not
evidence of distinct honest participants.

<!-- BEGIN GENERATED: ground_truth -->

| Field | Class | Tier | Empty value | Meaning |
|-------|-------|------|-------------|---------|
| `schema_version` | public | A0 | required | Version of this record schema; explicit allow-list. |
| `stream` | public | A0 | required | Which of the three streams this row belongs to. Guards against a row being written to, or concatenated into, the wrong file. |
| `experiment_id` | public | A0 | required | Identifier matching a definition under experiments/. |
| `run_id` | public | A0 | required | One execution of one experiment. UTC-timestamp shaped; prefixed 'synthetic-' for non-measured fixture runs. |
| `record_id` | public | A0 | required | Stable per-row identity, '<run_id>/<stream>/<seq>'. This is the join key that frozen predictions refer to. |
| `seq` | public | A0 | required | 0-based position of this row within its stream for this run. |
| `baseline_id` | public | A0 | required | Which baseline produced the row (B0, B1, B2-Allowlist, B2-Signature, B3-PrivGas-v1, B4..B6). The experimental condition, known to the attacker by construction. |
| `workload_id` | public | A0 | required | Canonical workload (docs/research-plan.md Sec. 4): W1-cold (primary ERC-20 W1; a smart account is deployed by the measured operation), W1-warm (AA-only ablation; account deployed beforehand), W2 ERC-721, W3 native ETH, W4 repeated actions. Like baseline_id this is an experimental condition the attacker knows by construction, not a hidden label. |
| `scenario_id` | public | A0 | required | Opaque identifier for the scenario / candidate set this row belongs to. Must carry no meaning: it is visible to the attacker, so an id like 'actor7-links-wallet3' would be a label leak. null only where a row is genuinely not scenario-scoped. |
| `software_revision` | public | A0 | required | Reproducibility identity of the code that produced the row: a real commit SHA when the worktree is clean, otherwise an explicit working-tree digest. Never a manufactured hash. |
| `data_origin` | public | A0 | required | 'measured' for rows derived from an actual execution; 'synthetic_fixture' for hand-written examples and test data. Synthetic rows are confined to run_ids prefixed 'synthetic-'. |
| `recorded_at_utc` | public | A0 | required | When the recorder wrote the row (harness wall clock). Distinct from block_timestamp_utc, which is chain time. |
| `seed` | secret | — | required | RNG seed for the run. SECRET: the seed determines the hidden assignment of actors to accounts and to timing, so it is the answer key in compressed form. The public run manifest carries only a commitment to it. |
| `subject_kind` | secret | — | required | What this ground-truth row is about: one operation, one stealth account, one issuance, or one funding event. |
| `actor_id` | secret | — | `null` / `not_applicable` ok | The hidden person/entity. Many accounts may map to one actor_id; nothing may infer otherwise. Opaque hidden handle. 'not_applicable' where the concept does not exist for this baseline; null where it exists but was not determined for this row. |
| `established_wallet_id` | secret | — | `null` / `not_applicable` ok | The actor's pre-existing, publicly known wallet (W). Opaque hidden handle. 'not_applicable' where the concept does not exist for this baseline; null where it exists but was not determined for this row. |
| `economic_funding_source_id` | secret | — | `null` / `not_applicable` ok | The ECONOMIC funding source (P): the wallet whose ETH supplied the balance that paid this operation's gas -- B0: the wallet that sent ETH to the recipient EOA; B1: the wallet that funded the smart account / its EntryPoint deposit; B2: the sponsor wallet that funded the Paymaster's EntryPoint deposit. Never the Paymaster contract or the charged account itself. Replaces 1.0.0-3.0.0 'funding_wallet_id'. Opaque hidden handle. 'not_applicable' where the concept does not exist for this baseline; null where it exists but was not determined for this row. |
| `immediate_gas_payer_kind` | public | A0 | required | Which balance the execution mechanism directly charged: 'eoa_balance', 'smart_account_entrypoint_deposit' or 'paymaster_entrypoint_deposit'. Public context (recoverable from the transaction or UserOperationEvent), kept separate from the hidden economic funding source. |
| `asset_sender_id` | secret | — | `null` / `not_applicable` ok | The account that sent the non-native asset to the stealth account. Distinct from economic_funding_source_id by design (they may coincide in value, as in B0/B1, without being the same concept). Opaque hidden handle. 'not_applicable' where the concept does not exist for this baseline; null where it exists but was not determined for this row. |
| `stealth_account_id` | secret | — | `null` / `not_applicable` ok | The fresh stealth-controlled account (S). Opaque hidden handle. 'not_applicable' where the concept does not exist for this baseline; null where it exists but was not determined for this row. |
| `credit_id` | secret | — | `null` / `not_applicable` ok | The hidden credit/note (C). 'not_applicable' for baselines with no credit system (B0/B1/B2). Opaque hidden handle. 'not_applicable' where the concept does not exist for this baseline; null where it exists but was not determined for this row. |
| `issuance_id` | secret | — | `null` / `not_applicable` ok | The issuance event (I) that created the credit. 'not_applicable' for baselines with no credit system. Opaque hidden handle. 'not_applicable' where the concept does not exist for this baseline; null where it exists but was not determined for this row. |
| `payer_to_operation_label` | secret | — | required | R1 answer key: which ECONOMIC funding source P is truly associated with operation O (not the immediate gas payer, which is public context). |
| `issuance_to_redemption_label` | secret | — | required | R2 answer key: which issuance event I truly supplied the authorization consumed by O. |
| `stealth_to_actor_label` | secret | — | required | R3 answer key: which actor A / established wallet W the stealth account S truly belongs to. |
| `public_anchors` | secret | — | required | Public on-chain values that identify this row's subject in the attacker-visible streams. The bridge used by the post-freeze evaluation join, and the only place a hidden handle is tied to an address. |

<!-- END GENERATED: ground_truth -->

### 5.0 R1: economic funding source vs. immediate gas payer (4.0.0)

R1 is **economic funding source ↔ operation** (`docs/threat-model.md`). The
ground truth records the two concepts separately:

| Concept | Field(s) | Visibility | B0 | B1 | B2-Allowlist / B2-Signature |
|---|---|---|---|---|---|
| immediate gas payer | `immediate_gas_payer_kind`, `public_anchors.immediate_gas_payer_address` | public context | `eoa_balance` — recipient EOA | `smart_account_entrypoint_deposit` — the SimpleAccount | `paymaster_entrypoint_deposit` — the Paymaster contract |
| economic funding source | `economic_funding_source_id` (hidden handle), `public_anchors.economic_funding_address` | **hidden R1 answer** | wallet that sent ETH to the EOA | wallet that funded the account / its deposit | sponsor wallet that funded the Paymaster's EntryPoint deposit |
| subject operation | `payer_to_operation_label.subject_ref` | public anchor | action tx hash | userop hash | userop hash |

The R1 label's `true_value` is the economic funding source handle. The
validator requires `immediate_gas_payer_kind` to match the baseline's
mechanism and rejects a sponsored row whose economic funding address equals the
Paymaster (`payer_conflation`). `funding_wallet_id` / `funding_address`
(1.0.0–3.0.0) no longer exist; `funding_wallet_id` stays on the public-key
denylist as an alias. The funding source is defined one hop back (the wallet
that directly funded the charged balance); where that wallet's own ETH came
from (e.g. a devnet faucet) is part of the public trace, not of the label.

**B3-PrivGas-v1 (5.0.0).** Both of its operations are charged to a Paymaster
deposit (`paymaster_entrypoint_deposit`: BootstrapPaymaster for Bootstrap,
CreditPaymaster for Spend); the economic funding source of both is the sponsor
wallet that funded those deposits with `EntryPoint.depositTo`. The asset sender's
forwarded `vMin` pays no gas and the admission fee is burned, so neither is a
one-hop funder (`docs/b3-evaluation.md` §8).

### 5.1 Relation labels

The three relation labels have one uniform shape so evaluation code can treat
them generically, and so a new baseline (B4/B5) needs no schema change:

```json
{"relation": "R1", "status": "observed",
 "subject_ref": "<attacker-visible anchor>",
 "true_value": "<hidden opaque handle>",
 "candidate_set_id": "<opaque>"}
```

| Field | Meaning |
|-------|---------|
| `relation` | `"R1"`, `"R2"` or `"R3"`, and must match the field it appears in. R1/R2/R3 are reported separately and never collapsed into one "unlinkability" number. |
| `status` | `"observed"` — the relation exists and `true_value` is the answer. `"absent"` — the relation is defined for this baseline but this subject has no link (a true negative; `true_value` is `null`, `subject_ref` is still required). `"not_applicable"` — the relation does not exist for this baseline at all; every other sub-field is `null`. |
| `subject_ref` | The attacker-visible anchor the label answers about — a `userop_hash`, a `transaction_hash`, or a `record_id`. This is the join key against frozen predictions. |
| `true_value` | The hidden opaque handle that is the correct answer. |
| `candidate_set_id` | Which candidate set the answer lives in, so top-k and effective-candidate-set-size are computable. |

The definitions of R1, R2 and R3 themselves are in `docs/threat-model.md`;
this table defines only how an answer is recorded.

Baseline consistency is enforced: a baseline with no credit lifecycle
(B0/B1/B2) must have R2 `status: "not_applicable"` and `credit_id` /
`issuance_id` equal to `"not_applicable"`. A baseline that does have one
(B3/B4/B5) may not use `"not_applicable"` for R2 — a subject with no link
uses `"absent"`.

---

### 5.2 R2 anchors (5.0.0)

For a baseline with a credit lifecycle, `public_anchors` carries the public
values the post-freeze R2 join needs: `issuance_transaction_hash` and
`issuance_userop_hash` (the operation that issued the credit — B3's Bootstrap),
`credit_commitment` (the deposited commitment) and `credit_nullifier` (the
nullifier revealed at redemption). All four are public on chain; **which
issuance a redemption consumed** is the secret, and it exists only in this
private stream (`issuance_to_redemption_label`, `credit_id`, `issuance_id`).
The validator requires all four for an observed R2 label and forbids them for
baselines without a credit system. B3 records two ground-truth rows per run:
the Spend operation (R2 observed) and the Bootstrap operation (R2 `absent` —
it redeems nothing; the negative is kept).

## 6. `public_events.jsonl` — tiers A0 / A1

Only values recoverable by someone with an ordinary archive node and, for A1,
ordinary public visibility of UserOperations. If a value needs an instrumented
bundler it belongs in §7; if it answers a linkage question it belongs in §5.
`observer_tier` is `"A0"` or `"A1"`; `"A2"` is rejected in this stream.

**Tier of included UserOperations (corrected in 2.0.0).** Every field of an
included UserOperation is in the mined `handleOps` calldata, and its outcome is
in EntryPoint logs, so rows derived from mined data are `"A0"` —
`docs/research-plan.md` §7 lists "on-chain UserOperations" under A0. `"A1"` is
only for rows obtained from a public UserOperation mempool/RPC before or
without inclusion. The 1.0.0 field tables and fixtures marked the ERC-4337
fields and mined UserOperation rows A1. The in-repo bundler used by B1/B2
exposes no public mempool, so current measured runs contain no A1 rows at all.

**The complete public trace (4.0.0).** Cost accounting and privacy observation
have different boundaries. A transaction excluded from a measured cost window
(faucet funding, contract deployments, a sponsor's Paymaster deposit, a warm-up
operation) is still public and can establish linkage, so **every mined
transaction of a run is recorded**, whatever the run calls its phase. Each row
carries `trace_phase` — `infrastructure`, `funding`, `authorization`,
`application` or `settlement` — which the validator requires to be a
deterministic function of the row's own `event_type` / `calldata_class`
(`TRACE_PHASE_RULES`): it is never a role or intent label ("funding" means
native value moved into an account or EntryPoint deposit, by whomever). Whether
a row lies inside the measured cost window is experiment metadata and is
written privately (`data/private/.../w1_cost_window.json`), never in this
stream.

**B3-PrivGas-v1 rows (5.0.0).** `announceAndFund` → `eoa_transaction` /
`stealth_announce_and_fund` [funding], `stealth_announcement` [authorization],
two `sponsorship_eligibility` [authorization], `native_transfer` registry →
account (forwarded `vMin`) [funding] and `native_transfer` / `fee_burn` registry
→ `address(0)` [authorization]; `EntryPoint.depositTo` → `paymaster_event` /
`paymaster_deposit` [funding] with the Paymaster in `subject_account`; inside
bundles `paymaster_event` / `paymaster_sponsorship`, `privacy_pool_event` /
`pool_root_update` (`merkle_root`), `pool_deposit` (`commitment`, `merkle_root`)
and `pool_redeem` (`nullifier`, the proof's `merkle_root`, `proof_metadata`)
[authorization, funding, authorization]. Every UserOperation row keeps its real
`sender`, so Bootstrap and Spend from one account are visible as such.

**Row structure of a real W1 run** (`experiments/workloads/w1/recording.py`):
one row per transaction, classified from on-chain content only
(`eoa_transaction`/`contract_creation` with the created contract in
`subject_account`, `asset_transfer`, `native_transfer`,
`paymaster_event`/`paymaster_deposit` followed by its `entrypoint_deposit`,
`paymaster_event`/`paymaster_policy`); a bundle transaction
yields an `eoa_transaction` row with calldata class `entrypoint_handle_ops`
(the bundle's own receipt gas), followed by one row per relevant log in log
order: `account_deployment`, `entrypoint_deposit`, `asset_transfer`,
`user_operation_event`. On a `user_operation_event` row `actual_gas_used` /
`actual_gas_cost` are the EntryPoint's per-operation figures, which differ
from the bundle transaction's receipt gas. EntryPoint v0.9.0 emits **no log**
when it debits or refunds a deposit during `handleOps`; that movement is
recoverable from `actual_gas_cost` (and archive state), not from an event, so
no row is fabricated for it.

Publicly visible privacy-protocol artefacts (`commitment`, `merkle_root`,
`nullifier`, `pool_id`, `proof_metadata`) belong here when they are on chain.
Recording them makes no claim that they are unlinkable — measuring that is the
experiment's job.

`proof_metadata` is a closed sub-schema (`scheme`, `verifier_address`,
`public_signal_count`, `proof_byte_length`, `tree_depth`) rather than a
free-form object, because an unconstrained bag would be the easiest place for
a hidden identifier to arrive under a new name.

`amount_bucket` is always `null` at recording time. Bucketing is an analysis
decision; computing it downstream keeps the boundaries visible in the analysis
code rather than frozen into the raw record.

<!-- BEGIN GENERATED: public_events -->

| Field | Class | Tier | Empty value | Meaning |
|-------|-------|------|-------------|---------|
| `schema_version` | public | A0 | required | Version of this record schema; explicit allow-list. |
| `stream` | public | A0 | required | Which of the three streams this row belongs to. Guards against a row being written to, or concatenated into, the wrong file. |
| `experiment_id` | public | A0 | required | Identifier matching a definition under experiments/. |
| `run_id` | public | A0 | required | One execution of one experiment. UTC-timestamp shaped; prefixed 'synthetic-' for non-measured fixture runs. |
| `record_id` | public | A0 | required | Stable per-row identity, '<run_id>/<stream>/<seq>'. This is the join key that frozen predictions refer to. |
| `seq` | public | A0 | required | 0-based position of this row within its stream for this run. |
| `baseline_id` | public | A0 | required | Which baseline produced the row (B0, B1, B2-Allowlist, B2-Signature, B3-PrivGas-v1, B4..B6). The experimental condition, known to the attacker by construction. |
| `workload_id` | public | A0 | required | Canonical workload (docs/research-plan.md Sec. 4): W1-cold (primary ERC-20 W1; a smart account is deployed by the measured operation), W1-warm (AA-only ablation; account deployed beforehand), W2 ERC-721, W3 native ETH, W4 repeated actions. Like baseline_id this is an experimental condition the attacker knows by construction, not a hidden label. |
| `scenario_id` | public | A0 | `null` ok | Opaque identifier for the scenario / candidate set this row belongs to. Must carry no meaning: it is visible to the attacker, so an id like 'actor7-links-wallet3' would be a label leak. null only where a row is genuinely not scenario-scoped. |
| `software_revision` | public | A0 | required | Reproducibility identity of the code that produced the row: a real commit SHA when the worktree is clean, otherwise an explicit working-tree digest. Never a manufactured hash. |
| `data_origin` | public | A0 | required | 'measured' for rows derived from an actual execution; 'synthetic_fixture' for hand-written examples and test data. Synthetic rows are confined to run_ids prefixed 'synthetic-'. |
| `recorded_at_utc` | public | A0 | required | When the recorder wrote the row (harness wall clock). Distinct from block_timestamp_utc, which is chain time. |
| `observer_tier` | public | A0 | required | Lowest adversary tier that could have obtained this row: 'A0' for anything derived from mined blocks, transactions, logs or archive state -- including included UserOperations, whose fields are all in the handleOps calldata; 'A1' only for rows obtained from a public UserOperation mempool/RPC. 'A2' is rejected here -- bundler observations live in a separate stream and directory. |
| `chain_id` | public | A0 | required | EIP-155 chain id as a JSON integer. A string chain id is rejected: mixed representations break cross-run joins. |
| `block_number` | public | A0 | `null` ok | Block containing the event; null if never included. |
| `block_hash` | public | A0 | `null` ok | Block hash; null if never included. |
| `block_timestamp_utc` | public | A0 | `null` ok | Chain time of the containing block. Distinct from recorded_at_utc (harness wall clock). |
| `transaction_index` | public | A0 | `null` ok | Position of the transaction within its block; part of the block-position signal in the D1 attack ladder. |
| `log_index` | public | A0 | `null` ok | Position of the log within the block, where the row comes from a log. |
| `transaction_hash` | public | A0 | `null` ok | Enclosing transaction hash; null if never included. |
| `userop_hash` | public | A0 | `null` ok | EntryPoint UserOperation hash. A0 once included (it is indexed in UserOperationEvent). Null for non-AA baselines and for rows that are not about a UserOperation. |
| `entrypoint_address` | public | A0 | `null` ok | EntryPoint contract the operation targeted. |
| `entrypoint_version` | public | A0 | `null` ok | EntryPoint semantic version, e.g. '0.9.0'. Recorded per row because gas accounting and the field set differ across versions. |
| `factory` | public | A0 | `null` ok | Account factory from initCode, where the operation deployed the account. |
| `sender` | public | A0 | `null` ok | The account the operation/transaction originates from. For an AA row this is the smart account, not the bundler EOA. |
| `paymaster` | public | A0 | `null` ok | Sponsoring Paymaster. Null where the baseline has none -- for B1 this is null by construction, not merely unknown. |
| `target` | public | A0 | `null` ok | Contract or account the application action addresses. |
| `subject_account` | public | A0 | `null` ok | Account an on-chain event is about when it is neither the row's sender nor its target: the account named in a Paymaster allowlist log, or the account credited by an EntryPoint Deposited log. Added in 2.0.0 because an ordinary allowlist Paymaster publishes the sponsored account before the operation, and the 1.0.0 schema had nowhere to record it. |
| `bundler_beneficiary` | public | A0 | `null` ok | Beneficiary address paid by the EntryPoint. Public on chain -- this is NOT bundler-private data. |
| `method_selector` | public | A0 | `null` ok | 4-byte selector of the public call. |
| `calldata_class` | public | A0 | `null` ok | Coarse class of the public calldata. A class rather than raw calldata so the field cannot become a dumping ground. |
| `nonce` | public | A0 | `null` ok | Account nonce as a decimal uint256 string. For ERC-4337 v0.7+ this is the full 256-bit key\|\|sequence value, which is why it is a string and not a JSON number. |
| `asset_type` | public | A0 | required | Kind of value moved by this event. |
| `asset_contract` | public | A0 | `null` ok | Token contract; null for native value. |
| `asset_amount` | public | A0 | `null` ok | Amount in base units as a decimal uint256 string. |
| `asset_token_id` | public | A0 | `null` ok | ERC-721 token id as a decimal uint256 string. |
| `amount_bucket` | public | A0 | `null` ok | Derived coarse bucket of asset_amount. Always null at recording time: bucketing is an analysis decision and is computed downstream so the boundaries are visible in the analysis code, not frozen into the raw record. |
| `max_fee_per_gas` | public | A0 | `null` ok | UserOperation maxFeePerGas, wei, decimal string. |
| `max_priority_fee_per_gas` | public | A0 | `null` ok | UserOperation maxPriorityFeePerGas, wei. |
| `verification_gas_limit` | public | A0 | `null` ok | UserOperation verificationGasLimit. |
| `call_gas_limit` | public | A0 | `null` ok | UserOperation callGasLimit. |
| `pre_verification_gas` | public | A0 | `null` ok | UserOperation preVerificationGas. |
| `paymaster_verification_gas_limit` | public | A0 | `null` ok | EntryPoint v0.7+ paymasterVerificationGasLimit. Null under v0.6, where paymasterAndData is not decomposed. |
| `paymaster_post_op_gas_limit` | public | A0 | `null` ok | EntryPoint v0.7+ paymasterPostOpGasLimit. Null under v0.6. |
| `actual_gas_used` | public | A0 | `null` ok | Gas actually consumed. For a user_operation_event row this is UserOperationEvent.actualGasUsed (includes preVerificationGas and any unused-gas penalty) and differs from the enclosing bundle transaction's receipt gasUsed, which is recorded on the entrypoint_handle_ops row. |
| `actual_gas_cost` | public | A0 | `null` ok | Wei actually charged. For a user_operation_event row this is UserOperationEvent.actualGasCost (a transfer from the payer's EntryPoint deposit to the beneficiary); for a transaction row it is gasUsed * effectiveGasPrice. |
| `effective_gas_price` | public | A0 | `null` ok | Effective gas price of the enclosing transaction, wei. |
| `success` | public | A0 | `null` ok | Execution result. Null where the operation was never included. A failed operation is kept, never dropped. |
| `revert_reason_class` | public | A0 | `null` ok | Coarse class of the public revert reason. A class rather than the raw string, which can carry arbitrary content. |
| `outcome` | public | A0 | required | Overall disposition of the row's subject. |
| `event_type` | public | A0 | required | What kind of observation this row is. |
| `trace_phase` | public | A0 | required | Coarse content-derived classification: infrastructure (deployments), funding (native value into an account or EntryPoint deposit; a stealth announce-and-fund call; a credit pool deposit), authorization (paymaster policy calls, sponsorship and eligibility logs, stealth announcements, fee burns, pool root updates and credit redemptions), application (asset transfers), settlement (bundles and UserOperation outcomes). A deterministic function of event_type and calldata_class, never a role or intent label; whether a row lies in a measured cost window is recorded privately, not here. Added in 4.0.0 so the complete public trace -- including setup-time transactions -- is recorded. |
| `commitment` | public | A0 | `null` ok | Publicly emitted commitment, 0x 32-byte hex. Public because it is on chain -- recording it makes no claim that it is unlinkable. |
| `merkle_root` | public | A0 | `null` ok | Publicly visible Merkle root the operation proved against. |
| `nullifier` | public | A0 | `null` ok | Publicly emitted nullifier. |
| `pool_id` | public | A0 | `null` ok | Public pool / group identifier. |
| `proof_metadata` | public | A0 | `null` ok | Publicly visible proof metadata (scheme, verifier, sizes). Closed sub-schema on purpose. |

<!-- END GENERATED: public_events -->

### 6.1 ERC-4337 version note (recorded ambiguity, not a guess)

The fee/gas field set follows EntryPoint **v0.7 / v0.8 / v0.9**, where the
account's gas limits and the paymaster's are separate and `paymasterAndData`
is decomposed into `paymaster`, `paymasterVerificationGasLimit` and
`paymasterPostOpGasLimit`. The B3 specimen vendored in this repository pins
`@account-abstraction/contracts@0.9.0` (`docs/b3-reproduction.md`).

Under **EntryPoint v0.6** the two paymaster gas-limit fields do not exist as
separate values. For a v0.6 run, record them as `null` and record the real
version in `entrypoint_version`; do not split `paymasterAndData` by guesswork.
`entrypoint_version` is per-row, not per-run, because gas accounting differs
across versions and a mixed-version comparison would be invalid.

### 6.2 Baseline capability rules

Derived from `docs/research-plan.md` §5 and enforced by the validator
(`experiments/recorder/baselines.py`):

| Baseline | ERC-4337 | Bundler | Paymaster | Credit system | Privacy artefacts |
|----------|----------|---------|-----------|---------------|--------------------|
| B0 sender-funded EOA | no | no | no | no | no |
| B1 sender-funded smart account | yes | yes | no | no | no |
| B2-Allowlist observable allowlist Paymaster (auxiliary) | yes | yes | yes | no | no |
| B2-Signature signature-verifying Paymaster | yes | yes | yes | no | no |
| B3-PrivGas-v1 frozen PrivGas v1 specimen (`b3_compat_local` profile only) | yes | yes | yes | yes | yes |
| B4 independent credit (reserved) | yes | yes | yes | yes | yes |
| B5 prior-art prepaid (reserved) | yes | yes | yes | yes | yes |
| B6 shielded-pool reference (reserved, provisional) | no | no | no | yes | yes |

A record that populates a field its baseline does not have is rejected. A B0
row carrying a `userop_hash` fails, because a fabricated UserOperation would
make B0 look like an account-abstraction baseline and would invent exactly the
sponsorship metadata D1 exists to isolate. The B0, B1, B2-Allowlist and
B2-Signature rows were confirmed against the real implementations
(`baselines/w1_b0_b2`, 2026-09-14): all five flags held for each. The
B3-PrivGas-v1 row was confirmed against measured runs of the unmodified specimen
(`docs/b3-evaluation.md`, 2026-09-15): it uses ERC-4337, the in-repo bundler, two
Paymasters, a credit lifecycle, and publishes commitment, root, nullifier and
proof metadata. Rows for B4–B6 are reserved: the capability flags encode the plan,
not an implementation, and B6's in particular must be confirmed against real
code before use.

---

## 7. `bundler_private.jsonl` — tier A2

Only for a bundler or RPC service we operate, or have written permission to
log. Nothing here may be assumed known to an A0/A1 observer.

**A baseline with no bundler produces no rows here at all** — not an empty
file. B0 executes a plain transaction: there is no mempool admission, no
simulation and no replacement lineage, and the recorder does not even create
the `observer_a2/` directory for it. An empty file would read as "we looked
and saw nothing", which is a different and false claim.

The raw bundler error message is deliberately not recorded. Implementations
embed addresses, calldata and internal state in error strings, which would
move uncontrolled content into an attacker-readable stream;
`rejection_message_class` records a coarse class instead.

**Mined bundle hashes are public (corrected in 2.0.0).** The hash of a mined
bundle transaction is on chain and is recorded in
`public_events.transaction_hash`. What an instrumented bundler knows that no
public observer does is the *pre-inclusion association*: that a given
UserOperation was placed in a bundle transaction it signed and broadcast, when,
and under which hash — including bundles later replaced or dropped. That is
`bundle_submission_timestamp_utc` and `submitted_bundle_transaction_hash`.
1.0.0 had a single `bundle_transaction_hash` field classified bundler-private,
which wrongly made a public on-chain value look A2-only.

<!-- BEGIN GENERATED: bundler_private -->

| Field | Class | Tier | Empty value | Meaning |
|-------|-------|------|-------------|---------|
| `schema_version` | public | A0 | required | Version of this record schema; explicit allow-list. |
| `stream` | public | A0 | required | Which of the three streams this row belongs to. Guards against a row being written to, or concatenated into, the wrong file. |
| `experiment_id` | public | A0 | required | Identifier matching a definition under experiments/. |
| `run_id` | public | A0 | required | One execution of one experiment. UTC-timestamp shaped; prefixed 'synthetic-' for non-measured fixture runs. |
| `record_id` | public | A0 | required | Stable per-row identity, '<run_id>/<stream>/<seq>'. This is the join key that frozen predictions refer to. |
| `seq` | public | A0 | required | 0-based position of this row within its stream for this run. |
| `baseline_id` | public | A0 | required | Which baseline produced the row (B0, B1, B2-Allowlist, B2-Signature, B3-PrivGas-v1, B4..B6). The experimental condition, known to the attacker by construction. |
| `workload_id` | public | A0 | required | Canonical workload (docs/research-plan.md Sec. 4): W1-cold (primary ERC-20 W1; a smart account is deployed by the measured operation), W1-warm (AA-only ablation; account deployed beforehand), W2 ERC-721, W3 native ETH, W4 repeated actions. Like baseline_id this is an experimental condition the attacker knows by construction, not a hidden label. |
| `scenario_id` | public | A0 | `null` ok | Opaque identifier for the scenario / candidate set this row belongs to. Must carry no meaning: it is visible to the attacker, so an id like 'actor7-links-wallet3' would be a label leak. null only where a row is genuinely not scenario-scoped. |
| `software_revision` | public | A0 | required | Reproducibility identity of the code that produced the row: a real commit SHA when the worktree is clean, otherwise an explicit working-tree digest. Never a manufactured hash. |
| `data_origin` | public | A0 | required | 'measured' for rows derived from an actual execution; 'synthetic_fixture' for hand-written examples and test data. Synthetic rows are confined to run_ids prefixed 'synthetic-'. |
| `recorded_at_utc` | public | A0 | required | When the recorder wrote the row (harness wall clock). Distinct from block_timestamp_utc, which is chain time. |
| `observer_tier` | bundler_private | A2 | required | Always 'A2'. This stream exists because the data requires an instrumented bundler; no A0/A1 observer has it. |
| `bundler_id` | bundler_private | A2 | required | Which instrumented bundler produced the observation. Required: a two-bundler experiment (docs/research-plan.md Sec. 13) is meaningless without it. |
| `userop_hash` | bundler_private | A2 | required | The operation observed. This is the join key against public_events for an A2 attacker. |
| `sender` | bundler_private | A2 | required | Smart account the operation claims as sender. |
| `nonce` | bundler_private | A2 | required | Full 256-bit nonce as a decimal string. |
| `submission_attempt` | bundler_private | A2 | required | 1-based attempt counter for this logical operation. |
| `receive_timestamp_utc` | bundler_private | A2 | required | When the bundler received the operation. |
| `simulation_timestamp_utc` | bundler_private | A2 | `null` ok | When validation simulation ran; null if it never ran. |
| `simulation_result` | bundler_private | A2 | required | Outcome of the bundler's validation simulation. |
| `rejection_category` | bundler_private | A2 | `null` ok | Why the operation was rejected; null when it was not. Rejections are recorded, never discarded. |
| `rejection_message_class` | bundler_private | A2 | `null` ok | Coarse class of the bundler's message. The raw message is deliberately not recorded: implementations embed addresses and internal state in error strings. |
| `replacement_lineage` | bundler_private | A2 | `null` ok | Ordered prior userop hashes this operation replaced. An empty list means 'observed, no replacement'; that is not the same as null, which would mean 'lineage not observed'. |
| `replacement_count` | bundler_private | A2 | `null` ok | Length of replacement_lineage; kept as its own field because it is a reported liveness metric. |
| `inclusion_timestamp_utc` | bundler_private | A2 | `null` ok | When the bundler observed the operation included on chain; null if it never was. |
| `bundle_submission_timestamp_utc` | bundler_private | A2 | `null` ok | When the bundler broadcast the bundle transaction that carried this operation; null if it never submitted one. |
| `submitted_bundle_transaction_hash` | bundler_private | A2 | `null` ok | The bundler's PRE-INCLUSION association between this operation and the bundle transaction it signed and broadcast; null if it never submitted one. The A2 knowledge is the association before mining (and for bundles that are later replaced or dropped). A MINED bundle transaction hash is public on chain and is recorded in public_events.transaction_hash; this field does not make it private. Replaces 1.0.0 'bundle_transaction_hash', which classified the mined hash as bundler-private. |
| `rpc_endpoint_id` | bundler_private | A2 | `null` ok | Opaque identifier of the RPC endpoint used. Opaque, not a URL: URLs carry credentials and host identity. |

<!-- END GENERATED: bundler_private -->

### 7.1 Recorded ERC-4337 ambiguity

"Rejection" spans at least three distinct situations:

1. a bundler-local policy or reputation drop (ERC-7562 throttling),
2. a `simulateValidation` revert,
3. an operation that simulated cleanly but failed on-chain inclusion.

`simulation_result` plus `rejection_category` distinguish (1) and (2); (3)
appears as an included-but-failed row in `public_events`. Where a bundler
implementation does not let us tell them apart, `rejection_category` is
`"other"` and `rejection_message_class` records which coarse class the
bundler reported. **These are not to be collapsed into one "failure" count.**

`replacement_lineage: []` means "observed, and there was no replacement".
`replacement_lineage: null` means "we did not observe the lineage at all".
Those are different facts and the schema keeps them different.

---

## 8. Privacy separation: what is enforced, and how

### 8.1 Schema-level

The public streams are a strict allow-list, so an unknown field is rejected
outright. On top of that, a denylist (`experiments/recorder/privatekeys.py`)
rejects the known private field names — `actor_id`, `established_wallet_id`,
`funding_wallet_id`, `asset_sender_id`, `stealth_account_id`, `credit_id`,
`issuance_id`, the three relation-label fields, `seed`, and generic aliases
such as `label` and `true_value` — **at any nesting depth**, with an error
that names the actual problem rather than "unknown field".

### 8.2 The research boundary: what it rests on, and what is only defence in depth

The separation between attacker-visible data and secret ground truth rests on
four things. **It does not rest on the import hook described at the end of
this section.**

1. **Distinct data paths.** Ground truth, the private manifest (seed) and the
   role/cost files exist only under `data/private/` (gitignored). A0/A1 and A2
   observations live in separate `observer_a0a1/` and `observer_a2/`
   directories under `data/public/` (§3.1).
2. **Distinct reader APIs.** Attack code reads through
   `experiments.attacker_view` (`load_run` requires the observer tier to be
   named explicitly and returns bundler rows only for A2). Evaluation reads
   through `experiments.labels`. Neither API offers the other side's data.
3. **An explicit attack/evaluation process boundary.** Predictions are frozen
   with a sha256 by the attack process; evaluation runs as a separate process,
   verifies the digest, and only then loads labels (§8.4).
4. **Validation and path guards.** Strict schema allow-lists and the
   private-key denylist at write time (§8.1); `attacker_view` refuses any path
   under `data/private/` and any file named `ground_truth.jsonl` or
   `run_manifest.private.json` wherever it has been moved to;
   `load_public_manifest` refuses a manifest carrying a non-null `seed`; the
   leakage self-check scans published output (§8.5).

**Defence in depth only — the import hook.** Importing `experiments.attacker_view`
or `experiments.labels` claims that side for the whole Python process, and
importing the other then raises `BoundaryViolation` (a `sys.meta_path` finder
refuses to resolve the opposite package, including via `importlib`).
`experiments/recorder/` is neutral and importable from both. The hook catches
an accidental mixed import early and loudly. It is trivially bypassable
(`open()`, editing `sys.meta_path`, a subprocess), so no claim in this
repository may be argued from it; if it were deleted, items 1–4 would still
hold. (Clarified 2026-09-14; the 1.0.0 text presented the hook as the primary
process-level mechanism.)

### 8.3 The seed is secret

**Ambiguous classification, resolved deliberately.** `docs/research-plan.md`
§10 lists `seed` under `ground_truth.jsonl`, and §1 of this document lists it
in the public per-run metadata. Those conflict once an attack is being run
against the data, because the seed determines the hidden assignment of actors
to accounts and to timing — it is the answer key in compressed form.

Resolution: **`seed` is private.** It lives in `run_manifest.private.json` and
in `ground_truth.jsonl`; the public manifest carries `"seed": null` (an
explicit statement that the value is withheld, not an omission) plus
`seed_commitment_sha256` = `sha256({"namespace": run_id, "value": seed})`.
That pins the seed so a later reveal can be checked without publishing it
during the attack phase. It is **not** a hiding commitment against a
determined adversary — the seed space is small and enumerable — and nothing in
this repository may treat it as a privacy mechanism. Metadata-only runs (§1)
that record no linkage labels may continue to carry the seed in the clear.

### 8.4 Label-join rule

Labels and predictions meet in exactly one function,
`experiments.labels.evaluation.join_for_evaluation`, and only after the
predictions have been frozen:

1. **Process 1** (`experiments.attacker_view`, cannot import labels) reads
   public and, at A2, bundler data; generates features; predicts; calls
   `freeze_predictions`, which writes `predictions.jsonl` plus a manifest
   recording its sha256, the relation (R1/R2/R3), the observer tier, and the
   feature set (`T`, `G`, or `T+G` — `docs/research-plan.md` §9.2).
2. **Process 2** (`experiments.labels`, cannot import attacker_view) verifies
   the manifest exists and that the file still hashes to the recorded digest,
   then loads ground truth and joins.

If the predictions file changed after freezing, the join raises instead of
scoring. Frozen files are never overwritten — re-running an attack takes a new
`attack_id`. The join also reports labelled subjects the attack made no
prediction about, and predicted subjects with no label; silently dropping the
former would inflate precision.

Labels are requested one relation at a time. There is no helper that returns
all three together, because a combined structure invites a single pooled
"unlinkability" score, which this project does not report.

### 8.5 Automated leakage self-check

`python3 -m experiments.labels [--all-runs]` scans `data/public/` in two
passes:

- **Key scan** — every JSON object at any depth, looking for any denylisted
  private field name. Catches output produced by a path that bypassed the
  validator, or files copied in from elsewhere.
- **Value scan** — loads the run's hidden identifiers and relation
  `true_value` answers from `data/private/` and searches the raw text of the
  public files for those exact strings. This is the pass that catches a
  hidden identifier copied into public output under a **renamed key**, which
  the key scan cannot see.

Exit code 1 on any finding, so it can gate a commit or a CI step.
`public_anchors` values are excluded by construction: they are public values
deliberately recorded in the private stream as the join bridge.

### 8.6 What the self-check does *not* prove

It is defence in depth, not a proof that no label information leaks. It cannot
detect a label that has been encoded, hashed, bucketed, permuted, or merely
**correlated** with a public field — and correlation between public features
and hidden relations is precisely what the D1 experiment exists to measure. A
clean run means "no forbidden key and no verbatim hidden identifier appears in
public output", and nothing more. No result in `paper/` or `results/` may cite
it as a privacy finding.

---

## 9. Schema versioning

`schema_version` is `MAJOR.MINOR.PATCH`; the current version is **`5.0.0`**.

### 9.0 Change log

- **`5.0.0`** (2026-09-15) — the frozen B3 specimen becomes measurable
  (`docs/b3-evaluation.md`). MAJOR because an enum value was renamed and a
  closed sub-object gained required keys: `baseline_id` `"B3"` →
  `"B3-PrivGas-v1"` (the id names the unmodified specimen at commit
  `02a3f0ab…`); `public_events` gains event types `stealth_announcement` and
  `sponsorship_eligibility` and calldata classes `stealth_announce_and_fund`,
  `fee_burn`, `paymaster_sponsorship` and `pool_root_update`, each with one
  deterministic `trace_phase` (a `privacy_pool_event` without a pool class is
  now rejected); `ground_truth.public_anchors` gains `issuance_transaction_hash`,
  `issuance_userop_hash`, `credit_commitment` and `credit_nullifier` — required
  for an observed R2 label, null for baselines without a credit system (§5.2).
  Runs gained an evaluation-chain profile (`eip170_standard`,
  `b3_compat_local`) recorded in manifests; compat-profile runs use the
  experiment-id prefix `baselines/b3-compat-local/`. 4.0.0 measured runs were
  archived under `data/private/archive/schema-4.0.0/` after identical
  regeneration was confirmed; synthetic examples were regenerated.

- **`4.0.0`** (2026-09-14) — final pre-Prompt-4 cleanup. MAJOR because fields
  were renamed/split: `ground_truth.funding_wallet_id` →
  `economic_funding_source_id`; new `ground_truth.immediate_gas_payer_kind`;
  `public_anchors.funding_address` → `economic_funding_address` +
  `immediate_gas_payer_address`, with rules (§5.0). `public_events` gains the
  required, content-derived `trace_phase` and calldata class
  `contract_creation`, so the complete public trace (including setup-time
  transactions) is recorded (§6). Attacker-side readers now also refuse
  `data/raw/`. 3.0.0 measured runs archived under
  `data/private/archive/schema-3.0.0/`.

- **`3.0.0`** (2026-09-14) — pre-Prompt-4 baseline hardening
  (`docs/w1-baselines.md`, `docs/decision-log.md`). MAJOR because existing
  enum values split and change meaning: `baseline_id` `"B2"` is removed and
  replaced by `"B2-Allowlist"` (the former B2, now auxiliary) and
  `"B2-Signature"`, so the two ordinary Paymaster designs can never share a
  baseline_id; `workload_id` `"W1"` is removed and replaced by `"W1-cold"`
  (primary; a smart account is deployed by the measured operation) and
  `"W1-warm"` (AA-only ablation; account deployed beforehand). New cross-field
  rule in every stream: `W1-warm` is rejected for baselines without ERC-4337.
  No field was added or removed. 2.0.0 measured runs were archived under
  `data/private/archive/schema-2.0.0/`; synthetic examples were regenerated.

- **`2.0.0`** (2026-09-14) — corrections forced by the first real B0/B1/B2
  runs (`docs/w1-baselines.md` §14, `docs/decision-log.md`). MAJOR because:
  `bundler_private.bundle_transaction_hash` removed and replaced by
  `submitted_bundle_transaction_hash` + `bundle_submission_timestamp_utc`
  (the mined hash is public); the address rule narrowed to lowercase; tier
  annotations of the ERC-4337 fields changed from A1 to A0 for included
  operations. Additive parts: `public_events.subject_account`; event type
  `entrypoint_deposit`; calldata classes `entrypoint_handle_ops` and
  `paymaster_policy`; rejection category `paymaster_validation_revert`; a
  rule that a rejected operation carries no bundle association. Also a
  validator bug fix (fractional-second timestamps). No measured data existed
  under 1.0.0; the synthetic examples were regenerated, not rewritten in
  place, and 1.0.0 rows are not readable by 2.0.0 code.
- **`1.0.0`** (2026-09-14) — initial recorder schema, written before any real
  baseline existed.

| Bump | For | Effect on readers |
|------|-----|-------------------|
| **MAJOR** | removing or renaming a field; narrowing an enum; changing a type, unit or meaning; moving a field between streams; reclassifying a field public↔private | Old readers must **not** accept the new rows. The new version is simply absent from the old code's `SUPPORTED_SCHEMA_VERSIONS`. |
| **MINOR** | adding a new field (with its empty-value semantics documented); adding a member to an open enum; adding a stream | Readers written for an earlier MINOR of the same MAJOR still parse the rows and ignore the new key. |
| **PATCH** | documentation, error messages, validator performance | Nothing about what validates changes. |

Rules:

- Every row carries its own `schema_version`. Records are **never rewritten in
  place** to a new version; re-recording a run produces a new `run_id` so the
  earlier record stays intact.
- `SUPPORTED_SCHEMA_VERSIONS` in `experiments/recorder/version.py` is an
  explicit allow-list. An unknown version is a hard validation failure in both
  directions — too old and too new — not a warning.
- **The semantics of a released version are frozen.** If a definition turns
  out to be wrong, it is corrected under a new MAJOR with a
  `docs/decision-log.md` entry saying why. A field's meaning is never silently
  changed under the same version number.

### 9.1 Differences from `docs/research-plan.md` §10

`research-plan.md` §10 is a sketch; the implemented schema differs in these
ways, all deliberate:

1. **`seed` is private, not public** — §8.3 above.
2. **`intended_relation_labels`** (one aggregate field) is implemented as
   three separate fields, `payer_to_operation_label`,
   `issuance_to_redemption_label` and `stealth_to_actor_label`, so R1/R2/R3
   cannot be collapsed by accident.
3. **`amount bucket`** is not recorded; bucketing happens downstream (§6).
4. **`RPC endpoint/bundler identifier`** is split into `bundler_id`
   (required) and `rpc_endpoint_id` (opaque, optional). A URL is never
   recorded: URLs carry credentials and host identity.
5. Several fields are added that §10 does not list — the shared envelope
   (§3.2), `observer_tier`, `entrypoint_address`/`entrypoint_version`,
   `factory`, the two paymaster gas limits, `bundler_beneficiary`,
   `revert_reason_class`, `submission_attempt`,
   `submitted_bundle_transaction_hash`, `bundle_submission_timestamp_utc`,
   `subject_account`.

---

## 10. Known limitations

1. **The self-check is not a privacy proof** — §8.6.
2. **The boundary is not a sandbox.** It rests on separate paths, separate
   reader APIs, the frozen-predictions process boundary and path guards
   (§8.2). None of these stops a script that reads `data/private/` with plain
   `open()`, and the import hook in `experiments/_boundary.py` is defence in
   depth only.
3. **The seed commitment is binding, not hiding** — §8.3.
4. **Synthetic examples are not measurements.** Real B0–B2 and B3-PrivGas-v1 exist
   (`baselines/w1_b0_b2`, runner `experiments/workloads/w1`) and record
   `data_origin: "measured"`. The example runs under
   `experiments/recorder/examples/` remain **synthetic fixtures**, marked
   `data_origin: "synthetic_fixture"` with `synthetic-` run_ids; they were
   first written before the baselines existed and were revised to the real
   event structure in 2.0.0. No number in them is real.
5. **Baseline capability flags for B4–B6 encode a plan, not code.** They must
   be confirmed against a real implementation before those baselines record
   anything. B6's flags are explicitly provisional.
6. **Cost accounting is not in the event schema.** ETH supplied vs. retained
   vs. gas consumed, sponsor cost, sender cost and user cost
   (`docs/research-plan.md` §5, §9.4) are per-run measurements produced by
   each baseline runner, not events. The recorder deliberately has no single
   aggregate "cost" field.
7. **Generated `data/public/` runs are gitignored** (policy changed
   2026-09-14, `docs/decision-log.md`). They are regenerable from `data/raw/`
   plus the private seed. Only the tiny synthetic `*-example/` runs, schema
   code and fixture generators are committable by default; publishing a
   measured run is an explicit decision, never taken before §8.5 passes.
8. **`entrypoint_version` is recorded, not validated against the chain.** The
   recorder trusts the runner's value; nothing here checks it against the
   deployed EntryPoint. (The W1 runner pins it through
   `baselines/w1_b0_b2/dependency-pin.json` and records deployed-bytecode
   digests in the manifest.)
9. **No A1 data exists yet.** The in-repo bundler has no public mempool, so no
   measured run contains pre-inclusion public UserOperation observations,
   replacement behaviour or fee changes.
10. **The in-repo bundler is experimental.** `privgas-minibundler-v1` is an
    instrumented experimental bundler; it does not establish ERC-7562 or
    production compatibility, and staking requirements were not tested. An
    independent compatible bundler is required before D2 liveness claims,
    production-compatibility claims, or replication of D1 results.
11. **Trace phases are coarse.** `trace_phase` is derived from content only, so
    it cannot say *why* ETH moved; distinguishing a gas-funding transfer from
    any other native transfer is left to the analysis, as it must be.
12. **B3-PrivGas-v1 is recorded only on a non-production chain profile.**
    `b3_compat_local` raises anvil's code-size limit so the frozen PoseidonT3
    (29,315 bytes) deploys; the records say nothing about deployability on an
    EIP-170 network, and the B3 Paymasters are unstaked on a bundler that
    enforces no ERC-7562 rules (`docs/b3-evaluation.md`). The current runs use a
    single witness (anonymity set 1) and no root contention.