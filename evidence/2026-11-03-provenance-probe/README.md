# Image-provenance probe, 2026-11-03 (timebox 2 h; took about 1 h)

**Question:** the accepted `compose_hash` pins NEAR's compose-manager launcher, not the model containers. Can a stranger tie a signed answer to the container and weights that actually served it?

**Finding: the deployment can be traced; the container's build provenance is not checked.**

1. Each model report carries `compose_manager_attestation`: a second TDX quote whose report data is `sha256(canonical action log) ‖ client nonce`. The log is canonical JSON (sorted keys, compact), as defined by `canonicalize_actions` in the public [nearai/compose-manager](https://github.com/nearai/compose-manager) `src/main.rs`. `fuin` recomputes the hash, checks the nonce, verifies the quote, and requires the same MRCONFIGID and RTMR3 as the model's own quote (same CVM).
2. The measured `app_compose` pins `GITHUB_REPO=https://github.com/nearai/cvm-compose-files` as a literal, not an overridable variable. Each `compose_up` in the log names a tag, a commit, a compose file and the file's sha256.
3. `fuin` replays the log to find which services are up, fetches each compose file at its logged commit from the public repo, checks the sha256, and reads every service that declares `--served-model-name <model>`.

Result on the `near-dev-60-r1` certificates (every file's sha256 matched):

| Model | Serving service(s) | Tag / file | Weights |
|---|---|---|---|
| Qwen/Qwen3.8-27B | `model-sg-qwen38-27b-fp8-tp1-coloc` | v0.0.539 `prod/small-models.yaml` | `Qwen/Qwen3.8-27B-FP8` rev `017b9c7a…` |
| z-ai/glm-5.3-flash | `model-sg-glm53-w4afp8-tp2-r1`…`r4` | v0.0.521 `prod/GLM-5.3-Flash-SGL-TP2x4-W4AFP8-*.yaml` | `graphistry/GLM-5.3-Flash-W4AFP8` snapshot `99f1fa70…` |

So the scores describe NEAR's deployed **quantized** weights (FP8; a W4AFP8 build), not the full-precision checkpoints that public benchmark tables usually report.

**Not covered:** the images' build provenance (cosign/SLSA attestations named in NEAR's compose README). Checking it needs tooling outside this verifier, so it stays a printed limit, and the trace does not gate the verdict (the spec gates only on verified image provenance). Contradictory trace evidence (hash, nonce, quote or file mismatch) is REFUSED `attestation_invalid` (fixture `edited-deployment-log`); an unavailable trace is a warning.
