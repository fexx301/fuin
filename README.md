# Fūin

Fūin (封印, pronounced *foo-een*) is Japanese for "seal": the test set is sealed on NEAR before any model runs.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/fuin-logo-dark.svg">
  <img src="assets/fuin-logo.svg" alt="Fūin logo" width="320">
</picture>

Fūin publishes a private benchmark result that a stranger can check **without an account and without the test set**. Every answer carries a signature from the model's attested TEE key on NEAR AI Cloud, the set and results are committed on NEAR, and a sample picked by a future NEAR block is revealed and re-scored.

Built at NEAR HACKATHON (Nov 1–14, 2026), track `privacy`.

## For judges

**Human reviewers (2 minutes):**
1. Read [the problem](#the-problem) and [the result](#result-which-near-ai-cloud-model-answers-near-developer-questions-correctly).
2. Look at [the refusals table](#try-it-no-account-no-api-key-no-test-set): 14 tampering cases, each caught by a named check.

**AI reviewers (Claude Code, Codex):**
- Run `scripts/review.sh`. It needs uv and network, takes about 5 minutes, and exits 0 with `ALL CHECKS PASSED`.
- `AGENTS.md` lists exit codes, what not to run and where evidence lives.

Every claim below maps to a command:

| Claim | Check | Expected |
|---|---|---|
| A stranger can verify a result without an account or the test set | `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-60-r1-qwen3.8-27b.json` | `VERIFIED`, 9 `[pass]` lines, exit 0 |
| Each answer is signed by the model's TEE-attested key | same output, `signatures` and `attestation` lines | `60/60 provider_tee …`; `quote UpToDate, NRAS True` |
| The served container and weights are traced to NEAR's public deployment repo | same output, `deployment trace` line | `… nearai/cvm-compose-files: model-sg-qwen38-27b-fp8-tp1-coloc …` |
| The set and results were committed on NEAR, with the seal before the commit and the commit before the close | same output, `registry` line | `seal … < commit … < close …` |
| The owner can't choose which items a committed round reveals | same output, `audit sample` line; fixture `changed-audit` | `first final block ≥ close+2`; `REFUSED audit_sample_mismatch` |
| Tampering is refused with a specific reason | `uv run python scripts/check_fixtures.py examples/tampered/manifest.json` | 14 `ok` lines, exit 0 |
| The registry can't be changed | `curl -s https://test.rpc.fastnear.com -H 'Content-Type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"query","params":{"request_type":"view_access_key_list","finality":"final","account_id":"registry.fuin.testnet"}}'` | `"keys":[]` |

## The problem

A benchmark owner has two bad options:

- **Publish the test set.** It leaks into the next model's training data, and the benchmark stops measuring anything.
- **Keep it private.** Then everyone has to take the owner's word for the scores: which model ran, whether answers were edited, and whether the grading was honest.

Fūin is a third option. The owner keeps the questions private. Anyone can check that the published score came from real, unedited answers by a named model running in a TEE, committed before the sample was drawn, and correct on the revealed sample.

## Result: which NEAR AI Cloud model answers NEAR developer questions correctly?

Three independent rounds of private questions (60, 60 and 300), each with exact answers cited to a line of [near/docs](https://github.com/near/docs) at commit `e2d2ea17`. Each round was sealed on NEAR before its run. Both models ran with reasoning on and temperature 0. The scorer is strict: the answer must be the number or term alone.

| Round (token cap) | Model (as served by NEAR AI Cloud) | Committed score | Revealed (k): correct · wrong · format · cut off | Whole run: cut off (owner-reported) |
|---|---|---|---|---|
| `near-dev-300-r3` (8,192) | z-ai/glm-5.3-flash, served as `graphistry/GLM-5.3-Flash-W4AFP8` | **122/300** (40.7%) | (28) 10 · 14 · 0 · 4 | 72/300 |
| `near-dev-300-r3` (8,192) | Qwen/Qwen3.8-27B, served as `Qwen/Qwen3.8-27B-FP8` | **77/300** (25.7%) | (28) 9 · 17 · 0 · 2 | 54/300 |
| `near-dev-60-r2` (8,192) | z-ai/glm-5.3-flash | **32/60** | (23) 13 · 4 · 2 · 4 | 6/60 |
| `near-dev-60-r2` (8,192) | Qwen/Qwen3.8-27B | **17/60** | (23) 7 · 13 · 0 · 3 | 7/60 |
| `near-dev-60-r1` (4,096) | z-ai/glm-5.3-flash | **25/60** | (23) 10 · 5 · 1 · 7 | 21/60 |
| `near-dev-60-r1` (4,096) | Qwen/Qwen3.8-27B | **17/60** | (23) 6 · 9 · 0 · 8 | 17/60 |

On all three suites, GLM-5.3-flash as NEAR serves it answers more NEAR developer questions correctly. On the 300-question round the gap is 45 questions (122 against 77). Qwen's revealed misses are mostly wrong answers rather than cut-offs. At the same 8,192 cap, round 3 cut off more answers (GLM 72/300, Qwen 54/300). GLM loses more answers to the cap and still leads, so the cap doesn't explain the gap. The rounds use different questions, so compare models within a round, not percentages across rounds.

**Reading the columns:**
- **Revealed breakdown:** a reading aid computed from the revealed bytes (`fuin show`), not a score. *Format* means the right value in a form the strict scorer rejects, such as `**10%**`. *Cut off* means no final answer before the cap.
- **Scorer and cut-offs:** the scorer reads only the final answer text and ignores whether generation was cut off. A cut-off response usually has no final answer, so it scores 0; every revealed cut-off here had none.
- **Weights column:** comes from the deployment trace taken at each run's preflight (see below). These are NEAR's deployed quantized builds, not the full-precision checkpoints that public benchmark tables usually describe.

**Disclosure:**
- **Round 1:** the audit directly reveals 23 items, which is what the verifier reports as "directly revealed 23, unrevealed 37". One unrevealed item cites the same docs line as two revealed items, and its answer follows from theirs. It is indirectly disclosed, which the verifier does not compute. Known disclosure: **24 items; 36 stay hidden.**
- **Round 2:** one question per cited line, so its known disclosure is the 23 revealed; **37 stay hidden.**
- **Round 3:** one question per cited line, and none shares a line with rounds 1–2. The audit reveals 28; **272 of 300 (91%) stay hidden**, at the same 95% detection power as the 60-question rounds.

**Disclosure at scale.** The audit size depends on the detection target, not on suite size, so larger private suites disclose a far smaller share. From the same `core.audit_size` code, at ≥95% detection power for ≥10% incorrect scores:

| Suite size n | Items revealed k | Share revealed |
|---|---|---|
| 60 | 23 | 38.3% |
| 200 | 27 | 13.5% |
| **300 (round 3, measured)** | **28** | **9.3%** |
| 500 | 28 | 5.6% |
| 1,000 | 29 | 2.9% |

## Try it (no account, no API key, no test set)

You need [uv](https://docs.astral.sh/uv/) and network access to Intel PCS, NVIDIA NRAS, a NEAR testnet RPC (FastNEAR by default; set `FUIN_TESTNET_RPC` to use another), the NEAR AI model catalog and raw.githubusercontent.com. One verification takes about 40 seconds.

1. **Verify a real certificate.**

   ```sh
   git clone https://github.com/fexx301/fuin && cd fuin
   env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-60-r1-qwen3.8-27b.json
   ```

   You see `VERIFIED` with nine passing checks (rows, commitments, policy, signatures, attestation, deployment trace, registry, audit sample, reveals), the scope line (`… audit passed 23/60 with zero mismatches; detection power 95.3564% for ≥6 incorrect item scores under the stated sampling assumptions (not the probability that the total is correct); directly revealed 23, unrevealed 37 …`), the warnings and the limits. Repeat with the other certificates in `examples/` (two models × two rounds).

2. **Watch tampering get refused.**

   ```sh
   uv run python scripts/check_fixtures.py examples/tampered/manifest.json
   ```

   You see 14 `ok` lines. Each fixture makes one change, listed in `examples/tampered/manifest.json`, and gets exactly its expected verdict:

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
   | changed-audit | the owner cherry-picks a different sample | REFUSED `audit_sample_mismatch` |
   | answer-hint | a real round where the owner put the answer in the prompt; signed and committed | REFUSED `request_policy_mismatch` |
   | external-model | relabelled as a non-TEE gateway model | CAN'T CERTIFY `model_not_tee` |
   | evidence-unavailable | NEAR RPC unreachable | CAN'T CERTIFY `evidence_unavailable` |

3. **Read the audit.**

   ```sh
   uv run fuin show examples/cert-near-dev-60-r2-glm-5.3-flash.json --audit
   ```

   You see the revealed-sample summary and miss breakdown, then each of the 23 revealed questions with its expected answer, docs source, what the model said and its score.

4. **Run the tests.** `uv run pytest` (64 tests, including hostile-input and outage cases that run offline) and `cd contract && cargo test` (15 tests).

## How it works

Flow: **seal → run → commit → close → sample → reveal → verify.**

1. **Seal.** The owner commits a Merkle root over the salted items (each with a secret 32-byte nonce) and a policy hash on the NEAR registry. The policy fixes the request template, generation settings, scorer (pinned by file hash) and audit size: `k` is the smallest sample that catches at least one of `D = ceil(n/10)` wrong scores with probability ≥ 95%, computed exactly (k = 23 for n = 60). That is detection power against a stated amount of mis-scoring, not a probability that the total is correct.
2. **Run.** Each question goes to the NEAR AI Cloud gateway non-streaming, with the nonce in the request's `user` field. The model's TEE key signs `model:sha256(request):sha256(response)` over the exact bytes (`provider_tee` signature). A fresh attestation report is fetched before the run.
3. **Commit.** The owner commits each run's Merkle root and total; the contract numbers the runs.
4. **Close.** The round closes, and no more runs can join it.
5. **Sample.** The audit seed is the hash of the first finalized block at height ≥ close + 2, bound to the round's records. The owner can't know it when committing. One sample serves every model in the round.
6. **Reveal.** The sampled items, salts, nonces and exact request and response bytes are published with Merkle proofs.
7. **Verify.** The verifier first checks every field's form; malformed input is refused, never crashes. It runs every check that needs no network before any that does, so a service outage can't hide tampering that local checks catch. An outage only defers the verdict to CAN'T CERTIFY. Anyone rebuilds both roots from all `n` rows, checks every signature against a key attested in an Intel TDX quote (with NVIDIA GPU attestation via NRAS), and reads the registry over RPC. They then re-derive the sample from the chain, rebuild each revealed request from the sealed template, and re-score each revealed answer.

**Deployment trace.** Each model report includes NEAR's compose-manager attestation: a second TDX quote over the log of deployments on that machine. Fūin recomputes the log hash and fetches each logged compose file from the public [nearai/cvm-compose-files](https://github.com/nearai/cvm-compose-files) repo at the logged commit, checking its sha256. From those files it reports the container image digest and the weights serving the model. Details: `evidence/2026-11-03-provenance-probe/`.

## NEAR tools used

- **NEAR AI Cloud:** TEE-hosted open models through the gateway (`/v1/chat/completions` with `x-no-aliasing`); `provider_tee` response signatures (`/v1/signature`); model attestation reports (Intel TDX quote, NVIDIA GPU evidence, event log, compose-manager attestation); the public model catalog (`verifiable`, `attestationSupported`).
- **NEAR testnet contract** [`registry.fuin.testnet`](https://testnet.nearblocks.io/address/registry.fuin.testnet) (Rust, near-sdk 5.30, built with cargo-near): `seal`, `commit_run`, `close_round`, `get_benchmark`, `get_run`. Records can't be overwritten, runs are numbered per model, and callers pay for their own storage. **The account has no access keys**, so its code (hash `HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef`) can't be replaced. The verifier checks this.
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
uv run fuin status --id my-bench-1      # at any point: which steps are done and the exact next command
```

For a second person trying Fūin on their own private questions, [PILOT.md](PILOT.md) is a step-by-step kit with a report form.

`fuin check` catches malformed items, duplicate questions, answers that appear in their own question, questions that don't say what form to answer in, and two items citing the same source line (revealing one can disclose the other). It also states the disclosure for your suite size, for example "60 items → reveals 23 (38.3%)" or "1,000 items → reveals 29 (2.9%)". `fuin seal` runs the same suite check and refuses a suite with errors, because a seal can't be undone.

Each suite line is `{"question", "answer", "answer_type": "numeric"|"exact", "accept"?, "tolerance"?, "source"?}`. Salts, nonces and raw bytes stay in `private/` (gitignored); back that folder up, because without it a round can't be revealed. `scripts/leak_guard.py` checks that no hidden item appears in tracked files except as its own round's reveal.

## Limits (printed with every VERIFIED)

- Every published signature and commitment is checked; score correctness and request-policy compliance are checked on the revealed sample only.
- Model instances can share a key even with different configurations. Matching a signer does not identify the serving instance or prove its exact configuration.
- Accepted configurations are recorded from NEAR's endpoints in the verifier's policy. The serving container is traced from NEAR's attested deployment log at preflight to a public compose file (image digest, weights, revision); a redeploy during the run would not show, and the image's build provenance is not verified.
- Run numbering exposes committed attempts only, not discarded API calls, private rehearsals or uncommitted runs.
- Sampling assumes the selected future finalized block is unpredictable and not adversarially biased (SHA-256 as a pseudorandom expander); not validator-proof randomness.
- Reveals permanently disclose the sampled questions and answers; later rounds grow the disclosed union.
- The seal precedes the result commitment; this does not prove when inference happened.

Also: verification needs the public services listed above (it is account-free, not offline). Requests pass through NEAR's gateway, so their privacy in transit relies on NEAR operating it. Failed inference attempts are owner-reported and can't be verified. Testnet only.

## Repository

| Path | What |
|---|---|
| `src/fuin/` | CLI (`cli.py`), owner workflow (`owner.py`), verifier (`verify.py`), attestation (`attestation.py`), deployment trace (`provenance.py`), protocol core (`core.py`), scorers, NEAR access (`near.py`) |
| `contract/` | the registry contract and its tests |
| `policy/` | the verifier's attestation policies (accepted configurations per model) |
| `examples/` | real certificates; `tampered/` fixtures and their manifest |
| `evidence/` | dated command output, transactions and probe write-ups behind every claim here |
| `scripts/` | fixture builder and checker, suite source checker, leak guard, results-page builder |
| `site/` | interactive page: verify certificates in the browser (every local check, live NEAR RPC checks, and the Intel TDX quote via Phala's WASM build of `dcap-qvl`; NVIDIA's GPU verdict is shown as recorded), tamper with them live, explore results. Open `site/index.html`; data from `scripts/build_page.py`, vendored crypto from `scripts/build_vendor.sh`, tested by `node scripts/test_site_verifier.mjs` |

MIT licence.
