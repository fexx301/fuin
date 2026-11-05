#!/usr/bin/env bash
# One-command review: every check a judge can run without an account, API key or the hidden test set.
# Exit 0 only if all pass. Needs uv and network (Intel PCS, NVIDIA NRAS, NEAR testnet RPC, NEAR AI catalog, GitHub raw).
# Optional: cargo, for the contract tests (skipped with a note if absent). Takes about 10 minutes.
set -u
cd "$(dirname "$0")/.."
unset NEARAI_API_KEY
fail=0
step() { printf '\n== %s\n' "$1"; }

step "1/5 verify the real certificates (expect VERIFIED for each)"
for c in examples/cert-*.json; do
  uv run fuin verify "$c" | head -1
  [ "${PIPESTATUS[0]}" -eq 0 ] || fail=1
done

step "2/5 tamper fixtures (expect every line 'ok')"
uv run python scripts/check_fixtures.py examples/tampered/manifest.json || fail=1

step "3/5 unit tests"
uv run pytest -q 2>&1 | tail -1
[ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

step "4/5 contract tests and the TEE scorer (Rust)"
if command -v cargo >/dev/null; then
  (cd contract && cargo test -q 2>&1 | grep "test result" | head -1; exit "${PIPESTATUS[0]}") || fail=1
  # The TEE scorer pins Rust 1.95.0 for a reproducible build; skipped rather than downloading a toolchain for you.
  if rustup toolchain list 2>/dev/null | grep -q '^1\.95\.0'; then
    (cd tee && cargo test -q --release 2>&1 | grep "test result" | grep -v " 0 passed" ; exit "${PIPESTATUS[0]}") || fail=1
    pin=$(python3 -c 'import json;print(json.load(open("policy/tee-v1.json"))["scorer"]["wasm_sha256"])')
    built=$(tee/build.sh 2>/dev/null | tail -1 | cut -d' ' -f1)
    if [ "$built" = "$pin" ]; then echo "TEE scorer rebuilt: sha256 $built = the pin in policy/tee-v1.json"
    elif [ "$(uname -sm)" = "Darwin arm64" ]; then echo "TEE scorer rebuilt as $built, pin is $pin"; fail=1
    else echo "TEE scorer rebuilt as $built on $(uname -sm); the pin was built on macOS arm64, and builds aren't yet identical across platforms (not counted as a failure)"; fi
  else
    echo "TEE scorer tests skipped: needs the pinned toolchain (rustup toolchain install 1.95.0 --target wasm32-wasip2)"
  fi
else
  echo "cargo not found: skipped (install Rust to run them)"
fi

step "5/5 in-browser verifier, run in Node (expect every line 'ok')"
if command -v node >/dev/null && node -e 'if (!globalThis.crypto?.subtle || !globalThis.fetch) process.exit(1)' 2>/dev/null; then
  node scripts/test_site_verifier.mjs || fail=1
else
  echo "skipped: needs Node 20+ (Web Crypto and fetch); the page itself runs in any modern browser"
fi

printf '\n== %s\n' "$([ $fail -eq 0 ] && echo 'ALL CHECKS PASSED' || echo 'SOME CHECKS FAILED')"
exit $fail
