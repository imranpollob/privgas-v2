#!/usr/bin/env bash
# scripts/env-report.sh
#
# Prints a single, timestamped snapshot of everything needed to reproduce
# or audit a result: repo identity, git state, and every tool version this
# project's experiments might depend on. See docs/experiment-schema.md —
# every recorded experiment must be traceable back to a report like this.
#
# Usage:
#   scripts/env-report.sh          # print to stdout
#   scripts/env-report.sh --save   # also write results/env/<timestamp>.txt
#
# This script is read-only aside from the optional --save output file.

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

timestamp_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

report_version() {
  # $1 = label, $2.. = command + args to run; prints first line of output
  local label="$1"; shift
  if command -v "$1" >/dev/null 2>&1; then
    local out
    out="$("$@" 2>&1 | head -n 1)"
    printf '  %-22s %s\n' "$label" "$out"
  else
    printf '  %-22s %s\n' "$label" "not found"
  fi
}

generate_report() {
  echo "=== privgas-v2 environment report ==="
  echo "generated_at_utc: $timestamp_utc"
  echo

  echo "--- Repository ---"
  echo "  repo_root:            $repo_root"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if commit="$(git rev-parse --verify -q HEAD 2>/dev/null)"; then
      echo "  git_commit:           $commit"
      echo "  git_branch:           $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    else
      echo "  git_commit:           no commits yet"
      echo "  git_branch:           n/a"
    fi
    dirty="clean"
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then dirty="dirty"; fi
    echo "  git_worktree_status:  $dirty"
  else
    echo "  git_commit:           not a git repository"
  fi
  echo

  echo "--- Host ---"
  echo "  os:                   $(uname -s)"
  echo "  os_release:           $(uname -r)"
  echo "  arch:                 $(uname -m)"
  echo "  shell:                ${SHELL:-unknown}"
  echo

  echo "--- Core tool versions ---"
  report_version "git"    git --version
  report_version "make"   make --version
  report_version "bash"   bash --version
  echo

  echo "--- Language toolchains (if present) ---"
  report_version "node"    node --version
  report_version "npm"     npm --version
  report_version "pnpm"    pnpm --version
  report_version "yarn"    yarn --version
  report_version "python3" python3 --version
  report_version "pip3"    pip3 --version
  echo

  echo "--- Blockchain / contract tooling (if present) ---"
  report_version "forge"   forge --version
  report_version "cast"    cast --version
  report_version "anvil"   anvil --version
  report_version "solc"    solc --version
  echo

  echo "--- Circuit tooling (if present) ---"
  report_version "circom"  circom --version
  report_version "snarkjs" snarkjs --version
  echo

  echo "--- Containers (if present) ---"
  report_version "docker"  docker --version
  echo

  echo "=== end of report ==="
}

if [ "${1:-}" = "--save" ]; then
  out_dir="$repo_root/results/env"
  mkdir -p "$out_dir"
  out_file="$out_dir/$(date -u +%Y%m%dT%H%M%SZ).txt"
  generate_report | tee "$out_file"
  echo
  echo "Saved to $out_file"
else
  generate_report
fi
