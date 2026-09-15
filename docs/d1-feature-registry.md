# D1 feature registry: T / AA / G

Status: **canonical partition of every public observation used by the D1 pilot
(2026-09-15).** The tables below are generated from
`experiments/privacy/d1/registry.py` (`python3 -m experiments.privacy.d1.registry --write`);
a test fails if they drift. Results: `docs/d1-pilot-results.md`.

## Families

| Family | Meaning |
|---|---|
| **T** | application / stealth-workflow trace: exists independently of how gas is paid (asset sender, recipient account, ERC-20 transfer, token, amount, target, selector, destination, application timing) |
| **AA** | account-abstraction trace: caused by ERC-4337 smart-account execution but not specifically by the gas mechanism (EntryPoint, factory, UserOperation sender, bundle transaction, generic limits) |
| **G** | gas-mechanism trace: caused specifically by how gas is funded or sponsored (B0/B1 sender ETH funding; Paymaster address, limits, funding, authorization; B3 admission, Bootstrap, CreditPool deposit, commitment, root, nullifier, proof metadata; gas values set by the mechanism) |
| AUX | auxiliary attacker knowledge, not an on-chain observation: the R3 established-wallet directory |

## Decision rules (causal origin, never attack usefulness)

1. **Row origin.** A row belongs to the transaction / UserOperation that emitted it. Transactions and operations that exist only because of the gas mechanism — sender ETH allowance/prefund transfers, Paymaster deposits, `setSponsored`, `announceAndFund`, and the entire B3 Bootstrap operation — are G-origin; every row they emit is G.
2. **Counterfactual value.** For the rows of the W1 application operation (which mixes all three families) a field is G if its value changes when only the gas mechanism is swapped among the matched baselines B1 / B2-Signature / B3 (same actor, account and call); AA if it exists with the same value in every AA baseline; T if it is the application call's own content.

Values co-emitted by one transaction (block number, timestamp) are visible through every row of that transaction; each derived feature reads them from the rows of its declared family.

## Genuine ambiguities (reported, not silently resolved)

