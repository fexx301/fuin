# Fresh-clone rehearsal, 2026-11-03

`git clone https://github.com/fexx301/fuin` into an empty directory (at commit `c995dc3`), then `./scripts/review.sh` with `NEARAI_API_KEY` unset. Result: **ALL CHECKS PASSED** in 243 s on the builder's Mac (uv and Rust already installed):

- both `examples/cert-near-dev-60-r1-*.json` VERIFIED;
- 14/14 tamper fixtures with their expected verdicts;
- 33 Python tests and 15 contract tests passed.

**Not yet shown:** a fresh AI-agent session (Claude Code or Codex) given only the README, and a machine without uv or Rust preinstalled.
