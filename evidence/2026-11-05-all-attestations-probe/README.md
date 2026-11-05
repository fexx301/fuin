# Can a report list every instance that shares a signing key? Probe, 2026-11-05

**Question.** The limits say "Model instances can share a key even with different configurations." NEAR's direct-endpoint reports carry an `all_attestations` field. If it listed every instance holding the model's signing key, the verifier could require all of them to run an approved configuration, and that limit would narrow.

**Method.** One keyless report request, each with a fresh nonce, to each of three direct endpoints listed in the public registry `https://completions.near.ai/endpoints`: `qwen3-8-27b`, `glm-5-3-flash` and `deepseek-v4-1-flash`. Also one gateway report (`cloud-api.near.ai/v1/attestation/report?model=Qwen/Qwen3.8-27B`).

**Result.**

| Endpoint | `all_attestations` entries | Same quote as the report's own? | Compose hash |
|---|---|---|---|
| qwen3-8-27b | 1 | yes | `5e513dbd…` |
| glm-5-3-flash | 1 | yes | `5f7ebd85…` |
| deepseek-v4-1-flash | 1 | yes | `ae66f844…` |

- Each list holds only the instance that answered, bound to our nonce. It doesn't enumerate other instances.
- The gateway report has no `all_attestations` field. Its `model_attestations` also holds one entry.
- Policy v6 approves two configurations for GLM (`5f7ebd85…`, `a0e3c6f4…`) that sign with one key, so instances sharing a key do exist.

**Conclusion.** The limit stays as written. No report available today lets a verifier enumerate the instances behind a signing key. If NEAR's `all_attestations` starts listing them, the verifier can require every entry to pass the same checks as the preflight report.
