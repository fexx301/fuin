**Overall: 7.0/10 — solid, with particularly strong technical implementation and Privacy-track fit.** I would shortlist it for technical consideration, but the repository does not yet justify an unqualified top-prize score.

I reviewed commit `12a6ed4`. The overall score is the unweighted mean below because no weights are published. I awarded credit for working behavior and evidence, not documentation volume. No tracked files were changed.

| Criterion | Score | Evidence and deductions |
|---|---:|---|
| Technical implementation | **8/10** | All 20 published certificates and both pilot certificates verified through the CLI. The implementation checks signatures, commitments, transaction ordering, attestation, deployment provenance, and TEE scoring. Python, Rust, and browser-verifier tests passed. Deductions: a confirmed limit-disclosure bug, an unresolved asker concurrency risk, and binary reproducibility that I could not independently complete. |
| Design | **7/10** | Specific verdicts, visible check stages, tampering controls, and an audit viewer make complex evidence understandable. The supplied screenshot and UI source show a coherent interface. Owner onboarding remains demanding: the recorded pilot needed 80 minutes of setup. I tested browser logic in Node, but could not assess live browser interaction or mobile usability. |
| Impact | **6/10** | Confidential, independently checkable evaluation is a useful problem, and the pilot certificates genuinely verify. However, the outside pilot used synthetic questions; sustained independent use is unproven. The demonstrated benchmark primarily measures exact documentation recall. Grounding establishes answer-string presence, not whether a hidden question has the correct answer. |
| Originality | **8/10** | The combination of sealed benchmarks, attested model signatures, future-block sampling, private TEE scoring, and enclave-controlled requests is distinctive and purposeful. NEAR is integral to the evidence chain. The originality is in the system’s composition, rather than a new cryptographic primitive. |
| Sustainability | **6/10** | Account-free verification, packaging, automated checks, and explicit version pins provide a credible maintenance foundation. Against that: testnet-only deployment, several live service dependencies, manual attestation-policy maintenance, and duplicated verifier implementations. Continued usefulness beyond the hackathon has not been demonstrated. |

**a. Claims checked by execution.** I kept review caches and logs inside the repository and unset `NEARAI_API_KEY` for certificate verification.

| Command/check | What happened |
|---|---|
| `uv sync` | Succeeded. Dependency preparation took **10m 22s**, substantially longer than the fresh-clone estimate on this connection. |
| `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-96-r6-deepseek-v4.1-flash-1017.json` | **VERIFIED**, exit 0: **38/96**, 96 signatures, zero reveals, matching TEE score, and 92/96 grounded keys with four explicitly flagged. |
| Same verification command for round 7 | **VERIFIED**, exit 0: **19/37**, locked asker project, seal-bound requests, zero unreadable answers, **one retried ask**. |
| `bash scripts/review.sh`, followed by `.venv/bin/python .review-tmp/resume-review.py` | The usage interruption stopped the original script after six certificates. I resumed its unfinished certificate and fixture checks separately. **All 20 published certificates and both pilot certificates verified.** The original script did not reach its final banner. |
| `.venv/bin/python scripts/check_fixtures.py examples/tampered/manifest.json` | **39/39 matched**, exit 0: 29 REFUSED, nine CAN’T CERTIFY, one VERIFIED. No outage retries were needed. |
| `uv run pytest -q` | **155 passed in 6.66s.** |
| `cargo test --manifest-path contract/Cargo.toml -q` | **15 passed.** |
| `cargo test --manifest-path tee/Cargo.toml --release -q` | **18 passed**, including scorer parity and synthetic-round checks; Cargo 1.95.0. |
| `node scripts/test_site_verifier.mjs` | Exit 0; **60 successful checks**, **148/148** revealed-answer comparisons, **3,600/3,600** generated scorer comparisons. Uploaded certificates correctly received PARTIAL without recorded GPU evidence. |
| `uv run fuin show examples/cert-near-dev-60-r2-glm-5.3-flash.json --audit` | Displayed **23 revealed items**, expected answers, model responses, sources, and score classifications. |
| README’s `curl` RPC query for `view_access_key_list` on `registry.fuin.testnet` | Returned **`"keys":[]`**, at block 277090989. |
| Artifact-count script | Confirmed **20 certificates, 2,302 answers, seven models**, and the stated fixture distribution. |

