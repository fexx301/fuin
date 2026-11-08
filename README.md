# Fūin

Fūin (封印, pronounced *foo-een*) is Japanese for "seal": the test set is sealed on NEAR before any result is committed.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/fuin-logo-dark.svg">
  <img src="assets/fuin-logo.svg" alt="Fūin logo" width="320">
</picture>

Fūin publishes a private benchmark result that a stranger can check **without an account and without the test set**. Every answer carries a signature from the model's attested TEE key on NEAR AI Cloud, the set and results are committed on NEAR, and every answer is re-scored inside a TEE on OutLayer. A round can also reveal a sample picked by a future NEAR block, or reveal nothing at all. In round 7 a TEE made every model call itself and refused to ask any question twice, so no owner could re-ask and keep the best answer.

Built at NEAR HACKATHON (Nov 1–14, 2026), tracks `privacy` and `open`.

![The browser verifier refusing a real round-3 certificate whose revealed answer was edited after signing: REFUSED signature_text_mismatch](assets/verify-refused.png)

*The browser verifier on a real round-3 certificate after "Edit an answer": the checks pass until the revealed sample is re-scored, where the edited answer no longer matches what the model signed.*

## For judges

**Human reviewers (2 minutes):**
1. Read [the problem](#the-problem), [the three kinds of round](#three-kinds-of-round) and [the result](#result-which-near-ai-cloud-model-answers-near-developer-questions-correctly).
2. Look at [the refusals table](#try-it-no-account-no-api-key-no-test-set): 34 cases (25 tampered or malformed certificates refused, 9 that can't be certified), each caught by a named check.

**AI reviewers (Claude Code, Codex):**

**Quick check (about 2 minutes, timed from a fresh clone):**

```sh
uv sync                                    # first run downloads the dependencies
env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-96-r6-deepseek-v4.1-flash-1017.json   # about 1 minute: VERIFIED, every check printed
uv run pytest -q                           # 5 seconds, offline: 140 passed
uv run python scripts/check_fixtures.py examples/tampered/manifest.json   # optional, about 4 minutes: all 24 tampered or unsupported certificates caught
```

CAN'T CERTIFY with `evidence_unavailable` means a public service (NEAR's RPC, Intel or NVIDIA) didn't answer, not that the certificate is wrong: run the same command again.

**Full review (optional):**
- Run `scripts/review.sh` in the background. It takes about 30 minutes (allow 45), longer than many agents' command timeouts: it waits on Intel, NVIDIA, NEAR, OutLayer, GitHub and Docker Hub, and retries a public service's rate limit. It needs uv and network, and exits 0 with `ALL CHECKS PASSED`. If a free RPC keeps rate-limiting (for example, two reviews running at once from one network), a line says CAN'T CERTIFY `evidence_unavailable`: that is an outage, not a verdict; run that certificate again later. `FUIN_REVIEW_WORKERS` (default 3) sets how many certificates verify at once.
- `AGENTS.md` lists exit codes, what not to run and where evidence lives.

Every claim below maps to a command:

| Claim | Check | Expected |
|---|---|---|
| A stranger can verify a result without an account or the test set | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-60-r1-qwen3.8-27b.json` | `VERIFIED`, 10 `[pass]` lines, exit 0 |
| Each answer is signed by the model's TEE-attested key | same output, `signatures` and `attestation` lines | `60/60 provider_tee …`; `quote UpToDate, NRAS True` |
| The served container and weights are traced to NEAR's public deployment repo | same output, `deployment trace` line | `… nearai/cvm-compose-files: model-sg-qwen38-27b-fp8-tp1-coloc …` |
| The set and results were committed on NEAR, with the seal before the commit and the commit before the close | same output, `registry` line | `seal … < commit … < close …` |
| The owner can't choose which items a committed round reveals | same output, `audit sample` line; fixture `changed-audit` | `first final block ≥ close+2`; `REFUSED audit_sample_mismatch` |
| Tampering is refused with a specific reason | `uv run python scripts/check_fixtures.py examples/tampered/manifest.json` | 34 `ok` lines, exit 0 |
| Round 3's totals were re-scored over every answer inside a TEE, not only the sample | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-300-r3-glm-5.3-flash.json` | `[pass] tee score: all 300 items rebuilt and re-scored inside an OutLayer TDX enclave … total 122/300 and both roots match` |
| A round can reveal nothing and still be checked, with no answer predating its seal | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-155-r4-deepseek-v4.1-flash-1017.json` | `VERIFIED`; `[pass] reveals: none: a TEE-scored round reveals nothing …`; `[pass] tee score: all 155 items rebuilt and re-scored …: total 84/155 …`; fixtures `zero-reveal-unscored`, `zero-reveal-scorer-swapped` |
| A zero-reveal round's answer keys come from their cited sources | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-96-r6-glm-5.3-flash.json` | `[pass] answer keys: 92/96 answer keys appear in their cited line of near/docs at e2d2ea17, checked inside an OutLayer TDX enclave …; 4 flagged, not checked …: items 14, 35, 46, 94`; fixtures `ground-other-round`, `ground-hidden-flag`, `ground-fork-commit`, `ground-unpinned-build` |
| Each answer was asked once, by a TEE, not by the owner (no re-asking to keep the best answer) | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-37-r7-deepseek-v4.1-flash-1017.json` | `VERIFIED`; `[pass] asked once: all 37 answers asked once inside an OutLayer TDX enclave by asker dbbb286b744c… in ask.fuin.testnet/asker … 1 retried ask … every request rebuilt with the seal block's hash … equals the signed one, so every ask came after the seal … ask.fuin.testnet/asker was locked at the seal …`; fixtures `asked-unscored`, `asked-unchecked`, `asked-other-project`, `asked-total-edited`, `asked-check-edited`, `asked-hidden-retry` |
| Questions and answers can stay end-to-end encrypted, so NEAR's gateway never sees them | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-96-r5-glm-5.3-flash.json` | `VERIFIED`; the policy line ends `fuin-request-v3 (end-to-end encrypted)`, and the limits print the end-to-end-encryption line; probe: `evidence/2026-11-05-e2ee-probe/` |
| The TEE scorer that ran is this repository's code | `tee/build-docker.sh` (any host with Docker; about 1.5 minutes once the image is pulled) | prints `b301d22b…`, the current pin in `policy/tee-v2.json` (scorer v9: scores as v7, grounds answer keys, runs the asked-check); `ask/build-docker.sh aaa2083` prints `dbbb286b…`, the asker locked in `ask.fuin.testnet/asker`. The earlier accepted builds rebuild the same way from their recorded commits: v8 `bb0d9a5d…` (round 7's grounding, `39a2da3`), v7 `acd9286f…` (groundings of rounds 4–6, `58523c7`), v2 `dabae968…` (rounds 1–4, `6381ee9`), v3 `2614ddaa…` (round 5, `907aec0`), v4 `cd36c486…` (the v4 rehearsal, `54a5b6e`), v5 `86db8213…` (`170c488`), v6 `67c2292e…` (round 6, `6b0705c`) |
| The registry's code can't be replaced (its seal and commit values are also checked against the owner's signed transactions) | `curl -s https://archival-rpc.testnet.fastnear.com -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"view_access_key_list","finality":"final","account_id":"registry.fuin.testnet"}}'` | `"keys":[]` |

## The problem

A benchmark owner has two bad options:

- **Publish the test set.** It leaks into the next model's training data, and the benchmark stops measuring anything.
- **Keep it private.** Then everyone has to take the owner's word for the scores: which model ran, whether answers were edited, and whether the grading was honest.

A live example: NEAR's Delta League ranks improved versions of Qwen 3.5 0.8B by their score on a private eval set, designed so progress doesn't map onto standard benchmarks (Illia Polosukhin, Nov 6, 2026: [results](https://x.com/ilblackdragon/status/2118587268776829036), [the private eval set](https://x.com/ilblackdragon/status/2118591003368296561)).

Fūin is a third option. The owner keeps the questions private. Anyone can check that the published score came from real, unedited answers by a named model running in a TEE, committed before any sample was drawn, and scored correctly against the owner's sealed answer key: on the revealed sample and, when the owner adds a TEE score (every published certificate has one), on every answer. In the four rounds that reveal nothing, a TEE also checked each answer key against the near/docs line it cites: 374 of 384 appear there (ignoring commas, backticks and asterisks), and the other 10 are flagged as unchecked. That rules out a key that appears nowhere in the cited line, such as an invented value or a typo; it can't rule out a wrong value that happens to appear in the line the owner chose. Whether the questions are any good stays with the owner, and in a round that reveals nothing, only the owner can see them. Fūin certifies models that NEAR AI Cloud serves in an attested TEE; certifying fine-tuned submissions like Delta League's would need them served the same way. In rounds 1–6 a certificate can't show whether the owner re-asked a question and kept the best signed answer (see the limits). In round 7 a TEE asked every question itself, after the seal, and kept the first answer it recorded, so the certificate does show it ([asked once](#asked-once-round-7)).

## Result: which NEAR AI Cloud model answers NEAR developer questions correctly?

Seven independent rounds of private questions (60, 60, 300, 155, 96, 96 and 37), each with exact answers cited to a line of [near/docs](https://github.com/near/docs) at commit `e2d2ea17`. They come in [three kinds](#three-kinds-of-round): rounds 1–3 reveal a sample, rounds 4–6 reveal nothing, and in round 7 a TEE asked every question once. Each round was sealed on NEAR before its run: for rounds 4–6, each request's nonce is bound to the seal block, so no answer can predate the seal; for rounds 1–3 the public checks show only that the seal preceded the committed results, and the run's timing is the owner's word. Every model ran with reasoning on and temperature 0. Rounds 4–6 reveal nothing; their scores are checked only inside the TEE. Rounds 5 and 6 also encrypted every question and answer end to end, so NEAR's gateway never saw them. Round 6 runs all seven models NEAR serves in its own TEEs, including two "abliterated" versions (a LoRA adapter that removes refusal training, on the same base weights). The scorer is strict about form: the answer must be the number or term alone. It ignores surrounding quotes, backticks and markdown emphasis and one trailing period, and compares exact answers case-insensitively, so `u128::MAX` counts as `U128::MAX`.

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
- **Served as (in the model column):** comes from the deployment trace taken at each run's preflight (see below). These are NEAR's deployed quantized builds, not the full-precision checkpoints that public benchmark tables usually describe.

**Disclosure:**
- **Round 1:** the audit directly reveals 23 items, which is what the verifier reports as "directly revealed 23, unrevealed 37". One unrevealed item cites the same docs line as two revealed items, and its answer follows from theirs. It is indirectly disclosed, which the verifier does not compute. Known disclosure: **24 items; 36 stay hidden.**
- **Round 2:** one question per cited line, so its known disclosure is the 23 revealed; **37 stay hidden.**
- **Round 3:** one question per cited line, and none shares a line with rounds 1–2. The audit reveals 28; **272 of 300 (91%) stay hidden**, at the same 95% detection power as the 60-question rounds.
- **Round 4:** reveals nothing. All 155 stay hidden, one question per cited line, none shared with rounds 1–3.
- **Round 5:** reveals nothing, and its questions and answers were end-to-end encrypted. All 96 stay hidden, one question per cited line, none shared with rounds 1–4.
- **Round 6:** reveals nothing, end-to-end encrypted, seven models. All 96 stay hidden, one question per cited line, none shared with rounds 1–5.
- **Round 7:** reveals nothing, end-to-end encrypted, and every question was asked once by a TEE ([asked once](#asked-once-round-7)). All 37 stay hidden, one question per cited line, none shared with rounds 1–6. Its 4,096-token cap (rounds 4–6 used 8,192) is what fits a TEE-made call, so its score isn't comparable with round 6's.
- **Every round, scored inside a TEE:** all twenty totals were computed over every signed answer (2,302 in all) inside an Intel TDX enclave on OutLayer and match the commitments, so the unrevealed scores (37, 37, 272, 155, 96, 96 and 37 per run) are checked exactly, not by sample ([TEE score](#tee-score)).
- **Answer keys checked at the source:** in rounds 4–7, which reveal nothing, a TEE fetched every cited near/docs line and found 374 of the 384 sealed answer keys in it (ignoring commas, backticks and asterisks); 10 are flagged as unchecked (derived numbers, or an alternative broader than the line) ([answer keys](#answer-keys-checked-against-their-sources)).

**Disclosure at scale.** For a fixed detection target the audit size grows only slowly with suite size and levels off (23 items at 60, 29 at 1,000), so larger private suites disclose a far smaller share. From the same `core.audit_size` code, at ≥95% detection power for ≥10% incorrect scores:

| Suite size n | Items revealed k | Share revealed |
|---|---|---|
| 60 | 23 | 38.3% |
| 200 | 27 | 13.5% |
| **300 (round 3, measured)** | **28** | **9.3%** |
| 500 | 28 | 5.6% |
| 1,000 | 29 | 2.9% |

## Try it (no account, no API key, no test set)

You need [uv](https://docs.astral.sh/uv/) and network access to Intel PCS, NVIDIA NRAS, an archival NEAR testnet RPC (certificates cite blocks older than regular nodes keep): FastNEAR's, with NEAR's own archival endpoint as the fallback when one throttles; set `FUIN_TESTNET_RPC` to pin another, the NEAR AI model catalog, raw.githubusercontent.com and Docker Hub (for image build provenance; if it is unreachable, the verifier says it didn't check). One verification takes about 40 seconds.

1. **Verify a real certificate.**

   ```sh
   git clone https://github.com/fexx301/fuin && cd fuin
   env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-60-r1-qwen3.8-27b.json
   ```

   You see `VERIFIED` with ten passing checks (rows, commitments, policy, signatures, reveals, attestation, deployment trace, registry, audit sample, TEE score; a certificate whose serving image NEAR built adds an eleventh, build provenance), the scope line (`… audit passed 23/60 with zero mismatches; detection power 95.3564% for ≥6 incorrect item scores under the stated sampling assumptions (not the probability that the total is correct); directly revealed 23, unrevealed 37 …`), the warnings and the limits. Repeat with the other certificates in `examples/` (nineteen: two models in each of the three sampled rounds, three in each of rounds 4 and 5, and seven in round 6).

2. **Watch tampering get refused.**

   ```sh
   uv run python scripts/check_fixtures.py examples/tampered/manifest.json
   ```

   You see 34 `ok` lines. Each fixture makes one change, listed in `examples/tampered/manifest.json`, and gets exactly its expected verdict:

   | Fixture | What changed | Verdict |
   |---|---|---|
   | edited-answer | a revealed answer edited after signing | REFUSED `signature_text_mismatch` |
   | inflated-total | published total +1 | REFUSED `total_score_mismatch` |
   | missing-item / duplicate-item | a row deleted / duplicated | REFUSED `item_set_mismatch` |
   | out-of-range-score | a score of 2 | REFUSED `score_range_invalid` |
   | changed-set | a benchmark leaf changed after the seal | REFUSED `merkle_root_mismatch` |
   | altered-policy | sealed audit size lowered | REFUSED `policy_mismatch` |
   | unattested-signer | an answer signed by a key that isn't the model's | REFUSED `signer_not_attested_for_model` |
   | invalid-attestation | one byte of the TDX quote flipped | REFUSED `attestation_invalid` |
   | edited-deployment-log | NEAR's attested deployment log edited | REFUSED `attestation_invalid` |
   | emptied-deployment-quote | the deployment log's TDX quote replaced with an empty string | REFUSED `attestation_invalid` |
   | malformed-evidence | the attempt log's container replaced with a string | REFUSED `certificate_invalid` |
   | changed-audit | the owner cherry-picks a different sample | REFUSED `audit_sample_mismatch` |
   | swapped-commit | the commit transaction pointed at another model's real commit in the same round, height included | REFUSED `record_mismatch` |
   | answer-hint | a real round where the owner put the answer in the prompt; signed and committed | REFUSED `request_policy_mismatch` |
   | external-model | relabelled as a non-TEE gateway model | CAN'T CERTIFY `model_not_tee` |
   | deployment-untraced | NEAR's deployment attestation removed, so the serving container can't be traced | CAN'T CERTIFY `deployment_untraced` |
   | tee-edited-total | the TEE's reported total raised by one | REFUSED `tee_score_invalid` |
   | tee-rehashed-total | the same, with the record's output hash recomputed to match | REFUSED `tee_score_mismatch` |
   | tee-forged-task | OutLayer's task id edited in the record | REFUSED `tee_attestation_invalid` |
   | tee-unpinned-scorer | the record names a scorer build other than the pinned one | CAN'T CERTIFY `tee_unapproved` |
   | zero-reveal-unscored | a zero-reveal round's certificate with its TEE score removed, so nothing checks its scores | CAN'T CERTIFY `tee_score_missing` |
   | zero-reveal-scorer-swapped | the TEE record names a build other than the one sealed in the round's policy | REFUSED `tee_score_mismatch` |
   | evidence-unavailable | NEAR RPC unreachable | CAN'T CERTIFY `evidence_unavailable` |

3. **Read the audit.**

   ```sh
   uv run fuin show examples/cert-near-dev-60-r2-glm-5.3-flash.json --audit
   ```

   You see the revealed-sample summary and miss breakdown, then each of the 23 revealed questions with its expected answer, docs source, what the model said and its score.

4. **Run the tests.** `uv run pytest` (140 tests, including hostile-input, outage, unapproved-OS, TEE-evidence, answer-key-grounding, enclave-asked-round and end-to-end-encryption cases that run offline), `cd contract && cargo test` (15 tests) and `cd tee && cargo test` (the TEE scorer against Python on 3,600 generated cases, including Python's 28-digit rounding of numeric differences, and signed synthetic rounds: reproduced; six refusals; the seal-bound template refused with the wrong seal block or none; the end-to-end-encrypted template re-encrypted and decrypted, and refused with another key or none; an unreadable answer scored 0 even when its item accepts an empty answer; answer-key grounding matched to Python on edge cases such as `\r\n` endings and line breaks only Python would split on, and unsafe source paths refused).

## How it works

### Three kinds of round

Every round seals its questions on NEAR first, and every certificate is checked the same way. The rounds differ in what they reveal and in who calls the model, and each kind is a trade-off:

| | Sampled (`fuin seal`) | TEE-scored (`fuin seal --tee`) | Asked once (`fuin seal --ask`) |
|---|---|---|---|
| Questions revealed | a sample, picked by a future NEAR block | none | none |
| Who calls the model | the owner | the owner | a TEE, once per question, after the seal |
| How scores are checked | anyone re-scores the sample; a TEE re-scores every answer | a TEE re-scores every answer | the TEE scores each answer as it asks |
| Can the owner re-ask a question and keep the best answer? | yes (a printed limit) | yes (a printed limit) | no: the TEE refuses a second ask |
| Models and token cap | all seven, 8,192 | all seven, 8,192 | fast models only, a smaller cap (DeepSeek-V4.1-Flash at 4,096) |
| Rounds here | 1–3 | 4–6 | 7 |

Why the last column is narrower: an asked round's model call happens inside an OutLayer task that NEAR has to answer within about two minutes, so only answers a model can write in that time fit. The other two kinds still run every model at 8,192 tokens. Pick sampled or TEE-scored for the widest comparison, asked once when it matters that nobody could re-draw answers. Scores from different caps aren't comparable.

### The flow

Flow: **seal → run → commit → close → sample → reveal → verify.**

1. **Seal.** The owner commits a Merkle root over the salted items (each with a secret 32-byte nonce) and a policy hash on the NEAR registry. The policy fixes the request template, generation settings, scorer (pinned by file hash) and audit size: `k` is the smallest sample that catches at least one of `D = ceil(n/10)` wrong scores with probability ≥ 95%, computed exactly (k = 23 for n = 60). That is detection power against a stated amount of mis-scoring, not a probability that the total is correct.
2. **Run.** Each question goes to the NEAR AI Cloud gateway non-streaming, with the nonce in the request's `user` field. The model's TEE key signs `model:sha256(request):sha256(response)` over the exact bytes (`provider_tee` signature). A fresh attestation report is fetched before the run.
3. **Commit.** The owner commits each run's Merkle root and total; the contract numbers the runs.
4. **Close.** The round closes, and no more runs can join it.
5. **Sample.** The audit seed is the hash of the first finalized block at height ≥ close + 2, bound to the round's records. The owner can't know it when committing. One sample serves every model in the round.
6. **Reveal.** The sampled items, salts, nonces and exact request and response bytes are published with Merkle proofs.
7. **Verify.** The verifier first checks every field's form; malformed input is refused, never crashes. It runs every check that needs no network before any that does, so a service outage can't hide tampering that local checks catch. An outage only defers the verdict to CAN'T CERTIFY. Anyone rebuilds both roots from all `n` rows, checks every signature against a key attested in an Intel TDX quote whose application (MRCONFIGID, RTMR3) and OS (MRTD, RTMR0-2) measurements are both approved, with NVIDIA GPU attestation via NRAS. VERIFIED also requires the deployment trace below. It reads the registry over an archival RPC. They then re-derive the sample from the chain, rebuild each revealed request from the sealed template, and re-score each revealed answer.

**Deployment trace.** Each model report includes NEAR's compose-manager attestation: a second TDX quote over the log of deployments on that machine. Fūin recomputes the log hash and fetches each logged compose file from the public [nearai/cvm-compose-files](https://github.com/nearai/cvm-compose-files) repo at the logged commit, checking its sha256. From those files it reports the container image digest and the weights serving the model. Details: `evidence/2026-11-03-provenance-probe/`.

### TEE score

The audit checks a sample; a TEE score checks every answer. The owner encrypts one run (each item's sealed bytes and salt, the sealed policy, the signed requests and responses) to a key that exists only inside Fūin's TEE scorer, which runs in an Intel TDX enclave on OutLayer. The scorer (`tee/`) rebuilds every benchmark leaf from the sealed bytes, rebuilds every request from the sealed template and requires it to equal the signed bytes, recovers every signature, scores every answer with the sealed scorer's exact rules, and returns only the two roots, the total and the signer. `fuin verify` then checks the OutLayer attestation (the Intel quote, OutLayer's task hash, the worker's approval at the execution's block, and the request and result on chain) and that the output equals the certificate's own roots, total, model and signer.

Every certificate of rounds 1–6 carries a TEE score; round 7's carries the asker's aggregate instead ([asked once](#asked-once-round-7)). The scores (rounds 1–3 re-scored, OutLayer tasks 21078–21084; rounds 4–6 scored only this way, tasks 21125–21127, 21373–21375 and 25501–25515), so every hidden score is checked exactly rather than by sample, under the TEE trust assumptions in the limits. Round 5's scorer (v3) predates the count of unreadable answers, so its certificates print the limit that a total could be lowered unseen. It doesn't make rounds 1–3's audited items private again. Each encrypted run was hosted on a secret gist for the run and deleted afterwards; the attestation binds only its hash. The scores were first computed on a build that reproduced only on macOS, then re-done on the canonical build, which reproduces on any host; the first build is no longer accepted. Details: `evidence/2026-11-05-reverify-tee-score/` and `evidence/2026-11-05-reverify-tee-v2/`.

### Answer keys checked against their sources

A zero-reveal round's score is exact against the owner's sealed answer key, so a wrong key would favour or penalise a model and nobody could see it. Grounding narrows that: a key must appear in the near/docs line its item cites, so an invented value, a typo or a key taken from elsewhere is flagged. It doesn't stop a wrong value that happens to appear in a line the owner chose to cite. Every item cites one line of near/docs at a pinned commit, so the TEE checks the key at the source: the owner encrypts the round's items to scorer v7's in-enclave key, and the enclave fetches each cited file from GitHub at that commit, recomputes the sealed benchmark root, and flags every item whose answer, or any accepted alternative, doesn't appear in its cited line (after removing `,`, `` ` `` and `*`). It returns only the root, the commit, the count and a bit per flagged item. It runs once per round, after the fact, bound to the root sealed on chain, so no sealed score or scorer build changes; `fuin verify` checks it like a TEE score and prints the flagged items.

