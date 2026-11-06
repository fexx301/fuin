# Rebuilding the deployed registry, 2026-11-06

`registry.fuin.testnet` is locked (no access keys). Its on-chain code hash is `HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef`: sha256 `fb85b35f…`, 134,882 bytes, built with `cargo near build non-reproducible-wasm` (cargo-near 0.22.0, rustc 1.95.0). `contract/` is unchanged since commit `2cddfd8`.

| Build from a clean checkout of `2cddfd8` | Host | sha256 | Matches the chain |
|---|---|---|---|
| cargo-near 0.22.0 installed from crates.io | macOS arm64, the build machine | `fb85b35f…` | yes |
| cargo-near 0.22.0 official release binary | macOS arm64, the build machine | `fb85b35f…` | yes |
| release binary in Docker `rust:1.95.0-slim`, build paths recreated | Linux x86_64 | `ec5a9973…` | no |
| the same | Linux arm64 | `b0b26ae0…` | no |

- **Why paths matter:** the wasm embeds the build machine's home-directory paths to dependency and standard-library sources (panic locations). The Docker builds recreated those paths, read from the deployed code. On Linux x86_64 the data section (every string and the embedded ABI) and the export list then match byte for byte; the compiled code doesn't.
- **The compiler output depends on the host:** with wasm-opt off, macOS gives `03a41c78…` and Linux x86_64 `2aafad80…`.
- **Result:** the deployed code is tied to `contract/` only on the machine that built it, so the verifier's printed limit says so. The seal and commit values are checked against the owner's signed transactions either way.