Detailed results are retained in the resumed review log (`.review-tmp/resume-review.log`), round 6 CLI output (`.review-tmp/quick-verify.log`), and browser-verifier log (`.review-tmp/browser-verifier.log`).

**b. Claims I could not independently establish.**

- **Hidden benchmark quality:** the unrevealed questions are intentionally absent. Valid certificates do not establish representative question selection, semantic answer correctness, or freedom from benchmark-owner bias.
- **Fresh owner workflow:** I did not create a round or make model calls. These require credentials and signing operations explicitly excluded from the review instructions.
- **Deployed binaries matching source:** Docker was not running, so scorer/asker rebuilds were unavailable. I also did not reproduce the registry’s specialized build. Passing native tests does not substitute for those hash comparisons.
- **Live UI usability:** the browser-control service was unavailable. Node tests validate verifier behavior, not the complete user experience.
- **Pilot circumstances, costs, and adoption:** its certificates verify, but reported setup times, expenditure, and willingness to use it remain supplied evidence. Local Git history is consistent with the build window, not independent proof of when all work originated.

**c. The three weaknesses costing the most points, and the smallest fixes.**

1. **The strongest “asked once” guarantee needs tighter enforcement and wording.**  
   Retries already make “refused to ask any question twice” literally inaccurate. There is also a concurrency concern in the asker (`ask/src/main.rs:118`): after claiming a pending record, a task re-reads it and later uses that newer record for its final compare-and-set. My local state-machine reproduction (`.review-tmp/ask-race-model.py`) permits another task’s completed answer to be overwritten and the retry count to become zero. **This is a conditional source-level finding, not a demonstrated live OutLayer exploit**; execution serialization could matter.  
   **Smallest fix:** retain and validate the task’s own claim/version through finalization, preserve monotonic attempt counts, and test overlapping tasks against the actual storage API. Describe the current guarantee as one recorded answer with disclosed retries. A corrected immutable deployment would require a new pinned asker project.

2. **Independent practical value is still weakly demonstrated.**  
   The outside pilot (`evidence/2026-11-06-outside-pilot/README.md:10`) establishes portability, but used synthetic questions; its original independent-machine verifier was the entrant. My verification strengthens certificate reproducibility, not evidence of user demand.  
   **Smallest fix:** obtain one independent benchmark owner’s report using their own meaningful private suite, with a separate verifier and a concrete model-selection or publishing decision enabled by the certificate.

3. **Historical verification has a fragile operational lifetime.**  
   The verifier is pinned to testnet (`src/fuin/near.py:20`), and the repository acknowledges that a reset would make certificates unverifiable. Multiple live services and evolving approval policies also need continued maintenance.  
   **Smallest credible fix:** demonstrate one supported durable deployment and a certificate that verifies against it, with configurable deployment settings and a tested archival/recovery procedure. Another maintenance document alone would not close this gap.

**d. README statements needing correction or qualification.**

- **“Refused to ask any question twice” is overstated.** Round 7’s actual CLI output reports one retried ask and explicitly qualifies the single-draw guarantee. The opening paragraph, comparison table, and limits summary should use that narrower wording.
- **“Every VERIFIED prints the limits that apply” is currently false.** In verify.py:33 (`src/fuin/verify.py:33`), the positional constants point to the wrong entries. Ordinary zero-reveal rounds consequently omit the explicit re-asking warning and retain an obsolete inference-timing warning. I observed both in the round 6 output. Use named constants and test the selected limits for each round type.
- **The linked limits are not entirely “word for word.”** `docs/LIMITS.md` lacks the current `ASKED_LIMIT` wording explaining timeout retries and owner-controlled time limits.
- **The opening says every answer is “re-scored.”** Round 7 scores answers as it asks them; the later table states this correctly. “Scored inside a TEE” would cover all rounds accurately.
- **Answer-key grounding needs its qualification beside the claim.** “Keys come from their cited sources” means string occurrence in cited lines, not semantic validation. The README eventually acknowledges this, so this is potentially misleading shorthand rather than a concealed limitation.
- **Timing estimates are optimistic for a genuinely fresh environment.** My install alone exceeded ten minutes. I would qualify the estimate rather than deduct technical points solely for download speed.