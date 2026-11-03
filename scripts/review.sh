#!/usr/bin/env bash
# One-command review: every check a judge can run without an account, API key or the hidden test set.
# Exit 0 only if all pass. Needs uv and network (Intel PCS, NVIDIA NRAS, NEAR testnet RPC, NEAR AI catalog, GitHub raw).
# Optional: cargo, for the contract tests (skipped with a note if absent). Takes about 10 minutes.
set -u
cd "$(dirname "$0")/.."
unset NEARAI_API_KEY
fail=0
step() { printf '\n== %s\n' "$1"; }

step "1/4 verify the real certificates (expect VERIFIED for each)"
for c in examples/cert-*.json; do
  uv run fuin verify "$c" | head -1
  [ "${PIPESTATUS[0]}" -eq 0 ] || fail=1
done

step "2/4 tamper fixtures (expect every line 'ok')"
uv run python scripts/check_fixtures.py examples/tampered/manifest.json || fail=1

step "3/4 unit tests"
uv run pytest -q 2>&1 | tail -1
[ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

step "4/4 contract tests"
if command -v cargo >/dev/null; then
  (cd contract && cargo test -q 2>&1 | grep "test result" | head -1; exit "${PIPESTATUS[0]}") || fail=1
else
  echo "cargo not found: skipped (install Rust to run them)"
fi

printf '\n== %s\n' "$([ $fail -eq 0 ] && echo 'ALL CHECKS PASSED' || echo 'SOME CHECKS FAILED')"
exit $fail
