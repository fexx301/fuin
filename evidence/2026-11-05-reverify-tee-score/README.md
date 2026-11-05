# Round 3 re-scored inside a TEE, 2026-11-05

The random audit checks a sample. A TEE score checks every answer. Round 3's two runs were re-scored, all 300 answers each, inside an Intel TDX enclave on OutLayer (NEAR's verifiable off-chain compute, built by FastNEAR). Both certificates now carry the evidence, and `fuin verify` checks it (`verify-output.txt`, `verify.jsonl`: VERIFIED, exit 0, with a `tee score` check).

| Run | TEE total | Committed total | OutLayer task | Transaction |
|---|---|---|---|---|
| glm-5.3-flash | 122/300 | 122/300 | 20867 | `Hb86GaLmQPw5vFJghpxYoiULc3rnX7EWeyZXECuf5SP` |
| Qwen3.8-27B | 77/300 | 77/300 | 20868 | `CNgQqWtpFTPGRvYpbQNdTobGCqXK3cWyS46b8J7x83Tf` |

**What ran.** `tee/` is the scorer: Rust compiled to WASI P2. For one run it:
- rebuilds every benchmark leaf from the item's sealed bytes and salt, and the benchmark root from those leaves;
- rebuilds every request from the sealed template and requires it to equal the signed bytes;
- recovers every EIP-191 signature, with one signer for the whole run;
- scores every answer with the sealed scorer's rules (Python's whitespace, Unicode digits and case folding, generated from Python 3.13);
- rebuilds the run root.

It returns only the two roots, the total, the policy hash and the signer. It refuses anything it can't reproduce byte for byte.

**How the private run reached it.**
- **The key.** The scorer generated an X25519 keypair inside the enclave (keygen task 20858, transaction `4pKsVLymDVrnst9597cMVd7976QnZfF61QejXrbnFtLJ`). It sealed the secret under an OutLayer encryption key bound to the scorer build's sha256 and to the calling account, so only this exact build, called by `fuin.testnet`, can open it.
- **The ciphertext.** The owner encrypted each run to that key (X25519, HKDF-SHA256, ChaCha20-Poly1305) and hosted the ciphertext, base64, on a secret GitHub gist for the duration of the run. The gist was deleted as soon as the scorer had fetched it.
- **What the attestation needs.** It binds the ciphertext's hash, not its location, so verification doesn't need the file.

**What the verifier checks** (`src/fuin/tee.py`):
- **Locally, before any network call:**
  - the record names the pinned scorer build;
  - the record's input and output hashes match the evidence;
  - the caller is the benchmark owner;
  - the output equals the certificate's model, n, total, benchmark root, policy hash, run root and signer.
- **Then over the network:**
  - the record's Intel TDX quote, checked with the same dcap-qvl path as the model attestations;
  - OutLayer's V1 task hash, rebuilt and found in the quote's report data;
  - the worker's measurements, approved by `worker.outlayer.testnet` at the execution's own block (archival RPC), so a later rotation doesn't change the verdict;
  - the `request_execution` transaction and its result, read back from the chain.

**Before the real runs:**
- **Parity.** Natively, the scorer reproduced every benchmark root, run root, total, policy hash and signer for all 840 real rows of the six published runs. It also matched the Python scorers on 3,000 generated edge cases × 2 scorer versions (`tee/tests/parity.rs`).
- **Synthetic run.** A signed synthetic round (`tests/fixtures/tee-synthetic-round.json`) was scored inside OutLayer and matched Python's outcome (task 20860, now the offline test fixture `tests/fixtures/tee-synthetic-evidence.json`).
- **Reproducible build.** `tee/build.sh` gives sha256 `a848254b9d2cda2ca522e839b4e4f7de33ec1d51a364fb9a0d92d88f252f69a7` from a fresh clone at another path, and that is the pin in `policy/tee-v1.json`. The binary is served from FastFS at the URL there.

**Tampering** (`examples/tampered/`, checked live):

| Case | Verdict |
|---|---|
| TEE total edited | REFUSED `tee_score_invalid` |
| Total edited and the record's output hash recomputed | REFUSED `tee_score_mismatch` |
| OutLayer task id edited | REFUSED `tee_attestation_invalid` |
| A scorer build other than the pinned one | CAN'T CERTIFY `tee_unapproved` |

**What this does and doesn't change.**
- **What it adds.** The 272 unrevealed items' scores are now checked exactly, not statistically, under the TEE trust assumptions printed with the limits.
- **What it doesn't.** It doesn't un-reveal the 28 audited items. A round that reveals nothing would need a different sealed policy, which no current round uses.
- **What it trusts.** On top of NEAR AI Cloud's TEE for inference: Intel TDX, OutLayer's worker-measurement governance, and its key service (NEAR MPC key derivation).
