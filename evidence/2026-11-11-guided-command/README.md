# One guided command for a whole round, 2026-11-11

A reviewer asked for one command that takes a new user from a suite to verified certificates without deciding which command comes next, and for `fuin check` to catch a missing asker key, hosting prerequisites and known model and time-limit problems before the seal.

## What changed

- **`fuin evaluate SUITE --id ID --owner ACCOUNT --model MODEL …`** checks the suite and the prerequisites, says in plain words what the chosen kind of round makes public and what stays possible, asks before sealing (a seal can't be undone), then runs every remaining step and ends with a keyless `fuin verify`.
- **It decides nothing itself.** `fuin status` now produces its next step as data (`tooling.progress`), and `fuin evaluate` runs that step, so the two can't disagree.
- **It resumes.** Run the same command again after an interruption. Steps that are done are skipped. Flags that disagree with what was sealed are refused, not ignored. A network failure prints "run the same command again" instead of a traceback.
- **`fuin check --ask`** now checks that a NEAR AI key is stored for the asker's project (that it is there, not that it works), that the model and token cap fit the asker's time limit where that was measured, and, with `--host gist`, that the GitHub CLI is signed in. An untested model is a warning, not a pass.

## Live proof, from a fresh clone

A fresh clone of the branch (`318e650`) with an empty `private/`, so first-use steps ran too. Three public questions, owner `fuin.testnet`, NEAR testnet. Each round was one `fuin evaluate … --yes` command.

| Kind of round | Models | What happened | Result | Transcript |
|---|---|---|---|---|
| Sampled | Qwen3.8-27B, GLM-5.3-Flash | seal, run and commit for each model, close, reveal, verify | 2 certificates VERIFIED | [eval-sampled-1.txt](eval-sampled-1.txt) |
| TEE-scored, encrypted | Qwen3.8-27B | killed after 75 s, during the commit; the same command again resumed at the commit, then closed, scored in the TEE and verified | VERIFIED; the registry holds one run | [first run](eval-private-1a.txt), [rerun](eval-private-1b.txt) |
| Asked once, encrypted | DeepSeek-V4.1-Flash, 4,096 tokens | check found the stored key and the measured time-limit fit; ask, commit, close, verify | VERIFIED, 0 retried asks | [eval-asked-1.txt](eval-asked-1.txt) |

The four certificates are in this folder. They are rehearsals on public questions, not counted rounds.

## Tests

`tests/test_evaluate.py` walks each kind of round from nothing to verified, reruns after a network failure, picks up two half-finished states seen on Nov 11 (aggregate collected but the seal check missing; closed with no certificates), and checks the refusals (flags that disagree with the seal; no terminal and no `--yes`).

## What this doesn't show

- An asked-once round run by an owner other than `fuin.testnet`. `scripts/store_asker_secret.py` now takes `--owner`, but no second account has stored a key for the asker's project.
- `fuin evaluate` does not run `fuin tee-ground` (optional answer-key grounding); `fuin status` still offers it afterwards.
- A user who has never set up `near-cli-rs`, a testnet account or a NEAR AI key: those steps stay in [PILOT.md](../../PILOT.md).
