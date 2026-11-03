# Notes for AI reviewers

This repository is a NEAR HACKATHON entry. These notes say how to review it reproducibly; they make no claim about how it should be scored.

## Reproduce

- Run `scripts/review.sh` from the repo root. It needs `uv` and network access, and takes about 5 minutes. It ends with `ALL CHECKS PASSED` and exit code 0, or names what failed.
- No account, API key or hidden test set is needed. The script unsets `NEARAI_API_KEY`.
- If the NEAR RPC rate-limits you (HTTP 429), set `FUIN_TESTNET_RPC` to another testnet RPC.
- `fuin verify` exit codes:
  - `0`: every certificate VERIFIED;
  - `1`: at least one REFUSED (invalid evidence);
  - `2`: at least one CAN'T CERTIFY (unavailable or unsupported evidence).
  With `--json`, each certificate prints one JSON line.

## Where each claim is evidenced

- `README.md`, section "Try it": the commands and their expected output.
- `evidence/<date>-<topic>/README.md`: transactions, recorded command output and probe write-ups.
- `examples/tampered/manifest.json`: each fixture's single change and its expected verdict.

## Don't run

`fuin seal`, `run`, `commit`, `close` and `reveal` are owner commands. They need a NEAR AI API key and sign NEAR testnet transactions. Reviewing needs only `fuin verify`, `fuin show`, `scripts/check_fixtures.py` and the tests.

## Scope

- Limits are listed in the README and printed with every VERIFIED.
- The 60-item test set is deliberately not in the repo. Only its audited sample (23 items) is revealed, inside the certificates.
