#!/usr/bin/env bash
# The canonical TEE scorer build: Linux x86_64 inside a digest-pinned Rust image, so a Mac (under emulation) and a Linux
# machine produce the same bytes. Copies only the sources into the container (no host target/), runs build.sh there,
# and writes dist/fuin-tee.wasm. Prints the sha256 that policy/tee-v2.json pins as "current".
set -euo pipefail
cd "$(dirname "$0")"
IMAGE="rust@sha256:e14e87345b4d5964ddcc3491d27ee046a0f23820f340c3c1e24da6880141f7c0"  # rust:1.95.0-slim, linux/amd64
mkdir -p dist
docker run --rm --platform linux/amd64 -v "$PWD":/src:ro -v "$PWD/dist":/dist "$IMAGE" bash -c '
  set -e; mkdir /fuin-tee
  cp -r /src/Cargo.toml /src/Cargo.lock /src/rust-toolchain.toml /src/manifest.json /src/build.sh /src/src /src/tests /fuin-tee/
  cd /fuin-tee && ./build.sh >&2 && cp target/wasm32-wasip2/release/fuin-tee.wasm /dist/fuin-tee.wasm'
if command -v sha256sum >/dev/null; then sha256sum dist/fuin-tee.wasm; else shasum -a 256 dist/fuin-tee.wasm; fi
