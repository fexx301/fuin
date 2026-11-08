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

## Update, 2026-11-08: it rebuilds on GitHub's macOS runners

`.github/workflows/registry-rebuild.yml` rebuilds `contract/` on GitHub's `macos-15` arm64 runner and compares the sha256 with the code on chain. Run 42441304546 built `fb85b35fa74cce30800098ff3ee1660e29e4eafb52a755203a49136027bb99ac`, the deployed code, byte for byte.

What it took:
- **rustc 1.95.0 under the toolchain name `stable`**, as on the build machine.
- **cargo-near 0.22.0.**
- **The build machine's home-directory layout:** the workflow reads the path from the deployed code itself, so no personal path is written in the repository, and it masks the path in logs.
- **The `rust-src` component.** With it installed, rustc records the standard library's real source paths (`…/lib/rustlib/src/rust/library/…`) instead of `/rustc/<hash>/…`. A first run without it built 134,450 bytes instead of 134,882.
- **Not needed:** the checkout path. A local rebuild from a different directory gave the same hash.

Linux still gives different compiled code, so the limit now names macOS arm64 rather than "the machine that built it". It runs on every change to `contract/`, and anyone can start it by hand.
