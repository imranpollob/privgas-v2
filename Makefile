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
        baselines-build baselines-test run-matched-baselines calibrate-pvg

help: ## Show this help
	@echo "privgas-v2 — available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-24s %s\n", $$1, $$2}'

install: ## Verify required tooling is present (no app dependencies exist yet)
	@echo "Checking core tooling..."
	@command -v git   >/dev/null || { echo "git not found"; exit 1; }
	@command -v bash  >/dev/null || { echo "bash not found"; exit 1; }
	@command -v make  >/dev/null || { echo "make not found"; exit 1; }
	@chmod +x scripts/*.sh 2>/dev/null || true
	@echo "Core tooling OK. No project dependency manifests exist yet"
	@echo "(no contracts/circuits/app code has been added — see docs/decision-log.md)."
	@echo "Run 'make env-report' for the full version report."

test: scaffold-test recorder-test baselines-test ## Run the full test suite

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

calibrate-pvg: baselines-build ## CALIBRATION phase: measure EntryPoint overhead O -> baselines/w1_b0_b2/calibration/pvg-overhead.json
	@python3 -m experiments.workloads.w1.calibrate --seed $(or $(SEED1),910001) --seed $(or $(SEED2),910002)

baselines-test: baselines-build ## Forge semantics tests + live anvil tests for real B0/B1/B2
	@echo "Running B0/B1/B2 Foundry tests..."
	@cd baselines/w1_b0_b2 && forge test
	@echo "Running B0/B1/B2 live W1 tests against anvil..."
	@python3 -m unittest discover -s experiments/workloads/w1/tests -t .

run-matched-baselines: ## Real W1 runs (B0, B1 cold/warm, B2-Allowlist, B2-Signature) through the recorder: make run-matched-baselines SEED=<seed> [VARIANT=all]
	@if [ -z "$(SEED)" ]; then echo "ERROR: SEED is required, e.g. make run-matched-baselines SEED=42 [VARIANT=B1:W1-warm]"; exit 1; fi
	@python3 -m experiments.workloads.w1 --variant $(or $(VARIANT),all) --seed $(SEED)

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

clean: ## Remove local, regenerable artifacts (does not touch data/private)
	@echo "Cleaning regenerable artifacts..."
	@find results -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
	@find figures -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
	@find data/raw -mindepth 1 ! -name '.gitkeep' -delete 2>/dev/null || true
	@echo "Done. data/private/ was left untouched."

env-report: ## Print exact tool versions + git state (the reproducibility snapshot)
	@scripts/env-report.sh
