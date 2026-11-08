# Round 7: each question asked once, inside the enclave, 37 questions, 2026-11-08

Rounds 1–6 left one gap a certificate couldn't close (blind review 3, weakness c1). The owner made the model calls, and NEAR AI Cloud's temperature-0 serving isn't deterministic, so an owner could re-send a sealed request and commit the best signed answer: every signature stays valid. In round 7 the owner makes no model call. Each question is asked by the **asker** (`ask/`), an OutLayer enclave component in a project nobody can change, and it refuses a second ask of the same question.

**How it works.**
- **The asker runs as the project `ask.fuin.testnet/asker`.** The owner account `ask.fuin.testnet` had its only key deleted before the round (tx `6krbzCT1Lb9EGTRqxqviAMzaBNNxRU7hGr9BhuBXMZDe`), so the project can't be deleted, re-versioned or transferred. Its only version is the asker build `dbbb286b…`, which rebuilds byte for byte with `ask/build-docker.sh`.
- **For each item, the asker:**
  1. records the ask in sealed project storage, named by the sealed round (benchmark root, model, index), never by the caller;
  2. builds the sealed request (template v3: the question encrypted to the model's attested key, the nonce bound to the seal block);
  3. calls NEAR AI with the owner's key, which the owner stored as an OutLayer secret themselves;
  4. checks the `provider_tee` signature and scores the answer with the scorer's own code (`fuin_tee`);
  5. records it final.

  A final record is re-emitted, never re-asked. A record still pending (no answer ever left the enclave) may be retried, and every retry is counted.
- **No question, answer or response body leaves the enclave.** The owner gets each answer's hashes, score and signature. A last task (`aggregate`) reads every final record and attests the run's roots and total, exactly as the TEE scorer does.
- **`fuin verify` checks:**
  - that the aggregate came from the sealed asker in the sealed project and equals the committed run;
  - and, on the archival chain at the seal block, that the project's owner had no keys and no code, and that the asker was the project's only version.

**Result.** VERIFIED keyless by both verifiers (`verify-output.txt`, `verify.jsonl`; the browser verifier in Node gives VERIFIED too).

| Model | Correct | 95% interval | Asked | Commit | Aggregate (OutLayer task) |
|---|---|---|---|---|---|
| deepseek-ai/DeepSeek-V4.1-Flash-1017 | **19/37** | 36–67% | 37 asks, 1 retried | `7EDzYgZmB6KtxpdfUAUm5f75LEx32b1LpL5AXhumWpLg` | `CaERs6ok2Ud2VCcpcwUKeX7mVaq3YGRi6aTp1hmoWMGj` (27207) |

- **Seal:** `7NmmAkLeQzc7LRezVYp5tD4Y1irhxaeVA5Fd4r4izHoa` at height 276695392, after the lock.
- **Close:** `14BZmP5vL83jQHJErjrvzViszVVYz1qgGnBBxCXYZwZY` at 276697978.
- **Settings:** temperature 0, a cap of **4,096 tokens**, unlike the 8,192 of rounds 4–6. The cap is what fits NEAR's yield window (below), so round 7's score isn't comparable with round 6's.
- **Retried ask:** item 31. Its first two requests outlived NEAR's yield window ("Execution promise failed … Refunded"), so no answer had left the enclave. The third was asked and scored 0, and the certificate prints "1 retried ask".
- **Answer keys:** 37/37 appear in their cited line of near/docs at `e2d2ea17`, checked in the enclave by scorer v8 (`bb0d9a5d…`; tx `AAchzbzhpUWcE3d45f7p2fAMDTqA4b1J3ws25c8cTBYr`, task 27212).
- **Suite:** 37 new questions, one per cited line, from 31 files, none used by rounds 1–6. All of them stay private.
- **Hosting:** the encrypted round sat on a secret gist while the asker fetched it, then was deleted. One gist was left behind by a stopped run and deleted by hand; `gh gist list` shows none left.

**Why 4,096 tokens.** The asker's call has to finish inside one OutLayer task, and three limits apply (measured, `spike/ask/README.md` on branch `spike/enclave-ask`):
1. OutLayer cuts outbound requests at 30 s unless the component's manifest declares a longer `timeout_secs`. The asker declares 170 s for `cloud-api.near.ai`, compiled into the attested build.
2. Streaming isn't a way around it: a streamed answer gets only a `gateway` signature, not `provider_tee`.
3. NEAR's yield/resume window ends an on-chain request after about 125 s.

Writing 4,096 tokens took DeepSeek-V4.1-Flash 52 s inside the enclave. 8,192 tokens did not fit, and Qwen3.8 and GLM were too slow even at 4,096, so this round has one model.

**Before the round.**
- **Spike** (branch `spike/enclave-ask`): ask-once in project storage (tasks 26845–26847), the enclave-made call (26866) and the timing tests.
- **Rehearsals** `ask-rehearsal-1` to `-3` (3 public questions, the unlocked spike project): each passed ask, aggregate, commit and certificate. Both verifiers REFUSED their certificates `tee_asked_unlocked`, as designed, because that project's owner has keys. Two bugs were found and fixed:
  1. the asker's round-key label differed from the owner's;
  2. the remote check didn't accept a project's version as the executed build.

  A third bug was caught on round 7's first ask: the in-enclave key was cached per build rather than per (build, project). It failed before any record was written and was fixed (`fuin/asker.py`).

**Limits printed with this certificate:**
- the ask-once guarantee rests on OutLayer's storage not being rolled back by its operator, as every TEE result rests on Intel TDX and OutLayer;
- separate rounds aren't linked, so an owner could seal the same questions twice and publish the better round.
