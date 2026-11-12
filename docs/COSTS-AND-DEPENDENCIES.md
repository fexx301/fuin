# What Fūin costs and what it depends on

Every figure here comes from the published rounds' own transactions and signed answers (measured 2026-11-08), not from estimates. Fūin runs on NEAR **testnet**, so its gas is free testnet NEAR from the [faucet](https://near-faucet.io); only the model calls cost real money.

## What one round costs

**Model calls (NEAR AI Cloud, real money).** You pay NEAR AI for every answer, at its published per-token prices (the `/v1/model/list` catalog). Round 6 asked the same 96 questions of seven models, at a cap of 8,192 tokens. The costs below come from the token counts in its signed answers:

| Model | Output tokens per question (average) | Price per million (in / out) | Round 6 (96 questions) | Per 100 questions |
|---|---|---|---|---|
| deepseek-ai/DeepSeek-V4.1-Flash-1017 | 1,055 | $0.30 / $1.20 | $0.12 | $0.13 |
| deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated | 929 | $0.30 / $1.20 | $0.11 | $0.11 |
| z-ai/glm-5.3-flash | 3,038 | $0.08 / $0.50 | $0.15 | $0.15 |
| Qwen/Qwen3.6-35B-A3B-FP8 | 2,165 | $0.17 / $1.10 | $0.23 | $0.24 |
| Qwen/Qwen3.8-27B | 2,995 | $0.04 / $1.35 | $0.39 | $0.40 |
| Qwen/Qwen3.8-27B-abliterated | 3,398 | $0.04 / $1.35 | $0.44 | $0.46 |
| Qwen/Qwen3-VL-30B-A3B-Instruct | 5 | $0.15 / $0.55 | $0.00 | $0.00 |
| **All seven** | | | **$1.44** | |

Reasoning models spend most of their tokens thinking, so the cap matters more than the number of questions. A failed or retried call is billed again. In an enclave-asked round (`--ask`) the enclave makes the calls with your key, at the same prices.

**Chain and enclave fees (testnet NEAR, free).** From round 7's own transactions:

