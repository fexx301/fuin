# A cost bound, a spending limit and measured usage, 2026-11-11

A reviewer asked for the expected cost before a round starts, with inference, token caps, retry allowances and chain costs shown separately; a spending limit that accounts for concurrent requests and retries; and a clear line between estimates and measured usage. Done when a user can understand the cost before starting, and reaching the limit leaves a resumable round.

## What changed

Three things, kept apart in the code (`src/fuin/cost.py`) and in what is printed:

- **A bound, before the seal.** `fuin check` and `fuin evaluate` print the most the model calls can cost: every answer using its whole token cap, at NEAR AI Cloud's public catalog prices read at that moment. It is labelled a bound, not a forecast and not a bill, and it points to the measured table in [docs/COSTS-AND-DEPENDENCIES.md](../../docs/COSTS-AND-DEPENDENCIES.md). Chain and enclave fees are a separate line, in testnet NEAR.
- **A limit, while it runs.** `--max-spend USD` on `fuin evaluate`, `run` and `ask`. A call starts only if the round's spend so far plus the bound of every call in flight stays within the limit. A finished call counts at its measured tokens. A failed call stays at its bound, because NEAR AI can bill a call that failed or was abandoned. An answer that comes back but can't be kept (its signature is missing or wrong) is logged as an attempt and stays at its bound too, and so does an answer that carries no token count. Spend is recomputed from saved state at every start, so running the command again doesn't reset it. A stop at the limit is not written to the attempt log.
- **Measured usage, afterwards.** `fuin cost --id ID`, and the last lines of `fuin evaluate`: token counts from the signed answers. The dollars are those tokens at the catalog price read at that moment, so it is a computation; NEAR AI's dashboard is the bill.

The retry allowance is stated as it is: a question gets up to three attempts each time the command runs, and a rerun allows three more, so only the limit caps the total.

The per-call bound is the question's length in bytes plus 64 input tokens, plus the whole cap of output tokens. In the 2,312 answers saved from every round so far, prompt tokens were never more than the question's bytes plus 23, and no answer exceeded its cap. `tests/test_cost.py` re-checks that on the published certificates' revealed answers.

## Live run

A fresh clone of the branch, six public questions, `Qwen/Qwen3.8-27B`, cap 4,096, four questions in flight at once, owner `fuin.testnet`.

1. **`fuin evaluate … --parallel 4 --max-spend 0.012`** ([cost-limit-1a.txt](cost-limit-1a.txt)). The bound for one call is about $0.0055, so two calls in flight fit and a third doesn't. Two answers came back, then: "spending limit $0.01 reached: $0.0111 is spent or reserved, so item 2 was not sent. Nothing is lost: run the same command again with a higher --max-spend". `fuin status` showed 2/6 answered, resumable, 0 retries logged.
2. **The same command with `--max-spend 0.05`** ([cost-limit-1b.txt](cost-limit-1b.txt)). It resumed, asked only the four remaining questions, committed, closed, revealed and verified: **VERIFIED**, 6/6. It ended with "6 answers, 401 prompt + 252 completion tokens = under $0.01".

(The message shows the limit of 0.012 as "$0.01": it was rounded for display at that commit, and has printed exactly as given since.)

The bound printed before the seal was "at most $0.03 if all 6 answers used the whole 4,096-token cap". The measured use was 252 completion tokens, about 1% of that, which is why the bound is not called a forecast.

**An asked-once round** (three public questions, `deepseek-ai/DeepSeek-V4.1-Flash-1017`, cap 4,096, at commit `45af8d8`). The owner never sees an enclave-made call's usage, so each ask counts at its bound, about $0.005:

3. **`fuin evaluate … --ask --e2ee --max-spend 0.008`** ([cost-asked-1a.txt](cost-asked-1a.txt)). One ask fits, two don't. After item 0: "spending limit $0.008 reached: $0.0050 spent, so item 1's ask was not sent."
4. **The same command with `--max-spend 0.05`** ([cost-asked-1b.txt](cost-asked-1b.txt)). It asked items 1 and 2 only, then aggregated, committed, closed and verified: **VERIFIED**, 3/3, 0 retried asks. Its measured line reads "not available, because an asked-once round's answers never leave the enclave; 3 asks counted by the TEE".

Both certificates are in this folder. They are rehearsals on public questions, not counted rounds.

## Two corrections from a reviewer (the same day, after 1.2.0)

A reviewer checked commit `2f992b6` and found two faults in the limit's bookkeeping. Both were real.

1. **A killed run forgot a call that may have been billed.** The reservation lived only in memory, so a run that died between sending a call and saving its answer started again with that call uncounted. In the reviewer's simulation six interrupted attempts passed the limit while recorded spend stayed at zero. Now each call is noted in the round's saved state before it is sent. A run that finds such a note when it starts records it as a failed attempt ("interrupted: the run stopped before this call's answer was saved"), counts it at its bound, and the certificate's count of failed attempts includes it.
2. **A settlement recorded the smaller of the actual cost and the amount held.** It now records the actual cost in full, and if that takes the round past the limit, every later call is refused.

The reviewer's two tests pass unchanged against the fix, and are in `tests/test_cost.py` with two more (a call is on record while in flight and cleared with its answer; an unresolved call counts at its bound).

**Live** (six public questions, `Qwen/Qwen3.8-27B`, commit `a0bb742`): the run was killed with `kill -9` at the moment its saved state showed a call in flight ([kill-limit-1a.txt](kill-limit-1a.txt)). The state then held no answer and one call in flight. The same command again ([kill-limit-1b.txt](kill-limit-1b.txt)) recorded that call as an interrupted attempt, asked all six questions, and ended **VERIFIED** with "owner-reported failed inference attempts: 1" and "1 failed attempt left no token count and may have been billed".

## Tests

`tests/test_cost.py`: catalog prices parse to the dollars-per-million in the COSTS table; with four calls in flight and three injected failures, what NEAR AI could have billed never passes the limit, the stop leaves no entry in the attempt log, and a higher limit finishes with every question answered exactly once; thirty reruns at the same limit can't push spend past it; with a limit set and no readable price, nothing is sent; an asked-once round's asks are each counted once; a discarded answer is logged and still counted after ten reruns; an answer with no token count is counted at its bound.

## What this doesn't show

- **What an asked-once round really used.** Its answers never leave the enclave, so the limit counts every ask at its bound and the measured line says "not available".
- **A bill.** The limit is kept on the owner's machine from token counts and catalog prices. A call that was in flight when a run was killed is counted at its bound, not at what it really used, and prices can change between the estimate and the invoice.
- **A forecast.** Fūin doesn't predict how many tokens your questions will use.
