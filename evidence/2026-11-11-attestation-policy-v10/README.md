# Attestation policy v10, 2026-11-11

NEAR rolled new deployments across its model CVMs between Nov 8 and Nov 11. The daily `policy-drift` workflow noticed on Nov 8 and opened issue #1 with a drafted policy. Until a policy with the new configurations is accepted, an owner's `fuin run` on those models stops at preflight with `measurement_unapproved`. Published certificates are unaffected: each records the policy version its owner checked.

## What was reviewed

The drafts from the workflow runs of Nov 8, 9 and 10 and four local `fuin policy-update` runs on Nov 11 (replicas serve different deployments, so one run doesn't see them all). `fuin policy-update` only proposes a configuration whose evidence holds: Intel quote, nonce binding, RTMR3 event log and NVIDIA's verdict.

| Compose | Models | Deployment (nearai/cvm-compose-files) |
|---|---|---|
| `e8416a02…` | Qwen3.8-27B and its abliterated LoRA, Qwen3.6-35B-A3B-FP8, Qwen3-VL-30B-A3B-Instruct, GLM-5.3-flash | `prod/small-models.yaml`, v0.0.551 to v0.0.554 |
| `c5e7bd5f…` | DeepSeek-V4.1-Flash-1017 and its abliterated LoRA | v0.0.546 |
| `448683dd…` | the same two | v0.0.553 |
| `c53e254e…` | the same two | v0.0.553 |

For every new entry:
- **Signers:** unchanged from v9 (for example `0xfe007189…` for DeepSeek, `0x3b753b44…` for GLM).
- **OS:** an image and measurements (MRTD, RTMR0–2) v9 already approves.
- **Quote and GPU:** Intel quote UpToDate, NVIDIA's verdict true.
- **Images:** the serving images are unchanged. One image is new, `nearaidev/compose-manager@sha256:a0c07308…`; its SLSA build provenance verifies to `nearai/compose-manager`'s build workflow on `master`.

Policies only add: every v9 entry is in v10 unchanged.

## After accepting it

- `owner.ATTESTATION_POLICY` points at `policy/attestation-v10.json`.
- A live preflight check accepts exactly one candidate for each of the seven models, on two runs in a row.
- Certificates from rounds 1, 6 and 7 still VERIFY; the tests pass.
- Released as fuin 1.0.1, because the verifier ships its policies.
