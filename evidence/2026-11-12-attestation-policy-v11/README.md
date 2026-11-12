# Attestation policy v11, 2026-11-12

NEAR redeployed GLM-5.3-flash between Nov 11 and Nov 12. Round 8's `fuin ask` for that model stopped at preflight with `measurement_unapproved`, before asking anything. Published certificates are unaffected: each records the policy version its owner checked.

## What was reviewed

Three `fuin policy-update` runs on Nov 12 (replicas can serve different deployments, so one run may not see them all). All three proposed the same single entry, and `fuin policy-update` only proposes a configuration whose evidence holds: Intel quote, nonce binding, RTMR3 event log and NVIDIA's verdict.

| Compose | Model | Deployment (nearai/cvm-compose-files) |
|---|---|---|
| `c900dc73…` | GLM-5.3-flash | `prod/GLM-5.3-Flash-SGL-TP2x4-W4AFP8-V12Q8.yaml` at v0.0.567 (four replicas), with two replicas still on `prod/GLM-5.3-Flash-SGL-TP4-W4AFP8.yaml` at v0.0.443 |

For the new entry:
- **Signer:** unchanged from v10, `0x3b753b44…`.
- **OS:** an image and measurements (MRTD, RTMR0–2) v10 already approves.
- **Attested images:** all four are ones v10 already lists.
- **Quote and GPU:** Intel quote UpToDate, NVIDIA's verdict true.
- **Serving image:** one is new, `nearaidev/sglang@sha256:050b1adf…`. Its SLSA build provenance verifies to `nearai/cvm-compose-files`, workflow `publish-glm53-v0523.yaml` on `main`, commit `2cf337c2`. The other, `…21f133cc`, was already in use.

The six other models were checked in the same runs and are served from configurations v10 already approves. Policies only add: every v10 entry is in v11 unchanged.

## After accepting it

- `owner.ATTESTATION_POLICY` points at `policy/attestation-v11.json`.
- A live preflight check accepts exactly one candidate for GLM-5.3-flash, DeepSeek-V4.1-Flash and Qwen3.6-35B, on two runs in a row.
- Certificates from rounds 1, 6 and 7 still VERIFY; the tests pass.
