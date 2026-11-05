# Fixes from a blind review in progress, 2026-11-06

A second blind review (Codex, model gpt-6-astra, fresh clone of `d144258`, the neutral prompt) hit its usage limit before writing its verdict. Its working notes already contained two findings and an independent reproduction.

**Reproduced by the reviewer:**
- **Tests:** 103 Python, 15 contract and 14 TEE scorer tests pass.
- **Sources:** all 74 revealed items' cited lines contain their anchors.
- **Builds:** all three accepted TEE scorer builds rebuilt to their pinned hashes from their recorded commits: v2 `dabae968…`, v3 `2614ddaa…`, v4 `cd36c486…`.

**Finding 1: a malformed certificate crashed the verifier.** An attestation entry with `model_name` deleted gave CAN'T CERTIFY `verifier_error` (a `KeyError`), where the README promises malformed input is refused.
- **Fix:** the schema check now requires every field the verifier reads from each attestation entry: `signing_address`, `model_name`, `intel_quote`, `request_nonce`, `event_log`, `nvidia_payload` and `info.tcb_info.app_compose`.
- **Result:** such a certificate is REFUSED `certificate_invalid` before any network call (`tests/test_verify_hostile.py`, four fields).

**Finding 2: numeric scoring differed across the three scorers on edge cases.**

| Case | Sealed Python scorer | Browser (before) | TEE scorer v4 (before) |
|---|---|---|---|
| answer `.5`, model says `0.5` | 1 | 0 | 1 |
| answer `1.`, model says `1` | 1 | 0 | 1 |
| answer `0`, tolerance `1`, model says `1.00000000000000000000000000001` | 1 | 0 | 0 |

- **The cause of the last row.** Python's `Decimal` rounds the difference to the default context's 28 significant digits (half-even) before comparing it with the tolerance. The browser and the Rust scorer compared the exact difference.
- **Which one is right.** The sealed Python scorer is the reference by its pinned file hash, so the other two now reproduce it:
  - both round the difference the same way;
  - the browser reads sealed answers and tolerances as `Decimal()` does: `.5` and `5.` forms, surrounding whitespace, Unicode digits, and `_` between digits.
- **New parity cases.** `scripts/make_scorer_parity.py` adds 600 generated cases of both kinds (3,600 in all; 18 of them flip under Python's rounding). The Rust scorer (`tee/tests/parity.rs`) and the browser (`scripts/test_site_verifier.mjs`) match Python on all 3,600, for scorer v1 and v2.
- **No published score changes.** Every published certificate's answers and TEE scores already matched Python: rounds 1–5, 1,593 answers.

**Scorer v5.** The Rust change is a new build. `tee/build-docker.sh` at commit `170c488` gives `86db82137a8da1c6095a95339848572cdd1e08e4962eb2296a072af7d3f7e35b` (742,076 bytes), served from FastFS. It is now the current pin; v2–v4 stay accepted for the rounds and rehearsal that sealed them. Inside OutLayer it scored the synthetic encrypted round 2/3 with `unreadable` 1, matching Python (task 22288, `tests/fixtures/tee-synthetic-evidence-v5.json`).

The reviewer's verdict is pending: the session resumes after the usage limit resets.
