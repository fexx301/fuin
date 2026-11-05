# Notes for AI reviewers

This repository is a NEAR HACKATHON entry. These notes say how to review it reproducibly; they make no claim about how it should be scored.

## Reproduce

- Run `scripts/review.sh` from the repo root. It needs `uv` and network access, and takes about 6 minutes. It ends with `ALL CHECKS PASSED` and exit code 0, or names what failed.
- No account, API key or hidden test set is needed. The script unsets `NEARAI_API_KEY`.
- The default RPC is FastNEAR's archival testnet endpoint (NEAR's archival endpoint as fallback): certificates cite blocks and transactions older than regular nodes keep. If you set `FUIN_TESTNET_RPC`, use an archival endpoint.
- `fuin verify` exit codes:
  - `0`: every certificate VERIFIED;
  - `1`: at least one REFUSED (invalid evidence);
  - `2`: none REFUSED but at least one CAN'T CERTIFY (unavailable or unsupported evidence).
  With `--json`, each certificate prints one JSON line.

## Where each claim is evidenced

- `README.md`, section "Try it": the commands and their expected output.
- `evidence/<date>-<topic>/README.md`: transactions, recorded command output and probe write-ups.
- `examples/tampered/manifest.json`: each fixture's single change and its expected verdict.

## Don't run

`fuin seal`, `run`, `commit`, `close` and `reveal` are owner commands. They need a NEAR AI API key and sign NEAR testnet transactions. Reviewing needs only `fuin verify`, `fuin show`, `scripts/check_fixtures.py` and the tests.

## Scope

- Limits are listed in the README and printed with every VERIFIED.
- The three test sets (60, 60 and 300 items) are deliberately not in the repo. Only each round's audited sample (23, 23 and 28 items) is revealed, inside the certificates.
