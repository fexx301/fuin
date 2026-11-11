# Asker v2: every attempt counted when asks overlap, 2026-11-11

Blind review 4 found that the first asker (`dbbb286b…`, round 7) could record one retry fewer than happened when two asks of the same item overlapped by milliseconds ([its note](../2026-11-10-blind-review-4/README.md)). A locked asker can't be patched, so the fix is a second locked asker. Round 7 and its certificate are unchanged and still verify against the first.

## What changed

`ask/src/record.rs` holds the record protocol. An ask claims the next attempt under its own random id, reads the record back, and calls the model only if the record is, byte for byte, its own claim. It writes the final answer with a compare-and-set from that claim. So:

- the attempt count never goes down;
- every model call belongs to its own confirmed claim, so the count is never below the number of model calls;
- at most one ask finalises, and the final record is never rewritten.

A claim that never reaches the model is still counted: the count can overstate, never understate.

## Tests

`cargo test` in `ask/` runs every interleaving of two and of three overlapping asks, asks killed after each step, and restarts, against a store with compare-and-set. The same tests run against the first asker's logic find the undercount. `scripts/review.sh` runs them and rebuilds every pinned asker at its recorded commit.

## Build and lock

| Step | Result |
|---|---|
| Build | `ask/build-docker.sh 94ede9f` gives `edb89964e4517282b7d181ebaefe370eb1748722734361a29ca5d06e21980cec` (three builds, the same bytes) |
| Account | `ask2.fuin.testnet` created: [`BDkTHEy8rj…`](https://testnet.nearblocks.io/txns/BDkTHEy8rj6QypAjAK95o4sSDqdDRkzBNrTbCa2uxxBL) |
| Project | `ask2.fuin.testnet/asker` (`p0000000000000150`); its only version is `edb89964…` (`get_project` and `list_versions` on `outlayer.testnet`) |
| Lock | the account's only key deleted: [`GWLpy16HQm…`](https://testnet.nearblocks.io/txns/GWLpy16HQmU4HaDpn5zpuw7kFteUAnLoRosGWXtNLfhj); its access-key list is empty and it holds no code |
| Pin | `policy/tee-v2.json`, `askers`, second entry |

## Live rehearsal on OutLayer's storage

The tests use a model of the storage. These two rounds check the real one. Each is three public questions on `deepseek-ai/DeepSeek-V4.1-Flash-1017`, owner `fuin.testnet`. `scripts/overlap_asks.py` puts several asks of one item into one transaction, so they reach the enclave together, which `fuin ask` never does.

An ask that returns "record changed during the ask" made a model call whose answer was not kept. The final record's attempts must be at least one more than the number of those.

**Round `ask2-rehearsal-1`, before the lock** (seal [`6QyKRk2Hxv…`](https://testnet.nearblocks.io/txns/6QyKRk2Hxv61ccRNFYpLQj7VEJX62BwW8EZrtsXfytES), block 277194970):

| Item | Asks in one transaction | Returned | Final attempts |
|---|---|---|---|
| 0 | 1 ([`2YRJV5iiDq…`](https://testnet.nearblocks.io/txns/2YRJV5iiDq9VUVt3cWQZdVt5qCWerJMYem4aZutZjanX)) | 1 final | 1 |
| 1 | 2 ([`FqLzFcGQJd…`](https://testnet.nearblocks.io/txns/FqLzFcGQJdA3PbUMrcJ7jn3jwLHTPssdzaQbYgtBu4oD)) | 1 "record changed during the ask", 1 final | 2 |
| 2 | 3 ([`5Z6GhGdptp…`](https://testnet.nearblocks.io/txns/5Z6GhGdptp1kdasvoiVvuhhrkRMfyN7N5XgubEMFfwsM)) | 2 "record changed during the ask", 1 final | 3 |

`fuin ask` then got each recorded answer back without a new model call, and the aggregate (task 55018) reports 3 retried asks. Both verifiers pass every other check and refuse the certificate `tee_asked_unlocked`, as they must: the project's owner still had a key at the seal.

The first two-ask transaction of this round ([`4KNm3bZ7ig…`](https://testnet.nearblocks.io/txns/4KNm3bZ7igd7GXa672L5fQi9dTiW9qwGhnzL9RDgny5W)) failed on OutLayer before either ask claimed an attempt: item 0's next ask was attempt 1. They were the first asks sent to this project; the cause wasn't determined and it didn't recur.

**Round `ask2-rehearsal-2`, after the lock** (seal [`KiTPjKAQW6…`](https://testnet.nearblocks.io/txns/KiTPjKAQW6f9AokCsDWm2nxfm4S9zZrifjuLQieWfxG), block 277198605):

| Item | Asks in one transaction | Returned | Final attempts |
|---|---|---|---|
| 0 | 2 ([`EBxxVhEGMb…`](https://testnet.nearblocks.io/txns/EBxxVhEGMbvMKhJH2oiHAMQHetPdZRpA8WGkYRNry8UE)) | the same final twice: the second ask ran after the first and got the recorded answer | 1 |
| 1 | 3 ([`EpCdGjEw2f…`](https://testnet.nearblocks.io/txns/EpCdGjEw2fgWxTYPQk4ndm8wBzfXXL2Fim5ukyRh9H15)) | 1 "record changed during the ask", the same final twice | 2 |
| 2 | none; asked by `fuin ask` | 1 final | 1 |

Result 2/3 with 1 retried ask: aggregate [`6AEtSDDREf…`](https://testnet.nearblocks.io/txns/6AEtSDDREfYw8gXhT22x8Ttam26oaEcHB4PD1hGRiL1E) (task 55428), asked-check task 55439, commit [`5GES3zT9BG…`](https://testnet.nearblocks.io/txns/5GES3zT9BGSrwTzQRzDuchz5RH2QbMGmF3xbcfcVTw7T), close [`AfdmMrgSTj…`](https://testnet.nearblocks.io/txns/AfdmMrgSTjLVYCQw9ntGZSB9heo2LLzUorm7sP7pKbsy).

- `fuin verify`: **VERIFIED**, "ask2.fuin.testnet/asker was locked at the seal (block 277198605)" ([verify-output.txt](verify-output.txt)).
- The browser verifier, run in Node: VERIFIED for round 2 and REFUSED `tee_asked_unlocked` for round 1 ([browser-verify-output.txt](browser-verify-output.txt)).
- Certificates: [round 2](cert-ask2-rehearsal-2-deepseek-v4.1-flash-1017.json), [round 1](cert-ask2-rehearsal-1-deepseek-v4.1-flash-1017.json).

These are rehearsals, not counted rounds: the published results stay at seven rounds and 20 certificates.

## What this doesn't show

- A live run can't choose which millisecond two asks collide in. The collisions above are the ones that happened; the exhaustive orderings are in the tests.
- Overlapping asks are still extra draws. Each is counted, no answer leaves the enclave until one is final, and the printed limit bounds their effect by the retried count.
- The limit on OutLayer's storage (not rolled back by its operator) and on separate rounds (not linked) is unchanged.

## Limit wording

A certificate from the second asker prints the asked-once limit without the overlap sentence. Round 7's certificate prints it as before (`docs/LIMITS.md` lists both; `tests/test_limit_selection.py`).
