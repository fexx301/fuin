# Fūin

Fūin (封印, pronounced *foo-een*) is Japanese for "seal": the test set is sealed on NEAR before any result is committed.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/fuin-logo-dark.svg">
  <img src="assets/fuin-logo.svg" alt="Fūin logo" width="320">
</picture>

Fūin publishes a private benchmark result that a stranger can check **without an account and without the test set**. Every answer carries a signature from the model's attested TEE key on NEAR AI Cloud, the set and results are committed on NEAR, and every answer is re-scored inside a TEE on OutLayer. A round can also reveal a sample picked by a future NEAR block, or reveal nothing at all.

Built at NEAR HACKATHON (Nov 1–14, 2026), tracks `privacy` and `open`.

## For judges

**Human reviewers (2 minutes):**
1. Read [the problem](#the-problem) and [the result](#result-which-near-ai-cloud-model-answers-near-developer-questions-correctly).
2. Look at [the refusals table](#try-it-no-account-no-api-key-no-test-set): 24 cases (19 tampered or malformed certificates refused, 5 that can't be certified), each caught by a named check.

**AI reviewers (Claude Code, Codex):**
- Run `scripts/review.sh` in the background. It takes about 16 minutes (allow 30), longer than many agents' command timeouts: it waits on Intel, NVIDIA, NEAR, OutLayer, GitHub and Docker Hub, and retries a public service's rate limit. It needs uv and network, and exits 0 with `ALL CHECKS PASSED`. If a free RPC keeps rate-limiting (for example, two reviews running at once from one network), a line says CAN'T CERTIFY `evidence_unavailable`: that is an outage, not a verdict; run that certificate again later. `FUIN_REVIEW_WORKERS` (default 4) sets how many certificates verify at once.
- `AGENTS.md` lists exit codes, what not to run and where evidence lives.

Every claim below maps to a command:

| Claim | Check | Expected |
|---|---|---|
| A stranger can verify a result without an account or the test set | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-60-r1-qwen3.8-27b.json` | `VERIFIED`, 10 `[pass]` lines, exit 0 |
| Each answer is signed by the model's TEE-attested key | same output, `signatures` and `attestation` lines | `60/60 provider_tee …`; `quote UpToDate, NRAS True` |
| The served container and weights are traced to NEAR's public deployment repo | same output, `deployment trace` line | `… nearai/cvm-compose-files: model-sg-qwen38-27b-fp8-tp1-coloc …` |
| The set and results were committed on NEAR, with the seal before the commit and the commit before the close | same output, `registry` line | `seal … < commit … < close …` |
| The owner can't choose which items a committed round reveals | same output, `audit sample` line; fixture `changed-audit` | `first final block ≥ close+2`; `REFUSED audit_sample_mismatch` |
| Tampering is refused with a specific reason | `uv run python scripts/check_fixtures.py examples/tampered/manifest.json` | 23 `ok` lines, exit 0 |
| Round 3's totals were re-scored over every answer inside a TEE, not only the sample | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-300-r3-glm-5.3-flash.json` | `[pass] tee score: all 300 items rebuilt and re-scored inside an OutLayer TDX enclave … total 122/300 and both roots match` |
| A round can reveal nothing and still be checked, with no answer predating its seal | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-155-r4-deepseek-v4.1-flash-1017.json` | `VERIFIED`; `[pass] reveals: none: a TEE-scored round reveals nothing …`; `[pass] tee score: all 155 items rebuilt and re-scored …: total 84/155 …`; fixtures `zero-reveal-unscored`, `zero-reveal-scorer-swapped` |
| Questions and answers can stay end-to-end encrypted, so NEAR's gateway never sees them | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-96-r5-glm-5.3-flash.json` | `VERIFIED`; the policy line ends `fuin-request-v3 (end-to-end encrypted)`, and the limits print the end-to-end-encryption line; probe: `evidence/2026-11-05-e2ee-probe/` |
| The TEE scorer that ran is this repository's code | `tee/build-docker.sh` (any host with Docker; about 1.5 minutes once the image is pulled) | prints `67c2292e…`, the current pin in `policy/tee-v2.json` (scorer v6). The earlier accepted builds rebuild the same way from their recorded commits: v2 `dabae968…` (rounds 1–4, `6381ee9`), v3 `2614ddaa…` (round 5, `907aec0`), v4 `cd36c486…` (the v4 rehearsal, `54a5b6e`), v5 `86db8213…` (`170c488`) |
| The registry's code can't be replaced (its seal and commit values are also checked against the owner's signed transactions) | `curl -s https://archival-rpc.testnet.fastnear.com -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"view_access_key_list","finality":"final","account_id":"registry.fuin.testnet"}}'` | `"keys":[]` |

## The problem

A benchmark owner has two bad options:

- **Publish the test set.** It leaks into the next model's training data, and the benchmark stops measuring anything.
- **Keep it private.** Then everyone has to take the owner's word for the scores: which model ran, whether answers were edited, and whether the grading was honest.

Fūin is a third option. The owner keeps the questions private. Anyone can check that the published score came from real, unedited answers by a named model running in a TEE, committed before any sample was drawn, and scored correctly against the owner's sealed answer key: on the revealed sample and, when the owner adds a TEE score (every published certificate has one), on every answer. Whether the questions and that key are any good stays with the owner, and in a round that reveals nothing, only the owner can see them.

## Result: which NEAR AI Cloud model answers NEAR developer questions correctly?

Five independent rounds of private questions (60, 60, 300, 155 and 96), each with exact answers cited to a line of [near/docs](https://github.com/near/docs) at commit `e2d2ea17`. Each round was sealed on NEAR before its run: for rounds 4 and 5, each request's nonce is bound to the seal block, so no answer can predate the seal; for rounds 1–3 the public checks show only that the seal preceded the committed results, and the run's timing is the owner's word. Every model ran with reasoning on and temperature 0. Rounds 4 and 5 reveal nothing; their scores are checked only inside the TEE. Round 5 also encrypted every question and answer end to end, so NEAR's gateway never saw them. The scorer is strict about form: the answer must be the number or term alone. It ignores surrounding quotes, backticks and markdown emphasis and one trailing period, and compares exact answers case-insensitively, so `u128::MAX` counts as `U128::MAX`.

| Round (token cap) | Model (as served by NEAR AI Cloud) | Committed score | Revealed (k): correct · wrong · format · cut off | Whole run: cut off (owner-reported) |
|---|---|---|---|---|
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

DeepSeek-V4.1-Flash, added in round 4, leads both rounds it ran: 84 of 155 and 48 of 96. On all five suites, GLM-5.3-flash as NEAR serves it answers more NEAR developer questions correctly than Qwen. On the 300-question round the gap is 45 questions (122 against 77). Qwen's revealed misses are mostly wrong answers rather than cut-offs. At the same 8,192 cap, round 3 cut off GLM 72 times and Qwen 54 times. Even if every cut-off had ended in a correct answer, GLM would still lead (194 against 131), but that is an upper bound, not a measurement: what either model would answer with a larger cap is unknown without a higher-cap rerun. The rounds use different questions, so compare models within a round, not percentages across rounds.

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
- **Every round, scored inside a TEE:** all twelve totals were computed over every signed answer (1,593 in all) inside an Intel TDX enclave on OutLayer and match the commitments, so the unrevealed scores (37, 37, 272, 155 and 96 per run) are checked exactly, not by sample ([TEE score](#tee-score)).

**Disclosure at scale.** For a fixed detection target the audit size grows only slowly with suite size and levels off (23 items at 60, 29 at 1,000), so larger private suites disclose a far smaller share. From the same `core.audit_size` code, at ≥95% detection power for ≥10% incorrect scores:

| Suite size n | Items revealed k | Share revealed |
|---|---|---|
| 60 | 23 | 38.3% |
| 200 | 27 | 13.5% |
| **300 (round 3, measured)** | **28** | **9.3%** |
| 500 | 28 | 5.6% |
| 1,000 | 29 | 2.9% |

## Try it (no account, no API key, no test set)

You need [uv](https://docs.astral.sh/uv/) and network access to Intel PCS, NVIDIA NRAS, FastNEAR's archival NEAR testnet RPC (certificates cite blocks older than regular nodes keep; NEAR's own archival endpoint now only returns a deprecation notice, so set `FUIN_TESTNET_RPC` to use another archival endpoint you have access to), the NEAR AI model catalog, raw.githubusercontent.com and Docker Hub (for image build provenance; if it is unreachable, the verifier says it didn't check). One verification takes about 40 seconds.

1. **Verify a real certificate.**

   ```sh
   git clone https://github.com/fexx301/fuin && cd fuin
   env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-60-r1-qwen3.8-27b.json
   ```

   You see `VERIFIED` with ten passing checks (rows, commitments, policy, signatures, reveals, attestation, deployment trace, registry, audit sample, TEE score; a certificate whose serving image NEAR built adds an eleventh, build provenance), the scope line (`… audit passed 23/60 with zero mismatches; detection power 95.3564% for ≥6 incorrect item scores under the stated sampling assumptions (not the probability that the total is correct); directly revealed 23, unrevealed 37 …`), the warnings and the limits. Repeat with the other certificates in `examples/` (twelve: two models in each of the three sampled rounds, three models in each of the two zero-reveal rounds).

2. **Watch tampering get refused.**

   ```sh
   uv run python scripts/check_fixtures.py examples/tampered/manifest.json
   ```

   You see 24 `ok` lines. Each fixture makes one change, listed in `examples/tampered/manifest.json`, and gets exactly its expected verdict:

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

4. **Run the tests.** `uv run pytest` (107 tests, including hostile-input, outage, unapproved-OS, TEE-evidence and end-to-end-encryption cases that run offline), `cd contract && cargo test` (15 tests) and `cd tee && cargo test` (the TEE scorer against Python on 3,600 generated cases, including Python's 28-digit rounding of numeric differences, and signed synthetic rounds: reproduced; six refusals; the seal-bound template refused with the wrong seal block or none; the end-to-end-encrypted template re-encrypted and decrypted, and refused with another key or none; an unreadable answer scored 0 even when its item accepts an empty answer).

## How it works

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

Every certificate carries a TEE score (rounds 1–3 re-scored, OutLayer tasks 21078–21084; rounds 4 and 5 scored only this way, tasks 21125–21127 and 21373–21375), so every hidden score is checked exactly rather than by sample, under the TEE trust assumptions in the limits. Round 5's scorer (v3) predates the count of unreadable answers, so its certificates print the limit that a total could be lowered unseen. It doesn't make rounds 1–3's audited items private again. Each encrypted run was hosted on a secret gist for the run and deleted afterwards; the attestation binds only its hash. The scores were first computed on a build that reproduced only on macOS, then re-done on the canonical build, which reproduces on any host; the first build is no longer accepted. Details: `evidence/2026-11-05-reverify-tee-score/` and `evidence/2026-11-05-reverify-tee-v2/`.

### Zero-reveal rounds

`fuin seal --tee` seals a round that reveals nothing. Three things differ from a sampled round:
- **The policy** names the exact scorer build (by sha256) that will score every item inside the TEE, and has no audit sample.
- **The verifier** requires that TEE score: without it the certificate is CAN'T CERTIFY `tee_score_missing`, and a record naming any other build is REFUSED `tee_score_mismatch`.
- **Every request's nonce** is `sha256("fuin-nonce-v2" ‖ item nonce ‖ seal block hash)`. That block hash didn't exist before the seal, so no signed answer can predate it, which a sampled round can't show. The TEE scorer rebuilds each nonce from the hash, and the verifier compares the hash with the chain.

The trade-off: a sampled round's score check needs only public bytes, while a zero-reveal round's relies on the TEE (Intel TDX, OutLayer's worker governance and key service). In exchange, no question is ever published. Round 4 (`near-dev-155-r4`) is a zero-reveal round: 155 questions, three models, nothing revealed. Details: `evidence/2026-11-05-round-near-dev-155-r4/`.

### End-to-end encryption

`fuin seal --e2ee` (request template v3) encrypts every question to the model's attested TEE key, with NEAR AI Cloud's end-to-end encryption on the model's secp256k1 signing key (`X-Signing-Algo: ecdsa`): ECDH, HKDF-SHA256, AES-256-GCM. The answer comes back encrypted to a key only the owner holds. NEAR's gateway carries ciphertext for both; it still sees the model, the settings, the nonce, the timing and the sizes.

The evidence is unchanged, because the model signs the exact encrypted bytes it received and returned (`provider_tee`, probe: `evidence/2026-11-05-e2ee-probe/`). To stay checkable, every random value derives from the item's secret salt: whoever holds the salt (a verifier of a revealed item, or the TEE scorer) re-encrypts the question byte for byte, which pins exactly what the model decrypted, and decrypts the answer. An answer that doesn't decrypt scores 0, even when the item accepts an empty answer: before scorer v6 it read as an empty answer and would have matched one (a blind reviewer's probe; no published suite accepts an empty answer, and suite checking now rejects one; enclave run: task 22597). The TEE scorer also requires that the key the questions went to is the key that signed every answer. The key an answer comes back to travels in an unsigned header, so from scorer v4 the TEE also counts answers that don't decrypt, and the count is printed with the TEE score (`evidence/2026-11-05-scorer-v4-unreadable-count/`, with a verifiable rehearsal certificate).

Round 5 (`near-dev-96-r5`) is zero-reveal and end-to-end encrypted: 96 questions, three models; nothing was revealed, and no question or answer crossed NEAR's gateway in the clear. Details: `evidence/2026-11-05-round-near-dev-96-r5/`.

## NEAR tools used

- **NEAR AI Cloud:** TEE-hosted open models through the gateway (`/v1/chat/completions` with `x-no-aliasing`); end-to-end encryption to the model's attested key (`X-Signing-Algo: ecdsa`, `X-Client-Pub-Key`, `X-Model-Pub-Key`); `provider_tee` response signatures (`/v1/signature`); model attestation reports (Intel TDX quote, NVIDIA GPU evidence, event log, compose-manager attestation); the public model catalog (`verifiable`, `attestationSupported`).
- **NEAR testnet contract** [`registry.fuin.testnet`](https://testnet.nearblocks.io/address/registry.fuin.testnet) (Rust, near-sdk 5.30, built with cargo-near): `seal`, `commit_run`, `close_round`, `get_benchmark`, `get_run`. Records can't be overwritten, runs are numbered per model, and callers pay for their own storage. **The account has no access keys**, so its code (hash `HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef`) can't be replaced. The verifier checks this.
- **OutLayer** (FastNEAR's verifiable off-chain compute on NEAR): `request_execution` on `outlayer.testnet` runs the TEE scorer in an Intel TDX enclave; an encryption key bound to the scorer's sha256 seals its private key; worker measurements are approved on `worker.outlayer.testnet`.
- **FastFS** serves the TEE scorer binary from a NEAR testnet transaction.
- **NEAR block hashes** as the audit seed; reads over JSON-RPC at `final` finality.
- **near-cli-rs** for the owner's transactions; keys stay in the OS keychain.

Transactions for every round: `evidence/*/README.md`.

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
uv run fuin status --id my-bench-1      # at any point: which steps are done and the exact next command
```

To reveal nothing, seal with `--tee` (every item scored inside the TEE by the sealed scorer build; run `tee-score` for every model after `close`, and the certificates are written once all are scored). Add `--e2ee` to encrypt each question and answer end to end between you and the model's attested key, so NEAR's gateway never sees them.

When NEAR redeploys a model, a run's preflight stops with no accepted attestation. `uv run --env-file .env fuin policy-update` fetches fresh reports. For any configuration whose evidence holds (Intel quote, nonce binding, RTMR3, NVIDIA's verdict) but isn't approved yet, it drafts `policy/attestation-v<N+1>.json` with the measurements and deployment trace for review. It approves nothing itself: the verifier keeps its current policy until a person points `owner.ATTESTATION_POLICY` at the reviewed file.

For a second person trying Fūin on their own private questions, [PILOT.md](PILOT.md) is a step-by-step kit with a report form.

`fuin check` catches malformed items, duplicate questions, answers that appear in their own question, questions that don't say what form to answer in, and two items citing the same source line (revealing one can disclose the other). It also states the disclosure for your suite size, for example "60 items → reveals 23 (38.3%)" or "1,000 items → reveals 29 (2.9%)". `fuin seal` runs the same suite check and refuses a suite with errors, because a seal can't be undone.

Each suite line is `{"question", "answer", "answer_type": "numeric"|"exact", "accept"?, "tolerance"?, "source"?}`. Salts, nonces and raw bytes stay in `private/` (gitignored); back that folder up, because without it a round can't be revealed. `scripts/leak_guard.py` checks that no hidden item appears in tracked files except as its own round's reveal.

## Limits (printed with every VERIFIED)

- Every published signature and commitment is checked; score correctness and request-policy compliance are checked on the revealed sample, and on every item only when the certificate carries a TEE score.
- Model instances can share a key even with different configurations. Matching a signer does not identify the serving instance or prove its exact configuration.
- Accepted configurations are recorded from NEAR's attested reports in the verifier's policy: the application (compose hash) and the OS (MRTD, RTMR0-2), as observed, not rebuilt from source. The serving container is traced from NEAR's attested deployment log at preflight to a public compose file (image digest, weights, revision); a redeploy during the run would not show. The image's build provenance is verified where NEAR publishes it (SLSA v1 through sigstore, from a workflow in NEAR AI's GitHub organisation); other images are named in the warnings.
- Run numbering exposes committed attempts only, not discarded API calls, private rehearsals or uncommitted runs.
- Sampling assumes the selected future finalized block is unpredictable and not adversarially biased (SHA-256 as a pseudorandom expander); not validator-proof randomness.
- Reveals permanently disclose the sampled questions and answers; later rounds grow the disclosed union.
- The seal precedes the result commitment; this does not prove when inference happened.
- The registry contract is locked (no access keys) but wasn't built reproducibly, so its code isn't tied to this repository: the seal and commit values are checked against the owner's signed transactions, while run numbering and the close rely on the deployed code.
- Each item's 0/1 score is public (it is part of the run commitment), so a certificate shows which hidden items a model answered correctly, though not what they ask.

Printed as well when a certificate carries a TEE score:

- A TEE score trusts Intel TDX, OutLayer's worker-measurement approvals (worker.outlayer.testnet, checked at the execution's block) and its key service. Each accepted scorer build is pinned by sha256 and rebuilds with tee/build-docker.sh, on any host with Docker, from tee/ at the commit policy/tee-v2.json records.

For a zero-reveal round, the sampling and reveal limits are not printed, and this one is:

- Nothing is revealed, so no one but the owner can check the questions or the expected answers: the total is exact against the owner's sealed answer key, which is unchecked, and the choice of questions is the owner's.

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
| `site/` | interactive page: verify certificates in the browser (every local check, live NEAR RPC checks, and the Intel TDX quote via Phala's WASM build of `dcap-qvl`; the TEE score's OutLayer record (quote, task hash, worker approval, chain record) is checked live; the deployment trace is replayed live (vendored js-yaml reads the compose files); NVIDIA's GPU verdict can't run in a browser, so a published certificate shows `fuin verify`'s recorded result for it (matched to its exact bytes) and an uploaded one gets PARTLY CHECKED), tamper with them live, explore results. Open `site/index.html`; data from `scripts/build_page.py`, vendored crypto from `scripts/build_vendor.sh`, tested by `node scripts/test_site_verifier.mjs` |

MIT licence.
