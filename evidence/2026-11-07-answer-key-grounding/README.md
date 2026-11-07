# Answer keys checked against their sources (Nov 7, 2026)

**Why:** blind review 3 (`evidence/2026-11-07-blind-review-3/`, weakness c2) found that a zero-reveal round's answer key is unchecked: an owner could seal a wrong key to favour or penalise a model, and nobody could ever see it.

**What changed:** scorer v7 (`acd9286f…`, `tee/build-docker.sh` at `58523c7`, pinned as current and as the only grounder in `policy/tee-v2.json`) adds a `ground` mode. The owner encrypts the round's items (salts and sealed bytes) to v7's in-enclave key. The enclave:
1. fetches each cited file from `raw.githubusercontent.com/near/docs/<commit>/<path>` (the repository is hard-coded; the round must cite one commit; unsafe paths are refused);
2. recomputes the benchmark root from the sealed bytes;
3. flags every item whose answer, or any `accept` alternative, doesn't appear in its cited line (split on `\n`, a trailing `\r` dropped, `,` `` ` `` `*` removed).

It returns the root, the commit, the count and one bit per flagged item. It runs once per round, after the fact, bound to the root sealed on chain, so the sealed scores and their sealed scorer builds are untouched. Each certificate of the round carries the same evidence as `run.evidence.tee_ground`; nothing else in the certificates changed (checked field by field against the previous commit).

**Results** (OutLayer TDX, testnet; ciphertext on a secret gist, deleted after each task):

| Round | Keys in their cited line | Flagged items | Task | Transaction |
|---|---|---|---|---|
| 4 (`near-dev-155-r4`) | 151/155 | 16, 40, 135, 139 | 26243 | `GL39n4bJNWBf7J48GoqZLnigxBDCfZpBxJtV3HDo6RsV` |
| 5 (`near-dev-96-r5`) | 94/96 | 33, 63 | 26242 | `82GJN7rsFStPd6yYC8mj76bVQR4TDwKBHaBpoFP5CXfM` |
| 6 (`near-dev-96-r6`) | 92/96 | 14, 35, 46, 94 | 26241 | `FH6rbqvU11SMgbzWLh6PhUVim8XtaZcKbfbE6Ahqte3k` |

Every result equals the owner's own run of the Python reference (`fuin.tee.ground_round`) on the same files, and the flagged items are the ones the offline rule found before any enclave ran. A flagged key isn't necessarily wrong (a derived number, or an alternative longer than the cited text); it is a key nobody checked.

**The commit pin:** GitHub serves a commit pushed to any fork of near/docs under `near/docs/<sha>` too, so an owner could otherwise cite a fork commit with an edited line. Tested on Nov 7: commit `6269ab678bc7…`, which exists only on a public fork (`gh api repos/near/docs/compare/6269ab67…...master`: `diverged`), was served by `raw.githubusercontent.com/near/docs/6269ab67…/docs/tutorials/fts.md` with HTTP 200. The verifier accepts only commits listed in `ground_commits`; `e2d2ea173cf4…` was checked to be on near/docs `master` (`gh api repos/near/docs/compare/e2d2ea17…...master`: status `ahead`, behind by 0), committed 2026-11-01, before every seal.

**Checks:** the Rust grounding matches Python on synthetic edge cases (`tests/fixtures/tee-ground-cases.json`, `tee/tests/ground.rs`) and on all three real rounds, run natively; Python tests in `tests/test_tee_ground.py`; four tamper fixtures (`ground-other-round`, `ground-hidden-flag`, `ground-fork-commit`, `ground-unpinned-build`); the 13 grounded certificates re-verified, results in `evidence/2026-11-07-reverify-ground/verify.jsonl`.

**Chance matches, measured by the owner on the cached files (not attested):** a grounded key could appear in its line by accident, inside a longer word or number. Of the 337 grounded keys, 6 appear only inside a longer token, and all 6 are legitimate: a number written against its unit with no space, or an accepted alternative contained in the main answer. No numeric key appears only inside a longer number. A whole-word rule would therefore have flagged 6 correct keys and caught nothing, so it wasn't adopted; a rule that a numeric key may not touch another digit changes no result here and is planned for the next scorer build.

**Limits (printed by the verifier):** a grounded key appears in its cited line; that doesn't prove it is the right answer to its question, and a short key can appear by chance. Flagged keys were not checked. The flags show which hidden items were flagged, not what they ask; GitHub saw which near/docs files each round cites.
