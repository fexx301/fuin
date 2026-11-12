# Blind review 5 (Claude Code), 2026-11-12

A fresh clone of `be5feb2` (version 1.2.2), run with no API key and no project memory, given the neutral judging prompt used for reviews 1 to 4. The verdict is in [review.md](review.md), copied as written except that one sentence naming a log file on the reviewer's machine is removed.

**Scores:** technical 9, design 7, impact 6, originality 8, sustainability 6. Overall 8/10. Everything it ran held: all 20 certificates VERIFIED, 39 fixtures matched, 218 Python tests, the contract, scorer and asker tests, the scorer and both askers rebuilt to their pins, and the browser verifier agreed on every verdict. It also built 13 tampered certificates of its own; each got the right verdict.

## Fixed

| Finding | Change |
|---|---|
| The README understated what predates the Nov 1 start: it said no earlier code is reused, while the code cites a "spec" that isn't in the repository. | The README now names both things from Oct 24: a written design, and two probe scripts (171 lines), one of which `src/fuin/attestation.py` was rewritten from, keeping two lines word for word. A code comment that dated the TCB rule to Oct 27 had no source; it now cites that design (`af4bc58`). |
| "182 passed" in two places; the suite has 218. | The README states no count, since nothing kept the number current (`2075a47`). |
| The opening sentence on round 7 said no owner could quietly re-ask, ahead of its caveat. | It says "within that round", and that rounds aren't linked (`b3dae52`). |
| "One verification takes about 40 seconds" took 59 s. | "About a minute", as the quick check already said (`de00ddb`). |
| "Every committed score was computed over every answer inside a TEE" reads as if a TEE score were required. | It is optional evidence for a sampled round. Checked: a round 2 certificate with its TEE score removed still gives VERIFIED, with no `tee score` line and a scope covering the revealed sample only. The README says so (`cc7ab59`). |
| The headline result partly measures the token cap and the answer format: GLM was cut off on 28 of 96 answers in round 6 and 72 of 300 in round 3. | The README says to read the scores as a demonstration of the protocol, not a leaderboard, with those counts beside them (`894cc28`). |
| "Abliterated" and "LoRA adapter, unpinned" were unexplained. | One bullet explains both, and that the Qwen adapter's certificate pins the base weights, not the adapter (`894cc28`). |
| The claim table packed eight scorer hashes into one cell, and `…` was unexplained. | The row names the current build and both askers and points to `policy/tee-v2.json` for the seven earlier builds; the header explains `…` (`d5fd928`). The second asker's rebuild line was missing there and is added. |
| No doc said what happens when Intel or NVIDIA stop accepting old evidence. | `docs/COSTS-AND-DEPENDENCIES.md` says what each case produces (`e8b9aac`). |
| The fixed second asker has no published round. | Not run (see below); the README now says it has run rehearsal rounds only (`acd91e6`). |

## Checked, and not a fault

- **"One rate-limited RPC; add a second working fallback."** There are two: `archival-rpc.testnet.fastnear.com` and `archival-rpc.testnet.near.org`. Both served round 1's seal block on Nov 12, and a rate limit on one moves on to the other, with about 1.5 minutes of back-off before CAN'T CERTIFY.
- **"10 `[pass]` lines" for the round 1 Qwen certificate**, which the reviewer couldn't count through a rate limit: counted here, 10.
- **"A merged outside pull request."** The pull request was closed, not merged. Its fix landed in the author's own commit (`24a7dee`), with the pilot user credited.

## Not changed

- **A counted asked-once round on the second asker, with several models.** It would change the published counts, the page and the video two days before the deadline, and only one model is measured to fit the asker's time limit. Its locked rehearsal certificates are in `evidence/2026-11-11-asker-v2/`.
- **Storing Intel's collateral and NVIDIA's verdict in the certificate**, to verify as of the recorded time. That is a certificate-format change; it isn't made this close to the deadline.
- **A mainnet round.** Fūin runs on testnet, and the docs say what a testnet reset would do.
- **No outside owner with their own real questions, and no outside verifier.** Still true; see `evidence/2026-11-11-agriculture-pilot/`.
- **The full review takes 30 to 45 minutes** (42 here). Stated as such.
