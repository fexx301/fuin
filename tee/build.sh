#!/usr/bin/env bash
# Reproducible build of the TEE scorer: the pinned toolchain (rust-toolchain.toml), locked dependencies (Cargo.lock),
# and paths remapped so the binary doesn't depend on where the repo, cargo or rustup live. Prints the sha256 that
# policy/tee-v1.json pins; rebuild from a fresh clone and compare.
set -euo pipefail
cd "$(dirname "$0")"
export RUSTFLAGS="--remap-path-prefix=$PWD=/fuin-tee --remap-path-prefix=${CARGO_HOME:-$HOME/.cargo}=/cargo --remap-path-prefix=${RUSTUP_HOME:-$HOME/.rustup}=/rustup"
export SOURCE_DATE_EPOCH=0
cargo build --release --locked --target wasm32-wasip2 --bin fuin-tee
w=target/wasm32-wasip2/release/fuin-tee.wasm
if command -v sha256sum >/dev/null; then sha256sum "$w"; else shasum -a 256 "$w"; fi  # Linux, then macOS
