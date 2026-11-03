# Round `near-dev-60-r1`, 2026-11-03

60 hidden NEAR-developer questions, each answer cited to a line of near/docs at commit e2d2ea17 (checked by `scripts/check_suite_sources.py`, 60/60). The suite is not in this repo; only the audited sample is revealed. Models: Qwen/Qwen3.8-27B and z-ai/glm-5.3-flash, both with `max_tokens` 4096, temperature 0, reasoning on (GLM cannot turn it off). Scorer `fuin-scorer-v2` (strict: the answer must be the number or term alone). Owner `fuin.testnet`; registry `registry.fuin.testnet` (locked: 0 access keys).

| Step | Transaction | Height |
|---|---|---|
| seal (n=60, D=6, k=23) | [GyvMjM5JvGKCaJR4PHdpTSp9shBFhWFNJ7z7Xr2tAaTF](https://testnet.nearblocks.io/txns/GyvMjM5JvGKCaJR4PHdpTSp9shBFhWFNJ7z7Xr2tAaTF) | 276079270 |
| commit_run Qwen3.8-27B, run 0: **17/60** | [9UTrvDF5hGPkNK8gVaGUEFV8wkUtcRYPzmtvvietrLYS](https://testnet.nearblocks.io/txns/9UTrvDF5hGPkNK8gVaGUEFV8wkUtcRYPzmtvvietrLYS) | 276088479 |
| commit_run glm-5.3-flash, run 0: **25/60** | [Dn2wWnsX2aAyXKZvu12LDXScEV5EMToxYQ2k2AMggZxL](https://testnet.nearblocks.io/txns/Dn2wWnsX2aAyXKZvu12LDXScEV5EMToxYQ2k2AMggZxL) | 276088494 |
| close_round | [6vqe9Q8q3u4WDrhhQwPRB4taPp4k8iKL1zB9sHiWS8GL](https://testnet.nearblocks.io/txns/6vqe9Q8q3u4WDrhhQwPRB4taPp4k8iKL1zB9sHiWS8GL) | 276088507 |

Seed block 276088509 (first final block ≥ close+2). Both certificates reveal the same 23 items.

| Model | Committed score | Answers cut off at the 4096-token cap (scored 0) | Owner-reported retries |
|---|---|---|---|
| Qwen3.8-27B | 17/60 | 17 | 1 |
| glm-5.3-flash | 25/60 | 21 | 1 |

Read the scores with the cap counts: a cut-off answer scores 0 whatever the model knew. The cap was sealed before the run and applies to both models.

**Disclosure:** 23 items are revealed by the audit. One more unrevealed item (index 17) cites the same docs line as revealed items 16 and 18, and its answer follows from theirs, so it is counted as disclosed: **24 disclosed, 36 hidden**. The thin-path questions, whose facts recur in this suite, are withheld from the repo (see `../2026-11-03-thin-path/`).

`verify-output.txt`: `env -u NEARAI_API_KEY uv run fuin verify …` on both certificates → VERIFIED, exit 0.
