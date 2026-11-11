# Limits

Every VERIFIED prints the limits that apply to its certificate. This is the full list, word for word.

- Every published signature and commitment is checked; score correctness and request-policy compliance are checked on the revealed sample, and on every item only when the certificate carries a TEE score.
- Model instances can share a key even with different configurations. Matching a signer does not identify the serving instance or prove its exact configuration.
- Accepted configurations are recorded from NEAR's attested reports in the verifier's policy: the application (compose hash) and the OS (MRTD, RTMR0-2), as observed, not rebuilt from source. The serving container is traced from NEAR's attested deployment log at preflight to a public compose file (image digest, weights, revision); a redeploy during the run would not show. The image's build provenance is verified where NEAR publishes it (SLSA v1 through sigstore, from a workflow in NEAR AI's GitHub organisation); other images are named in the warnings.
- Run numbering exposes committed attempts only, not discarded API calls, private rehearsals or uncommitted runs.
- An owner could send the same sealed request more than once and commit the best signed answer; every signature stays valid, so a certificate can't show that.

For an enclave-asked round that passes the asked-once check, that limit reads instead as the first line below. Round 7 used the first asker (`dbbb286b…`), which could miscount when two asks of one item overlapped, so its certificate prints the second line; the second asker (`edb89964…`, `ask/src/record.rs`) closes that:

- Each item was asked inside the enclave, after the seal, and its answer recorded once; that rests on OutLayer's storage not being rolled back by its operator, as every TEE result rests on Intel TDX and OutLayer. A retried ask (an earlier attempt ran out of time, or lost the record to another ask of the same item; no answer had left the enclave) is a second draw, and the owner sets the task's time limit: a single draw per item could differ from the total by at most the retried count. An owner could still seal the same questions as another round and publish the better one: separate rounds aren't linked.
- Each item was asked inside the enclave, after the seal, and its answer recorded once; that rests on OutLayer's storage not being rolled back by its operator, as every TEE result rests on Intel TDX and OutLayer. A retried ask (one whose first request ran out of time, so no answer had left the enclave) is a second draw, and the owner sets the task's time limit: a single draw per item could differ from the total by at most the retried count. Two asks of the same item that overlap by milliseconds could record one retry fewer than happened; neither answer leaves the enclave until one is final, so the owner can't choose between them, and fixing the count needs a new locked asker. An owner could still seal the same questions as another round and publish the better one: separate rounds aren't linked.
- Sampling assumes the selected future finalized block is unpredictable and not adversarially biased (SHA-256 as a pseudorandom expander); not validator-proof randomness.
- Reveals permanently disclose the sampled questions and answers; later rounds grow the disclosed union.
- The seal precedes the result commitment; this does not prove when inference happened.
- The registry contract is locked (no access keys), and its code rebuilds byte for byte from contract/ on macOS arm64 with the recorded toolchain (GitHub's runners: .github/workflows/registry-rebuild.yml), not on Linux; the seal and commit values are checked against the owner's signed transactions, while run numbering and the close rely on the deployed code.
- Each item's 0/1 score is public (it is part of the run commitment), so a certificate shows which hidden items a model answered correctly, though not what they ask.

Printed as well when a certificate carries a TEE score:

- A TEE score trusts Intel TDX, OutLayer's worker-measurement approvals (worker.outlayer.testnet, checked at the execution's block) and its key service. Each accepted scorer build is pinned by sha256 and rebuilds with tee/build-docker.sh, on any host with Docker, from tee/ at the commit policy/tee-v2.json records.

For a zero-reveal round, the sampling and reveal limits are not printed, and this one is:

- Nothing is revealed, so no one but the owner can check the questions or the expected answers: the total is exact against the owner's sealed answer key, which is unchecked, and the choice of questions is the owner's.

When the certificate carries an answer-key grounding, that limit reads instead, with one more:

- Nothing is revealed, so no one but the owner can check the questions; the choice of questions is the owner's. Answer keys were checked inside a TEE only against their cited line (see the answer keys check).
- A grounded answer key appears in the line of near/docs the owner cited; that doesn't prove it is the right answer to its question: a cited line can contain a wrong value, and a short key (a number, a word) can appear in a line by chance. Flagged keys were not checked. The flags show which hidden items were flagged, not what they ask; GitHub saw which near/docs files the round cites.

With a seal-bound request template (v2 or v3), the timing limit is replaced by:

- Request nonces are bound to the seal block's hash, so no signed answer predates the seal; answers between the seal and the commitment are not individually timestamped.

With end-to-end encryption (request template v3), also:

- Questions and answers were end-to-end encrypted to the model's attested key; NEAR's gateway still saw the model, the generation settings, the nonce, the timing and the sizes.
- The key each answer is encrypted back to travels in an unsigned header, so an owner could have chosen answers encrypted to another key and commit them unreadable (each scores 0): a total could be lowered without the certificate showing it.

When the round's TEE scorer counts unreadable answers (scorer v4 onwards), that limit reads instead:

- The key each answer is encrypted back to travels in an unsigned header, so an owner could have chosen answers encrypted to another key and commit them unreadable (each scores 0); the TEE scorer counts such answers, and the count is printed with the TEE score.

Also: verification needs the public services listed in [COSTS-AND-DEPENDENCIES.md](COSTS-AND-DEPENDENCIES.md) (it is account-free, not offline). Without end-to-end encryption, requests pass through NEAR's gateway in the clear, so their privacy in transit relies on NEAR operating it. Failed inference attempts are owner-reported and can't be verified. Testnet only.
