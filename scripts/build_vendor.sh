#!/usr/bin/env bash
# Rebuild site/vendor/noble.js: audited secp256k1 + keccak (paulmillr/noble, MIT) bundled for the in-browser verifier.
set -euo pipefail
cd "$(dirname "$0")/../site/vendor"
npm install --no-audit --no-fund
npx esbuild entry.mjs --bundle --format=iife --global-name=Noble --minify --legal-comments=inline --outfile=noble.body.js
{ printf '/*! Bundled from @noble/curves 2.4.0 and @noble/hashes 2.4.0 — MIT License (c) Paul Miller (paulmillr.com). Rebuild: scripts/build_vendor.sh */\n'; cat noble.body.js; } > noble.js && rm noble.body.js
shasum -a 256 noble.js
