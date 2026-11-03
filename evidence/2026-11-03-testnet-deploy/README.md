# Registry deployment, NEAR testnet, 2026-11-03

| Step | Transaction |
|---|---|
| Create `fuin.testnet` (faucet) | [CnEzSoNsYVQkQk5bKK2Xk5Ye2sAuDSzEQFK8s5FCYGSh](https://testnet.nearblocks.io/txns/CnEzSoNsYVQkQk5bKK2Xk5Ye2sAuDSzEQFK8s5FCYGSh) |
| Create `registry.fuin.testnet` (3 NEAR) | [6fUy8zfnfWxHxxLkNVBbr4hYWEZL2aFSgy699CFhftoh](https://testnet.nearblocks.io/txns/6fUy8zfnfWxHxxLkNVBbr4hYWEZL2aFSgy699CFhftoh) |
| Deploy `contract/` + `new()` | [FJGqyUNVYpecHBrKgWdPyJLHvVrS3fH9VqZhQvRuiw7w](https://testnet.nearblocks.io/txns/FJGqyUNVYpecHBrKgWdPyJLHvVrS3fH9VqZhQvRuiw7w) |

- Build: `cd contract && cargo near build non-reproducible-wasm` (cargo-near 0.22.0, rustc 1.95.0) → `fuin_registry.wasm`, sha256 `cbf03d1cf90160c803da8f30b5f08e27270c7ca46a25a3d43c2a9a2a2f89b1b9`.
- On-chain `code_hash` (base58 sha256): `Ej6EQ3yyVPL9xNLdvpZJaJWUYnyrx6T7Gw67kwTkH8BA` — matches the local build.
- Access keys: one full-access key is **still held** on `registry.fuin.testnet`, so the code can still be replaced. It is deleted before the first real sealed run; until then, records here are not append-only guaranteed.
