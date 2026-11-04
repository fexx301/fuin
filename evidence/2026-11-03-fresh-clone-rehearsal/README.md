# Fresh-clone rehearsal, 2026-11-03

`git clone https://github.com/fexx301/fuin` into an empty directory (at commit `c995dc3`), then `./scripts/review.sh` with `NEARAI_API_KEY` unset. Result: **ALL CHECKS PASSED** in 243 s on the builder's Mac (uv and Rust already installed):

- both `examples/cert-near-dev-60-r1-*.json` VERIFIED;
- 14/14 tamper fixtures with their expected verdicts;
- 33 Python tests and 15 contract tests passed.

**Not yet shown:** a fresh AI-agent session (Claude Code or Codex) given only the README, and a machine without uv or Rust preinstalled.

## Re-run, 2026-11-04 (after the review fixes and round 2)

Fresh clone at `9d68c4c`, `./scripts/review.sh` with no API key: **ALL CHECKS PASSED** in 234 s. All 4 certificates (2 models × 2 rounds) VERIFIED; 14/14 fixtures with their expected verdicts; 55 Python tests (including 21 offline hostile-input and outage tests) and 15 contract tests passed.

## Re-run, 2026-11-04 (interactive page and in-browser verifier)

Fresh clone at `8b2d232`, `./scripts/review.sh` with no API key: **ALL CHECKS PASSED** in 311 s on Node 24. Steps: 4 certificates VERIFIED; 14/14 fixtures; 55 Python and 15 contract tests; and the in-browser verifier (`site/verify.js`, run under Node) matching the CLI on all 20 cases. Those cases cover the 4 real certificates, 13 tamper and outage cases (including a forged TDX quote, an edited app_compose and an unapproved configuration that must not hide registry tampering) and scorer parity on all 92 revealed answers.
