# Agriculture pilot: a private round on questions written from public extension pages, 2026-11-11

A second outside run of the pilot kit ([PILOT.md](../../PILOT.md), section 4A) by [zkasuran](https://github.com/zkasuran), run by the owner's coding agent on the owner's Linux machine, with the owner's own NEAR AI Cloud key and testnet account.

| | |
|---|---|
| Kit | Fūin 1.1.0, commit `769d8ee`, run unmodified |
| Machine | Ubuntu 24.04.5; uv 0.11.19, near-cli-rs 0.30.1, gh 2.45.0, Python 3.13.13 |
| Round | `pilot-1`, owner `zkasuran-fuin.testnet`, 48 questions, two models. Private: every item scored inside OutLayer's TEE by scorer `b301d22b…`, nothing revealed, questions and answers end-to-end encrypted (request template v3). |
| Results | z-ai/glm-5.3-flash 28/48 (OutLayer task 61493); Qwen/Qwen3.8-27B 19/48 (task 61489). Seal at block 277238378, close at 277242768. |
| Runs | Sequential (`--parallel 1`). About 1 hour of waiting in total; per-step timestamps were not kept, so this is approximate. |
| Answers cut off at the token cap | Qwen 3 of 48, GLM 2 of 48 (scored as misses) |
| Testnet NEAR | 10.0000 at the start, 9.98796 after: about 0.012 spent |
| NEAR AI cost | Not read from the dashboard; the API has no usage endpoint. Not reported. |

## Questions, and how the answer keys were checked

The questions are about agronomy and livestock extension guidance: nitrogen timing, soil water terms, calf colostrum and heat stress, herbicide resistance, grain storage, soybean and wheat staging, soybean aphid thresholds.

- **Who wrote them:** a language model (`google/gemini-2.5-pro`, not one of the two models tested, and not told what the questions were for) wrote candidates from the text of 27 public university-extension and government web pages. The owner's coding agent then picked 48 and reworded some. No person wrote a question.
- **First attempt, discarded:** when the same model was asked for questions with source URLs of its own choosing, 1 of 84 citations checked out (43 returned 404). None of that batch was used.
- **Key check:** a script required each quoted sentence to appear verbatim in the fetched page text and each answer to appear in that sentence. 63 of 81 candidates passed. The 48 questions kept came from those.
- **Not done:** no person reviewed the keys or the wording. The source pages are public, so the facts are not private knowledge and the models may have seen them. Several questions say "according to" one source. `fuin tee-ground` was not run (it checks keys against `near/docs`, which these are not).

The scores therefore say how two models do on this particular question set, not how good either model is at agriculture.

## Verification

- **Owner's machine, in the repo:** both VERIFIED, keyless, exit 0, 53 s ([verify-output.txt](verify-output.txt)).
- **Owner's machine, clean environment:** a fresh venv with `pip install fuin` 1.1.0, empty environment, no key: both VERIFIED, 84 s.
- **Not done: a third-party verifier.** No other person has checked these certificates. The pilot asks for that; this entry does not have it.

The certificates here are byte-identical to the files `fuin evaluate` wrote:

| File | SHA-256 |
|---|---|
| [cert-pilot-1-qwen3.8-27b.json](cert-pilot-1-qwen3.8-27b.json) | `35c70c3200e39e00ac5b4cb9b96a24dfe3e81cd2550347b22eedee6d6634e918` |
| [cert-pilot-1-glm-5.3-flash.json](cert-pilot-1-glm-5.3-flash.json) | `4c24d1a0ce5663e497192474eaf7381dcfed39cc8ab33e2a4e61f0be5c351afd` |

## What broke

| What happened | Change |
|---|---|
| Each `tee-score` step printed `secret gist … was not deleted (unknown flag: --yes`, and the ciphertext gist stayed on the account. gh 2.45.0 has no `gist delete --yes`. The two gists were deleted by hand. | [PR #2](https://github.com/fexx301/fuin/pull/2) |
| `uv` is a pyenv shim on this machine and the repo's `.python-version` hid it. Worked around with `PYENV_VERSION`. | None needed |

`fuin check` also flagged one question that contained its own answer and three with no answer form; all were fixed before sealing. Nothing stopped `fuin evaluate`; it ran from seal to verified certificates in one invocation.

## What this pilot doesn't show

- **No real private suite.** The questions came from public pages through a model, so this tests the tool end to end on a second outside Linux machine, not the writing of a private benchmark from someone's own work.
- **No independent verifier** (see above).
- **Privacy:** the certificates name the testnet account `zkasuran-fuin.testnet` and, through the scorer's request URL, the GitHub account that hosted the gists (`zkasuran`).
- **No cost figure** for NEAR AI.
