# Changelog

## 1.0.0 (2026-11-10)

The first public release, built at NEAR HACKATHON.

**What it does.** Fūin publishes a private benchmark result that anyone can check without an account and without the test set:
- the questions are sealed on NEAR before any model runs;
- every answer carries a signature from the model's attested TEE key on NEAR AI Cloud;
- every answer is scored inside a TEE on OutLayer.

**Three kinds of round:**
- **sampled:** a future NEAR block picks the questions to reveal;
- **TEE-scored:** nothing is revealed;
- **asked once:** a TEE in a locked OutLayer project asks each question itself, after the seal, so nobody can re-ask and keep the best answer.

**Also in this release:**
- **End-to-end encryption:** questions and answers can stay encrypted between the owner and the model's TEE, so NEAR's gateway never sees them.
- **Answer keys:** each key is checked inside a TEE against the docs line it cites.
- **Two verifiers that must agree:** the `fuin verify` command and a browser verifier. Both give three outcomes: VERIFIED, REFUSED with a reason code, or CAN'T CERTIFY when evidence is missing or a service is down.
- **Reproducible builds:** the TEE scorer and the asker (Docker), with their hashes pinned in `policy/tee-v2.json`.
- **Seven verified rounds:** 20 certificates, 2,302 TEE-checked answers, seven models, and 39 tamper fixtures.
- **For owners:** `fuin check`, `fuin status`, `fuin policy-update`, a GitHub Action, and `pip install fuin`.
- **Hardened after an external review** (`evidence/2026-11-08-external-review/`): stricter suite and evidence form checks, a pinned deployment trace, NVIDIA verdict tokens verified, and the browser verifier aligned with the command line.
