#!/usr/bin/env bash
# scripts/run_b3_original.sh
#
# Reproduces the existing B3 (PrivGas v1) test suite exactly as vendored in
# baselines/b3_privgas_v1, with no modification, and emits machine-readable
# output to results/b3/. See docs/b3-reproduction.md for the narrative and
# docs/experiment-schema.md for the general reproducibility contract.
#
# Usage: scripts/run_b3_original.sh

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
baseline_dir="$repo_root/baselines/b3_privgas_v1"
out_dir="$repo_root/results/b3"
mkdir -p "$out_dir"

if [ ! -d "$baseline_dir/.git" ] && [ ! -f "$baseline_dir/.git" ]; then
  echo "ERROR: $baseline_dir is not initialized. Run:" >&2
  echo "  git submodule update --init --recursive baselines/b3_privgas_v1" >&2
  exit 1
fi

cd "$baseline_dir"
commit="$(git rev-parse HEAD)"
pinned_commit="02a3f0abdb979446545aa87149080bfb44e43a3e"
if [ "$commit" != "$pinned_commit" ]; then
  echo "WARNING: baselines/b3_privgas_v1 is at $commit, expected pinned commit $pinned_commit" >&2
  echo "         (see docs/references.md / docs/decision-log.md)" >&2
fi

echo "=== Reproducing B3 (PrivGas v1) test suite at commit $commit ==="
echo "forge version: $(forge --version | head -n1)"
echo

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
test_json_file="$out_dir/forge-test.json"
test_log_file="$out_dir/forge-test.log"

set +e
forge test --json > "$test_json_file" 2> "$test_json_file.stderr"
json_exit=$?
forge test -v > "$test_log_file" 2>&1
log_exit=$?
set -e
finished_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

pass_count="$(grep -c '\[PASS\]' "$test_log_file" || true)"
fail_count="$(grep -c '\[FAIL' "$test_log_file" || true)"

cat > "$out_dir/reproduction.json" <<EOF
{
  "baseline_id": "b3_privgas_v1",
  "source_repo": "https://github.com/imranpollob/stealth-protocol",
  "baseline_commit": "$commit",
  "expected_pinned_commit": "$pinned_commit",
  "commit_matches_pin": $([ "$commit" = "$pinned_commit" ] && echo true || echo false),
  "started_at_utc": "$started_at",
  "finished_at_utc": "$finished_at",
  "forge_version": "$(forge --version | head -n1 | sed 's/"/\\"/g')",
  "test_exit_code": $log_exit,
  "tests_passed": $pass_count,
  "tests_failed": $fail_count,
  "raw_json_log": "results/b3/forge-test.json",
  "raw_text_log": "results/b3/forge-test.log"
}
EOF

echo
echo "Passed: $pass_count, Failed: $fail_count"
echo "Wrote $out_dir/reproduction.json, $test_json_file, $test_log_file"

if [ "$fail_count" -ne 0 ]; then
  echo "One or more tests failed -- see $test_log_file" >&2
  exit 1
fi
