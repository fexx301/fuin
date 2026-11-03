# Registry deployment, NEAR testnet, 2026-11-03

| Step | Transaction |
|---|---|
| Create `fuin.testnet` (faucet) | [CnEzSoNsYVQkQk5bKK2Xk5Ye2sAuDSzEQFK8s5FCYGSh](https://testnet.nearblocks.io/txns/CnEzSoNsYVQkQk5bKK2Xk5Ye2sAuDSzEQFK8s5FCYGSh) |
| Create `registry.fuin.testnet` (3 NEAR) | [6fUy8zfnfWxHxxLkNVBbr4hYWEZL2aFSgy699CFhftoh](https://testnet.nearblocks.io/txns/6fUy8zfnfWxHxxLkNVBbr4hYWEZL2aFSgy699CFhftoh) |
| Deploy `contract/` + `new()` | [FJGqyUNVYpecHBrKgWdPyJLHvVrS3fH9VqZhQvRuiw7w](https://testnet.nearblocks.io/txns/FJGqyUNVYpecHBrKgWdPyJLHvVrS3fH9VqZhQvRuiw7w) |

- Build: `cd contract && cargo near build non-reproducible-wasm` (cargo-near 0.22.0, rustc 1.95.0) → `fuin_registry.wasm`, sha256 `cbf03d1cf90160c803da8f30b5f08e27270c7ca46a25a3d43c2a9a2a2f89b1b9`.
- On-chain `code_hash` (base58 sha256): `Ej6EQ3yyVPL9xNLdvpZJaJWUYnyrx6T7Gw67kwTkH8BA` — matches the local build.
- Access keys: one full-access key is **still held** on `registry.fuin.testnet`, so the code can still be replaced. It is deleted before the first real sealed run; until then, records here are not append-only guaranteed.

## Redeploy, 2026-11-03: storage paid by callers

Before this change anyone could call `seal` repeatedly and the registry paid the storage from its own balance; an owner could append runs without limit. Now `seal`, `commit_run` and `close_round` are payable: each call pays for the bytes it adds (`env::storage_byte_cost`), excess is refunded, and a benchmark holds at most 32 runs. The stored layout is unchanged, so the existing round reads as before.

- Redeploy (same account, no init): [A5pqvHDFJL5AtX6nQogeyhnfePJdZn6JULLyHT8NWEqb](https://testnet.nearblocks.io/txns/A5pqvHDFJL5AtX6nQogeyhnfePJdZn6JULLyHT8NWEqb). wasm sha256 `fb85b35fa74cce30800098ff3ee1660e29e4eafb52a755203a49136027bb99ac`; on-chain `code_hash` `HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef` matches the local build. The verifier now pins this hash.
- On-chain check: `seal` with 0 NEAR attached → `Smart contract panicked: attach at least 2740000000000000000000 yoctoNEAR to pay for 274 bytes of storage`. With 0.05 NEAR attached → sealed (`storage-check-1`, [8Dco3LWZotocaUd4xmXQ8fkPhSCZELPCr4pjssa3Uyrt](https://testnet.nearblocks.io/txns/8Dco3LWZotocaUd4xmXQ8fkPhSCZELPCr4pjssa3Uyrt)); the caller spent ≈0.003 NEAR including gas, and the rest was refunded. `storage-check-1` is a test record, not a benchmark.
- The thin-path round (`near-dev-thin-1`) was sealed under the previous code. Its certificate was re-revealed so its registry field carries the new pinned hash; the seed, sample and reveals are unchanged (a one-line diff), and it still verifies. That this was possible is the disclosed consequence of the full-access key still being held.

## Registry locked, 2026-11-03

At the user's go-ahead, the only full-access key on `registry.fuin.testnet` was deleted: [BSzPeYQaLQeuyqBD1P1KZR1EVB8Kc57RRUQphVFchep7](https://testnet.nearblocks.io/txns/BSzPeYQaLQeuyqBD1P1KZR1EVB8Kc57RRUQphVFchep7). `view_access_key_list` now returns 0 keys, so the code (hash `HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef`) can no longer be replaced and the contract has no admin or upgrade methods. Records written from here on are append-only. The verifier checks the key count and warns if a registry still has a key. The thin-path round was sealed before the lock; its history is as disclosed above.
