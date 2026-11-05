# DeepSeek V4.1 Flash review, 2026-11-05

This is the third model for the zero-reveal round: `deepseek-ai/DeepSeek-V4.1-Flash-1017`, which NEAR AI Cloud runs in a TEE. The gateway report (`gateway-report.json`) was reviewed the same way as Qwen's and GLM's:
- **Report checks:** all pass. The quote is UpToDate; the report data binds the signer `0xfe007189…` and our nonce; debug is off; MRCONFIGID and the RTMR3 replay match; NVIDIA NRAS passes.
- **OS:** the measurements (MRTD, RTMR0-2) equal a set already approved for Qwen and GLM, and `os_image_hash` is the same (`91fd5d69…`).
- **Application:** `app_compose` (`ae66f844…`) differs from Qwen's approved configuration only in `INSTANCE_LABEL` (gpu13 to gpu02).
- **Deployment trace:**
  - The vLLM services (`model-vllm-dsv41-dp0` to `dp7` and two DEP4x2 replicas; compose file `prod/DeepSeek-V4.1-Flash-1017-vLLM-DEP8-Abliterated.yaml` at nearai/cvm-compose-files `c4a3ce6a`, tag v0.0.546) load the base weights `deepseek-ai/DeepSeek-V4.1-Flash-1017` at snapshot `1bae0e1088…` and serve them as `--served-model-name deepseek-ai/DeepSeek-V4.1-Flash-1017`.
  - The same instances also serve an abliterated LoRA adapter (UnderTides heretic LoRA) under a different name, `deepseek-ai/DeepSeek-V4.1-Flash-1017-abliterated`. A request to the base name doesn't use it. The trace now reports such adapters.
  - Before this review the trace parser read weights only from `--model-path`. It now also reads vLLM's positional Hugging Face cache path.

Added as attestation policy **v6**.
