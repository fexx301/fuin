# Qwen redeployment, 2026-11-04

While round 3 started, every gateway report for Qwen/Qwen3.8-27B carried a configuration (`app_compose` hash `31d3b2389e06…`) that wasn't in attestation policy v3, so `fuin run` refused the preflight (`measurement_unapproved`), as designed.

**Checks on the new configuration:**
- Every attestation check passes: quote, report data (signer `0x835ab53d…`, unchanged, plus our nonce), debug off, MRCONFIGID, RTMR3 and NRAS.
- The diff against the v3 configuration is two lines:
  - the compose-manager launcher image `nearaidev/compose-manager@sha256:6e035c8f…` → `sha256:a320bb48…`;
  - `INSTANCE_LABEL=gpu13` → `cm-gpu32-g7`.
- The new launcher image has **SLSA v1 build provenance** from GitHub's attestation service (`gh attestation verify oci://docker.io/nearaidev/compose-manager@sha256:a320bb48… --owner nearai`): workflow `nearai/compose-manager/.github/workflows/build.yml` on `refs/heads/master`, commit `be649f88…`, subject digest matching. That is the signing identity the measured configuration itself requires (`LAUNCHER_COSIGN_IDENTITY_REGEXP=https://github.com/nearai/compose-manager/.github/workflows/.*`). Output: `compose-manager-slsa-attestation.json`.

**Decision:** add the configuration as attestation policy **v4**. This is the spec's procedure for an image update (the verifier's trust policy, not the sealed round policy, so no reseal). Certificates checked under v3 still verify under v4, which only adds an entry.
