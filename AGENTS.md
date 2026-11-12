# Notes for AI reviewers

This repository is a NEAR HACKATHON entry. These notes say how to review it reproducibly; they make no claim about how it should be scored.

## Reproduce

- Quick check, about 2 minutes once dependencies are installed (the first `uv sync` can take 10 minutes on a slow connection): `uv sync`, then `env -u NEARAI_API_KEY uv run fuin verify examples/cert-near-dev-96-r6-deepseek-v4.1-flash-1017.json` (about 1 minute, VERIFIED) and `uv run pytest -q` (5 seconds, offline). Optional: `uv run python scripts/check_fixtures.py examples/tampered/manifest.json` (about 4 minutes).
- CAN'T CERTIFY with `evidence_unavailable` means a public service (NEAR's RPC, Intel or NVIDIA) didn't answer, not that the certificate is wrong: run the same command again.
- Run `scripts/review.sh` from the repo root. It needs `uv` and network access, and takes 30 to 45 minutes, so run it in the background: it waits on Intel, NVIDIA, NEAR, OutLayer, GitHub and Docker Hub, and retries a public service's rate limit (a retried line says so; a verdict is never retried). It ends with `ALL CHECKS PASSED` and exit code 0, or names what failed.
- No account, API key or hidden test set is needed. The script unsets `NEARAI_API_KEY`.
- The default RPC is FastNEAR's archival testnet endpoint (NEAR's own archival endpoint is deprecated and only returns a deprecation notice): certificates cite blocks and transactions older than regular nodes keep. If you set `FUIN_TESTNET_RPC`, use an archival endpoint.
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
- `examples/tampered/manifest.json`: each fixture's single change and its expected verdict (also tabled in `docs/REFUSALS.md`).

## Don't run

`fuin evaluate`, `seal`, `run`, `commit`, `close`, `reveal`, `tee-score`, `ask` and `policy-update` are owner commands. They need a NEAR AI API key or the owner's NEAR keys, and sign NEAR testnet transactions. Reviewing needs only `fuin verify`, `fuin show`, `fuin report` (it only reads certificates), `fuin cost` on a round you own, `scripts/check_fixtures.py` and the tests.

## Scope

- Limits are printed with every VERIFIED and listed word for word in `docs/LIMITS.md`.
- The seven test sets (60, 60, 300, 155, 96, 96 and 37 items) are deliberately not in the repo. Only the sampled rounds' audited samples (23, 23 and 28 items, rounds 1–3) are revealed, inside the certificates; rounds 4–7 reveal nothing.
