# Round `near-dev-300-r3`, 2026-11-04

A third, independent hidden suite, five times larger than the earlier rounds. It has 300 new questions with exact answers cited to near/docs at commit e2d2ea17, drawn from 102 docs files. Each cited line has one question, and no cited line is shared with round 1 or 2. This was checked by `scripts/check_suite_sources.py`, the leak guard and by hand. Answers that coincide with earlier rounds (small numbers, common terms) are different facts. Before sealing, `fuin check` flagged nine questions whose wording gave the answer away, and they were rewritten. The settings match round 2: Qwen/Qwen3.8-27B and z-ai/glm-5.3-flash with reasoning on, `max_tokens` **8192**, temperature 0 and scorer `fuin-scorer-v2`. The round was sealed on the locked registry.

| Step | Transaction | Height |
|---|---|---|
| seal (n=300, D=30, k=28) | [HoUbqUD2n6RdsAgPoBPwvTHR62icAxwDM7TVK37JiEYp](https://testnet.nearblocks.io/txns/HoUbqUD2n6RdsAgPoBPwvTHR62icAxwDM7TVK37JiEYp) | 276216186 |
| commit_run Qwen3.8-27B, run 0: **77/300** | [2MqaZxhncAewTx7cCPkbMpiKhiZNzPrx3EY46YFpNq9N](https://testnet.nearblocks.io/txns/2MqaZxhncAewTx7cCPkbMpiKhiZNzPrx3EY46YFpNq9N) | 276244711 |
| commit_run glm-5.3-flash, run 0: **122/300** | [EkDw99GvrhJ3x4Auo66zcSNDYGtFwJhSRzu96e4TdaRG](https://testnet.nearblocks.io/txns/EkDw99GvrhJ3x4Auo66zcSNDYGtFwJhSRzu96e4TdaRG) | 276244725 |
| close_round | [7RxrYV2BCKMorup43aQPatQqU5PmHQ4dM8B7hAzdBjcm](https://testnet.nearblocks.io/txns/7RxrYV2BCKMorup43aQPatQqU5PmHQ4dM8B7hAzdBjcm) | 276244738 |

| Model | Committed | Revealed: correct / wrong / format / cut off | Whole run: cut off (owner-reported) | Owner-reported failed attempts |
|---|---|---|---|---|
| glm-5.3-flash | 122/300 (40.7%) | 10 / 14 / 0 / 4 | 72/300 | 0 |
| Qwen3.8-27B | 77/300 (25.7%) | 9 / 17 / 0 / 2 | 54/300 | 92 |

**Detection power for this audit:** 28 of 300 items are revealed, which is 95.49% detection power for 30 or more incorrect item scores. With 60 questions, 23 of 60 had to be revealed for the same guarantee. Here 272 of 300 (91%) stay hidden, against 37 of 60 (62%).

**Qwen's 92 failed attempts, all disclosed in its certificate (`run.evidence.attempt_log`):**
- **40 read timeouts.** The client gave up after 180 s. Long reasoning answers under 4–8 parallel requests took longer, so they were abandoned and re-asked. The timeout is now 1200 s (entry commit `836c00a`).
- **40 `RemoteDisconnected`.** The gateway closed long-running connections without a response. Each was retried.
- **10 discarded.** These answers completed after an earlier item in the same parallel window failed. They were thrown away and re-asked so that rows stay in index order.
- **2 abandoned.** Two operator restarts, one to switch from batch to rolling-window parallelism and one to switch to the network-patient runner (`scripts/run_round.sh`). The requests in flight at those moments were dropped.

None of these is a scored answer. Each committed row is the first answer that came back signed for its item, after earlier attempts failed. The verifier prints the count, and it is owner-reported.

**The preflight was refused before policy v4.** As the run started, NEAR had redeployed Qwen with a new compose-manager launcher. `fuin run` refused the unrecognised configuration (`measurement_unapproved`) until it was reviewed and added as attestation policy v4 (`../2026-11-04-qwen-redeploy/`). The preflight that was eventually accepted drew the v3 configuration `5e513dbd…`, and GLM's drew `5f7ebd85…`.

**Disclosure:** 28 directly revealed per model, from the same sample, and 272 hidden. No cited line is shared with earlier rounds, so there is no known indirect disclosure. `verify-output.txt` and `verify.jsonl` show both certificates VERIFIED with no API key, exit 0.

**Cost:** about 0.92 M output tokens for Qwen and 0.78 M for GLM, roughly $1.6 at list prices, plus the discarded attempts.
