# Results

Which NEAR AI Cloud model answers NEAR developer questions correctly?

Seven independent rounds of private questions (60, 60, 300, 155, 96, 96 and 37), each with exact answers cited to a line of [near/docs](https://github.com/near/docs) at commit `e2d2ea17`. They come in [three kinds](HOW-IT-WORKS.md#three-kinds-of-round): rounds 1–3 reveal a sample, rounds 4–6 reveal nothing, and in round 7 a TEE asked every question once. Each round was sealed on NEAR before its run: for rounds 4–7, each request's nonce is bound to the seal block, so no answer can predate the seal; for rounds 1–3 the public checks show only that the seal preceded the committed results, and the run's timing is the owner's word. Every model ran with reasoning on and temperature 0. Rounds 4–7 reveal nothing; their scores are checked only inside the TEE. Rounds 5–7 also encrypted every question and answer end to end, so NEAR's gateway never saw them. Round 6 runs all seven models NEAR serves in its own TEEs, including two "abliterated" versions (a LoRA adapter that removes refusal training, on the same base weights). The scorer is strict about form: the answer must be the number or term alone. It ignores surrounding quotes, backticks and markdown emphasis and one trailing period, and compares exact answers case-insensitively, so `u128::MAX` counts as `U128::MAX`.

| Round (token cap) | Model (as served by NEAR AI Cloud) | Committed score | Revealed (k): correct · wrong · format · cut off | Whole run: cut off (owner-reported) |
|---|---|---|---|---|
| `near-dev-37-r7` (4,096), zero-reveal, end-to-end encrypted, **each question asked once by a TEE** | deepseek-ai/DeepSeek-V4.1-Flash-1017 | **19/37** (51.4%) | nothing revealed | not visible: no response left the enclave |
| `near-dev-96-r6` (8,192), zero-reveal, end-to-end encrypted, seven models | deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated (LoRA adapter on the base weights) | **40/96** (41.7%) | nothing revealed | 2/96 |
| `near-dev-96-r6` (8,192), zero-reveal, end-to-end encrypted, seven models | deepseek-ai/DeepSeek-V4.1-Flash-1017 | **38/96** (39.6%) | nothing revealed | 2/96 |
| `near-dev-96-r6` (8,192), zero-reveal, end-to-end encrypted, seven models | z-ai/glm-5.3-flash | **33/96** (34.4%) | nothing revealed | 28/96 |
| `near-dev-96-r6` (8,192), zero-reveal, end-to-end encrypted, seven models | Qwen/Qwen3.6-35B-A3B-FP8 | **22/96** (22.9%) | nothing revealed | 8/96 |
| `near-dev-96-r6` (8,192), zero-reveal, end-to-end encrypted, seven models | Qwen/Qwen3.8-27B | **22/96** (22.9%) | nothing revealed | 14/96 |
| `near-dev-96-r6` (8,192), zero-reveal, end-to-end encrypted, seven models | Qwen/Qwen3.8-27B-abliterated (LoRA adapter, unpinned) | **21/96** (21.9%) | nothing revealed | 24/96 |
| `near-dev-96-r6` (8,192), zero-reveal, end-to-end encrypted, seven models | Qwen/Qwen3-VL-30B-A3B-Instruct | **11/96** (11.5%) | nothing revealed | 0/96 |
| `near-dev-96-r5` (8,192), zero-reveal, end-to-end encrypted | deepseek-ai/DeepSeek-V4.1-Flash-1017 | **48/96** (50.0%) | nothing revealed | 2/96 |
| `near-dev-96-r5` (8,192), zero-reveal, end-to-end encrypted | z-ai/glm-5.3-flash | **42/96** (43.8%) | nothing revealed | 26/96 |
| `near-dev-96-r5` (8,192), zero-reveal, end-to-end encrypted | Qwen/Qwen3.8-27B | **27/96** (28.1%) | nothing revealed | 9/96 |
| `near-dev-155-r4` (8,192), zero-reveal | deepseek-ai/DeepSeek-V4.1-Flash-1017 | **84/155** (54.2%) | nothing revealed | 1/155 |
| `near-dev-155-r4` (8,192), zero-reveal | z-ai/glm-5.3-flash | **64/155** (41.3%) | nothing revealed | 36/155 |
| `near-dev-155-r4` (8,192), zero-reveal | Qwen/Qwen3.8-27B | **39/155** (25.2%) | nothing revealed | 26/155 |
| `near-dev-300-r3` (8,192) | z-ai/glm-5.3-flash, served as `graphistry/GLM-5.3-Flash-W4AFP8` | **122/300** (40.7%) | (28) 10 · 14 · 0 · 4 | 72/300 |
| `near-dev-300-r3` (8,192) | Qwen/Qwen3.8-27B, served as `Qwen/Qwen3.8-27B-FP8` | **77/300** (25.7%) | (28) 9 · 17 · 0 · 2 | 54/300 |
| `near-dev-60-r2` (8,192) | z-ai/glm-5.3-flash | **32/60** | (23) 13 · 4 · 2 · 4 | 6/60 |
| `near-dev-60-r2` (8,192) | Qwen/Qwen3.8-27B | **17/60** | (23) 7 · 13 · 0 · 3 | 7/60 |
| `near-dev-60-r1` (4,096) | z-ai/glm-5.3-flash | **25/60** | (23) 10 · 5 · 1 · 7 | 21/60 |
| `near-dev-60-r1` (4,096) | Qwen/Qwen3.8-27B | **17/60** | (23) 6 · 9 · 0 · 8 | 17/60 |

DeepSeek-V4.1-Flash, added in round 4, leads all three rounds it ran: 84 of 155, 48 of 96 and 38 of 96 (40 for its abliterated version). In round 6, removing refusal training made no measurable difference: +2 for DeepSeek and −1 for Qwen, well inside each pair's 95% interval. On all six suites, GLM-5.3-flash as NEAR serves it answers more NEAR developer questions correctly than Qwen. On the 300-question round the gap is 45 questions (122 against 77). Qwen's revealed misses are mostly wrong answers rather than cut-offs. At the same 8,192 cap, round 3 cut off GLM 72 times and Qwen 54 times. Even if every cut-off had ended in a correct answer, GLM would still lead (194 against 131), but that is an upper bound, not a measurement: what either model would answer with a larger cap is unknown without a higher-cap rerun. The rounds use different questions, so compare models within a round, not percentages across rounds.

**Reading the columns:**
- **Revealed breakdown:** a reading aid computed from the revealed bytes (`fuin show`), not a score. *Format* means the right value in a form the strict scorer rejects, such as `**10%**`. *Cut off* means no final answer before the cap.
- **Scorer and cut-offs:** the scorer reads only the final answer text and ignores whether generation was cut off. A cut-off response usually has no final answer, so it scores 0; every revealed cut-off here had none.
- **Served as (in the model column):** comes from the deployment trace taken at each run's preflight ([deployment trace](HOW-IT-WORKS.md#the-flow)). These are NEAR's deployed quantized builds, not the full-precision checkpoints that public benchmark tables usually describe.

**Disclosure:**
- **Round 1:** the audit directly reveals 23 items, which is what the verifier reports as "directly revealed 23, unrevealed 37". One unrevealed item cites the same docs line as two revealed items, and its answer follows from theirs. It is indirectly disclosed, which the verifier does not compute. Known disclosure: **24 items; 36 stay hidden.**
- **Round 2:** one question per cited line, so its known disclosure is the 23 revealed; **37 stay hidden.**
- **Round 3:** one question per cited line, and none shares a line with rounds 1–2. The audit reveals 28; **272 of 300 (91%) stay hidden**, at the same 95% detection power as the 60-question rounds.
- **Round 4:** reveals nothing. All 155 stay hidden, one question per cited line, none shared with rounds 1–3.
- **Round 5:** reveals nothing, and its questions and answers were end-to-end encrypted. All 96 stay hidden, one question per cited line, none shared with rounds 1–4.
- **Round 6:** reveals nothing, end-to-end encrypted, seven models. All 96 stay hidden, one question per cited line, none shared with rounds 1–5.
- **Round 7:** reveals nothing, end-to-end encrypted, and every question was asked once by a TEE ([asked once](HOW-IT-WORKS.md#asked-once-round-7)). All 37 stay hidden, one question per cited line, none shared with rounds 1–6. Its 4,096-token cap (rounds 4–6 used 8,192) is what fits a TEE-made call, so its score isn't comparable with round 6's.
- **Every round, scored inside a TEE:** all twenty totals were computed over every signed answer (2,302 in all) inside an Intel TDX enclave on OutLayer and match the commitments, so the unrevealed scores (37, 37, 272, 155, 96, 96 and 37 per run) are checked exactly, not by sample ([TEE score](HOW-IT-WORKS.md#tee-score)).
- **Answer keys checked at the source:** in rounds 4–7, which reveal nothing, a TEE fetched every cited near/docs line and found 374 of the 384 sealed answer keys in it (ignoring commas, backticks and asterisks); 10 are flagged as unchecked (derived numbers, or an alternative broader than the line) ([answer keys](HOW-IT-WORKS.md#answer-keys-checked-against-their-sources)).

**Disclosure at scale.** For a fixed detection target the audit size grows only slowly with suite size and levels off (23 items at 60, 29 at 1,000), so larger private suites disclose a far smaller share. From the same `core.audit_size` code, at ≥95% detection power for ≥10% incorrect scores:

| Suite size n | Items revealed k | Share revealed |
|---|---|---|
| 60 | 23 | 38.3% |
| 200 | 27 | 13.5% |
| **300 (round 3, measured)** | **28** | **9.3%** |
| 500 | 28 | 5.6% |
| 1,000 | 29 | 2.9% |
