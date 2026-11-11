# A shareable report for your own certificates, 2026-11-11

A reviewer asked for a report someone else can read and check: model scores, comparable settings, verification status, retries, unreadable answers and links to the certificates, with the page's comparison and uncertainty applied to the user's own results, and an explanation when two results aren't comparable.

## What changed

`fuin report CERT… --out DIR` verifies each certificate (or takes recorded `fuin verify --json` lines with `--recorded`, matched by the certificate's sha256) and writes:

- `DIR/report.html`: one self-contained page, light and dark, no scripts;
- `DIR/report.json`: the same content as data;
- `DIR/certs/`: byte-for-byte copies of the certificates, so the folder can be sent as it is.

How it decides what to show:

- **Only VERIFIED results are compared.** Anything else is listed apart, with its code.
- **A group is one sealed round with one set of model settings** (sealed set, kind of round, number of questions, token cap, temperature, request template, scorer). Scores are compared inside a group only. For every pair of groups the report says what differs.
- **Uncertainty** is the 95% Wilson interval the results page uses (`site/app.js`); a test checks the two give the same numbers. The report says whether two models' intervals overlap.
- **Retries and unreadable answers** are shown only where a TEE counted them. Otherwise the cell says "not attested", never 0. The owner's own log of failed attempts is shown as "not verifiable".
- **No private question is shown.** Nothing from a certificate's revealed sample is rendered, and every string taken from a certificate is escaped.
- **Limits** are the verifier's own, word for word.

## Live run

[report/report.html](report/report.html) was made from this session's six rehearsal certificates, each verified at that moment with no API key:

| Group | Kind | Result |
|---|---|---|
| eval-sampled-1 | sampled | Qwen3.8-27B 3/3, GLM-5.3-Flash 3/3: intervals overlap |
| eval-private-1 | TEE-scored | Qwen3.8-27B 3/3; 0 unreadable answers, counted in the TEE |
| eval-asked-1 | asked once | DeepSeek-V4.1-Flash 3/3; 0 retried asks |
| ask2-rehearsal-2 | asked once | DeepSeek-V4.1-Flash 2/3; 1 retried ask, counted in the TEE |
| (not verified) | asked once | ask2-rehearsal-1: REFUSED `tee_asked_unlocked`, left out of every comparison |

Three questions per round is far too few to rank models; the intervals in the report say so.

## A reader checks it without the questions

From the report folder alone, with the published package and no key ([independent-verify.txt](independent-verify.txt)):

```sh
cd report && uvx --from fuin==1.0.3 fuin verify certs/*.json
```

It prints VERIFIED for five certificates and REFUSED `tee_asked_unlocked` for the sixth, the same verdicts as the report.

## Tests

`tests/test_report.py` runs offline on the 20 published certificates with their recorded results: seven groups, 21 pairs explained, round 7's retry shown as counted in the TEE, no revealed question or answer in the HTML or JSON, certificate text escaped, an unverified result kept out of comparisons, and a file that isn't a certificate listed instead of crashing.

## What this doesn't show

- The report doesn't judge the questions or the answer keys: a private set's quality is the owner's claim.
- Two rounds that happen to hold the same questions are still separate groups, because their certificates can't show it.
- A sampled round's certificate carries its own revealed sample. The report shows none of it, but the copied certificate does.
