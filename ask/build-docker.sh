#!/usr/bin/env bash
# The canonical asker build: Linux x86_64 in the same digest-pinned Rust image as tee/build-docker.sh, so any host with
# Docker gets the same bytes. Copies only sources (ask/ and the scorer library it depends on), writes dist/fuin-ask.wasm
# and prints the sha256 that policy/tee-v2.json pins under "askers".
set -euo pipefail
cd "$(dirname "$0")"
IMAGE="rust@sha256:e14e87345b4d5964ddcc3491d27ee046a0f23820f340c3c1e24da6880141f7c0"  # rust:1.95.0-slim, linux/amd64
mkdir -p dist
out=$(mktemp -d)  # outside the read-only source mount: a nested mount confuses Docker Desktop's file sharing
docker run --rm --platform linux/amd64 -v "$PWD/..":/src:ro -v "$out":/dist "$IMAGE" bash -c '
  set -e; mkdir -p /b/tee /b/ask
  cp -r /src/tee/Cargo.toml /src/tee/Cargo.lock /src/tee/rust-toolchain.toml /src/tee/manifest.json /src/tee/src /b/tee/
  cp -r /src/ask/Cargo.toml /src/ask/Cargo.lock /src/ask/rust-toolchain.toml /src/ask/manifest.json /src/ask/build.sh /src/ask/src /b/ask/
  cd /b/ask && ./build.sh >&2 && cp target/wasm32-wasip2/release/fuin-ask.wasm /dist/fuin-ask.wasm'
cp "$out/fuin-ask.wasm" dist/fuin-ask.wasm && rm -rf "$out"
if command -v sha256sum >/dev/null; then sha256sum dist/fuin-ask.wasm; else shasum -a 256 dist/fuin-ask.wasm; fi
