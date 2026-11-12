# Verdict: Fūin scores 8/10 overall

It is a strong contender in the `privacy` track. Everything the README asks a judge to run passed here, and 13 tampered certificates I built myself (none copied from the repo's fixtures) were all handled correctly. The points it loses are on impact and sustainability, not on whether it works.

## Scores

| Criterion | Score | Evidence |
|---|---|---|
| Technical implementation | 9 | All 20 certificates verify against live Intel, NVIDIA, NEAR and OutLayer evidence. The Python verifier, the Rust TEE scorer and the browser verifier agree on every certificate and fixture. The scorer and both askers rebuilt in Docker to their pinned hashes. The registry contract is small and clean, with no admin methods and no access keys on the account. |
| Design | 7 | Three clear outcomes (VERIFIED, REFUSED, CAN'T CERTIFY) with reason codes, limits printed with every verdict, and a browser verifier with "try to cheat" buttons (judged from the screenshot and its Node run only). The concept is heavy: three round kinds, nine scorer versions, and a README claim table that is hard to scan. |
| Impact | 6 | The problem is real, and NEAR's own private-eval league is a plausible user. But it runs on testnet only, the single owner is the author, and both outside pilots used throwaway questions. The published benchmark itself is weak evidence about the models (see weakness 1). |
| Originality | 8 | Combining signed TEE inference, on-chain seal/commit/close, block-seeded audit samples, and in-enclave re-scoring is new to me. The "asked once" round, where a locked enclave project makes the model calls so the owner cannot re-ask, is a novel answer to a cheat most such schemes ignore. |
| Sustainability | 6 | It is on PyPI (1.2.2), has a GitHub Action, scheduled re-verification workflows, a maintenance guide and a merged outside pull request. But verification depends on six live public services and one rate-limited RPC, and testnet records can be reset. |

I did not reward the volume of documentation. It did help that the docs state limits that cut against the entry.

## a. Claims I checked by running something

| Command | Result |
|---|---|
| `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-96-r6-deepseek-v4.1-flash-1017.json` | VERIFIED, exit 0, 59 s, 12 `[pass]` lines |
| `uv run pytest -q` | 218 passed in 5.3 s (README says 182) |
| `scripts/review.sh` | `ALL CHECKS PASSED`, exit 0, 42 min 17 s |
| ↳ step 1: all 20 certificates | all VERIFIED |
| ↳ step 2: 39 tamper fixtures | all `ok` (29 REFUSED, 9 CAN'T CERTIFY, 1 VERIFIED, as stated) |
| ↳ step 4: Rust tests | contract 15 passed; scorer and asker tests passed |
| ↳ step 4: `tee/build-docker.sh` | rebuilt to `b301d22b…`, the current pin |
| ↳ step 4: `ask/build-docker.sh` at both recorded commits | rebuilt to `dbbb286b…` and `edb89964…`, both pinned |
| ↳ step 5: browser verifier in Node | 20 certificates and 34 tamper cases `ok`; scorer parity 148/148 and 3,600/3,600 |
| README's `curl … view_access_key_list … registry.fuin.testnet` | `"keys":[]`; a second query returned code hash `HvqaWNNc…`, matching the README |
| `fuin verify` on the round 7 certificate | VERIFIED, with the "asked once … 1 retried ask … locked at the seal" line as the README quotes it |
| `fuin show examples/cert-near-dev-60-r2-glm-5.3-flash.json --audit` | 23 revealed questions with expected answer, model answer and docs source |
| Totals read from the 20 certificate files | match the README results table |
| PyPI metadata for `fuin`; `git tag` | version 1.2.2 pointing at this repo; `v1` tag exists (I did not install or run the Action) |

**My own tampering** (13 certificates, built in the scratchpad):
- **Flip a score and recompute the run root in a zero-reveal round:** REFUSED `tee_score_mismatch`.
- **The same forgery on a sampled round, with proofs recomputed and the TEE score stripped:** every local check passed, then REFUSED `record_mismatch` at the on-chain commitment. This is the forgery that matters most, and the chain caught it.
- **Swap two signatures, or relabel the model:** REFUSED `signature_text_mismatch`.
- **Graft round 5's TEE score onto round 6:** REFUSED `tee_score_mismatch`.
- **Change the owner, or zero the retry count in round 7:** REFUSED `tee_score_invalid`.
- **Point at another registry account:** REFUSED `registry_mismatch`.
- **Edit a revealed answer key:** REFUSED `reveal_mismatch`.
- **Add an unknown top-level field:** REFUSED `certificate_invalid`.
- **Strip the TEE score from a sampled certificate, or the answer-key check from a zero-reveal one:** still VERIFIED, exit 0. This is by design (both are optional evidence), but see section d.

One of my extra runs returned CAN'T CERTIFY `evidence_unavailable` (HTTP 429 from the NEAR RPC) while the review script was running in parallel. The verifier reported it as an outage, not a verdict, as documented.

## b. Claims I couldn't check

- **Question quality:** rounds 4–7 reveal nothing, so only the owner knows what they ask. The entry says so.
- **No re-asking in rounds 1–6:** the owner could have re-asked and kept the best answer, and no certificate can show it. This is a printed limit and covers 19 of the 20 certificates.
- **Owner workflow** (`seal`, `run`, `commit`, `evaluate`, `ask`): needs keys and a paid API key, and the instructions say not to run it.
- **Earlier scorer builds v2–v8:** only the current scorer and the two askers were rebuilt.
- **The hosted page at fexx301.github.io and real-browser behaviour:** I only ran `verify.js` in Node and looked at the repo's screenshot.
- **The two outside pilots and the "blind reviews" by other AI models:** the evidence folders exist, but I can't confirm who ran what.
- **"Everything here was written during the event":** the git history starts Nov 3, which fits, but history can't prove the absence of earlier work.
- **End-to-end encryption hiding questions from NEAR's gateway:** I read the probe folder's name only and did not reproduce it.

## c. The three costliest weaknesses

1. **The headline result is weaker than the machinery behind it.**
   - Scoring is strict whole-message matching, and answers cut off at the token cap score 0.
   - In round 6, GLM was cut off on 28 of 96 answers; in round 3, on 72 of 300.
   - Every score is a single run, and the questions are short doc-lookup trivia.
   - So "which model answers NEAR developer questions correctly" is partly measuring token caps and formatting.
   - **Smallest fix:** add the cut-off column from `docs/RESULTS.md` to the README table and retitle the section as a demonstration, or rerun one round at a higher cap.

2. **The strongest guarantee is demonstrated once, on the smallest round.**
   - Only round 7 (37 questions, one model, with a known retry-undercount in its asker) stops the owner from re-asking.
   - The fixed second asker has no published round in `examples/`.
   - **Smallest fix:** publish one multi-model asked-once round through `ask2.fuin.testnet/asker` and add its certificate.

3. **Verification is fragile over time, and everything is on testnet.**
   - Each check re-queries Intel, NVIDIA and one archival RPC at today's date. I hit a rate limit with only four verifications in flight.
   - The full review took 42 minutes.
   - A testnet reset would turn every certificate into CAN'T CERTIFY, which the docs admit.
   - No doc says what happens when NVIDIA or Intel stop accepting old evidence.
   - **Smallest fix:** store the signed NVIDIA verdict and Intel collateral in the certificate and verify them as of the recorded time, and add a second working RPC fallback. A single mainnet round would address the reset risk.

## d. Confusing, wrong or overstated in the README

- **Wrong:** "182 passed" and "182 offline tests" (two places). The actual count is 218. The repo's own doc-count test doesn't cover this number.
- **Optimistic timings:** "one verification takes about 40 seconds" was 59 s here. "About 30 minutes (allow 45)" was 42 minutes.
- **Overstated:** "Every committed score was computed over every answer inside a TEE" is true of these 20 files. But the verifier still prints VERIFIED for a sampled certificate with that evidence removed; I didn't read whether the scope and limits text changes. A reader could take the TEE score as required.
- **Overstated:** the opening sentence on round 7, "no owner could quietly re-ask", sits ahead of the caveat that the same questions can be sealed again as a new round. The comparison table and Limits section do say it.
- **Incomplete:** the README says the work "builds on three small research probes from Oct 24". The code also cites an external "spec" that is not in the repo, and a "TCB policy (2026-10-27)". Some design work predates the build window beyond what is disclosed.
- **Confusing:** the "Every claim maps to a command" table packs eight scorer hashes and commit ids into one cell, and expected outputs are elided with "…", so a judge can't match them by eye.
- **Confusing:** "abliterated" models and "LoRA adapter, unpinned" appear in the results without explanation. One certified model's adapter is not pinned to a revision; this is in `docs/RESULTS.md` but not the README.
- **Unverified count:** the README promises "10 `[pass]` lines" for the round 1 Qwen certificate. My one direct run of it hit the rate limit at 8, and the review script, which did verify it, prints only the verdict line.

No tracked files were changed.
