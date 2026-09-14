#!/usr/bin/env bash
# scripts/run_b3_ordinary_deploy.sh
#
# Attempts to deploy B3's CreditPool (baselines/b3_privgas_v1) with a real,
# ordinary signed transaction against a plain, default Anvil node (no
# --code-size-limit override) -- i.e. an EIP-170-enforcing EVM, using a real
# private key via `forge script --broadcast`, never vm.prank/vm.etch
# impersonation. See docs/b3-reproduction.md for why this matters and what
# the expected/observed result is.
#
# This script starts its own throwaway anvil instance and tears it down on
# exit, so it's safe to run repeatedly.
#
# Usage: scripts/run_b3_ordinary_deploy.sh

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
proj_dir="$repo_root/test/b3_ordinary_deploy"
out_dir="$repo_root/results/b3"
mkdir -p "$out_dir"

# Anvil's well-known default dev key for account (0) -- an ordinary key with a
# real private key/signature, not a cheatcode-impersonated address.
DEPLOYER_PK="0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
RPC_URL="http://127.0.0.1:8555"
ANVIL_LOG="$out_dir/ordinary-deploy-anvil.log"
DEPLOY_LOG="$out_dir/ordinary-deploy.log"

anvil --port 8555 > "$ANVIL_LOG" 2>&1 &
anvil_pid=$!
cleanup() { kill "$anvil_pid" >/dev/null 2>&1; }
trap cleanup EXIT

# Wait for anvil to accept connections.
for _ in $(seq 1 30); do
  if cast chain-id --rpc-url "$RPC_URL" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

echo "=== Attempting ordinary-key deployment of B3's CreditPool ===" | tee "$DEPLOY_LOG"
echo "anvil: default settings, no --code-size-limit override (i.e. EIP-170 enforced)" | tee -a "$DEPLOY_LOG"
echo | tee -a "$DEPLOY_LOG"

cd "$proj_dir"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
DEPLOYER_PK="$DEPLOYER_PK" forge script script/OrdinaryDeploy.s.sol:OrdinaryDeploy \
  --rpc-url "$RPC_URL" --broadcast -vvvv >> "$DEPLOY_LOG" 2>&1
deploy_exit=$?
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

status="unknown"
reason=""
if [ "$deploy_exit" -eq 0 ]; then
  status="succeeded"
else
  status="failed"
  reason="$(grep -m1 'above the contract size limit' "$DEPLOY_LOG" || true)"
fi

cat > "$out_dir/ordinary-deploy-result.json" <<EOF
{
  "baseline_id": "b3_privgas_v1",
  "target_contract": "CreditPool",
  "method": "forge script --broadcast, ordinary anvil default dev key (account 0), default (EIP-170-enforcing) anvil settings",
  "started_at_utc": "$started_at",
  "finished_at_utc": "$finished_at",
  "exit_code": $deploy_exit,
  "status": "$status",
  "reason": "$(printf '%s' "$reason" | sed 's/"/\\"/g')",
  "raw_log": "results/b3/ordinary-deploy.log"
}
EOF

echo | tee -a "$DEPLOY_LOG"
echo "Status: $status" | tee -a "$DEPLOY_LOG"
[ -n "$reason" ] && echo "Reason: $reason" | tee -a "$DEPLOY_LOG"
echo "Wrote $out_dir/ordinary-deploy-result.json"

exit 0
