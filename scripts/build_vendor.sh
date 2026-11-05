#!/usr/bin/env bash
# Rebuild the in-browser verifier's vendored crypto from pinned npm packages (all MIT):
#   site/vendor/noble.js  secp256k1 + keccak (paulmillr/noble) for EIP-191 signature recovery
#   site/vendor/yaml.js   YAML (js-yaml) for the deployment trace
#   site/vendor/dcap.js   Intel TDX quote verification (Phala dcap-qvl, Rust compiled to WASM, embedded as base64)
set -euo pipefail
cd "$(dirname "$0")/../site/vendor"
npm install --no-audit --no-fund
npx esbuild entry.mjs --bundle --format=iife --global-name=Noble --minify --legal-comments=inline --outfile=noble.body.js
{ printf '/*! Bundled from @noble/curves 2.4.0 and @noble/hashes 2.4.0 — MIT License (c) Paul Miller (paulmillr.com). Rebuild: scripts/build_vendor.sh */\n'; cat noble.body.js; } > noble.js && rm noble.body.js
npx esbuild yaml-entry.mjs --bundle --format=iife --global-name=Yaml --minify --legal-comments=inline --outfile=yaml.body.js
{ printf '/*! Bundled from js-yaml 4.1.0 — MIT License (c) Vitaly Puzrin. Rebuild: scripts/build_vendor.sh */\n'; cat yaml.body.js; } > yaml.js && rm yaml.body.js
npx esbuild dcap-entry.mjs --bundle --format=iife --global-name=Dcap --minify --loader:.wasm=base64 --legal-comments=inline --outfile=dcap.body.js
{ printf '/*! Bundled from @phala/dcap-qvl-web 0.3.3 (Rust dcap-qvl compiled to WASM) — MIT License, Phala Network. Rebuild: scripts/build_vendor.sh */\n'; cat dcap.body.js; } > dcap.js && rm dcap.body.js
shasum -a 256 noble.js dcap.js yaml.js
