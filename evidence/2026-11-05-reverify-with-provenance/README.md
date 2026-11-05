# All twelve certificates re-verified with image build provenance, 2026-11-05

`verify.jsonl` is one keyless `fuin verify --json` pass over every certificate in `examples/`. `verify-output.txt` renders the same results with the CLI's own printer (`cli._print_verdict`) rather than verifying twice, which halves the load on the public services.

**What's new in these results:**
- **Build provenance.** NEAR publishes SLSA v1 provenance for its serving images, as sigstore bundles attached to the image digest. The verifier checks it with sigstore-python against sigstore's public-good trusted root, pinned in `policy/sigstore-trusted-root.json` (sha256 `6494e21e…`, from tuf-repo-cdn.sigstore.dev, 2026-11-05). Three things must hold:
  - the bundle comes from a GitHub Actions workflow in NEAR AI's organisation;
  - it is logged in Rekor;
  - it is about exactly the traced digest.

  Where all three hold, a `build provenance` line names the workflow and source commit.
- **Which images.** GLM's and DeepSeek's images are NEAR's builds from `nearai/cvm-compose-files` publish workflows. Qwen's serving image is upstream `lmsysorg/sglang`, which publishes none, so its certificates carry the warning `no published build provenance (SLSA)`.
- **Round 5 limits.** Round 5's certificates print the end-to-end-encryption limits, including that the key each answer is encrypted back to travels in an unsigned header.

These records supersede the earlier ones for these exact certificate bytes (`scripts/build_page.py` matches results by `cert_sha256`).
