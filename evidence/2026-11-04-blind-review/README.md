# Blind review, 2026-11-04

**Setup.** An AI reviewer (Codex, model gpt-6-astra) got a fresh clone of commit `5a0b8e7` and a neutral judging prompt:
- **Prompt:** the event, the track, the five criteria and a 1–10 scale. It didn't say who built the entry and gave no earlier scores.
- **Instructions:** follow the README's instructions for judges, and use no API key.
- **Sandbox:** network on, writes limited to the clone and the uv, cargo and rustup caches.

**Result.** It ran `scripts/review.sh` (ALL CHECKS PASSED), then probed beyond the supplied tests.

| Criterion | Score |
|---|---|
| Technical implementation | 6 |
| Design | 7 |
| Impact | 6 |
| Originality | 8 |
| Sustainability | 6 |
| **Overall (equal weights)** | **6.6** |

## Findings, checked against the code, and what changed

| Finding | Confirmed? | Change |
|---|---|---|
| The attestation check approved the application (MRCONFIGID, RTMR3) but not the OS it runs on (MRTD, RTMR0-2); the policy's `os_image_hash` was recorded but never compared | Yes, in `attestation.check_report` | Attestation policy v5 pins each configuration's OS measurements, as observed in 18 Intel-verified quotes, and its `os_image_hash`. Anything else is CAN'T CERTIFY `measurement_unapproved`, in the CLI and the browser. The deployment trace's same-machine check now compares the OS measurements too. |
| A certificate with its deployment attestation removed, or its quote emptied, was still VERIFIED (with a warning) | Yes, in `verify.py` | VERIFIED requires the trace. Missing evidence is CAN'T CERTIFY `deployment_untraced`; a malformed or emptied quote is REFUSED `attestation_invalid`. New tamper cases `deployment-untraced` and `emptied-deployment-quote`. |
| `run.evidence` set to a string crashed the verifier after every check passed | Yes, the line ran outside the catch-all | Schema check on `run.evidence`; tamper case `malformed-evidence` and two offline tests |
| In the browser, an uploaded certificate whose GPU evidence wasn't checked was VERIFIED | Yes | The browser can't call NVIDIA's NRAS or run the trace. VERIFIED now needs `fuin verify`'s recorded result for both on that exact, unmodified certificate; otherwise PARTLY CHECKED. |
| The browser scorer folds case differently from Python (`Straße` vs `STRASSE`) | Yes, and wider: 3,000 generated edge cases gave 364 (v1) and 589 (v2) mismatches, also from whitespace and Unicode digits | The browser port now uses Python's whitespace set, digit values and case folding, generated from Python 3.13. 0 mismatches on the 3,000 cases, now part of the browser test. |
| README overstatements | Yes | "Sealed before any model runs" became "before any result is committed". The cap claim is now an explicit upper bound. Case counts, the column note, the audit-size wording, the round count and the browser verdict rule were corrected. |

**Found while fixing, not in the review:**
- **Intel outages were refused as forgeries.** An Intel collateral outage raised the same error as a forged quote, so it was REFUSED rather than CAN'T CERTIFY. Quote parsing, collateral fetching and verification are now separate steps. A collateral failure counts as an outage only if the request failed or Intel doesn't answer.
- **Old transactions were disappearing from the RPC.** The regular testnet endpoints had already dropped the Nov 3 transactions on Nov 5, so by judging every certificate would have been CAN'T CERTIFY. Reads now default to FastNEAR's archival endpoint, with NEAR's archival endpoint as fallback (`../2026-11-05-reverify-policy-v5/`).

**Not addressed:**
- **Independent use.** An outside benchmark owner completing `PILOT.md` hasn't happened yet.
- **OS measurements rebuilt from source.** v5 pins measurements as observed in NEAR's reports. It doesn't recompute them from the dstack OS image, and the limits say so.
