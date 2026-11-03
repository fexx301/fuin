# Thin path, 2026-11-03 (one model, 5 items, all revealed)

Suite `suites/thin-5.jsonl`: 5 NEAR-developer questions, answers pinned to near/docs commit e2d2ea17. Owner `fuin.testnet`, registry `registry.fuin.testnet`.

| Step | Transaction | Execution height |
|---|---|---|
| seal | [5tUABH68SfnZrYgtVVd53TmQSY9QmWm6of5GsuYF336B](https://testnet.nearblocks.io/txns/5tUABH68SfnZrYgtVVd53TmQSY9QmWm6of5GsuYF336B) | 276073537 |
| commit_run (Qwen/Qwen3.8-27B, run 0, 2/5) | [3mF17GaExqBrhDLkAt1vJBgM3Z2DfUQemfzgRw7R8BbR](https://testnet.nearblocks.io/txns/3mF17GaExqBrhDLkAt1vJBgM3Z2DfUQemfzgRw7R8BbR) | 276073620 |
| close_round | [8e1QCYLDRgFqdf3xDkrvzr3vhqB6Lv5AcJRrAG8F7ZX4](https://testnet.nearblocks.io/txns/8e1QCYLDRgFqdf3xDkrvzr3vhqB6Lv5AcJRrAG8F7ZX4) | 276073646 |

Seed block 276073648. `env -u NEARAI_API_KEY uv run fuin verify …` output: `verify-output.txt` (real cert VERIFIED; `examples/tampered/edited-answer.json` REFUSED `signature_text_mismatch`).

Not shown by this run: keeping part of the set hidden (all 5 revealed), a second model, the other refusal fixtures. The registry's full-access key was still held at the time, so its code could have been replaced.
