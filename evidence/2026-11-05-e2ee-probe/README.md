# End-to-end encryption keeps Fūin's evidence intact: probe, 2026-11-05

**Question.** The limits say requests pass through NEAR's gateway, so their privacy in transit relies on NEAR operating it. NEAR AI Cloud documents end-to-end encryption to a model's attested key. Its main path uses Ed25519 keys; a "legacy" path keeps ECDSA keys, the ones Fūin's signatures and attestation checks use. The question was whether that path still produces the evidence Fūin needs.

**Method** (`probe.py`, one completion on a synthetic question, GLM-5.3-flash):
- **Key.** Fetched a model report with a fresh nonce and accepted it under the verifier's attestation policy. Checked that the report's `signing_public_key` hashes to the attested signing address.
- **Request.** Encrypted the question to that key: secp256k1 ECDH with a fresh ephemeral key, HKDF-SHA256 (`ecdsa_encryption`), AES-256-GCM. Sent it through the gateway with `X-Signing-Algo: ecdsa`, our own public key in `X-Client-Pub-Key` and the model's in `X-Model-Pub-Key`.
- **Hashes.** Hashed the exact bytes sent and received, as Fūin does for every answer.

**Result** (`result.json`):

| Check | Result |
|---|---|
| Question visible in the request bytes the gateway carries | no: `content` is ciphertext |
| Answer and reasoning in the response | both ciphertext, encrypted to our key |
| Decrypted answer | `42` (correct) |
| `/v1/signature` | `provider_tee`, ECDSA, text = `model:sha256(request):sha256(response)` over the exact encrypted bytes |
| Signature recovers to the attested signer | yes (`0x3b753b44…`) |

**What it means for the protocol.** The model signs the ciphertext it received and the ciphertext it returned. A verifier can check an encrypted round with the same signature check, given two things:
- **Request side.** Rebuild the exact encrypted request. This works if the encryption's randomness is derived from the item's salt, so a revealed item, or the TEE scorer, re-encrypts the question byte for byte.
- **Response side.** Decrypt the response with a client key derived the same way, then score the plaintext.

The gateway would still see the model, the generation settings, the nonce and the timing, but not the questions or the answers.
