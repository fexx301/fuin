# Fūin (Privacy track): review

**What it is:** Fūin lets someone publish benchmark scores while keeping the test questions private, and a stranger can still check those scores. The owner seals a Merkle root of the questions on a NEAR testnet contract. Each answer carries a `provider_tee` signature from a NEAR AI Cloud model whose TEE key is attested with Intel TDX and NVIDIA NRAS. Each run's results are committed on chain. For checking, a sample can be revealed, picked by a future block hash. Or the round reveals nothing, and every answer is re-scored in an OutLayer TDX enclave by a pinned, reproducible WASM scorer. Questions and answers can also be end-to-end encrypted so NEAR's gateway never sees them.

Every claim I ran held up. The weaknesses are in the trust model and in reach, not in the code.

## Scores

| Criterion | Score | Evidence |
|---|---|---|
| **Technical implementation** | **9** | <ul><li>`src/fuin/verify.py` checks the certificate's format first, then every offline check, then the network checks. A service outage only delays the verdict (`verify.py:166-171`), so an outage can't hide tampering. An unexpected path never ends in VERIFIED (`:405`).</li><li>The sample size is exact hypergeometric math, and the sampler avoids modulo bias (`core.py:124-159`).</li><li>The TEE check binds OutLayer's task hash to the TDX quote's report data, checks the worker's approval at the execution's block, and matches the request and result against the transaction on chain (`tee.py:340-382`).</li><li>The deployment trace runs from NEAR's compose-manager quote to a public compose file, with SLSA/sigstore build provenance.</li><li>All 19 real certificates VERIFIED, all 24 fixtures got their expected verdict, and the scorer matched on 3,600 generated cases.</li></ul> |
| **Design** | **7** | <ul><li>The three outcomes (VERIFIED, REFUSED, CAN'T CERTIFY) are well designed, with named codes, and every VERIFIED prints its own limits.</li><li>There is a browser verifier with live tamper buttons.</li><li>But the README is dense and internally inconsistent (see d). A full review takes 30 minutes and depends on about 7 outside services. Owner setup took the outside pilot 1 h 20 min.</li></ul> |
| **Impact** | **6** | <ul><li>The problem is real, and the README cites a current example (Delta League's private eval set).</li><li>But everything is on testnet. The only real benchmark is the author's own NEAR-docs suite. The one outside user ran script-generated questions.</li><li>It only certifies models that NEAR AI Cloud serves, which the README admits rules out fine-tuned submissions like Delta League's.</li></ul> |
| **Originality** | **8** | Commit-reveal benchmarks aren't new. What is new here: signatures from the model provider's TEE, combined with a sample picked by a block hash, combined with a zero-reveal mode where a second TEE (OutLayer) re-scores every answer. That fits the privacy track well. |
| **Sustainability** | **6** | <ul><li>Good: an MIT licence, a GitHub Action, CI twice a day, `fuin status`, PILOT.md, and a tool that drafts policy updates.</li><li>Fragile: there are nine attestation policy versions in 5 days (`policy/attestation-v1…v9`), and each NEAR redeploy needs a hand-reviewed update.</li><li>There is one hard-coded archival RPC with no fallback (`near.py:20`; the page's `rpc_fallback` list is empty).</li><li>The registry contract only rebuilds on the author's Mac. There is one author.</li></ul> |

**Overall: 7.5/10.** This is a strong contender in the Privacy track. Its engineering and verification rigour are well above a typical entry; adoption and trust-model gaps keep it from a 9.

## a. Claims I checked by running something

| Command | Result |
|---|---|
| `uv sync`; `uv run pytest -q` | 114 passed (30 s with review.sh running at the same time; 5.45 s inside review.sh) |
| `fuin verify …r6-deepseek…json`, first try (while review.sh was running) | **CAN'T CERTIFY evidence_unavailable, HTTP 429**, exit 2. The README warns about exactly this, and every offline check had already passed. |
| Same command, run alone | **VERIFIED** in 41 s: 11 checks pass, including "tee score … task 25501 … 0 unreadable answers" |
| `scripts/review.sh` (about 30 min) | **ALL CHECKS PASSED**, exit 0. All 19 certificates VERIFIED (README says 12; see d). The 24 fixtures matched the manifest exactly. Contract tests: 15 passed. TEE scorer Rust tests: 1 + 14 passed. The browser verifier, run in Node, matched every verdict, including the extra cases "RPC down + tampered → REFUSED" and "TEE record pointed at another real tx → REFUSED". Scorer parity: 148/148 revealed answers and 3600/3600 generated cases. |
| `curl … view_access_key_list registry.fuin.testnet` | `"keys":[]`: the registry account is locked, as claimed |
| `fuin show …r2-glm… --audit` | 13/23 correct, as in the README table; each question shows its pinned near/docs line |

## b. Claims I couldn't check

- **The TEE scorer rebuilds to the pinned hash `67c2292e…`:** Docker wasn't running, so review.sh skipped the rebuild.
- **The contract code hash matches `contract/`:** the README itself says it only rebuilds on the author's Mac.
- **Questions and answers stayed hidden from NEAR's gateway (rounds 5–6):** the certificate shows template v3 and the TEE rebuilds the ciphertext, but whether the gateway saw plaintext can't be observed from outside. I didn't re-run the probe in `evidence/2026-11-05-e2ee-probe/` because it needs an API key.
- **The outside pilot:** I didn't verify those certificates or contact the person. I also can't confirm the secret gists were deleted.
- **The hidden test sets' quality and answer keys:** private by design.
- **The page in a real browser:** I only ran it in Node.

## c. The three weaknesses that cost the most points

1. **An owner can ask each question several times and keep the best signed answer, and no certificate can show it.** The repo's own evidence shows temperature 0 isn't deterministic on NEAR's serving: re-asking 43 items changed 5 scores (`evidence/2026-11-05-round-near-dev-155-r4/README.md:23`). Every signature stays valid, so a score can be inflated undetectably. The printed limit ("not discarded API calls") doesn't say this plainly.
   - *Smallest fix:* add an explicit limit line: "an owner could resample an item and commit its best signed answer."
   - *Real fix:* have the OutLayer enclave make the single inference call per item itself.
2. **In zero-reveal rounds the answer key is unchecked.** The owner could seal a wrong key to favour or penalise a model, and nobody can ever check it.
   - *Smallest fix:* every item already cites a near/docs line at a pinned commit. Have the TEE scorer fetch that line and refuse an item whose expected answer doesn't appear in it. A zero-reveal certificate could then attest "every answer key is grounded in its cited source."
3. **Live-service fragility, and no proof of outside adoption.** I hit a 429 on the very first quick check. There's a single archival RPC with an empty fallback list, and the policy churns with every NEAR redeploy (v9 in 5 days).
   - *Smallest fix:* ship a list of 2–3 archival RPCs and try them in turn on 429/5xx, in both `near.py` and `site/data.js`.
   - *For impact:* run one round with someone else's real private questions, not script-generated ones.

## d. README problems

- **Fixture count:** the claims table says "23 `ok` lines" (`README.md:50`); everywhere else says 24, and 24 is what ran.
- **Certificate count:** "twelve" certificates in `examples/` (`:131`). There are 19.
- **Worker default:** "`FUIN_REVIEW_WORKERS` (default 4)" (`:38`). The script defaults to 3 (`review.sh:15`).
- **Timings disagree:** one verification is "about 40 seconds" (`:122`) versus "about 1 minute" in the quick check. Tests take "5 seconds", which only holds when nothing else is running.
- **Tracks:** "tracks `privacy` and `open`" (`:12`), while the entry was submitted to `privacy`. That's minor but potentially confusing.
- **Overstated framing:** "Anyone can check that the published score came from real, unedited answers" is true. But readers will take it to mean "the model's actual score", and resampling (c1) and the unchecked answer key (c2) break that reading.
- **The privacy claim needs a caveat:** "no question or answer crossed NEAR's gateway in the clear" is stated as fact, but it rests on NEAR AI's E2EE implementation and a probe, not on anything in the certificate. Also, each item's 0/1 score is public, so per-item correctness leaks. That is disclosed under Limits, but not in the results discussion.
- **Density:** the results paragraph mixes confidence intervals, upper bounds on cut-offs and abliteration findings. It's honest, but hard to scan, and pulls attention away from the product.