| Step | Count per round | Testnet NEAR each |
|---|---|---|
| Seal, commit (one per model), close: registry calls | 2 + one per model | about 0.0002 in gas |
| An OutLayer enclave task: TEE score, grounding, ask, aggregate, asked-check | one per model, one per round, one per question (`--ask`), one per model, one per model | about 0.0025–0.003 (gas plus OutLayer's fee; the 0.1 NEAR attached to each request is refunded) |
| Uploading a scorer build to FastFS (only when you build your own) | once per build | about 0.002 in gas |
| Storage deposits: the in-enclave key, an asker project's secret | once per build or project | 0.004–0.005, refundable |

A 96-question TEE-scored round with one model is a few thousandths of testnet NEAR. An enclave-asked round adds one task per question: about 0.1 testnet NEAR for 37 questions.

**Verifying costs nothing.** `fuin verify` and the browser verifier need no account, no key and no payment. They only read public services (below).

**Before and during your own round.** `fuin check` and `fuin evaluate` print a bound on the model calls before you seal: every answer using its whole cap, at the catalog prices read at that moment. It is a bound, not a forecast: the rounds above used a fraction of their caps. `--max-spend USD` stops a run before a call could take the round's spend past that amount, counting calls in flight and failed calls at their bound, and leaves the round resumable. Each call is noted on disk before it is sent, so a run that is killed mid-call still counts it when it starts again. `fuin cost --id ID` shows the tokens the signed answers actually used. NEAR AI's dashboard remains the bill.

## What Fūin depends on, and what happens when each is down

The verifier is built so that **an outage can only delay a verdict, never change it**. When a service it needs doesn't answer, the result is CAN'T CERTIFY `evidence_unavailable` (exit code 2), and every check that needs no network has already run, so tampering is still REFUSED offline. It never prints VERIFIED or REFUSED because a service was down. Run it again later.

| Service | Who uses it | For what | If it's down |
|---|---|---|---|
| **NEAR testnet RPC** (archival: `archival-rpc.testnet.fastnear.com`, falling back to `archival-rpc.testnet.near.org`) | owner and verifier | Seal, commit and close transactions; the verifier reads the registry record, the seal and close blocks, OutLayer transactions, worker approvals and the asker project's lock | **Verifier:** the other RPC is tried; if both fail, CAN'T CERTIFY until one answers. **Owner:** steps wait and retry. |
| **NEAR AI Cloud** (`cloud-api.near.ai`) | owner, and the asker enclave | Model calls, their `provider_tee` signatures, attestation reports at preflight | **Owner:** no new runs. **Verifier:** unaffected; it only uses the public model list to word one reason (a model that isn't served in a TEE), and still decides without it. |
| **Intel PCS** (TDX quote collateral; the browser verifier uses Phala's PCCS mirror, `pccs.phala.network`) | verifier | Checking the model's and OutLayer's Intel TDX quotes | CAN'T CERTIFY until it answers. |
| **NVIDIA NRAS** (`nras.attestation.nvidia.com`) | verifier (command line; browsers are blocked, so the page shows the recorded result) | The GPU attestation verdict | CAN'T CERTIFY until it answers. |
| **GitHub raw files** (`raw.githubusercontent.com`) | verifier; the grounding enclave | The deployment trace's public compose files (`nearai/cvm-compose-files`); near/docs lines for grounding | **Verifier:** CAN'T CERTIFY until it answers (VERIFIED requires the trace). **Grounding:** the task fails and can be run again. |
| **Docker Hub and sigstore** | verifier | Fetching the serving image's SLSA build provenance (sigstore's trust root is pinned in `policy/`) | A warning ("build provenance not checked"), never a verdict. |
| **OutLayer** (`outlayer.testnet`, its workers and key service, `testnet-api.outlayer.ai`) | owner | Running the TEE scorer, grounding and asker tasks; fetching each task's attestation record once, at run time | **Owner:** no new TEE tasks. **Verifier:** unaffected; the record is in the certificate, and the chain and Intel are checked instead. |
| **FastFS** (`test.fastfs.io`) | OutLayer, when it fetches a pinned build | Hosting the scorer and asker builds | **Owner:** no new tasks with an uncached build. **Verifier:** unaffected; builds are pinned by sha256 and rebuild from source. |
| **GitHub gists** | owner | Hosting an encrypted round only while an enclave fetches it, then deleting it | Use FastFS hosting instead (`--host fastfs`; permanent, still encrypted). |

## What would end a Fūin deployment, and the way out

- **NEAR redeploys a model.** Its measurements change, and preflight stops with no accepted attestation. Run `fuin policy-update`, which drafts the next policy with the evidence checked, have a person review it, and point the verifier at it. Old certificates keep verifying under the policy they were made with. A scheduled check (`.github/workflows/policy-drift.yml`) notices redeploys daily.
- **OutLayer changes its attestation format.** Old records keep verifying (the verifier pins the V1 task-hash format); new tasks would need a verifier update.
- **Intel or NVIDIA change their view of old evidence.** A certificate doesn't carry their verdicts: every verification asks them again, at today's date. If Intel later marks a platform out of date, the certificate still verifies, with a warning. If Intel revokes it, the certificate reads REFUSED `tcb_revoked`. If NVIDIA's service later rejects the recorded GPU evidence, it reads REFUSED `attestation_invalid`; if either service stops answering, CAN'T CERTIFY. The twice-daily re-verification of every published certificate ([MAINTAINING.md](../MAINTAINING.md)) is how such a change would be noticed.
- **testnet resets.** The registry and its records would go with it, and certificates would read CAN'T CERTIFY. The protocol doesn't depend on testnet: the same contract and flow run on mainnet, where gas costs real NEAR.
