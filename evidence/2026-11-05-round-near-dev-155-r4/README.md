# Round 4: zero-reveal, 155 questions, three models, 2026-11-05

Round 4 reveals nothing. Its sealed policy names the TEE scorer build (`dabae968…`, scorer v2) that scores every item inside OutLayer's Intel TDX enclave, and there is no audit sample. Each request's nonce is bound to the seal block's hash (request template v2), so no signed answer can predate the seal. All three certificates VERIFY keyless (`verify-output.txt`, `verify.jsonl`, exit 0).

**Suite.** 155 new questions, one per cited line of [near/docs](https://github.com/near/docs) at `e2d2ea17`. None cites a line used by rounds 1–3. All of them stay private.

| Model (served as) | Committed = TEE total | Cut off (owner-reported) | Commit | TEE score (OutLayer task) |
|---|---|---|---|---|
| deepseek-ai/DeepSeek-V4.1-Flash-1017 (same name) | **84/155** | 1 | `6z2yNdZXNFeWsjvZjwWz2AspTFUaoWEworbq1SAKc7Pj` | `EyL5vh2DDPbKXSLAeCLXHj8R5hx9nV2a9UQRA6tH9zrR` (21126) |
| z-ai/glm-5.3-flash (`graphistry/GLM-5.3-Flash-W4AFP8`) | **64/155** | 36 | `AtpBhz8op4KSsfdWCpFARCSn2KEcfQDzbbft2T5DTp5h` | `3dh6PUMi1ffcQBrQKtzgPSJzRja9nvsuiLJuCeAWRkGv` (21125) |
| Qwen/Qwen3.8-27B (`Qwen/Qwen3.8-27B-FP8`) | **39/155** | 26 | `EJuUuQGyiDoKDXVAyFi41o91qMasNBQUcjKPkXmiNNfb` | `6bryoXPETDDwJhNW7jt6w4iaxmY7T5xUXee1rdNSqZ2k` (21127) |

- **Seal:** `DPwbZJfRNm56Rn1PPKviiyiHKCjqsnnYGtopWoxUrkRN` at height 276342995 (block hash `28aMp94qPuYhTJiY44q2y9FPvmjz9FjWewwttuuGbSKt`).
- **Close:** `GJzFGpfyV3QkCm53pQDDuikV7jh3Q6VfEuhNpWra5QBG` at 276349181.
- **Settings:** reasoning on, temperature 0 and a cap of 8,192 tokens for all three models. Every model returned `reasoning_content`.
- **TEE hosting:** each encrypted run sat on a secret gist only while the scorer fetched it, then was deleted.

**Failed attempts (owner-reported, in each certificate's attempt log):**
- **GLM:** one retried request.
- **DeepSeek:** none.
- **Qwen:** a burst of `Connection reset by peer` at 13:33Z. Item 69 failed three times, so the run stopped, and the 43 answers that had already completed after it were discarded and re-asked when it resumed (29 failed attempts in all).
  - The attempt log keeps each discarded answer's score and response hash.
  - Five re-asked items scored differently: one went up, four went down, net −3 (21 → 18 on those items). Temperature 0 is not fully deterministic on NEAR's serving.
  - `fuin run` now keeps answers that complete after a failure and uses them on resume instead of re-asking (`src/fuin/owner.py`, test in `tests/test_parallel_run.py`).

**Tampering a zero-reveal certificate** (`examples/tampered/`, checked live):

| Case | Verdict |
|---|---|
| TEE score removed, so nothing checks the scores | CAN'T CERTIFY `tee_score_missing` |
| TEE record names a build other than the sealed one | REFUSED `tee_score_mismatch` |

**What this round shows and doesn't.**
- **Shows:** every hidden score is checked exactly inside the TEE, nothing is revealed, and no answer predates the seal.
- **Doesn't:** the questions still passed through NEAR's gateway in the clear. Round 5 adds end-to-end encryption to the model's TEE (request template v3).
- **Comparisons:** compare models within this round. Its questions differ from rounds 1–3.
