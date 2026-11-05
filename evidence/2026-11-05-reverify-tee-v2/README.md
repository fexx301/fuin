# Every TEE score re-done with the cross-platform scorer build, 2026-11-05

The six TEE scores in `../2026-11-05-reverify-tee-score/` ran on scorer v1 (`a848254b…`). Its build reproduces only on macOS arm64. All six were re-done on scorer v2 (`dabae968…`), the canonical build: `tee/build-docker.sh` builds Linux x86_64 in a digest-pinned Rust image, so any host with Docker gets the same bytes. This repository's HEAD rebuilds to exactly that hash (81 s on a warm image).

Same method as before: one secret gist per run, deleted as soon as the scorer had fetched it. The certificates changed only in `run.evidence.tee_score`.

| Run | TEE total | Committed total | OutLayer task | Transaction |
|---|---|---|---|---|
| r3 glm-5.3-flash | 122/300 | 122/300 | 21082 | `6Cqfqk6D4zUhCXQ4HPUczYwXaS1VXiUB8wL6cepFxGZu` |
| r3 Qwen3.8-27B | 77/300 | 77/300 | 21084 | `Cy1vXQaFEEtxjq7CQDFMhKY7jDL67BZTVTMLFE7BdCA` |
| r2 glm-5.3-flash | 32/60 | 32/60 | 21080 | `6rkFJVpwPbLDRZ4yt2cVx7bKaCYSwqjDZAywXFUR9QcK` |
| r2 Qwen3.8-27B | 17/60 | 17/60 | 21081 | `B66bzJ4h17ZMp3kWs1GaLxGnCGwEMhHcaevfTenRur1Y` |
| r1 glm-5.3-flash | 25/60 | 25/60 | 21078 | `8y8ywZKzqwpxX1Jrfu8pFXQL1XEnucdzXwgGzFJxFsDe` |
| r1 Qwen3.8-27B | 17/60 | 17/60 | 21079 | `CPEGrDd6r7eFBqXc8jiPu3KP3fbtv1SpdpvnqT2gQwfm` |

`verify-output.txt` and `verify.jsonl`: all six VERIFIED. Each JSON line now records the certificate's sha256 (`cert_sha256`), and `scripts/build_page.py` uses a recorded result only for those exact bytes.

**What else changed with this:**
- **Scorer v1 retired.** `policy/tee-v2.json` now accepts only v2; `policy/tee-v1.json` is gone. A v1 TEE score is CAN'T CERTIFY `tee_unapproved`, so every accepted TEE score comes from a build anyone can reproduce.
- **The offline fixture** `tests/fixtures/tee-synthetic-evidence.json` was re-recorded on v2: OutLayer task 21092, total 3/3, matching Python. Its synthetic ciphertext is on FastFS. `scripts/score_tee_fixture.py` remakes it.
- **Tamper fixtures** were regenerated from the v2 certificates. All 21 still get their expected verdicts (`scripts/check_fixtures.py`).
- **Check order.** `tee.check_local` now runs every integrity check before the pin check. Evidence that both contradicts the certificate and names an unpinned build is REFUSED `tee_score_invalid`, not CAN'T CERTIFY (new test).
- **The limit printed with a TEE score** now says the scorer "rebuilds from tee/ with tee/build-docker.sh on any host with Docker."
- **The browser verifier checks the TEE score live.** It runs the same local checks, plus the record's Intel TDX quote, OutLayer's task hash, the worker's approval at the execution's block and the request and result on chain. `scripts/test_site_verifier.mjs` covers all six certificates plus six TEE tamper cases.
