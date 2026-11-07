# Round 6: seven models, zero-reveal and end-to-end encrypted, 96 questions, 2026-11-07

Round 6 runs every model NEAR AI Cloud serves in its own TEEs (seven) on the same 96 sealed questions. Like round 5, it reveals nothing, and no question or answer crossed NEAR's gateway in the clear.

- **Request template v3.** Each question is encrypted to the answering model's attested TEE key, and each answer comes back encrypted. Nonces are bound to the seal block's hash.
- **Scorer.** Every item is scored inside OutLayer's Intel TDX enclave by the sealed scorer v6 (`67c2292e…`), which counts unreadable answers. There were none.

All seven certificates VERIFY keyless (`verify-output.txt`, `verify.jsonl`).

**Suite.** 96 new questions, one per cited line of [near/docs](https://github.com/near/docs) at `e2d2ea17`, from 61 files. None cites a line used by rounds 1–5. All of them stay private. Every anchor was checked against its line with `scripts/check_suite_sources.py`.

| Model | Correct | 95% interval | Commit | TEE score (OutLayer task) |
|---|---|---|---|---|
| deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated | **40/96** | 32–52% | `3jbE9PrTbcG5zAvHGZWBYatANgfaaLRzNq4zk63SQMvV` | `GqgNgs6ooQFjQm9SYVWyyS1XvGwCcSeUJ1Q5XhcUHQCU` (25504) |
| deepseek-ai/DeepSeek-V4.1-Flash-1017 | **38/96** | 30–50% | `FARhmq8EZKFmmJbG2xF8hjava2sqdgZ2wQDqPqhJoLo6` | `EjMXdKmXTgwGwQ74FRR6gxz2sQih8e9Fu2rAnBdsCawv` (25501) |
| z-ai/glm-5.3-flash | **33/96** | 26–44% | `6FTFd6v4mRwnajMpu7EyJS9FRiu9CJmbFC85m6e7xRKk` | `5yot3AJTfCwhD2qr3CsCTeKd6xvsQ8xeAESZGrnkZeDU` (25505) |
| Qwen/Qwen3.6-35B-A3B-FP8 | **22/96** | 16–32% | `C1JsgQ8RCEC9YdTMtK2qbQidkj66Tg667JcMQzUVDdsD` | `7rWfvbnUMQFZZwznDKVisdawhGnoQidqDKyGc2jeZu12` (25507) |
| Qwen/Qwen3.8-27B | **22/96** | 16–32% | `59oxMta4qG5M5RFvYJNoZnSJM6E16edt1gkj1b6JiuKc` | `9PvfofiY8gbmV4obk2ZQ1HgonJxhcsZc4hwV4bsw3zU6` (25509) |
| Qwen/Qwen3.8-27B-abliterated | **21/96** | 15–31% | `CeyjkyTgGkC5ToH7R3cqftWvsbcJTgtTS6tvRZ5hjo95` | `H6oM9eL6fp65g3dPx8ofHmGooeSGXxJBMuza28SPX1Cm` (25511) |
| Qwen/Qwen3-VL-30B-A3B-Instruct | **11/96** | 7–19% | `DHuVUKpcioc3djtzd9A8PKwHo5vuhr3QRAgoexGT672Q` | `AJbZr4sSz1zovffsfygiWKhSPKL4jsSz2ek9deE6gWgT` (25515) |

- **Seal:** `FD5QSNm7bEmaDKsPTjDMBiCYurr1mGLLpgw2eSr8oJoW` at height 276592975.
- **Close:** `6ZhehthJZwirXdarTujJjB2fEsyat2g3XK98Hu3ZQvF2` at 276600324.
- **Settings:** reasoning on, temperature 0, a cap of 8,192 tokens, as in rounds 4 and 5.
- **Failed attempts (owner-reported):** none for any model.
- **TEE hosting:** each encrypted run sat on a secret gist only while the scorer fetched it, then was deleted (`gh gist list` shows none left).

**What the deployment traces show.** Each certificate traces its serving container from NEAR's attested deployment log to a public compose file:
- **DeepSeek-V4.1-Flash and its abliterated version** run the same base weights (snapshot `1bae0e10`). The abliterated name is a LoRA adapter on that instance, pinned to a Hugging Face revision: `UnderTides/DeepSeek-V4.1-Flash-1017-heretic-lora` at `196c06e3`.
- **Qwen3.8-27B's abliterated version** is a LoRA adapter on the Qwen3.8-27B-FP8 weights, loaded from `/adapters/abliterated`. It isn't pinned to a published revision, and its certificate says so in a warning.
- **Qwen3-VL-30B** traces to `Qwen3-VL-30B-A3B-Instruct-FP8` at revision `d9748a51`.

**A finding.** Removing refusal training (the abliterated LoRA adapters) made no measurable difference to NEAR knowledge on these questions: +2 for DeepSeek and −1 for Qwen, well inside each pair's 95% interval.

**Before the round:**
- **Policies v7–v9** (`policy/attestation-v7.json` to `-v9.json`) added the four new models, then two NEAR redeploys during the work: the abliterated Qwen CVM, and the DeepSeek CVMs. Each kept its signer, OS and container images. The DeepSeek redeploy landed mid-round: DeepSeek-abliterated's preflight failed four times as `measurement_unapproved` until v9 was reviewed, then its run went through.
- **Rehearsals** `e2ee-rehearsal-3` and `-4`: the four new models answered 3 synthetic questions each under end-to-end encryption, were TEE-scored and VERIFIED. They found two bugs, both fixed before this round: parallel `fuin run`s on one round lost runs (now a lock), and LoRA-served models failed the deployment trace (now traced).
- **Partner TEEs:** Kimi K2.6, DeepSeek V3.2 and Qwen3.5-397B (Chutes) and GLM-5.3 (Tinfoil) report in their providers' own attestation formats, which Fūin doesn't verify, so they aren't in this round.

**Verifying.** The first `--json` recording printed CAN'T CERTIFY `evidence_unavailable` for five certificates, because the public testnet RPC answered HTTP 429 after many calls in a row. Recorded again one at a time with the immutable-answer cache, all seven VERIFIED.
