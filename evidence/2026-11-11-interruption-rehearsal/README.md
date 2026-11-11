# Interrupting seal, commit and close on testnet, 2026-11-11

A reviewer asked that the whole owner workflow recover after an interruption, including the case where a transaction succeeds but the process exits before saving its receipt. Until now only `fuin run` and `fuin ask` resumed; an interrupted `fuin seal` had to be abandoned for a new id, and a second `fuin commit` would have published a duplicate run.

## What changed

Owner transactions are now signed first and sent second (`near.sign`, `near.deliver`). A transaction's hash is the sha256 of its unsigned bytes, so it is saved in private state, with the signed bytes, before anything reaches the chain. A rerun finds that pending transaction and looks it up. If the chain doesn't have it, the same signed bytes are sent again, and the same bytes can execute at most once. A new transaction is signed only when the pending one can no longer execute and the registry doesn't already hold the step's effect (`owner._registry_tx`).

- `fuin seal`, run again with the same arguments, finishes an interrupted seal with the salts and nonces saved then. A different suite, policy or owner is refused.
- `fuin commit` and `fuin close` refuse a second run of a finished step, and never send a commit the registry already holds.
- `fuin ask` saves each signed ask before sending it. A rerun waits for an ask still in flight instead of sending another, which would be a second model call. A network failure keeps the ask in flight; only a failed execution starts a new, counted attempt.

## Live rehearsal

Two throwaway rounds of two arithmetic questions on `Qwen/Qwen3.8-27B`, owner `fuin.testnet`. Each step was killed with `os._exit` at the named point, then the same command was run again.

| Step | Killed | Rerun | Transaction |
|---|---|---|---|
| seal (round 1) | right after the transaction was sent | "resuming with the transaction signed earlier"; same salts and nonces | [`GDAJDYVnAg…`](https://testnet.nearblocks.io/txns/GDAJDYVnAgu24nbvu9JbjqDH3ibDn6JA35VatdnR438U) |
| commit (round 1) | after it executed, before the receipt was saved | same transaction; `Committed … run 0`; a third `fuin commit` is refused as already committed | [`EogKyeGGhQ…`](https://testnet.nearblocks.io/txns/EogKyeGGhQuUqqmGcAvnMSBMQK1ZaUd6EM7eWuccc9yp) |
| close (round 1) | after signing, before sending | the saved signed bytes were sent | [`7RaRJEa4fM…`](https://testnet.nearblocks.io/txns/7RaRJEa4fMTdnzmkWWK14TToQZDbGTSuRqEoYLKkPuhL) |

Afterwards the registry holds one run for the model (run 0), one seal and one close. No model call was repeated. Round 1's certificate VERIFIES: [cert-resume-rehearsal-1-qwen3.8-27b.json](cert-resume-rehearsal-1-qwen3.8-27b.json).

Round 2 ran the same steps uninterrupted through the command line as a TEE-scored round, to exercise the changed OutLayer path (sign, send, wait, collect): seal [`BcsUjCtZSL…`](https://testnet.nearblocks.io/txns/BcsUjCtZSLit97EQEEDtH1WKZqftvi8kVeBzmsvsi4DJ), commit [`5ipbZ1WMUv…`](https://testnet.nearblocks.io/txns/5ipbZ1WMUvGEJFZ8z27CrbBL99gitoNU5Mej95SkmvgG), close [`C3eT6Sf4tq…`](https://testnet.nearblocks.io/txns/C3eT6Sf4tqqo5EvzQHTgbQniX48fV8QnVEwG1i2Ms2c1), TEE score [`BijiUu4bsm…`](https://testnet.nearblocks.io/txns/BijiUu4bsmeYPxwU7sxaeRWVXuotzgsg17F1rBQGkQnp). Its certificate VERIFIES with the TEE score: [cert-resume-rehearsal-2-qwen3.8-27b.json](cert-resume-rehearsal-2-qwen3.8-27b.json).

## Tests

`tests/test_resume.py` (18 tests) kills seal, commit and close at four points each (after signing, before sending, after sending, before the receipt is saved) against a registry that executes each signed transaction once, and checks one seal, one run, one close, the original salts and nonces, and that a sent transaction is reused rather than signed again. It also covers an ask interrupted in flight, a network failure during an ask, and a failed ask. Removing the line that saves the pending transaction makes 7 of them fail.

## Not covered

- An interrupted `tee-score`, `tee-ground`, `ask-check` or aggregate is simply run again: it repeats an OutLayer task, costs testnet gas, and makes no model call. If the process is killed outright, the secret gist holding that task's encrypted input isn't deleted; delete it by hand (`gh gist list`).
- Private state written before this change has no pending transactions. If such a state lost a receipt, the commands stop and say the registry already holds the record, rather than sending a duplicate.
- The in-flight ask wasn't killed live: that needs the locked asker and a new round. It is covered by the tests.
