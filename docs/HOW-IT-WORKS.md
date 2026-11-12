# How Fūin works

## Three kinds of round

Every round seals its questions on NEAR first, and every certificate is checked the same way. The rounds differ in what they reveal and in who calls the model, and each kind is a trade-off:

| | Sampled (`fuin seal`) | TEE-scored (`fuin seal --tee`) | Asked once (`fuin seal --ask`) |
|---|---|---|---|
| Questions revealed | a sample, picked by a future NEAR block | none | none |
| Who calls the model | the owner | the owner | a TEE, once per question, after the seal |
| How scores are checked | anyone re-scores the sample; a TEE re-scores every answer | a TEE re-scores every answer | the TEE scores each answer as it asks |
| Can the owner re-ask a question and keep the best answer? | yes (a printed limit) | yes (a printed limit) | not within a round: the TEE keeps one answer per question and counts any retry. Sealing the same questions as a separate round is still possible; rounds aren't linked |
| Models and token cap | all seven, 8,192 | all seven, 8,192 | models that answer within about two minutes, at a smaller cap of 4,096 (DeepSeek-V4.1-Flash in round 7; DeepSeek-V4.1-Flash, GLM-5.3-flash and Qwen3.6-35B in round 8) |
| Rounds here | 1–3 | 4–6 | 7 |

Why the last column is narrower: an asked round's model call happens inside an OutLayer task that NEAR has to answer within about two minutes, so only answers a model can write in that time fit. The other two kinds still run every model at 8,192 tokens. Pick sampled or TEE-scored for the widest comparison, asked once when it matters that nobody could re-draw answers. Scores from different caps aren't comparable.

## The flow

Flow: **seal → run → commit → close → sample → reveal → verify.**

1. **Seal.** The owner commits a Merkle root over the salted items (each with a secret 32-byte nonce) and a policy hash on the NEAR registry. The policy fixes the request template, generation settings, scorer (pinned by file hash) and audit size: `k` is the smallest sample that catches at least one of `D = ceil(n/10)` wrong scores with probability ≥ 95%, computed exactly (k = 23 for n = 60). That is detection power against a stated amount of mis-scoring, not a probability that the total is correct.
2. **Run.** Each question goes to the NEAR AI Cloud gateway non-streaming, with the nonce in the request's `user` field. The model's TEE key signs `model:sha256(request):sha256(response)` over the exact bytes (`provider_tee` signature). A fresh attestation report is fetched before the run.
3. **Commit.** The owner commits each run's Merkle root and total; the contract numbers the runs.
4. **Close.** The round closes, and no more runs can join it.
5. **Sample.** The audit seed is the hash of the first finalized block at height ≥ close + 2, bound to the round's records. The owner can't know it when committing. One sample serves every model in the round.
6. **Reveal.** The sampled items, salts, nonces and exact request and response bytes are published with Merkle proofs.
7. **Verify.** The verifier first checks every field's form; malformed input is refused, never crashes. It runs every check that needs no network before any that does, so a service outage can't hide tampering that local checks catch. An outage only defers the verdict to CAN'T CERTIFY. Anyone rebuilds both roots from all `n` rows, checks every signature against a key attested in an Intel TDX quote whose application (MRCONFIGID, RTMR3) and OS (MRTD, RTMR0-2) measurements are both approved, with NVIDIA GPU attestation via NRAS. VERIFIED also requires the deployment trace below. It reads the registry over an archival RPC. They then re-derive the sample from the chain, rebuild each revealed request from the sealed template, and re-score each revealed answer.

**Deployment trace.** Each model report includes NEAR's compose-manager attestation: a second TDX quote over the log of deployments on that machine. Fūin recomputes the log hash and fetches each logged compose file from the public [nearai/cvm-compose-files](https://github.com/nearai/cvm-compose-files) repo at the logged commit, checking its sha256. From those files it reports the container image digest and the weights serving the model. Details: `evidence/2026-11-03-provenance-probe/`.

## TEE score

The audit checks a sample; a TEE score checks every answer. The owner encrypts one run (each item's sealed bytes and salt, the sealed policy, the signed requests and responses) to a key that exists only inside Fūin's TEE scorer, which runs in an Intel TDX enclave on OutLayer. The scorer (`tee/`) rebuilds every benchmark leaf from the sealed bytes, rebuilds every request from the sealed template and requires it to equal the signed bytes, recovers every signature, scores every answer with the sealed scorer's exact rules, and returns only the two roots, the total and the signer. `fuin verify` then checks the OutLayer attestation (the Intel quote, OutLayer's task hash, the worker's approval at the execution's block, and the request and result on chain) and that the output equals the certificate's own roots, total, model and signer.

