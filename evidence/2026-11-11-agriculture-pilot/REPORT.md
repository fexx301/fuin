# Pilot report (PILOT.md section 6)

| Item | Answer |
|---|---|
| Round type, questions, models | 4A private, 48 questions, Qwen/Qwen3.8-27B and z-ai/glm-5.3-flash |
| Fūin version | `769d8ee` |
| Setup time (step 2) | About 5 minutes of hands-on time: clone, `uv sync` (about 1 s, packages cached), 199 offline tests (7 s), `near` already installed, testnet account from the faucet (3 s). Approximate. |
| Writing the suite (step 3) | The questions were not written by a person. A language model wrote candidates from 27 fetched public pages and a script checked quotes and keys (see README). An earlier attempt with model-chosen URLs failed (1 of 84 citations valid). |
| Check to certificates, hands-on time | Under 5 minutes: one `fuin check`, fixing 4 flagged questions, one `fuin evaluate … --yes` run in the background. |
| Waiting for model runs | About 1 hour, sequential. Approximate; no per-step timestamps. |
| NEAR AI cost | Not read. |
| Testnet NEAR spent | 0.0120 (10.0000 to 9.98796) |
| Each time the command stopped or failed | It never stopped. Each `tee-score` printed a warning that the secret gist was not deleted (`unknown flag: --yes`, gh 2.45.0); fixed in [PR #2](https://github.com/fexx301/fuin/pull/2). |
| Help from Fūin's builder | None. |
| Who verified | No third party. Run by the owner's agent on the same machine, in the repo (53 s) and in a clean venv from PyPI (84 s): both VERIFIED each time. |
| What was confusing | `uv` is a pyenv shim here, hidden by the repo's `.python-version`. |
| Decision the result supported | On this question set GLM 5.3 Flash scored 28/48 and Qwen3.8-27B 19/48. The set and keys are not reviewed, so this is a pointer only. |
| Would you use this for a real benchmark | Not answered. |

## Benchmark description
- **What it tests:** factual recall of agronomy and livestock extension guidance.
- **How the questions were chosen:** written by a language model from 27 public extension and government pages; 48 were kept after dropping duplicates, single-trial results and ambiguous items.
- **How the answer keys were checked:** by script against the cited sentence on the fetched page (63 of 81 passed). No person reviewed them.
