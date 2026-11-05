# Zero-reveal rehearsal, 2026-11-05

A three-question round with made-up questions, run end to end on testnet to prove the zero-reveal path before the real round:
1. `fuin seal --tee` sealed a policy with audit mode `tee-scored-v1` (k=0) that pins TEE scorer v2 (`dabae968…`), and request template `fuin-request-v2`, whose nonces are bound to the seal block.
2. GLM-5.3-flash answered all 3 (3/3); the run was committed and the round closed.
3. `fuin tee-score` re-scored the run inside OutLayer's TDX enclave (task 21069), and the result matched the commitment. Because the questions are synthetic, the ciphertext was hosted on FastFS.
4. The certificate reveals nothing. `fuin verify` (`verify-output.txt`, no API key) gives VERIFIED:
   - the policy line names the sealed scorer and template v2;
   - `reveals: none`;
   - `round closed` replaces the audit sample;
   - `tee score` passes;
   - the registry check includes the seal block hash;
   - the scope says nothing was revealed;
   - the limits drop the sampling, reveal and inference-timing lines and add the seal-bound-nonce and TEE lines.

The questions stay in `private/`; the certificate contains none of them.
