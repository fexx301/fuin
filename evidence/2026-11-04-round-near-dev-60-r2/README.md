# Round `near-dev-60-r2`, 2026-11-03/04

A second, independent hidden suite: 60 new questions with exact answers cited to near/docs at commit e2d2ea17. One question per cited line; no line and no fact shared with round 1 (checked by `scripts/check_suite_sources.py`, the leak guard and by hand). Mostly NEAR standards, SDK and RPC names. Models: Qwen/Qwen3.8-27B and z-ai/glm-5.3-flash, reasoning on, `max_tokens` **8192**, temperature 0, scorer `fuin-scorer-v2`. The round was sealed on the locked registry.

| Step | Transaction | Height |
|---|---|---|
| seal (n=60, D=6, k=23) | [6HF7FRRqWzskxWt1c2ydV9BoVW2yZzVE6QUkCxVvAYBq](https://testnet.nearblocks.io/txns/6HF7FRRqWzskxWt1c2ydV9BoVW2yZzVE6QUkCxVvAYBq) | 276092667 |
| commit_run Qwen3.8-27B, run 0: **17/60** | [2uWT68HnpUHdAqKz5gnwNC8H16tQxehPKLzB416coeUM](https://testnet.nearblocks.io/txns/2uWT68HnpUHdAqKz5gnwNC8H16tQxehPKLzB416coeUM) | 276156923 |
| commit_run glm-5.3-flash, run 0: **32/60** | [Hdzdmzay3MEK65CQpko7R42RFnWzNrDpdXCiGSpReYSL](https://testnet.nearblocks.io/txns/Hdzdmzay3MEK65CQpko7R42RFnWzNrDpdXCiGSpReYSL) | 276156936 |
| close_round | [9kb3RC1t4ckDhXpZnYc6jsFSCf3rhHRViaCkSDrVCHtX](https://testnet.nearblocks.io/txns/9kb3RC1t4ckDhXpZnYc6jsFSCf3rhHRViaCkSDrVCHtX) | 276156949 |

| Model | Committed | Revealed: correct / wrong / format / cut off | Whole run: cut off (owner-reported) | Owner-reported retries |
|---|---|---|---|---|
| glm-5.3-flash | 32/60 | 13 / 4 / 2 / 4 | 6/60 | 0 |
| Qwen3.8-27B | 17/60 | 7 / 13 / 0 / 3 | 7/60 | 10 |

**The run was interrupted.** The Mac lost network overnight (DNS failures, probably sleep). Qwen stopped at item 32 after recording failed attempts, and GLM's preflight failed until the network returned. `fuin run` resumed from the last saved item with the original preflight. All 10 failed attempts are in Qwen's certificate (`run.evidence.attempt_log`), and the verifier prints the count. The resumed run used `caffeinate`.

One Qwen preflight attempt before the interruption was refused: the gateway offered a candidate whose configuration is not in policy v3, and `fuin run` stops on that. The next attempt drew the accepted configuration. That candidate's report wasn't saved, so its configuration is unknown; if it recurs, diff it as was done for GLM's second host.

Disclosure: 23 directly revealed, 37 hidden. No cited line is shared, so there's no known indirect disclosure. `verify-output.txt`: both certificates VERIFIED with no API key, exit 0.