| Ambiguity | Primary | `field_kind` alternative |
|---|---|---|
| AA-shaped fields of the B3 Bootstrap op (sender, nonce, initCode/deployment, limits, bundle metadata): the operation exists only for sponsorship | G | AA |
| B3 stealth announcement (`announceAndFund` sender/subject, `AnnounceCalled`): W1's B0–B2 perform no announcement at all, so it exists only through the sponsorship admission; conceptually it is stealth workflow | G | T |
| `preVerificationGas`, `actualGasUsed/Cost` of the application op: generic UserOperation fields whose values are set by `paymasterAndData` and Paymaster validation (also contain application and account work) | G | — |
| B3 Spend nonce (1, because Bootstrap consumed 0) and factory placement (B3 deploys in Bootstrap) | G | AA |
| Plain ETH transfers: gas funding in B0/B1 workflow, environment funding in setup (features use only transfers into an operation's gas payer) | G | — |
| Gas used of the B0 recipient's own transaction: application execution and B0's gas payment at once | T | — |

Every R2 analysis is run under both conventions. The R2 *candidate set* (issuance events) is itself G-defined in both: a model restricted to T or T+AA sees no attribute of any candidate and is uniform by construction.

<!-- BEGIN GENERATED: d1-registry -->

### Row kinds

| Row kind | Public rows |
|---|---|
| `deploy` | eoa_transaction / contract_creation (setup; identical in every baseline) |
| `mint` | asset_transfer emitted by the token constructor (setup) |
| `eth_tx` | native_transfer / native_value_only, transaction level |
| `vmin_forward` | native_transfer / native_value_only emitted by AnnouncementRegistry (B3) |
| `fee_burn` | native_transfer / fee_burn (B3) |
| `pm_deposit_tx` | paymaster_event / paymaster_deposit (Paymaster funding transaction) |
| `pm_deposit_log` | entrypoint_deposit following a Paymaster funding transaction |
| `prefund_deposit_log` | entrypoint_deposit inside a bundle (B1 account prefund) |
| `erc20_tx` | asset_transfer / erc20_transfer, transaction level |
| `erc20_in_op` | asset_transfer inside a bundle (the application call's transfer) |
| `allowlist_tx` | paymaster_event / paymaster_policy (B2-Allowlist setSponsored) |
| `announce_tx` | eoa_transaction / stealth_announce_and_fund (B3 admission) |
| `announce_log` | stealth_announcement (B3 MockAnnouncer AnnounceCalled) |
| `eligibility_log` | sponsorship_eligibility (B3 EligibilityMirrored) |
| `bundle_tx@app` | eoa_transaction / entrypoint_handle_ops carrying the application op |
| `bundle_tx@bootstrap` | eoa_transaction / entrypoint_handle_ops carrying a B3 Bootstrap op |
| `deploy_log@app` | account_deployment inside the application op (B1/B2) |
| `deploy_log@bootstrap` | account_deployment inside a B3 Bootstrap op |
| `uoe@app` | user_operation_event of the application op |
| `uoe@bootstrap` | user_operation_event of a B3 Bootstrap op |
| `bootstrap_sponsored_log` | paymaster_event / paymaster_sponsorship (B3 BootstrapSponsored) |
| `root_update_log` | privacy_pool_event / pool_root_update (B3 RootMirrored) |
| `pool_deposit_log` | privacy_pool_event / pool_deposit (B3 CreditPool Deposited) |
| `pool_redeem_log` | privacy_pool_event / pool_redeem (B3 CreditSpent + proof) |

### Field registry (every varying public field of every row kind)

Context fields never used as features: `schema_version`, `stream`, `experiment_id`, `run_id`, `record_id`, `seq`, `baseline_id`, `workload_id`, `scenario_id`, `software_revision`, `data_origin`, `recorded_at_utc`, `observer_tier`, `chain_id`, `entrypoint_version`, `amount_bucket`, `asset_token_id`, `asset_type`, `event_type`, `calldata_class`, `trace_phase`, `block_hash`, `pool_id`.

| Row kind | Field | Family (primary) | field_kind alt. | Rationale | Ambiguity |
|---|---|---|---|---|---|
| `deploy` | `block_number` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `block_timestamp_utc` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `transaction_index` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `log_index` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `transaction_hash` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `userop_hash` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `entrypoint_address` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `factory` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `sender` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `paymaster` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `target` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `subject_account` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `bundler_beneficiary` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `method_selector` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `nonce` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `asset_contract` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `asset_amount` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `max_fee_per_gas` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `max_priority_fee_per_gas` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `verification_gas_limit` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `call_gas_limit` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `pre_verification_gas` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `paymaster_verification_gas_limit` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `paymaster_post_op_gas_limit` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `actual_gas_used` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `actual_gas_cost` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `effective_gas_price` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `success` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `revert_reason_class` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `outcome` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `commitment` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `merkle_root` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `nullifier` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `deploy` | `proof_metadata` | T |  | setup deployment; identical for every baseline and actor. Family of the deployed contract: W1Token -> T, EntryPoint/factory -> AA, Paymasters and B3 contracts -> G. Recorded as T for the row (not actor-specific; no attack feature reads it). | the row's family depends on WHICH contract is deployed; no feature uses it |
| `mint` | `block_number` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `block_timestamp_utc` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `transaction_index` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `log_index` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `transaction_hash` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `userop_hash` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `entrypoint_address` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `factory` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `sender` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `paymaster` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `target` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `subject_account` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `bundler_beneficiary` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `method_selector` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `nonce` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `asset_contract` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `asset_amount` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `max_fee_per_gas` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `max_priority_fee_per_gas` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `verification_gas_limit` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `call_gas_limit` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `pre_verification_gas` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `paymaster_verification_gas_limit` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `paymaster_post_op_gas_limit` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `actual_gas_used` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `actual_gas_cost` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `effective_gas_price` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `success` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `revert_reason_class` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `outcome` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `commitment` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `merkle_root` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `nullifier` | T |  | token supply minted to the treasury (setup) |  |
| `mint` | `proof_metadata` | T |  | token supply minted to the treasury (setup) |  |
| `eth_tx` | `block_number` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `block_timestamp_utc` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `transaction_index` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `log_index` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `transaction_hash` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `userop_hash` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `entrypoint_address` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `factory` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `sender` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `paymaster` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `target` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `subject_account` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `bundler_beneficiary` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `method_selector` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `nonce` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `asset_contract` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `asset_amount` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `max_fee_per_gas` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `max_priority_fee_per_gas` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `verification_gas_limit` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `call_gas_limit` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `pre_verification_gas` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `paymaster_verification_gas_limit` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `paymaster_post_op_gas_limit` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `actual_gas_used` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `actual_gas_cost` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `effective_gas_price` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `success` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `revert_reason_class` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `outcome` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `commitment` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `merkle_root` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `nullifier` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `eth_tx` | `proof_metadata` | G |  | a plain ETH transfer. In the workflow it is the B0/B1 gas-funding edge (sender -> fresh recipient that later pays gas): the gas mechanism of B0/B1. | setup faucet transfers share this row kind; they fund the asset senders' own application transactions (T-like environment). Features only use eth_tx rows whose recipient is an operation's gas payer. |
| `vmin_forward` | `block_number` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `block_timestamp_utc` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `transaction_index` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `log_index` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `transaction_hash` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `userop_hash` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `entrypoint_address` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `factory` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `sender` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `paymaster` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `target` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `subject_account` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `bundler_beneficiary` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `method_selector` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `nonce` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `asset_contract` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `asset_amount` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `max_fee_per_gas` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `max_priority_fee_per_gas` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `verification_gas_limit` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `call_gas_limit` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `pre_verification_gas` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `paymaster_verification_gas_limit` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `paymaster_post_op_gas_limit` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `actual_gas_used` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `actual_gas_cost` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `effective_gas_price` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `success` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `revert_reason_class` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `outcome` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `commitment` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `merkle_root` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `nullifier` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `vmin_forward` | `proof_metadata` | G |  | B3 admission: AnnouncementRegistry forwards vMin to the announced account (Sybil-resistance deposit; pays no gas) |  |
| `fee_burn` | `block_number` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `block_timestamp_utc` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `transaction_index` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `log_index` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `transaction_hash` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `userop_hash` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `entrypoint_address` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `factory` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `sender` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `paymaster` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `target` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `subject_account` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `bundler_beneficiary` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `method_selector` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `nonce` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `asset_contract` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `asset_amount` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `max_fee_per_gas` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `max_priority_fee_per_gas` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `verification_gas_limit` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `call_gas_limit` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `pre_verification_gas` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `paymaster_verification_gas_limit` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `paymaster_post_op_gas_limit` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `actual_gas_used` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `actual_gas_cost` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `effective_gas_price` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `success` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `revert_reason_class` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `outcome` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `commitment` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `merkle_root` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `nullifier` | G |  | B3 admission: non-refundable fee burned |  |
| `fee_burn` | `proof_metadata` | G |  | B3 admission: non-refundable fee burned |  |
| `pm_deposit_tx` | `block_number` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `block_timestamp_utc` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `transaction_index` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `log_index` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `transaction_hash` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `userop_hash` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `entrypoint_address` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `factory` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `sender` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `paymaster` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `target` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `subject_account` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `bundler_beneficiary` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `method_selector` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `nonce` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `asset_contract` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `asset_amount` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `max_fee_per_gas` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `max_priority_fee_per_gas` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `verification_gas_limit` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `call_gas_limit` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `pre_verification_gas` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `paymaster_verification_gas_limit` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `paymaster_post_op_gas_limit` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `actual_gas_used` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `actual_gas_cost` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `effective_gas_price` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `success` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `revert_reason_class` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `outcome` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `commitment` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `merkle_root` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `nullifier` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_tx` | `proof_metadata` | G |  | Paymaster funding by the sponsor wallet |  |
| `pm_deposit_log` | `block_number` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `block_timestamp_utc` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `transaction_index` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `log_index` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `transaction_hash` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `userop_hash` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `entrypoint_address` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `factory` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `sender` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `paymaster` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `target` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `subject_account` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `bundler_beneficiary` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `method_selector` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `nonce` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `asset_contract` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `asset_amount` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `max_fee_per_gas` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `max_priority_fee_per_gas` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `verification_gas_limit` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `call_gas_limit` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `pre_verification_gas` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `paymaster_verification_gas_limit` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `paymaster_post_op_gas_limit` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `actual_gas_used` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `actual_gas_cost` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `effective_gas_price` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `success` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `revert_reason_class` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `outcome` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `commitment` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `merkle_root` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `nullifier` | G |  | Paymaster EntryPoint deposit event |  |
| `pm_deposit_log` | `proof_metadata` | G |  | Paymaster EntryPoint deposit event |  |
| `prefund_deposit_log` | `block_number` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `block_timestamp_utc` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `transaction_index` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `log_index` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `transaction_hash` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `userop_hash` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `entrypoint_address` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `factory` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `sender` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `paymaster` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `target` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `subject_account` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `bundler_beneficiary` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `method_selector` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `nonce` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `asset_contract` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `asset_amount` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `max_fee_per_gas` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `max_priority_fee_per_gas` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `verification_gas_limit` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `call_gas_limit` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `pre_verification_gas` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `paymaster_verification_gas_limit` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `paymaster_post_op_gas_limit` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `actual_gas_used` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `actual_gas_cost` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `effective_gas_price` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `success` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `revert_reason_class` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `outcome` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `commitment` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `merkle_root` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `nullifier` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `prefund_deposit_log` | `proof_metadata` | G |  | B1 account prefund credited to the EntryPoint deposit (sender-funded gas) |  |
| `erc20_tx` | `block_number` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `block_timestamp_utc` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `transaction_index` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `log_index` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `transaction_hash` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `userop_hash` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `entrypoint_address` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `factory` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `sender` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `paymaster` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `target` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `subject_account` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `bundler_beneficiary` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `method_selector` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `nonce` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `asset_contract` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `asset_amount` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `max_fee_per_gas` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `max_priority_fee_per_gas` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `verification_gas_limit` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `call_gas_limit` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `pre_verification_gas` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `paymaster_verification_gas_limit` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `paymaster_post_op_gas_limit` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `actual_gas_used` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). | B0 action: gas used/cost of the recipient EOA's own transaction is both application execution and the B0 gas payment; kept T (no G counterpart field exists in B0) |
| `erc20_tx` | `actual_gas_cost` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). | B0 action: gas used/cost of the recipient EOA's own transaction is both application execution and the B0 gas payment; kept T (no G counterpart field exists in B0) |
| `erc20_tx` | `effective_gas_price` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). | B0 action: gas used/cost of the recipient EOA's own transaction is both application execution and the B0 gas payment; kept T (no G counterpart field exists in B0) |
| `erc20_tx` | `success` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `revert_reason_class` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `outcome` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `commitment` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `merkle_root` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `nullifier` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_tx` | `proof_metadata` | T |  | ERC-20 transfer transaction: asset delivery (sender -> recipient), token distribution to asset senders (setup), and the B0 application action. Its fee fields are paid by the plain transaction sender in every baseline (asset sender; B0 recipient EOA). |  |
| `erc20_in_op` | `block_number` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `block_timestamp_utc` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `transaction_index` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `log_index` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `transaction_hash` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `userop_hash` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `entrypoint_address` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `factory` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `sender` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `paymaster` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `target` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `subject_account` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `bundler_beneficiary` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `method_selector` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `nonce` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `asset_contract` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `asset_amount` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `max_fee_per_gas` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `max_priority_fee_per_gas` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `verification_gas_limit` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `call_gas_limit` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `pre_verification_gas` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `paymaster_verification_gas_limit` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `paymaster_post_op_gas_limit` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `actual_gas_used` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `actual_gas_cost` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `effective_gas_price` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `success` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `revert_reason_class` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `outcome` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `commitment` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `merkle_root` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `nullifier` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `erc20_in_op` | `proof_metadata` | T |  | the W1 application call's token transfer (account -> destination), byte-identical in B1/B2/B3 |  |
| `allowlist_tx` | `block_number` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `block_timestamp_utc` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `transaction_index` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `log_index` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `transaction_hash` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `userop_hash` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `entrypoint_address` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `factory` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `sender` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `paymaster` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `target` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `subject_account` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `bundler_beneficiary` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `method_selector` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `nonce` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `asset_contract` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `asset_amount` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `max_fee_per_gas` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `max_priority_fee_per_gas` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `verification_gas_limit` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `call_gas_limit` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `pre_verification_gas` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `paymaster_verification_gas_limit` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `paymaster_post_op_gas_limit` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `actual_gas_used` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `actual_gas_cost` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `effective_gas_price` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `success` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `revert_reason_class` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `outcome` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `commitment` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `merkle_root` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `nullifier` | G |  | B2-Allowlist public sponsor authorization |  |
| `allowlist_tx` | `proof_metadata` | G |  | B2-Allowlist public sponsor authorization |  |
| `announce_tx` | `block_number` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `block_timestamp_utc` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `transaction_index` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `log_index` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `transaction_hash` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `userop_hash` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `entrypoint_address` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `factory` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `sender` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `paymaster` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `target` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `subject_account` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `bundler_beneficiary` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `method_selector` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `nonce` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `asset_contract` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `asset_amount` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `max_fee_per_gas` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `max_priority_fee_per_gas` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `verification_gas_limit` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `call_gas_limit` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `pre_verification_gas` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `paymaster_verification_gas_limit` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `paymaster_post_op_gas_limit` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `actual_gas_used` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `actual_gas_cost` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `effective_gas_price` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `success` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `revert_reason_class` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `outcome` | G | T | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_tx` | `commitment` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `merkle_root` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `nullifier` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_tx` | `proof_metadata` | G |  | B3 announceAndFund: admission value (vMin + fee) and announcement in one transaction |  |
| `announce_log` | `block_number` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `block_timestamp_utc` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `transaction_index` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `log_index` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `transaction_hash` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `userop_hash` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `entrypoint_address` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `factory` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `sender` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `paymaster` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `target` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `subject_account` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `bundler_beneficiary` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `method_selector` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `nonce` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `asset_contract` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `asset_amount` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `max_fee_per_gas` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `max_priority_fee_per_gas` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `verification_gas_limit` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `call_gas_limit` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `pre_verification_gas` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `paymaster_verification_gas_limit` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `paymaster_post_op_gas_limit` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `actual_gas_used` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `actual_gas_cost` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `effective_gas_price` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `success` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `revert_reason_class` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `outcome` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `commitment` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `merkle_root` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `nullifier` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `announce_log` | `proof_metadata` | G | T | B3 MockAnnouncer AnnounceCalled log | W1's B0/B1/B2 perform NO stealth announcement; the only announcement in the pilot is B3's, carried by the sponsorship admission call. Under the counterfactual rule it is G; conceptually a stealth announcement belongs to the stealth workflow (T). field_kind convention: T. |
| `eligibility_log` | `block_number` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `block_timestamp_utc` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `transaction_index` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `log_index` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `transaction_hash` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `userop_hash` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `entrypoint_address` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `factory` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `sender` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `paymaster` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `target` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `subject_account` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `bundler_beneficiary` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `method_selector` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `nonce` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `asset_contract` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `asset_amount` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `max_fee_per_gas` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `max_priority_fee_per_gas` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `verification_gas_limit` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `call_gas_limit` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `pre_verification_gas` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `paymaster_verification_gas_limit` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `paymaster_post_op_gas_limit` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `actual_gas_used` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `actual_gas_cost` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `effective_gas_price` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `success` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `revert_reason_class` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `outcome` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `commitment` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `merkle_root` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `nullifier` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `eligibility_log` | `proof_metadata` | G |  | B3 eligibility mirrored into the Paymasters |  |
| `bundle_tx@app` | `block_number` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `block_number` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `block_timestamp_utc` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `block_timestamp_utc` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `transaction_index` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `transaction_index` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `log_index` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `log_index` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `transaction_hash` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `transaction_hash` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `userop_hash` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `userop_hash` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `entrypoint_address` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `entrypoint_address` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `factory` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `factory` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `sender` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `sender` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `paymaster` | G |  | Paymaster address / Paymaster gas limits |  |
| `bundle_tx@bootstrap` | `paymaster` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `target` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `target` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `subject_account` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `subject_account` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `bundler_beneficiary` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `bundler_beneficiary` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `method_selector` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `method_selector` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `nonce` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `nonce` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `asset_contract` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `asset_contract` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `asset_amount` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `asset_amount` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `max_fee_per_gas` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `max_fee_per_gas` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `max_priority_fee_per_gas` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `max_priority_fee_per_gas` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `verification_gas_limit` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `verification_gas_limit` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `call_gas_limit` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `call_gas_limit` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `pre_verification_gas` | G |  | counterfactual: follows paymasterAndData length (B1 42,813 / B2-Signature 44,733 / B3 48,837 in W1) | a generic UserOperation field whose VALUE is set by the gas mechanism |
| `bundle_tx@bootstrap` | `pre_verification_gas` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `paymaster_verification_gas_limit` | G |  | Paymaster address / Paymaster gas limits |  |
| `bundle_tx@bootstrap` | `paymaster_verification_gas_limit` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `paymaster_post_op_gas_limit` | G |  | Paymaster address / Paymaster gas limits |  |
| `bundle_tx@bootstrap` | `paymaster_post_op_gas_limit` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `actual_gas_used` | G |  | counterfactual: includes Paymaster validation (ecrecover / Groth16) and PVG, so it differs by mechanism | also contains application execution (T) and account validation (AA); not separable from public data |
| `bundle_tx@bootstrap` | `actual_gas_used` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `actual_gas_cost` | G |  | counterfactual: includes Paymaster validation (ecrecover / Groth16) and PVG, so it differs by mechanism | also contains application execution (T) and account validation (AA); not separable from public data |
| `bundle_tx@bootstrap` | `actual_gas_cost` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `effective_gas_price` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `effective_gas_price` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `success` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `success` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `revert_reason_class` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `revert_reason_class` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `outcome` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `outcome` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `bundle_tx@app` | `commitment` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `commitment` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `merkle_root` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `merkle_root` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `nullifier` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `nullifier` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bundle_tx@app` | `proof_metadata` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `bundle_tx@bootstrap` | `proof_metadata` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `block_number` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `block_number` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `block_timestamp_utc` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `block_timestamp_utc` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `transaction_index` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `transaction_index` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `log_index` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `log_index` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `transaction_hash` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `transaction_hash` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `userop_hash` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `userop_hash` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `entrypoint_address` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `entrypoint_address` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `factory` | G | AA | counterfactual: B1/B2 deploy the account in the application op, B3 in the Bootstrap op | account deployment is AA; its placement is caused by the gas mechanism |
| `deploy_log@bootstrap` | `factory` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `sender` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `sender` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `paymaster` | G |  | Paymaster address / Paymaster gas limits |  |
| `deploy_log@bootstrap` | `paymaster` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `target` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `target` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `subject_account` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `subject_account` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `bundler_beneficiary` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `bundler_beneficiary` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `method_selector` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `method_selector` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `nonce` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `nonce` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `asset_contract` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `asset_contract` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `asset_amount` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `asset_amount` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `max_fee_per_gas` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `max_fee_per_gas` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `max_priority_fee_per_gas` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `max_priority_fee_per_gas` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `verification_gas_limit` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `verification_gas_limit` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `call_gas_limit` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `call_gas_limit` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `pre_verification_gas` | G |  | counterfactual: follows paymasterAndData length (B1 42,813 / B2-Signature 44,733 / B3 48,837 in W1) | a generic UserOperation field whose VALUE is set by the gas mechanism |
| `deploy_log@bootstrap` | `pre_verification_gas` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `paymaster_verification_gas_limit` | G |  | Paymaster address / Paymaster gas limits |  |
| `deploy_log@bootstrap` | `paymaster_verification_gas_limit` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `paymaster_post_op_gas_limit` | G |  | Paymaster address / Paymaster gas limits |  |
| `deploy_log@bootstrap` | `paymaster_post_op_gas_limit` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `actual_gas_used` | G |  | counterfactual: includes Paymaster validation (ecrecover / Groth16) and PVG, so it differs by mechanism | also contains application execution (T) and account validation (AA); not separable from public data |
| `deploy_log@bootstrap` | `actual_gas_used` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `actual_gas_cost` | G |  | counterfactual: includes Paymaster validation (ecrecover / Groth16) and PVG, so it differs by mechanism | also contains application execution (T) and account validation (AA); not separable from public data |
| `deploy_log@bootstrap` | `actual_gas_cost` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `effective_gas_price` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `effective_gas_price` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `success` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `success` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `revert_reason_class` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `revert_reason_class` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `outcome` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `outcome` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `deploy_log@app` | `commitment` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `commitment` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `merkle_root` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `merkle_root` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `nullifier` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `nullifier` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `deploy_log@app` | `proof_metadata` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `deploy_log@bootstrap` | `proof_metadata` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `block_number` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `block_number` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `block_timestamp_utc` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `block_timestamp_utc` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `transaction_index` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `transaction_index` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `log_index` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `log_index` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `transaction_hash` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `transaction_hash` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `userop_hash` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `userop_hash` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `entrypoint_address` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `entrypoint_address` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `factory` | G | AA | counterfactual: B1/B2 deploy the account in the application op, B3 in the Bootstrap op | account deployment is AA; its placement is caused by the gas mechanism |
| `uoe@bootstrap` | `factory` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `sender` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `sender` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `paymaster` | G |  | Paymaster address / Paymaster gas limits |  |
| `uoe@bootstrap` | `paymaster` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `target` | T |  | the application call target (token) |  |
| `uoe@bootstrap` | `target` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `subject_account` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `subject_account` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `bundler_beneficiary` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `bundler_beneficiary` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `method_selector` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `method_selector` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `nonce` | G | AA | counterfactual: the B3 Spend uses nonce 1 because the Bootstrap consumed nonce 0 (B1/B2: nonce 0) | AA-shaped field whose value is set by the gas mechanism |
| `uoe@bootstrap` | `nonce` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `asset_contract` | T |  | the application call target (token) |  |
| `uoe@bootstrap` | `asset_contract` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `asset_amount` | T |  | the application call target (token) |  |
| `uoe@bootstrap` | `asset_amount` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `max_fee_per_gas` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `max_fee_per_gas` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `max_priority_fee_per_gas` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `max_priority_fee_per_gas` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `verification_gas_limit` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `verification_gas_limit` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `call_gas_limit` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `call_gas_limit` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `pre_verification_gas` | G |  | counterfactual: follows paymasterAndData length (B1 42,813 / B2-Signature 44,733 / B3 48,837 in W1) | a generic UserOperation field whose VALUE is set by the gas mechanism |
| `uoe@bootstrap` | `pre_verification_gas` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `paymaster_verification_gas_limit` | G |  | Paymaster address / Paymaster gas limits |  |
| `uoe@bootstrap` | `paymaster_verification_gas_limit` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `paymaster_post_op_gas_limit` | G |  | Paymaster address / Paymaster gas limits |  |
| `uoe@bootstrap` | `paymaster_post_op_gas_limit` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `actual_gas_used` | G |  | counterfactual: includes Paymaster validation (ecrecover / Groth16) and PVG, so it differs by mechanism | also contains application execution (T) and account validation (AA); not separable from public data |
| `uoe@bootstrap` | `actual_gas_used` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `actual_gas_cost` | G |  | counterfactual: includes Paymaster validation (ecrecover / Groth16) and PVG, so it differs by mechanism | also contains application execution (T) and account validation (AA); not separable from public data |
| `uoe@bootstrap` | `actual_gas_cost` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `effective_gas_price` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `effective_gas_price` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `success` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `success` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `revert_reason_class` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `revert_reason_class` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `outcome` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `outcome` | G | AA | field of the B3 Bootstrap operation (exists only for sponsorship) | an AA-shaped field of a G-origin operation (the B3 Bootstrap exists only for sponsorship). Row origin -> G; field_kind convention -> AA. |
| `uoe@app` | `commitment` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `commitment` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `merkle_root` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `merkle_root` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `nullifier` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `nullifier` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `uoe@app` | `proof_metadata` | AA |  | ERC-4337 execution metadata, same for every AA baseline |  |
| `uoe@bootstrap` | `proof_metadata` | G |  | field of the B3 Bootstrap operation (exists only for sponsorship) |  |
| `bootstrap_sponsored_log` | `block_number` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `block_timestamp_utc` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `transaction_index` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `log_index` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `transaction_hash` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `userop_hash` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `entrypoint_address` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `factory` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `sender` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `paymaster` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `target` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `subject_account` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `bundler_beneficiary` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `method_selector` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `nonce` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `asset_contract` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `asset_amount` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `max_fee_per_gas` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `max_priority_fee_per_gas` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `verification_gas_limit` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `call_gas_limit` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `pre_verification_gas` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `paymaster_verification_gas_limit` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `paymaster_post_op_gas_limit` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `actual_gas_used` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `actual_gas_cost` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `effective_gas_price` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `success` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `revert_reason_class` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `outcome` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `commitment` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `merkle_root` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `nullifier` | G |  | BootstrapPaymaster log naming the account |  |
| `bootstrap_sponsored_log` | `proof_metadata` | G |  | BootstrapPaymaster log naming the account |  |
| `root_update_log` | `block_number` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `block_timestamp_utc` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `transaction_index` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `log_index` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `transaction_hash` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `userop_hash` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `entrypoint_address` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `factory` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `sender` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `paymaster` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `target` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `subject_account` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `bundler_beneficiary` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `method_selector` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `nonce` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `asset_contract` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `asset_amount` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `max_fee_per_gas` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `max_priority_fee_per_gas` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `verification_gas_limit` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `call_gas_limit` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `pre_verification_gas` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `paymaster_verification_gas_limit` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `paymaster_post_op_gas_limit` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `actual_gas_used` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `actual_gas_cost` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `effective_gas_price` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `success` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `revert_reason_class` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `outcome` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `commitment` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `merkle_root` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `nullifier` | G |  | CreditPaymaster RootMirrored |  |
| `root_update_log` | `proof_metadata` | G |  | CreditPaymaster RootMirrored |  |
| `pool_deposit_log` | `block_number` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `block_timestamp_utc` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `transaction_index` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `log_index` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `transaction_hash` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `userop_hash` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `entrypoint_address` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `factory` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `sender` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `paymaster` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `target` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `subject_account` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `bundler_beneficiary` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `method_selector` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `nonce` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `asset_contract` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `asset_amount` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `max_fee_per_gas` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `max_priority_fee_per_gas` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `verification_gas_limit` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `call_gas_limit` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `pre_verification_gas` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `paymaster_verification_gas_limit` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `paymaster_post_op_gas_limit` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `actual_gas_used` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `actual_gas_cost` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `effective_gas_price` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `success` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `revert_reason_class` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `outcome` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `commitment` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `merkle_root` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `nullifier` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_deposit_log` | `proof_metadata` | G |  | CreditPool Deposited: commitment, root, depositor |  |
| `pool_redeem_log` | `block_number` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `block_timestamp_utc` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `transaction_index` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `log_index` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `transaction_hash` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `userop_hash` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `entrypoint_address` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `factory` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `sender` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `paymaster` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `target` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `subject_account` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `bundler_beneficiary` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `method_selector` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `nonce` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `asset_contract` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `asset_amount` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `max_fee_per_gas` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `max_priority_fee_per_gas` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `verification_gas_limit` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `call_gas_limit` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `pre_verification_gas` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `paymaster_verification_gas_limit` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `paymaster_post_op_gas_limit` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `actual_gas_used` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `actual_gas_cost` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `effective_gas_price` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `success` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `revert_reason_class` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `outcome` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `commitment` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `merkle_root` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `nullifier` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |
| `pool_redeem_log` | `proof_metadata` | G |  | CreditPaymaster CreditSpent(nullifier, sender) + proof root / metadata |  |

### Derived attack features

| Feature | Relation | Subfamily | Families (primary) | Families (field_kind) | Baselines | Sources | Description |
|---|---|---|---|---|---|---|---|
| `r1_token_edge` | R1 | eq | T | T | B0 | `erc20_tx.sender`, `erc20_tx.subject_account` | candidate sent W1 tokens directly to the EOA that sends the B0 action transaction |
| `r1_token_edge_op` | R1 | eq | T | T | B1 | `erc20_tx.sender`, `erc20_tx.subject_account`, `erc20_in_op.sender` | candidate sent W1 tokens directly to the account whose application transfer the op made |
| `r1_token_edge_aa` | R1 | eq | T+AA | T+AA | B1 | `erc20_tx.sender`, `erc20_tx.subject_account`, `uoe@app.sender` | candidate sent W1 tokens to the UserOperation sender |
| `r1_eth_edge_t` | R1 | eq | T+G | T+G | B0 | `eth_tx.sender`, `eth_tx.target`, `erc20_tx.sender` | candidate sent ETH directly to the account that performs the application transfer (B0: action tx sender) |
| `r1_eth_edge_t_op` | R1 | eq | T+G | T+G | B1 | `eth_tx.sender`, `eth_tx.target`, `erc20_in_op.sender` | candidate sent ETH directly to the account whose application transfer the op made |
| `r1_eth_edge_aa` | R1 | eq | AA+G | AA+G | B1 | `eth_tx.sender`, `eth_tx.target`, `uoe@app.sender` | candidate sent ETH directly to the UserOperation sender |
| `r1_eth_edge_g` | R1 | eq | G | G | B1 | `eth_tx.sender`, `eth_tx.target`, `prefund_deposit_log.subject_account` | candidate sent ETH to the account credited by the op's prefund Deposited event |
| `r1_eth_amount_matches_prefund` | R1 | gas | AA+G | AA+G | B1 | `eth_tx.asset_amount`, `uoe@app.pre_verification_gas`, `uoe@app.verification_gas_limit`, `uoe@app.call_gas_limit`, `uoe@app.max_fee_per_gas` | candidate's ETH transfer amount equals the op's required prefund (verificationGasLimit + callGasLimit + PVG) * maxFeePerGas |
| `r1_eth_fanout` | R1 | structure | G | G | B0, B1 | `eth_tx.sender`, `eth_tx.target` | log(1 + number of distinct ETH recipients of the candidate) (faucet-like fan-out) |
| `r1_funding_rank_gap_t` | R1 | timing | T+G | T+G | B0 | `eth_tx.block_number`, `erc20_tx.block_number` | |rank of the candidate's ETH transfer - rank of the B0 action| / (N-1) |
| `r1_funding_rank_gap_op` | R1 | timing | T+G | T+G | B1 | `eth_tx.block_number`, `erc20_in_op.block_number` | |rank of the candidate's ETH transfer - rank of the application op| / (N-1) |
| `r1_token_rank_gap` | R1 | timing | T | T | B0 | `erc20_tx.block_number`, `erc20_tx.block_number` | |rank of the candidate's token transfer - rank of the B0 action| / (N-1) |
| `r1_token_rank_gap_op` | R1 | timing | T | T | B1 | `erc20_tx.block_number`, `erc20_in_op.block_number` | |rank of the candidate's token transfer - rank of the application op| / (N-1) |
| `r2_eq_g_account` | R2 | eq | G | G | B3-PrivGas-v1 | `pool_redeem_log.sender`, `pool_deposit_log.sender` | CreditSpent(nullifier, sender) names the same account as the issuance's CreditPool depositor |
| `r2_eq_aa_sender` | R2 | eq | AA+G | AA | B3-PrivGas-v1 | `uoe@app.sender`, `uoe@bootstrap.sender` | Spend UserOperation.sender == Bootstrap UserOperation.sender |
| `r2_eq_t_account` | R2 | eq | T+G | T+G | B3-PrivGas-v1 | `erc20_in_op.sender`, `pool_deposit_log.sender` | the account whose application transfer the Spend made == the issuance's depositor |
| `r2_eq_deploy` | R2 | eq | AA+G | AA | B3-PrivGas-v1 | `uoe@app.sender`, `deploy_log@bootstrap.sender` | Spend sender == account deployed by the issuance operation |
| `r2_rank_gap_g` | R2 | timing | G | G | B3-PrivGas-v1 | `pool_redeem_log.block_number`, `pool_deposit_log.block_number` | |rank of the redemption among redemptions - rank of the issuance among issuances| / (N-1)  (insertion-order / FIFO signal) |
| `r2_rank_gap_aa` | R2 | timing | AA+G | AA | B3-PrivGas-v1 | `uoe@app.block_number`, `uoe@bootstrap.block_number` | same rank gap read from the UserOperationEvent rows |
| `r2_dt_offset_g` | R2 | timing | G | G | B3-PrivGas-v1 | `pool_redeem_log.block_timestamp_utc`, `pool_deposit_log.block_timestamp_utc` | |(t_redeem - t_issue) - (median t_redeem - median t_issue)| / (run span), an unsupervised common-delay window |
| `r2_latest_issuance_g` | R2 | timing | G | G | B3-PrivGas-v1 | `pool_redeem_log.block_number`, `pool_deposit_log.block_number` | candidate is the most recent issuance before the redemption (nearest prior) |
| `r2_intervening_g` | R2 | timing | G | G | B3-PrivGas-v1 | `pool_redeem_log.block_number`, `pool_deposit_log.block_number` | number of issuances between the candidate and the redemption / N (root age proxy) |
| `r2_root_match` | R2 | pm | G | G | B3-PrivGas-v1 | `pool_redeem_log.merkle_root`, `pool_deposit_log.merkle_root` | the redemption proved against the root emitted by the candidate's deposit |
| `r2_bits_agree` | R2 | pm | G | G | B3-PrivGas-v1 | `pool_redeem_log.nullifier`, `pool_deposit_log.commitment` | fraction of equal bits in the low 64 bits of nullifier and commitment (cryptographic negative control) |
| `r2_gas_rank_gap` | R2 | gas | G | G | B3-PrivGas-v1 | `uoe@app.actual_gas_used`, `uoe@bootstrap.actual_gas_used` | |rank of Spend gas used - rank of Bootstrap gas used| / (N-1) |
| `r2_pvg_gap` | R2 | gas | G | G | B3-PrivGas-v1 | `uoe@app.pre_verification_gas`, `uoe@bootstrap.pre_verification_gas` | |z(Spend PVG) - z(Bootstrap PVG)| (within-run z-scores) |
| `r2_cand_gas_z` | R2 | gas | G | G | B3-PrivGas-v1 | `uoe@bootstrap.actual_gas_used` | within-run z-score of the Bootstrap op's gas used (insertion-position dependent) |
| `r2_cand_pvg_z` | R2 | gas | G | G | B3-PrivGas-v1 | `uoe@bootstrap.pre_verification_gas` | within-run z-score of the Bootstrap op's PVG (calldata zero bytes) |
| `r2_delivery_rank_gap_tg` | R2 | timing | T+G | T+G | B3-PrivGas-v1 | `erc20_tx.block_number`, `erc20_tx.subject_account`, `pool_deposit_log.sender`, `erc20_in_op.block_number` | |rank of token delivery to the candidate's depositor - rank of the Spend's application transfer| / (N-1) |
| `r3_dir_vs_action_rank_t` | R3 | timing | T | T | B1, B2-Signature, B2-Allowlist, B3-PrivGas-v1 | `AUX.directory_position`, `erc20_in_op.block_number` | |directory position of the wallet - rank of the application transfer| / (N-1) |
| `r3_dir_vs_action_rank_b0` | R3 | timing | T | T | B0 | `AUX.directory_position`, `erc20_tx.block_number` | |directory position - rank of the B0 action| / (N-1) |
| `r3_dir_vs_delivery_rank` | R3 | timing | T | T | B0, B1, B2-Signature, B2-Allowlist, B3-PrivGas-v1 | `AUX.directory_position`, `erc20_tx.block_number`, `erc20_tx.subject_account`, `erc20_in_op.sender` | |directory position - rank of the token delivery to the account| / (N-1) |
| `r3_dir_vs_op_rank_aa` | R3 | timing | AA | AA | B1, B2-Signature, B2-Allowlist, B3-PrivGas-v1 | `AUX.directory_position`, `uoe@app.block_number` | |directory position - rank of the UserOperation| / (N-1) |
| `r3_dir_vs_funding_rank_b0` | R3 | timing | T+G | T+G | B0 | `AUX.directory_position`, `eth_tx.block_number`, `eth_tx.target`, `erc20_tx.sender` | |directory position - rank of the ETH funding of the action's sender| / (N-1) |
| `r3_dir_vs_funding_rank_g` | R3 | timing | G | G | B1 | `AUX.directory_position`, `eth_tx.block_number`, `eth_tx.target`, `prefund_deposit_log.subject_account` | |directory position - rank of the ETH funding of the prefunded account| / (N-1) |
| `r3_dir_vs_allowlist_rank` | R3 | timing | AA+G | AA+G | B2-Allowlist | `AUX.directory_position`, `allowlist_tx.block_number`, `allowlist_tx.subject_account`, `uoe@app.sender` | |directory position - rank of setSponsored(op sender)| / (N-1) |
| `r3_dir_vs_issuance_rank_g` | R3 | timing | G | G | B3-PrivGas-v1 | `AUX.directory_position`, `pool_deposit_log.block_number`, `pool_deposit_log.sender`, `pool_redeem_log.sender` | |directory position - rank of the spender's issuance| / (N-1) |
| `r3_addr_hamming_t` | R3 | eq | T | T | B0, B1, B2-Signature, B2-Allowlist, B3-PrivGas-v1 | `AUX.wallet_address`, `erc20_tx.sender`, `erc20_in_op.sender` | normalised Hamming distance between the bits of the account that makes the application transfer and the wallet address |
| `r3_addr_prefix_t` | R3 | eq | T | T | B0, B1, B2-Signature, B2-Allowlist, B3-PrivGas-v1 | `AUX.wallet_address`, `erc20_tx.sender`, `erc20_in_op.sender` | shared leading hex nibbles of that account and the wallet address / 40 |
| `r3_gas_rank_vs_dir_g` | R3 | gas | G | G | B1, B2-Signature, B2-Allowlist, B3-PrivGas-v1 | `AUX.directory_position`, `uoe@app.actual_gas_used` | |rank of the op's gas used - directory position| / (N-1) |
| `r3_pvg_rank_vs_dir_g` | R3 | gas | G | G | B1, B2-Signature, B2-Allowlist, B3-PrivGas-v1 | `AUX.directory_position`, `uoe@app.pre_verification_gas` | |rank of the op's PVG - directory position| / (N-1) |

<!-- END GENERATED: d1-registry -->
