# Round 8: asked once on the second asker, 40 questions, three models, 2026-11-12

Blind review 5 named this as a weakness: the strongest guarantee, that an owner can't re-ask within a round, rested on one 37-question, one-model certificate from an asker with a known miscount. Round 8 is a counted asked-once round on the second, locked asker (`edb89964…` in `ask2.fuin.testnet/asker`; see [its evidence](../2026-11-11-asker-v2/README.md)), with three models.

**Result.** VERIFIED keyless by both verifiers ([verify-output.txt](verify-output.txt), [verify.jsonl](verify.jsonl); the browser verifier in Node gives VERIFIED for all three).

| Model | Correct | 95% interval | Asked | Commit | Aggregate (OutLayer task) |
|---|---|---|---|---|---|
| deepseek-ai/DeepSeek-V4.1-Flash-1017 | **18/40** | 31–60% | 40 asks, 1 retried (a single draw per item could differ by at most 1) | [`Go6MwTCeFY…`](https://testnet.nearblocks.io/txns/Go6MwTCeFYJM2y26JDd5iQGkrc47zSsRGxkjzBWgHFuo) | [`6T1n2puuny…`](https://testnet.nearblocks.io/txns/6T1n2puunywwwFKJB24JFxDX4HNbaux5iq8qr8nRjkTd) (75005) |
| z-ai/glm-5.3-flash | **16/40** | 26–55% | 40 asks, none retried | [`253B9JfLeL…`](https://testnet.nearblocks.io/txns/253B9JfLeLexyhXSjbtBN7AsxFPr7ofwEpnQ8ArCdx4E) | [`HgTLypbQPo…`](https://testnet.nearblocks.io/txns/HgTLypbQPoen5ySJHcZs3vQH7Cc5rMYvBywAdxdes6tm) (75708) |
| Qwen/Qwen3.6-35B-A3B-FP8 | **7/40** | 9–32% | 40 asks, none retried | [`Euk6GoQn6x…`](https://testnet.nearblocks.io/txns/Euk6GoQn6xFmWoSXqrG76tCoKmr8N8jSAoTLsiLVQ6JP) | [`DdjeBnS6D6…`](https://testnet.nearblocks.io/txns/DdjeBnS6D6Nxz2kHG1vzPurSuE13XoxptB86D24Wgjtb) (75907) |

DeepSeek and GLM are inside each other's interval: on 40 questions this round doesn't separate them. Read the scores as a demonstration of the protocol, as the README says of every round.

- **Seal:** [`8rcmM3B1CX…`](https://testnet.nearblocks.io/txns/8rcmM3B1CXXChvxsm69u7NJWUtJR1HiV2mq9Fm3V5ZRd) at height 277361676, after the asker's lock (Nov 11).
- **Close:** [`Dary22sCM1…`](https://testnet.nearblocks.io/txns/Dary22sCM1d8UcJtHVFXteyxN83aR2sdchXh2brjYFap) at 277372136.
- **Asked-check** (every request rebuilt with the seal block's hash equals the signed one): tasks 75017, 75712 and 75911, by scorer `b301d22b…`.
- **Settings:** temperature 0, a cap of 4,096 tokens, end-to-end encrypted (request template v3), as in round 7. Not comparable with the 8,192-token rounds.
- **Retried ask:** DeepSeek's item 37. Its first request outlived NEAR's yield window, so no answer had left the enclave; the second was asked and scored 0. The certificate prints "1 retried ask".
- **Owner-reported failed attempts:** 2 for DeepSeek (items 32 and 37), 0 for the others. Item 32's first request failed on OutLayer before the enclave claimed an attempt, so the enclave's count for it is 1 and it isn't a retried ask.
- **Answer keys:** 40/40 appear in their cited line of near/docs at `e2d2ea17`, checked in the enclave by scorer `b301d22b…` ([`BnHVMUcvdo…`](https://testnet.nearblocks.io/txns/BnHVMUcvdoAhwXutXz4M9uFCzHMpyWhxtPyN6jTZhBXo), task 75958).
- **Suite:** 40 new questions, one per cited line, from 34 files. No cited line and no answer is shared with rounds 1–7. All of them stay private. Like the earlier suites, they were written by the author's coding agent from the docs, not by a domain expert.
- **Hosting:** the encrypted round sat on a secret gist while the asker fetched it, then was deleted; `gh gist list` shows none left.
- **How it was run:** one `fuin evaluate … --ask --e2ee --max-spend 3` command, rerun after each stop below.

## Which models, and why

An asked-once call has to finish inside NEAR's yield window of about 125 s (see [round 7](../2026-11-08-round-near-dev-37-r7/README.md)). Before sealing, each certifiable model answered eight public questions (round 3's revealed ones) at 4,096 tokens, called directly, not through the enclave:

| Model | Slowest of 8 | Median |
|---|---|---|
| Qwen/Qwen3-VL-30B-A3B-Instruct | 2 s | 2 s |
| Qwen/Qwen3.6-35B-A3B-FP8 | 10 s | 8 s |
| z-ai/glm-5.3-flash | 37 s | 8 s |
| deepseek-ai/DeepSeek-V4.1-Flash-1017 | 84 s | 17 s |
| deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated | 81 s | 29 s |
| Qwen/Qwen3.8-27B | 182 s | 96 s |

GLM had been too slow for round 7 on Nov 7; NEAR has redeployed it since. Qwen3.8-27B doesn't fit and was left out. Three models from three families were sealed: DeepSeek-V4.1-Flash, GLM-5.3-flash and Qwen3.6-35B. The first timing run lost most of its calls to errors and was repeated for those models; Qwen3.8-27B's abliterated version wasn't measured cleanly.

## What interrupted it

- **NEAR redeployed GLM during the round.** After DeepSeek's run was committed, GLM's preflight stopped with `measurement_unapproved`, before any question was asked. Policy v11 was reviewed and accepted ([its note](../2026-11-12-attestation-policy-v11/README.md)), and the same command carried on. DeepSeek's certificate records policy v10; the other two record v11.
- **Three signing failures** from the `near` CLI ("not signed"), two between Qwen3.6's asks and one at the close. Each time nothing had been sent; the same command resumed, and no question was asked twice because of them.

## What this round doesn't show

- **Only models that answer fast enough.** Qwen3.8-27B, which earlier rounds ran, can't take part at this cap.
- **Sealing the same questions again as another round** is still possible; rounds aren't linked.
- **What the asks cost.** An asked-once round's answers never leave the enclave, so their token counts aren't visible to the owner. The bound printed before the seal was $0.46 for the round.
