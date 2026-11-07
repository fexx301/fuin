# Blind review 3 (Claude), 2026-11-07

A fresh clone of `66dbb25`, run with no API key, no project memory and no user-level plugins, given the neutral judging prompt used for reviews 1 and 2. The verdict is in [review.md](review.md), copied unedited.

**Scores:** technical 9, design 7, impact 6, originality 8, sustainability 6. Overall 7.5/10, "a strong contender in the Privacy track". Every claim it ran held. `review.sh` passed in full: 19 certificates VERIFIED, 24 fixtures matched, 114 tests, the contract and scorer tests, and the browser verifier matched every verdict.

## Fixed

| Finding | Change |
|---|---|
| c1. An owner can re-ask a question and commit the best signed answer, and no certificate can show it. The printed limit didn't say so plainly. | A new printed limit, also in the README's limits and the page's list: "An owner could send the same sealed request more than once and commit the best signed answer; every signature stays valid, so a certificate can't show that." The README's problem section points to it. |
| c3. Its first quick check hit HTTP 429 from the only archival RPC; the fallback list was empty. | NEAR's own archival endpoint serves the full history again (checked Nov 7: the Nov 3 seal transaction, live blocks, and CORS for browsers), so it is now the fallback in both verifiers. A JSON-RPC answer that says the endpoint is throttling or deprecated moves on to the other endpoint instead of ending the check. Tests cover both cases. |
| d. "23 `ok` lines" vs 24 fixtures; "twelve" certificates vs 19; `FUIN_REVIEW_WORKERS` "default 4" vs 3 | Corrected. |
| d. The gateway privacy claim was stated as fact | It now says it rests on NEAR AI Cloud's end-to-end encryption, observed by the probe, and that the certificate itself can't show it. |

## Not fixed, and why

- **c1, real fix (the enclave makes the single inference call per item):** a redesign of how runs are made. This close to the deadline the stated limit is the honest change.
- **c2, answer keys checked against their cited source inside the TEE:** the owner already does this check when the suite is built (`scripts/check_suite_sources.py`: every anchor on its cited line, and each answer either found literally or listed for review). Moving it into the enclave would need a new scorer build that fetches from the network, and re-scoring every round. A few answers are derived rather than literal (3 of 96 in round 6), so it would also need a rule for those. The unchecked-key limit stays printed.
- **Policy churn (v1–v9 in five days):** it follows NEAR's redeploys. `fuin policy-update` drafts each update, and a person reviews it.
- **Impact (no outside user with a real private benchmark) and README density:** not changed by code.
