# External review, 2026-11-04

An independent reviewer (another AI agent, run by the builder) ran `scripts/review.sh` (all checks passed), probed edge cases, and reported three defects. Each was reproduced before fixing:

| # | Finding | Reproduced | Fix |
|---|---|---|---|
| 1 | A one-byte revealed salt crashed the verifier (`AssertionError` in `core.benchmark_leaf`) instead of returning a verdict. | yes: `CRASH AssertionError` | Strict schema validation of every field before any check (REFUSED `certificate_invalid` naming the field); `core.benchmark_leaf` raises `ValueError`; any unexpected internal error returns CAN'T CERTIFY `verifier_error`, never a crash and never VERIFIED. |
| 2 | An outage could hide tampering: a corrupted signature text plus an unavailable model catalog gave CAN'T CERTIFY instead of REFUSED, because the catalog check ran before the local checks. | yes: `CANT_CERTIFY evidence_unavailable` | Checks now run in order: schema; model support (from the verifier's own policy, with the catalog only wording the reason); every local check (rows, roots, policy, signatures, reveals); then network checks. An outage in a network check only defers the verdict. |
| 3 | The README said a cut-off answer always scores 0, but the scorer ignores `finish_reason`: a truncated response containing the right answer scored 1. | yes: scores `1` | The documented rule now matches the code: the scorer reads only the final answer text. The published revealed cut-offs all had empty answers and scored 0, so no published total changes. Sealed scorers are unchanged, so existing certificates still verify. |

Regression tests: `tests/test_verify_hostile.py` (21 cases) runs offline with every service failing. It shows that malformed input gets a structured refusal, local tampering is REFUSED during an outage, and an untampered certificate with services down is CAN'T CERTIFY, not VERIFIED. All 14 fixtures still give their expected verdicts, and both real certificates still verify.

The reviewer also pointed to the inconsistent disclosure counts (verifier "23 disclosed" versus README "24"). The verifier now says "directly revealed 23, unrevealed 37" and that it doesn't compute indirect disclosure; the README gives the 24/36 known total and why. The detection-power wording now says it is not a probability that the total is correct.
