#!/usr/bin/env bash
# Reproducible build of the asker, as tee/build.sh does for the scorer: the pinned toolchain, locked dependencies and
# remapped paths. It depends on ../tee (the scorer library), so the container copies both.
set -euo pipefail
cd "$(dirname "$0")"
export RUSTFLAGS="--remap-path-prefix=$PWD=/fuin-ask --remap-path-prefix=$(cd ../tee && pwd)=/fuin-tee --remap-path-prefix=${CARGO_HOME:-$HOME/.cargo}=/cargo --remap-path-prefix=${RUSTUP_HOME:-$HOME/.rustup}=/rustup"
export SOURCE_DATE_EPOCH=0
cargo build --release --locked --target wasm32-wasip2 --bin fuin-ask
w=target/wasm32-wasip2/release/fuin-ask.wasm
if command -v sha256sum >/dev/null; then sha256sum "$w"; else shasum -a 256 "$w"; fi
