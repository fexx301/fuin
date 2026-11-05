#!/usr/bin/env bash
# One-command review: every check a judge can run without an account, API key or the hidden test set.
# Exit 0 only if all pass. Needs uv and network (Intel PCS, NVIDIA NRAS, an archival NEAR testnet RPC, NEAR AI catalog, GitHub raw,
# Docker Hub for image build provenance). Optional: Docker, for the TEE scorer rebuild; Node 20+, for the browser verifier.
# Optional: cargo, for the contract tests (skipped with a note if absent). Takes about 16 minutes; allow 30.
set -u
cd "$(dirname "$0")/.."
unset NEARAI_API_KEY
export FUIN_CACHE_DIR="$PWD/.fuin-cache"  # immutable downloads (image provenance bundles) stay inside the clone
fail=0
step() { printf '\n== %s\n' "$1"; }

step "1/5 verify the real certificates (expect VERIFIED for each)"
tmp=$(mktemp -d)
for c in examples/cert-*.json; do  # independent network-bound checks: run them together, print in order
  # a public service's rate limit is an outage, not a verdict: CAN'T CERTIFY evidence_unavailable is retried after a pause
  ( out="$tmp/$(basename "$c").out"
    for try in 1 2 3; do
      uv run fuin verify "$c" > "$out"; rc=$?
      if [ $rc -eq 2 ] && grep -q "evidence_unavailable" "$out" && [ $try -lt 3 ]; then sleep 60; continue; fi
      break
    done
    echo $rc > "$tmp/$(basename "$c").rc" ) &
  sleep 2  # stagger the starts: public RPCs throttle bursts
done
wait
for c in examples/cert-*.json; do
  head -1 "$tmp/$(basename "$c").out"
  [ "$(cat "$tmp/$(basename "$c").rc")" -eq 0 ] || fail=1
done
rm -rf "$tmp"

step "2/5 tamper fixtures (expect every line 'ok')"
uv run python scripts/check_fixtures.py examples/tampered/manifest.json || fail=1

step "3/5 unit tests"
uv run pytest -q 2>&1 | tail -1
[ "${PIPESTATUS[0]}" -eq 0 ] || fail=1

step "4/5 contract tests and the TEE scorer (Rust)"
if command -v cargo >/dev/null; then
  (cd contract && cargo test -q 2>&1 | grep "test result" | head -1; exit "${PIPESTATUS[0]}") || fail=1
  # The TEE scorer pins Rust 1.95.0; skipped rather than downloading a toolchain for you.
  if rustup toolchain list 2>/dev/null | grep -q '^1\.95\.0'; then
    (cd tee && cargo test -q --release 2>&1 | grep "test result" | grep -v " 0 passed" ; exit "${PIPESTATUS[0]}") || fail=1
  else
    echo "TEE scorer tests skipped: needs the pinned toolchain (rustup toolchain install 1.95.0 --target wasm32-wasip2)"
  fi
else
  echo "cargo not found: skipped (install Rust to run them)"
fi
# The canonical scorer build runs in a digest-pinned Linux image, so any host with Docker gets the same bytes.
pin=$(python3 -c 'import json;print(json.load(open("policy/tee-v2.json"))["current"])')
if docker info >/dev/null 2>&1; then
  # A build that can't complete (image pull, crate download, disk) is skipped; only a completed build with another hash fails.
  if out=$(tee/build-docker.sh 2>/dev/null) && built=$(printf '%s\n' "$out" | tail -1 | cut -d' ' -f1) && [ ${#built} -eq 64 ]; then
    if [ "$built" = "$pin" ]; then echo "TEE scorer rebuilt with tee/build-docker.sh: sha256 $built = the current pin in policy/tee-v2.json"
    else echo "TEE scorer rebuilt as $built, pin is $pin"; fail=1; fi
  else
    echo "TEE scorer rebuild skipped: tee/build-docker.sh could not complete (image pull, network or disk), not counted as a failure"
  fi
else
  echo "TEE scorer rebuild skipped: needs Docker (tee/build-docker.sh)"
fi

step "5/5 in-browser verifier, run in Node (expect every line 'ok')"
if command -v node >/dev/null && node -e 'if (!globalThis.crypto?.subtle || !globalThis.fetch) process.exit(1)' 2>/dev/null; then
  node scripts/test_site_verifier.mjs || fail=1
else
  echo "skipped: needs Node 20+ (Web Crypto and fetch); the page itself runs in any modern browser"
fi

printf '\n== %s\n' "$([ $fail -eq 0 ] && echo 'ALL CHECKS PASSED' || echo 'SOME CHECKS FAILED')"
exit $fail
