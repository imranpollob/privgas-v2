.DEFAULT_GOAL := help
SHELL := /bin/bash

# ID and SEED are required by run-local-experiment; CHAIN_ID and
# ENTRYPOINT_VERSION are part of the reproducibility contract
# (docs/experiment-schema.md) and should be overridden per run, e.g.:
#   make run-local-experiment ID=workloads/example-001 SEED=42 CHAIN_ID=31337 ENTRYPOINT_VERSION=0.7
CHAIN_ID ?= unset
ENTRYPOINT_VERSION ?= unset

.PHONY: help install test benchmark run-local-experiment clean env-report \
        recorder-test recorder-examples recorder-selfcheck recorder-docs \
        baselines-build baselines-test run-matched-baselines calibrate-pvg \
        b3-eval-build b3-prover-install b3-eip170-test run-b3-evaluation \
        d1-test d1-pilot-run d1-pilot-attack d1-registry-docs d1-b4-run d1-b4-attack d1-s1b-run d1-s1b-attack \
        d2-test d2-pilot-run d2-pilot-analyze \
        d2k-build d2k-contract-test d2k-test d2k-run d2k-analyze

help: ## Show this help
	@echo "privgas-v2 — available targets:"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

install: ## Verify required tooling is present (no app dependencies exist yet)
	@echo "Checking core tooling..."
	@command -v git   >/dev/null || { echo "git not found"; exit 1; }
	@command -v bash  >/dev/null || { echo "bash not found"; exit 1; }
	@command -v make  >/dev/null || { echo "make not found"; exit 1; }
	@chmod +x scripts/*.sh 2>/dev/null || true
	@echo "Core tooling OK. No project dependency manifests exist yet"
	@echo "(no contracts/circuits/app code has been added — see docs/decision-log.md)."
	@echo "Run 'make env-report' for the full version report."

test: scaffold-test recorder-test b3-eip170-test baselines-test d1-test d2-test d2k-test ## Run the full test suite

.PHONY: scaffold-test
scaffold-test: ## Repository-layout and gitignore self-checks
	@echo "Running scaffold self-checks..."
	@test -f .gitignore || { echo "FAIL: .gitignore missing"; exit 1; }
	@mkdir -p data/private
	@tmpfile="data/private/.selftest-$$$$"; \
	 touch "$$tmpfile"; \
	 if git check-ignore -q "$$tmpfile"; then \
	   echo "PASS: data/private/ is git-ignored"; \
	 else \
	   echo "FAIL: data/private/ is NOT git-ignored"; rm -f "$$tmpfile"; exit 1; \
	 fi; \
	 rm -f "$$tmpfile"
	@if git check-ignore --no-index -q data/public/baselines/b0-w1/20990101T000000Z-b0/observer_a0a1/public_events.jsonl; then \
	   echo "PASS: generated data/public/ runs are git-ignored"; \
	 else echo "FAIL: generated data/public/ runs are NOT git-ignored"; exit 1; fi
	@if git check-ignore --no-index -q data/public/baselines/b0-w1-example/synthetic-20260301T120000Z-b0/run_manifest.public.json; then \
	   echo "FAIL: synthetic data/public/ examples are git-ignored"; exit 1; \
	 else echo "PASS: synthetic data/public/*-example runs remain committable"; fi
	@for d in docs baselines contracts circuits test scripts experiments/workloads \
	          experiments/privacy experiments/liveness experiments/settlement \
	          experiments/analysis data/raw data/public data/private results figures paper; do \
	   test -d "$$d" || { echo "FAIL: missing directory $$d"; exit 1; }; \
	 done
	@echo "PASS: expected directory layout present"
	@echo "All scaffold self-checks passed."

recorder-test: ## Run the experiment-recorder + data-boundary test suite
	@echo "Running experiment-recorder tests..."
	@python3 -m unittest discover -s experiments/tests -t .

recorder-examples: ## Regenerate the synthetic B0/B1/B2 example runs
	@python3 -m experiments.recorder.examples.generate

recorder-selfcheck: ## Scan data/public/ for leaked private fields and values
	@python3 -m experiments.labels --all-runs

recorder-docs: ## Regenerate the schema field tables in docs/experiment-schema.md
	@python3 -m experiments.recorder.docgen --write

# --- Matched W1 baselines B0/B1/B2 (baselines/w1_b0_b2, experiments/workloads/w1)
# Requires Foundry (forge, anvil 1.4.1) and Python eth-account/eth-abi/eth-utils.
baselines-build: ## Compile the B0/B1/B2 contracts (EntryPoint v0.9.0, SimpleAccount, ObservablePaymaster)
	@cd baselines/w1_b0_b2 && forge build

# --- Frozen B3 (PrivGas v1) evaluation: NON-PRODUCTION | NON-EIP-170-DEPLOYABLE-AS-BUILT |
# PRIVACY-EVALUATION-ONLY. Compiles the unmodified submodule sources from baselines/b3_eval.
b3-eval-build: ## Compile the frozen B3 contracts (unmodified) for the b3_compat_local evaluation profile
	@cd baselines/b3_eval && forge build

b3-prover-install: ## Install the pinned Semaphore prover (@semaphore-protocol/core 4.14.2) from package-lock.json
	@cd experiments/workloads/w1/prover && npm ci --no-audit --no-fund

b3-eip170-test: ## Regression: the frozen PoseidonT3 still exceeds EIP-170 (docs/b3-reproduction.md)
	@cd test/b3_ordinary_deploy && forge test --match-test test_poseidonT3_confirmedExceedsEip170SizeLimit

calibrate-pvg: baselines-build b3-eval-build b3-prover-install ## CALIBRATION phase, both profiles: EntryPoint overhead O -> baselines/w1_b0_b2/calibration/pvg-overhead[.b3_compat_local].json
	@python3 -m experiments.workloads.w1.calibrate --seed $(or $(SEED1),910001) --seed $(or $(SEED2),910002)
	@python3 -m experiments.workloads.w1.calibrate --profile b3_compat_local --seed $(or $(SEED1),910001) --seed $(or $(SEED2),910002)

baselines-test: baselines-build b3-eval-build b3-prover-install ## Forge semantics tests + live anvil tests for real B0/B1/B2 and the frozen B3
	@echo "Running B0/B1/B2 Foundry tests..."
	@cd baselines/w1_b0_b2 && forge test
	@echo "Running B0/B1/B2 and B3-PrivGas-v1 live W1 tests against anvil..."
	@python3 -m unittest discover -s experiments/workloads/w1/tests -t .

run-matched-baselines: ## Real W1 runs (B0, B1 cold/warm, B2-Allowlist, B2-Signature) through the recorder: make run-matched-baselines SEED=<seed> [VARIANT=all]
	@if [ -z "$(SEED)" ]; then echo "ERROR: SEED is required, e.g. make run-matched-baselines SEED=42 [VARIANT=B1:W1-warm]"; exit 1; fi
	@python3 -m experiments.workloads.w1 --variant $(or $(VARIANT),all) --seed $(SEED)

run-b3-evaluation: b3-prover-install ## Matched B0/B1/B2-Signature on both profiles + B3-PrivGas-v1 on b3_compat_local, with profile effect: make run-b3-evaluation SEED=<seed>
	@if [ -z "$(SEED)" ]; then echo "ERROR: SEED is required, e.g. make run-b3-evaluation SEED=42"; exit 1; fi
	@python3 -m experiments.workloads.w1 --variant matched --profile eip170_standard --profile b3_compat_local --seed $(SEED)

# --- D1 multi-actor pilot (docs/d1-pilot-results.md) ---------------------------------
d1-test: b3-prover-install ## D1 pilot: static + live tests (workload, registry, splits, models, boundary)
	@python3 -m unittest discover -s experiments/workloads/d1/tests -t .
	@python3 -m unittest discover -s experiments/privacy/d1/tests -t .

d1-registry-docs: ## Regenerate the T/AA/G tables in docs/d1-feature-registry.md
	@python3 -m experiments.privacy.d1.registry --write

d1-pilot-run: baselines-build b3-eval-build b3-prover-install ## Run + record the pilot matrix: make d1-pilot-run SEED_FILE=data/private/d1-pilot/master_seed.txt BATCH=<utc stamp>
	@if [ -z "$(SEED_FILE)" ] || [ -z "$(BATCH)" ]; then echo "ERROR: SEED_FILE and BATCH are required"; exit 1; fi
	@python3 -m experiments.workloads.d1 --master-seed-file $(SEED_FILE) --batch $(BATCH) --no-build

d1-pilot-attack: ## Splits -> self-check -> training labels -> attacks -> scoring (separate processes): make d1-pilot-attack BATCH=<batch> ROUND=<round>
	@if [ -z "$(BATCH)" ] || [ -z "$(ROUND)" ]; then echo "ERROR: BATCH and ROUND are required"; exit 1; fi
	@test -f results/d1-pilot/$(BATCH)/splits.json || python3 -m experiments.privacy.d1.attack splits --batch $(BATCH)
	@python3 -m experiments.privacy.d1.evaluate selfcheck --batch $(BATCH)
	@test -d results/d1-pilot/$(BATCH)/training_labels || python3 -m experiments.privacy.d1.evaluate export-training-labels --batch $(BATCH)
	@python3 -m experiments.privacy.d1.attack run --batch $(BATCH) --round $(ROUND)
	@python3 -m experiments.privacy.d1.evaluate score --batch $(BATCH) --round $(ROUND) --write-doc

# --- D1 B4 causal ablation: B3-PrivGas-v1 vs B4-CrossAccount (docs/d1-b4-results.md) -------
d1-b4-run: baselines-build b3-eval-build b3-prover-install ## Run + record B3 vs B4-CrossAccount (S0/S1, N=4..32, 3 reps): make d1-b4-run SEED_FILE=data/private/d1-pilot/master_seed.txt BATCH=<utc stamp>
	@if [ -z "$(SEED_FILE)" ] || [ -z "$(BATCH)" ]; then echo "ERROR: SEED_FILE and BATCH are required"; exit 1; fi
	@python3 -m experiments.workloads.d1 --config b4 --master-seed-file $(SEED_FILE) --batch $(BATCH) --no-build

d1-b4-attack: ## Splits -> self-check -> training labels -> attacks -> scoring into docs/d1-b4-results.md: make d1-b4-attack BATCH=<batch> ROUND=<round>
	@if [ -z "$(BATCH)" ] || [ -z "$(ROUND)" ]; then echo "ERROR: BATCH and ROUND are required"; exit 1; fi
	@test -f results/d1-pilot/$(BATCH)/splits.json || python3 -m experiments.privacy.d1.attack splits --batch $(BATCH)
	@python3 -m experiments.privacy.d1.evaluate selfcheck --batch $(BATCH)
	@test -d results/d1-pilot/$(BATCH)/training_labels || python3 -m experiments.privacy.d1.evaluate export-training-labels --batch $(BATCH)
	@python3 -m experiments.privacy.d1.attack run --batch $(BATCH) --round $(ROUND)
	@python3 -m experiments.privacy.d1.evaluate score --batch $(BATCH) --round $(ROUND) --write-doc --doc b4

# --- D1 final timing sanity experiment: S1b issuance<->redemption timing only (docs/d1-s1b-results.md)
d1-s1b-run: baselines-build b3-eval-build b3-prover-install ## Run + record B3/B4 under S1b (N=8,16,32; 3 reps): make d1-s1b-run SEED_FILE=... BATCH=<utc stamp>
	@if [ -z "$(SEED_FILE)" ] || [ -z "$(BATCH)" ]; then echo "ERROR: SEED_FILE and BATCH are required"; exit 1; fi
	@python3 -m experiments.workloads.d1 --config s1b --master-seed-file $(SEED_FILE) --batch $(BATCH) --no-build

d1-s1b-attack: ## Scheduler gate (must pass) -> splits -> self-check -> labels -> attacks -> scoring: make d1-s1b-attack BATCH=<batch> ROUND=<round>
	@if [ -z "$(BATCH)" ] || [ -z "$(ROUND)" ]; then echo "ERROR: BATCH and ROUND are required"; exit 1; fi
	@python3 -m experiments.privacy.d1.evaluate schedule-gate --batch $(BATCH)
	@test -f results/d1-pilot/$(BATCH)/splits.json || python3 -m experiments.privacy.d1.attack splits --batch $(BATCH)
	@python3 -m experiments.privacy.d1.evaluate selfcheck --batch $(BATCH)
	@test -d results/d1-pilot/$(BATCH)/training_labels || python3 -m experiments.privacy.d1.evaluate export-training-labels --batch $(BATCH)
	@python3 -m experiments.privacy.d1.attack run --batch $(BATCH) --round $(ROUND)
	@python3 -m experiments.privacy.d1.evaluate score --batch $(BATCH) --round $(ROUND) --write-doc --doc s1b $(if $(COMPARE),--compare $(COMPARE),)

benchmark: ## Run the benchmark suite (placeholder until protocol code exists)
	@echo "No benchmarks defined yet — add them under experiments/ and wire this target"
	@echo "to run them once application code exists (see docs/decision-log.md)."

run-local-experiment: ## Run one experiment locally: make run-local-experiment ID=<id> SEED=<seed>
	@if [ -z "$(ID)" ]; then echo "ERROR: ID is required, e.g. make run-local-experiment ID=workloads/example-001 SEED=42"; exit 1; fi
	@if [ -z "$(SEED)" ]; then echo "ERROR: SEED is required, e.g. make run-local-experiment ID=$(ID) SEED=42"; exit 1; fi
	@run_dir="results/$(ID)/$$(date -u +%Y%m%dT%H%M%SZ)"; \
	 mkdir -p "$$run_dir"; \
	 commit="$$(git rev-parse --verify -q HEAD 2>/dev/null || echo 'no commits yet')"; \
	 if [ -n "$$(git status --porcelain 2>/dev/null)" ]; then dirty=true; else dirty=false; fi; \
	 started="$$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
	 echo "No experiment logic is implemented yet for '$(ID)' (see docs/decision-log.md)."; \
	 echo "Writing metadata record only, per docs/experiment-schema.md."; \
	 { \
	   echo "{"; \
	   echo "  \"experiment_id\": \"$(ID)\","; \
	   echo "  \"git_commit\": \"$$commit\","; \
	   echo "  \"git_dirty\": $$dirty,"; \
	   echo "  \"seed\": $(SEED),"; \
	   echo "  \"chain_id\": \"$(CHAIN_ID)\","; \
	   echo "  \"entrypoint_version\": \"$(ENTRYPOINT_VERSION)\","; \
	   echo "  \"started_at_utc\": \"$$started\","; \
	   echo "  \"finished_at_utc\": \"$$started\","; \
	   echo "  \"parameters\": {},"; \
	   echo "  \"outputs\": null,"; \
	   echo "  \"note\": \"no application logic implemented yet; see docs/decision-log.md\""; \
	   echo "}"; \
	 } > "$$run_dir/metadata.json"; \
	 scripts/env-report.sh > "$$run_dir/env-report.txt"; \
	 echo "Wrote $$run_dir/metadata.json and $$run_dir/env-report.txt"

# --- D2 pilot: validation-state contention and liveness of frozen B3 (docs/d2-pilot-results.md)
d2-test: b3-eval-build b3-prover-install ## D2 pilot: static + live tests (race, classification, frozen Bootstrap limit, depth-6 proof)
	@python3 -m unittest discover -s experiments/liveness/d2/tests -t .

d2-pilot-run: baselines-build b3-eval-build b3-prover-install ## Run the D2 pilot experiments: make d2-pilot-run BATCH=<utc stamp> [EXP=all]
	@if [ -z "$(BATCH)" ]; then echo "ERROR: BATCH is required"; exit 1; fi
	@python3 -u -m experiments.liveness.d2 run --batch $(BATCH) $(foreach e,$(or $(EXP),all),--exp $(e))

d2-pilot-analyze: ## Tables, statistics, figures and the generated block of docs/d2-pilot-results.md: make d2-pilot-analyze BATCH=<stamp>
	@if [ -z "$(BATCH)" ]; then echo "ERROR: BATCH is required"; exit 1; fi
	@python3 -m experiments.liveness.d2 analyze --batch $(BATCH) --write-doc

# --- D2 kill-condition: bounded root history + gas decomposition (docs/d2-killcondition-results.md)
# NEW result namespace `d2-killcondition`; the frozen D2 pilot batch is never regenerated.
d2k-build: ## Compile the D2-History-K variant and the gas-decomposition benchmarks (contracts/d2k)
	@cd contracts/d2k && forge build

d2k-contract-test: d2k-build ## Ring-buffer retention mechanics (Foundry): boundary, duplicates, K=1, bounded storage
	@cd contracts/d2k && forge test

d2k-test: b3-eval-build d2k-build b3-prover-install ## D2K static + live tests (boundary, security invariants, benchmark primitive, grant, detection)
	@python3 -m unittest discover -s experiments/liveness/d2k/tests -t .

d2k-run: baselines-build b3-eval-build d2k-build b3-prover-install ## Run the kill-condition experiments: make d2k-run BATCH=<utc stamp> [EXP=all|hist|gas|<name>]
	@if [ -z "$(BATCH)" ]; then echo "ERROR: BATCH is required"; exit 1; fi
	@python3 -u -m experiments.liveness.d2k run --batch $(BATCH) $(foreach e,$(or $(EXP),all),--exp $(e))

d2k-analyze: ## Tables, statistics, figures and the generated block of docs/d2-killcondition-results.md: make d2k-analyze BATCH=<stamp>
	@if [ -z "$(BATCH)" ]; then echo "ERROR: BATCH is required"; exit 1; fi
	@python3 -m experiments.liveness.d2k analyze --batch $(BATCH) --write-doc

clean: ## Remove local, regenerable artifacts (does not touch data/private)
	@echo "Cleaning regenerable artifacts..."
	@find results -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
	@find figures -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
	@find data/raw -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
	@echo "Done. data/private/ was left untouched."

env-report: ## Print exact tool versions + git state (the reproducibility snapshot)
	@scripts/env-report.sh