Every certificate of rounds 1–6 carries a TEE score; those of rounds 7 and 8 carry the asker's aggregate instead ([asked once](#asked-once-rounds-7-and-8)). Rounds 1–3 were re-scored this way (OutLayer tasks 21078–21084), and rounds 4–6 were scored only this way (tasks 21125–21127, 21373–21375 and 25501–25515), so every hidden score is checked exactly rather than by sample, under the TEE trust assumptions in the [limits](LIMITS.md). Round 5's scorer (v3) predates the count of unreadable answers, so its certificates print the limit that a total could be lowered unseen. It doesn't make rounds 1–3's audited items private again. Each encrypted run was hosted on a secret gist for the run and deleted afterwards; the attestation binds only its hash. The scores were first computed on a build that reproduced only on macOS, then re-done on the canonical build, which reproduces on any host; the first build is no longer accepted. Details: `evidence/2026-11-05-reverify-tee-score/` and `evidence/2026-11-05-reverify-tee-v2/`.

## Answer keys checked against their sources

A zero-reveal round's score is exact against the owner's sealed answer key, so a wrong key would favour or penalise a model and nobody could see it. Grounding narrows that: a key must appear in the near/docs line its item cites, so an invented value, a typo or a key taken from elsewhere is flagged. It doesn't stop a wrong value that happens to appear in a line the owner chose to cite. Every item cites one line of near/docs at a pinned commit, so the TEE checks the key at the source: the owner encrypts the round's items to scorer v7's in-enclave key, and the enclave fetches each cited file from GitHub at that commit, recomputes the sealed benchmark root, and flags every item whose answer, or any accepted alternative, doesn't appear in its cited line (after removing `,`, `` ` `` and `*`). It returns only the root, the commit, the count and a bit per flagged item. It runs once per round, after the fact, bound to the root sealed on chain, so no sealed score or scorer build changes; `fuin verify` checks it like a TEE score and prints the flagged items.

| Round | Keys in their cited line | Flagged | OutLayer task |
|---|---|---|---|
| 4 | 151/155 | 4 | 26243 |
| 5 | 94/96 | 2 | 26242 |
| 6 | 92/96 | 4 | 26241 |
| 7 | 37/37 | 0 | 27212 (scorer v8) |

A flagged key isn't necessarily wrong: a number worked out from the line (a unit conversion, a count) is flagged, as is an accepted alternative longer than the cited text. They are the keys nobody checked. The repository is fixed (`near/docs`), and the verifier accepts only commits listed in `policy/tee-v2.json`, each checked to be on near/docs master, because GitHub serves a fork's commits under the original repository's path too: tested on Nov 7 with a commit that exists only on a public fork, which `raw.githubusercontent.com/near/docs/<sha>/…` served with HTTP 200. Details: `evidence/2026-11-07-answer-key-grounding/`.

## Asked once (rounds 7 and 8)

This is the third [kind of round](#three-kinds-of-round). Until round 7 the owner made the model calls. NEAR AI Cloud's temperature-0 serving isn't deterministic (re-asking 43 of round 4's items changed 5 scores), so an owner could re-send a sealed request and commit the best signed answer, and every signature would still be valid. In an enclave-asked round (`fuin seal --ask`) the owner makes no model call:
- **The asker** (`ask/`) runs as the OutLayer project `ask.fuin.testnet/asker`. The account that owns it had its only key deleted before the round, so the project can't be deleted, re-versioned or transferred. Its only version is the asker build `dbbb286b…`, which rebuilds byte for byte with `ask/build-docker.sh`.
- **Each ask:** the asker records it in sealed project storage under a name derived from the sealed round (benchmark root, model, index), builds the sealed request, calls NEAR AI with the owner's key (an OutLayer secret the owner stores), checks the `provider_tee` signature, scores the answer with the scorer's own code and records it final. A final record is re-emitted, never re-asked; one still pending, whose answer never left the enclave, may be retried, and the retries are counted.
- **A second asker.** A review found that round 7's asker could record one retry fewer than happened when two asks of the same item overlapped by milliseconds. A locked asker can't be patched, so new rounds use a second one: build `edb89964…` in `ask2.fuin.testnet/asker`, locked the same way. It calls the model only after confirming its own claim on the record, so every attempt is counted however asks overlap, time out or restart (`ask/src/record.rs`, with tests over every interleaving). `fuin seal --ask` seals the newest pinned asker, and round 8 ran on it; round 7 keeps verifying against the first, and its certificate prints the overlap limit. Evidence: [`evidence/2026-11-11-asker-v2/`](../evidence/2026-11-11-asker-v2/README.md).
- **The certificate** carries the asker's aggregate: the run's roots and total from every final record, attested by OutLayer. `fuin verify` checks that it came from the sealed asker in the sealed project, that it equals the committed run, and, on the archival chain at the seal block, that the project's owner had no keys or code and the asker was its only version.
- **After the seal.** The asker's records are named by the sealed round, not by the seal block, so the certificate also carries scorer v9's asked-check: inside a TEE, every request is rebuilt with the seal block's hash and must equal the request the model signed. A request made before the seal, with a guessed seal hash, can't pass, so no owner could ask early, re-draw by changing salts, and seal the round they liked.

Round 7 (37 questions, DeepSeek-V4.1-Flash-1017) is VERIFIED this way: 19/37, 1 retried ask (item 31, whose first requests outlived NEAR's yield window; it scored 0). A retry is a second draw, so the verifier prints the bound: a single draw per item could differ from the total by at most the retried count, here 1. The cap is 4,096 tokens because a TEE-made call must finish inside NEAR's yield window of about 125 s: 8,192 tokens didn't fit, and on Nov 7 Qwen3.8 and GLM were too slow even at 4,096. Details: `evidence/2026-11-08-round-near-dev-37-r7/`.

Round 8 (40 new questions, three models, the second asker) is VERIFIED the same way: DeepSeek-V4.1-Flash 18/40 with 1 retried ask, GLM-5.3-flash 16/40 and Qwen3.6-35B 7/40, neither with a retry. By Nov 12 NEAR had redeployed GLM, and a timing test on eight public questions at 4,096 tokens took it at most 37 s, Qwen3.6-35B at most 10 s and DeepSeek at most 84 s. Qwen3.8-27B took a median of 96 s, so it was left out. Details: `evidence/2026-11-12-round-near-dev-40-r8/`.

## Zero-reveal rounds

`fuin seal --tee` seals a round that reveals nothing. Three things differ from a sampled round:
- **The policy** names the exact scorer build (by sha256) that will score every item inside the TEE, and has no audit sample.
- **The verifier** requires that TEE score: without it the certificate is CAN'T CERTIFY `tee_score_missing`, and a record naming any other build is REFUSED `tee_score_mismatch`.
- **Every request's nonce** is `sha256("fuin-nonce-v2" ‖ item nonce ‖ seal block hash)`. That block hash didn't exist before the seal, so no signed answer can predate it, which a sampled round can't show. The TEE scorer rebuilds each nonce from the hash, and the verifier compares the hash with the chain.

The trade-off: a sampled round's score check needs only public bytes, while a zero-reveal round's relies on the TEE (Intel TDX, OutLayer's worker governance and key service). In exchange, no question is ever published. Round 4 (`near-dev-155-r4`) is a zero-reveal round: 155 questions, three models, nothing revealed. Details: `evidence/2026-11-05-round-near-dev-155-r4/`.

## End-to-end encryption

`fuin seal --e2ee` (request template v3) encrypts every question to the model's attested TEE key, with NEAR AI Cloud's end-to-end encryption on the model's secp256k1 signing key (`X-Signing-Algo: ecdsa`): ECDH, HKDF-SHA256, AES-256-GCM. The answer comes back encrypted to a key only the owner holds. NEAR's gateway carries ciphertext for both; it still sees the model, the settings, the nonce, the timing and the sizes.

The evidence is unchanged, because the model signs the exact encrypted bytes it received and returned (`provider_tee`, probe: `evidence/2026-11-05-e2ee-probe/`). To stay checkable, every random value derives from the item's secret salt: whoever holds the salt (a verifier of a revealed item, or the TEE scorer) re-encrypts the question byte for byte, which pins exactly what the model decrypted, and decrypts the answer. An answer that doesn't decrypt scores 0, even when the item accepts an empty answer: before scorer v6 it read as an empty answer and would have matched one (a blind reviewer's probe; no published suite accepts an empty answer, and suite checking now rejects one; enclave run: task 22597). The TEE scorer also requires that the key the questions went to is the key that signed every answer. The key an answer comes back to travels in an unsigned header, so from scorer v4 the TEE also counts answers that don't decrypt, and the count is printed with the TEE score (`evidence/2026-11-05-scorer-v4-unreadable-count/`, with a verifiable rehearsal certificate).

Round 5 (`near-dev-96-r5`) is zero-reveal and end-to-end encrypted: 96 questions, three models; nothing was revealed, and no question or answer crossed NEAR's gateway in the clear (NEAR AI Cloud's end-to-end encryption, observed by the probe in `evidence/2026-11-05-e2ee-probe/`; the certificate itself can't show this). Details: `evidence/2026-11-05-round-near-dev-96-r5/`.

Round 6 (`near-dev-96-r6`) runs every model NEAR serves in its own TEEs, seven, on 96 new questions, zero-reveal and end-to-end encrypted; all seven certificates VERIFY, with no failed inference attempts. Details: `evidence/2026-11-07-round-near-dev-96-r6/`.