| Round | Keys in their cited line | Flagged | OutLayer task |
|---|---|---|---|
| 4 | 151/155 | 4 | 26243 |
| 5 | 94/96 | 2 | 26242 |
| 6 | 92/96 | 4 | 26241 |
| 7 | 37/37 | 0 | 27212 (scorer v8) |

A flagged key isn't necessarily wrong: a number worked out from the line (a unit conversion, a count) is flagged, as is an accepted alternative longer than the cited text. They are the keys nobody checked. The repository is fixed (`near/docs`), and the verifier accepts only commits listed in `policy/tee-v2.json`, each checked to be on near/docs master, because GitHub serves a fork's commits under the original repository's path too: tested on Nov 7 with a commit that exists only on a public fork, which `raw.githubusercontent.com/near/docs/<sha>/…` served with HTTP 200. Details: `evidence/2026-11-07-answer-key-grounding/`.

### Asked once (round 7)

This is the third [kind of round](#three-kinds-of-round). Until round 7 the owner made the model calls. NEAR AI Cloud's temperature-0 serving isn't deterministic (re-asking 43 of round 4's items changed 5 scores), so an owner could re-send a sealed request and commit the best signed answer, and every signature would still be valid. In an enclave-asked round (`fuin seal --ask`) the owner makes no model call:
- **The asker** (`ask/`) runs as the OutLayer project `ask.fuin.testnet/asker`. The account that owns it had its only key deleted before the round, so the project can't be deleted, re-versioned or transferred. Its only version is the asker build `dbbb286b…`, which rebuilds byte for byte with `ask/build-docker.sh`.
- **Each ask:** the asker records it in sealed project storage under a name derived from the sealed round (benchmark root, model, index), builds the sealed request, calls NEAR AI with the owner's key (an OutLayer secret the owner stores), checks the `provider_tee` signature, scores the answer with the scorer's own code and records it final. A final record is re-emitted, never re-asked; one still pending, whose answer never left the enclave, may be retried, and the retries are counted.
- **The certificate** carries the asker's aggregate: the run's roots and total from every final record, attested by OutLayer. `fuin verify` checks that it came from the sealed asker in the sealed project, that it equals the committed run, and, on the archival chain at the seal block, that the project's owner had no keys or code and the asker was its only version.
- **After the seal.** The asker's records are named by the sealed round, not by the seal block, so the certificate also carries scorer v9's asked-check: inside a TEE, every request is rebuilt with the seal block's hash and must equal the request the model signed. A request made before the seal, with a guessed seal hash, can't pass, so no owner could ask early, re-draw by changing salts, and seal the round they liked.

Round 7 (37 questions, DeepSeek-V4.1-Flash-1017) is VERIFIED this way: 19/37, 1 retried ask (item 31, whose first requests outlived NEAR's yield window; it scored 0). A retry is a second draw, so the verifier prints the bound: a single draw per item could differ from the total by at most the retried count, here 1. The cap is 4,096 tokens because a TEE-made call must finish inside NEAR's yield window of about 125 s: 8,192 tokens didn't fit, and Qwen3.8 and GLM were too slow even at 4,096. Details: `evidence/2026-11-08-round-near-dev-37-r7/`.

### Zero-reveal rounds

`fuin seal --tee` seals a round that reveals nothing. Three things differ from a sampled round:
- **The policy** names the exact scorer build (by sha256) that will score every item inside the TEE, and has no audit sample.
- **The verifier** requires that TEE score: without it the certificate is CAN'T CERTIFY `tee_score_missing`, and a record naming any other build is REFUSED `tee_score_mismatch`.
- **Every request's nonce** is `sha256("fuin-nonce-v2" ‖ item nonce ‖ seal block hash)`. That block hash didn't exist before the seal, so no signed answer can predate it, which a sampled round can't show. The TEE scorer rebuilds each nonce from the hash, and the verifier compares the hash with the chain.

The trade-off: a sampled round's score check needs only public bytes, while a zero-reveal round's relies on the TEE (Intel TDX, OutLayer's worker governance and key service). In exchange, no question is ever published. Round 4 (`near-dev-155-r4`) is a zero-reveal round: 155 questions, three models, nothing revealed. Details: `evidence/2026-11-05-round-near-dev-155-r4/`.

### End-to-end encryption

`fuin seal --e2ee` (request template v3) encrypts every question to the model's attested TEE key, with NEAR AI Cloud's end-to-end encryption on the model's secp256k1 signing key (`X-Signing-Algo: ecdsa`): ECDH, HKDF-SHA256, AES-256-GCM. The answer comes back encrypted to a key only the owner holds. NEAR's gateway carries ciphertext for both; it still sees the model, the settings, the nonce, the timing and the sizes.

The evidence is unchanged, because the model signs the exact encrypted bytes it received and returned (`provider_tee`, probe: `evidence/2026-11-05-e2ee-probe/`). To stay checkable, every random value derives from the item's secret salt: whoever holds the salt (a verifier of a revealed item, or the TEE scorer) re-encrypts the question byte for byte, which pins exactly what the model decrypted, and decrypts the answer. An answer that doesn't decrypt scores 0, even when the item accepts an empty answer: before scorer v6 it read as an empty answer and would have matched one (a blind reviewer's probe; no published suite accepts an empty answer, and suite checking now rejects one; enclave run: task 22597). The TEE scorer also requires that the key the questions went to is the key that signed every answer. The key an answer comes back to travels in an unsigned header, so from scorer v4 the TEE also counts answers that don't decrypt, and the count is printed with the TEE score (`evidence/2026-11-05-scorer-v4-unreadable-count/`, with a verifiable rehearsal certificate).

Round 5 (`near-dev-96-r5`) is zero-reveal and end-to-end encrypted: 96 questions, three models; nothing was revealed, and no question or answer crossed NEAR's gateway in the clear (NEAR AI Cloud's end-to-end encryption, observed by the probe in `evidence/2026-11-05-e2ee-probe/`; the certificate itself can't show this). Details: `evidence/2026-11-05-round-near-dev-96-r5/`.

Round 6 (`near-dev-96-r6`) runs every model NEAR serves in its own TEEs, seven, on 96 new questions, zero-reveal and end-to-end encrypted; all seven certificates VERIFY, with no failed inference attempts. Details: `evidence/2026-11-07-round-near-dev-96-r6/`.

## NEAR tools used

- **NEAR AI Cloud:** TEE-hosted open models through the gateway (`/v1/chat/completions` with `x-no-aliasing`); end-to-end encryption to the model's attested key (`X-Signing-Algo: ecdsa`, `X-Client-Pub-Key`, `X-Model-Pub-Key`); `provider_tee` response signatures (`/v1/signature`); model attestation reports (Intel TDX quote, NVIDIA GPU evidence, event log, compose-manager attestation); the public model catalog (`verifiable`, `attestationSupported`).
- **NEAR testnet contract** [`registry.fuin.testnet`](https://testnet.nearblocks.io/address/registry.fuin.testnet) (Rust, near-sdk 5.30, built with cargo-near): `seal`, `commit_run`, `close_round`, `get_benchmark`, `get_run`. Records can't be overwritten, runs are numbered per model, and callers pay for their own storage. **The account has no access keys**, so its code (hash `HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef`) can't be replaced. The verifier checks this.
- **OutLayer** (FastNEAR's verifiable off-chain compute on NEAR): `request_execution` on `outlayer.testnet` runs the TEE scorer in an Intel TDX enclave; an encryption key bound to the scorer's sha256 seals its private key; worker measurements are approved on `worker.outlayer.testnet`.
- **FastFS** serves the TEE scorer binary from a NEAR testnet transaction.
- **NEAR block hashes** as the audit seed; reads over JSON-RPC at `final` finality.
- **near-cli-rs** for the owner's transactions; keys stay in the OS keychain.

Transactions for every round: `evidence/*/README.md`.

## Use it on your benchmark

Install the command once, then anyone can check a certificate with no account and no key:

```sh
pip install fuin                                        # or: uv tool install fuin; puts `fuin` on your PATH, with the verifier's pinned policies
fuin verify cert.json                                  # VERIFIED, REFUSED or CAN'T CERTIFY, with every check printed
```

To check certificates in your own CI, use the GitHub Action in this repository. The step fails unless every certificate is VERIFIED; it retries once when a public service doesn't answer, and never retries a REFUSED:

```yaml
- uses: fexx301/fuin@main
  with:
    certs: certs/*.json
```

To publish your own certified scores, run a round as below or follow [PILOT.md](PILOT.md).

## Audit your own suite

```sh
# put NEARAI_API_KEY in .env (gitignored); have a NEAR testnet account in near-cli-rs's keychain
uv run --env-file .env fuin check my-suite.jsonl --owner you.testnet \
    --model Qwen/Qwen3.8-27B --model z-ai/glm-5.3-flash      # validates the suite, explains disclosure, checks prerequisites
uv run --env-file .env fuin seal my-suite.jsonl --id my-bench-1 --owner you.testnet \
    --model Qwen/Qwen3.8-27B --model z-ai/glm-5.3-flash
uv run --env-file .env fuin run --id my-bench-1 --model Qwen/Qwen3.8-27B   # resumable
uv run --env-file .env fuin run --id my-bench-1 --model z-ai/glm-5.3-flash
uv run --env-file .env fuin commit --id my-bench-1 --model Qwen/Qwen3.8-27B
uv run --env-file .env fuin commit --id my-bench-1 --model z-ai/glm-5.3-flash
uv run --env-file .env fuin close --id my-bench-1
uv run fuin reveal --id my-bench-1 --out examples
uv run --env-file .env fuin tee-score --id my-bench-1 --model z-ai/glm-5.3-flash --host gist   # optional: every answer re-scored in a TEE
uv run fuin tee-ground --id my-bench-1 --host gist     # optional, once per round: every answer key checked against its cited near/docs line in a TEE
uv run fuin status --id my-bench-1      # at any point: which steps are done and the exact next command
```

To reveal nothing, seal with `--tee` (every item scored inside the TEE by the sealed scorer build; run `tee-score` for every model after `close`, and the certificates are written once all are scored). Add `--e2ee` to encrypt each question and answer end to end between you and the model's attested key, so NEAR's gateway never sees them. To have a TEE ask every question once, seal with `--ask` instead, then run `fuin ask --id my-bench-1 --model <model> --host gist` for each model before `commit`: it needs your NEAR AI key stored for the asker's project once (`uv run --env-file .env python scripts/store_asker_secret.py --project ask.fuin.testnet/asker`), and the model must answer within the asker's time limit (DeepSeek-V4.1-Flash at a cap of 4,096 tokens does).

When NEAR redeploys a model, a run's preflight stops with no accepted attestation. `uv run --env-file .env fuin policy-update` fetches fresh reports. For any configuration whose evidence holds (Intel quote, nonce binding, RTMR3, NVIDIA's verdict) but isn't approved yet, it drafts `policy/attestation-v<N+1>.json` with the measurements and deployment trace for review. It approves nothing itself: the verifier keeps its current policy until a person points `owner.ATTESTATION_POLICY` at the reviewed file.

For a second person trying Fūin on their own private questions, [PILOT.md](PILOT.md) is a step-by-step kit with a report form. A fellow builder ([JUICEWRLD998](https://github.com/JUICEWRLD998)) ran it unmodified on Nov 6, on Windows 11 under WSL2: a private round of 46 script-generated questions on two models. Both certificates verify on another machine. It cost him $0.09 of NEAR AI usage, and he said he'd use Fūin for a real benchmark because a private test set can hardly be gamed. Each problem he hit (WSL's DNS, build packages, the keychain, two unclear messages, a dropped request to Intel) is now fixed or documented: [evidence/2026-11-06-outside-pilot](evidence/2026-11-06-outside-pilot/).

`fuin check` catches malformed items, duplicate questions, answers that appear in their own question, questions that don't say what form to answer in, and two items citing the same source line (revealing one can disclose the other). It also states the disclosure for your suite size, for example "60 items → reveals 23 (38.3%)" or "1,000 items → reveals 29 (2.9%)". `fuin seal` runs the same suite check and refuses a suite with errors, because a seal can't be undone.

Each suite line is `{"question", "answer", "answer_type": "numeric"|"exact", "accept"?, "tolerance"?, "source"?}`. Salts, nonces and raw bytes stay in `private/` (gitignored); back that folder up, because without it a round can't be revealed. `scripts/leak_guard.py` checks that no hidden item appears in tracked files except as its own round's reveal.

## Limits (printed with every VERIFIED)

- Every published signature and commitment is checked; score correctness and request-policy compliance are checked on the revealed sample, and on every item only when the certificate carries a TEE score.
- Model instances can share a key even with different configurations. Matching a signer does not identify the serving instance or prove its exact configuration.
- Accepted configurations are recorded from NEAR's attested reports in the verifier's policy: the application (compose hash) and the OS (MRTD, RTMR0-2), as observed, not rebuilt from source. The serving container is traced from NEAR's attested deployment log at preflight to a public compose file (image digest, weights, revision); a redeploy during the run would not show. The image's build provenance is verified where NEAR publishes it (SLSA v1 through sigstore, from a workflow in NEAR AI's GitHub organisation); other images are named in the warnings.
- Run numbering exposes committed attempts only, not discarded API calls, private rehearsals or uncommitted runs.
- An owner could send the same sealed request more than once and commit the best signed answer; every signature stays valid, so a certificate can't show that.

For an enclave-asked round that passes the asked-once check, that limit reads instead:

- Each item was asked once, inside the enclave; that rests on OutLayer's storage not being rolled back by its operator, as every TEE result rests on Intel TDX and OutLayer. An owner could still seal the same questions as another round and publish the better one: separate rounds aren't linked.
- Sampling assumes the selected future finalized block is unpredictable and not adversarially biased (SHA-256 as a pseudorandom expander); not validator-proof randomness.
- Reveals permanently disclose the sampled questions and answers; later rounds grow the disclosed union.
- The seal precedes the result commitment; this does not prove when inference happened.
- The registry contract is locked (no access keys), but its code rebuilds byte for byte from contract/ only on the macOS machine that built it, not on Linux, so others can't tie it to this repository: the seal and commit values are checked against the owner's signed transactions, while run numbering and the close rely on the deployed code.
- Each item's 0/1 score is public (it is part of the run commitment), so a certificate shows which hidden items a model answered correctly, though not what they ask.

Printed as well when a certificate carries a TEE score:

- A TEE score trusts Intel TDX, OutLayer's worker-measurement approvals (worker.outlayer.testnet, checked at the execution's block) and its key service. Each accepted scorer build is pinned by sha256 and rebuilds with tee/build-docker.sh, on any host with Docker, from tee/ at the commit policy/tee-v2.json records.

For a zero-reveal round, the sampling and reveal limits are not printed, and this one is:

- Nothing is revealed, so no one but the owner can check the questions or the expected answers: the total is exact against the owner's sealed answer key, which is unchecked, and the choice of questions is the owner's.

When the certificate carries an answer-key grounding, that limit reads instead, with one more:

- Nothing is revealed, so no one but the owner can check the questions; the choice of questions is the owner's. Answer keys were checked inside a TEE only against their cited line (see the answer keys check).
- A grounded answer key appears in the line of near/docs the owner cited; that doesn't prove it is the right answer to its question: a cited line can contain a wrong value, and a short key (a number, a word) can appear in a line by chance. Flagged keys were not checked. The flags show which hidden items were flagged, not what they ask; GitHub saw which near/docs files the round cites.

With a seal-bound request template (v2 or v3), the timing limit is replaced by:

- Request nonces are bound to the seal block's hash, so no signed answer predates the seal; answers between the seal and the commitment are not individually timestamped.

With end-to-end encryption (request template v3), also:

- Questions and answers were end-to-end encrypted to the model's attested key; NEAR's gateway still saw the model, the generation settings, the nonce, the timing and the sizes.
- The key each answer is encrypted back to travels in an unsigned header, so an owner could have chosen answers encrypted to another key and commit them unreadable (each scores 0): a total could be lowered without the certificate showing it.

When the round's TEE scorer counts unreadable answers (scorer v4 onwards), that limit reads instead:

- The key each answer is encrypted back to travels in an unsigned header, so an owner could have chosen answers encrypted to another key and commit them unreadable (each scores 0); the TEE scorer counts such answers, and the count is printed with the TEE score.

Also: verification needs the public services listed above (it is account-free, not offline). Without end-to-end encryption, requests pass through NEAR's gateway in the clear, so their privacy in transit relies on NEAR operating it. Failed inference attempts are owner-reported and can't be verified. Testnet only.

## Repository

| Path | What |
|---|---|
| `src/fuin/` | CLI (`cli.py`), owner workflow (`owner.py`), verifier (`verify.py`), attestation (`attestation.py`), deployment trace (`provenance.py`), protocol core (`core.py`), scorers, NEAR access (`near.py`) |
| `contract/` | the registry contract and its tests |
| `policy/` | the verifier's attestation policies (accepted configurations per model), `tee-v2.json` (the accepted TEE scorer builds, each with its source commit) and `sigstore-trusted-root.json` (sigstore's public trusted root, pinned, for image build provenance) |
| `tee/` | the TEE scorer: Rust compiled to WASI P2, its canonical reproducible build (`build-docker.sh`, which runs `build.sh` in a digest-pinned Linux image), its tests against the Python scorer |
| `examples/` | real certificates; `tampered/` fixtures and their manifest |
| `evidence/` | dated command output, transactions and probe write-ups behind every claim here |
| `scripts/` | fixture builder and checker, suite source checker, leak guard, results-page builder |
| `ask/` | the asker: Rust compiled to WASI P2, run as the locked OutLayer project `ask.fuin.testnet/asker`; reproducible build `ask/build-docker.sh` (pass the commit it was built from) |
| `docs/` | [how the code fits together](docs/ARCHITECTURE.md) and [what Fūin costs and depends on](docs/COSTS-AND-DEPENDENCIES.md) |
| `site/` | interactive page: verify certificates in the browser (every local check, live NEAR RPC checks, and the Intel TDX quote via Phala's WASM build of `dcap-qvl`; the TEE score's OutLayer record (quote, task hash, worker approval, chain record) is checked live; the deployment trace is replayed live (vendored js-yaml reads the compose files); NVIDIA's GPU verdict can't run in a browser, so a published certificate shows `fuin verify`'s recorded result for it (matched to its exact bytes) and an uploaded one gets PARTLY CHECKED), tamper with them live, explore results. Open `site/index.html`; data from `scripts/build_page.py`, vendored crypto from `scripts/build_vendor.sh`, tested by `node scripts/test_site_verifier.mjs` |

Running and fixing it: [MAINTAINING.md](MAINTAINING.md). Changes: [CHANGELOG.md](CHANGELOG.md). MIT licence.
