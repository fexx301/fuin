# Round 5: zero-reveal and end-to-end encrypted, 96 questions, three models, 2026-11-05

Round 5 reveals nothing, and its questions never crossed NEAR's gateway in the clear. Its sealed policy:
- **Request template v3.** Each question is encrypted to the answering model's attested TEE key, and the answer comes back encrypted to a key derived from the item's secret salt. Each nonce is bound to the seal block's hash.
- **Scorer.** Every item is scored inside OutLayer's Intel TDX enclave by the sealed scorer v3 (`2614ddaa…`). The scorer re-encrypts each question from its salt to match the signed bytes, and decrypts each answer before scoring.

All three certificates VERIFY keyless (`verify-output.txt`, `verify.jsonl`, exit 0). Each prints the end-to-end-encryption limit.

**Suite.** 96 new questions, one per cited line of [near/docs](https://github.com/near/docs) at `e2d2ea17`. None cites a line used by rounds 1–4. All of them stay private.

| Model (served as) | Committed = TEE total | Cut off (owner-reported) | Commit | TEE score (OutLayer task) |
|---|---|---|---|---|
| deepseek-ai/DeepSeek-V4.1-Flash-1017 (same name) | **48/96** | 2 | `GBpKnpgvdtBWpYzJMEvYJc9ywzpmrBV5625fczMT9y9D` | `Ft7Re7JonAWkWMMYU2JwqATu2rhx9oxNFNU75YDYYYUW` (21373) |
| z-ai/glm-5.3-flash (`graphistry/GLM-5.3-Flash-W4AFP8`) | **42/96** | 26 | `F9je6opfQvutVcvzaj6yhoG6tkLNy8Dekcy5An168qXH` | `J444HPEbsMp668Q4SZyhpchMvGgXzPwAkfuf2ZZv4Mp9` (21374) |
| Qwen/Qwen3.8-27B (`Qwen/Qwen3.8-27B-FP8`) | **27/96** | 9 | `BFDc5MKAa21KjKwyMTmMDKK8DguxgZYeMSMpM8gPzMsd` | `9pDZWWGkWHoWczvdHsoWF3bYEPZ3eyKyAvoD4xadfEXn` (21375) |

- **Seal:** `88z24HiczTdmJKBc932L6DqTrdUb6TphsNnXw68KfUo1` at height 276350082 (block hash `GrDFw8mbckEjD1VXCPD1Pdc3iZVAMoJoujsbGwXQeYoR`).
- **Close:** `Aav6gqN8Vh165xqjzse9vrtmZ8MQ6o7fzScnkyA16abq` at 276373812.
- **Settings:** reasoning on, temperature 0 and a cap of 8,192 tokens, as in round 4.
- **On the wire:** none of the 288 signed requests contains its question in plaintext. Every answer and its reasoning came back as ciphertext.
- **TEE hosting:** each encrypted run sat on a secret gist only while the scorer fetched it, then was deleted.

**Before the real round:**
- **Probe:** `../2026-11-05-e2ee-probe/`.
- **Synthetic round inside OutLayer:** scorer v3 matched Python (task 21122).
- **End-to-end rehearsal on testnet:** `e2ee-rehearsal-1`, 3 synthetic questions, sealed, run, committed, closed, TEE-scored (task 21135) and VERIFIED.

**Failed attempts (owner-reported, in each certificate's attempt log):**
- **DeepSeek:** none.
- **GLM:** three.
- **Qwen:** 55, all `Connection reset by peer` on long answers.
  - **No completed answer was discarded or re-asked.** Since round 4, `fuin run` keeps answers that complete after a failure and uses them on resume.
  - **Fix for later rounds:** TCP keepalive on completions (`47252a5`). It was released after Qwen's run had started.

**What this round shows.**
- **No answer predates the seal.**
- **Every hidden score is checked exactly inside the TEE.**
- **Nothing is revealed.**
- **The gateway never saw a question or an answer.** It saw the model, the settings, the nonce, the timing and the sizes.

**What it trusts.**
- **The answering model's TEE,** to decrypt honestly.
- **The TEE trust assumptions printed with every TEE score:** Intel TDX, and OutLayer's worker approvals and key service.

Compare models within this round; its questions differ from rounds 1–4.
