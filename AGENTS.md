# Notes for AI reviewers

This repository is a NEAR HACKATHON entry. These notes say how to review it reproducibly; they make no claim about how it should be scored.

## Reproduce

- Run `scripts/review.sh` from the repo root. It needs `uv` and network access, and takes about 16 minutes (allow 30), so run it in the background: it waits on Intel, NVIDIA, NEAR, OutLayer, GitHub and Docker Hub, and retries a public service's rate limit (a retried line says so; a verdict is never retried). It ends with `ALL CHECKS PASSED` and exit code 0, or names what failed.
- No account, API key or hidden test set is needed. The script unsets `NEARAI_API_KEY`.
- The default RPC is FastNEAR's archival testnet endpoint (NEAR's archival endpoint as fallback): certificates cite blocks and transactions older than regular nodes keep. If you set `FUIN_TESTNET_RPC`, use an archival endpoint.
- `fuin verify` exit codes:
  - `0`: every certificate VERIFIED;
  - `1`: at least one REFUSED (invalid evidence);
  - `2`: none REFUSED but at least one CAN'T CERTIFY (unavailable or unsupported evidence).
  With `--json`, each certificate prints one JSON line.
- Every certificate also carries a TEE score (`run.evidence.tee_score`, checked by `src/fuin/tee.py` and, in the browser, by `site/verify.js`): every answer re-scored inside an OutLayer TDX enclave. Its codes are `tee_score_invalid`, `tee_score_mismatch` and `tee_attestation_invalid` (REFUSED), and `tee_unapproved` and `tee_score_missing` (CAN'T CERTIFY). The last applies to a zero-reveal round (`benchmark.policy.audit.mode` = `tee-scored-v1`), whose TEE score is its only score check: such a certificate has no reveals and no audit seed.
- `scripts/review.sh` step 4 also runs the TEE scorer's Rust tests when Rust 1.95.0 with `wasm32-wasip2` is installed, and rebuilds the scorer with `tee/build-docker.sh` when Docker is running, expecting the `current` sha256 in `policy/tee-v2.json`. Each part says when it was skipped; a rebuild that can't complete (image pull, network) is skipped, not failed. The first rebuild pulls a Rust image and crates, which adds a few minutes.

## Where each claim is evidenced

- `README.md`, section "Try it": the commands and their expected output.
- `evidence/<date>-<topic>/README.md`: transactions, recorded command output and probe write-ups.
- `examples/tampered/manifest.json`: each fixture's single change and its expected verdict.

## Don't run

`fuin seal`, `run`, `commit`, `close`, `reveal` and `tee-score` are owner commands. They need a NEAR AI API key or the owner's NEAR keys, and sign NEAR testnet transactions. Reviewing needs only `fuin verify`, `fuin show`, `scripts/check_fixtures.py` and the tests.

## Scope

- Limits are listed in the README and printed with every VERIFIED.
- The three test sets (60, 60 and 300 items) are deliberately not in the repo. Only each round's audited sample (23, 23 and 28 items) is revealed, inside the certificates.
