"""Write tests/fixtures/tee-synthetic-round.json: a 3-item round with made-up questions, signed by a throwaway key
the way NEAR AI's TEE signs, plus the outcome the Python reference computes. The Rust scorer's tests must reproduce it
and refuse each tampering. Deterministic; contains nothing from a real suite."""
import json, sys
from pathlib import Path
from eth_account import Account
from eth_account.messages import encode_defunct
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fuin import core, inference, tee  # noqa: E402
from fuin import policy as P  # noqa: E402

import argparse  # noqa: E402
args = argparse.ArgumentParser(); args.add_argument("--v2", action="store_true", help="request template v2 (seal-bound nonces)")
args.add_argument("--v3", action="store_true", help="request template v3 (v2 plus end-to-end encrypted questions and answers)")
A = args.parse_args()
V3 = A.v3
V2 = A.v2 or V3  # v3 is seal-bound too
SEAL_HASH = "4Kp2YgCwZCU6nM8ZpCq3Y8qD3iJb8DqJ5tR7vV9xW2aB"  # a made-up 32-byte block hash (base58) for the v2 fixture
model = "z-ai/glm-5.3-flash"
acct = Account.from_key(bytes([7]) * 32)  # throwaway, not attested anywhere
items = [{"question": "Synthetic: what is 6 x 7? Answer with the number only.", "answer": "42", "answer_type": "numeric", "request_nonce": "11" * 32},
         {"question": "Synthetic: name the colour of a clear daytime sky. One word.", "answer": "blue", "answer_type": "exact", "accept": ["light blue"], "request_nonce": "22" * 32},
         {"question": "Synthetic: 1,000 plus 2,500? Number only.", "answer": "3500", "answer_type": "numeric", "tolerance": "0", "request_nonce": "33" * 32}]
answers = ["**42**", "Blue.", "3,500"]
pol = P.make_policy(3, {model: {"max_tokens": 64, "temperature": 0}}, tee_wasm=("ab" * 32 if V2 else None), e2ee=V3)
st = {"policy": pol, "items": [{"item": it, "salt": f"{i + 1:02x}" * 32} for i, it in enumerate(items)], "runs": {model: {"rows": []}},
      "seal": {"block_hash": SEAL_HASH}}
if V3:  # the throwaway signing key is also the model's E2EE key, as on NEAR AI Cloud
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from eth_keys import keys as eth_keys
    from fuin import e2ee
    PUB64 = eth_keys.PrivateKey(bytes([7]) * 32).public_key.to_bytes()
    st["runs"][model].update({"signer": acct.address.lower(), "model_report": {"model_attestations": [
        {"signing_address": acct.address.lower(), "signing_public_key": PUB64.hex()}]}})

    def model_encrypts(text, salt, i):  # what the model's TEE does with its answer; fixed randomness keeps the fixture stable
        eph = ec.derive_private_key(int.from_bytes(core.sha256(b"fixture-model-eph", bytes([i])), "big") % (e2ee.N - 1) + 1, ec.SECP256K1())
        nonce = core.sha256(b"fixture-model-nonce", bytes([i]))[:12]
        ct = AESGCM(e2ee._kdf(eph, e2ee._pub(e2ee.client_pub(salt, model)))).encrypt(nonce, text.encode(), None)
        return (eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint) + nonce + ct).hex()
bleaves, rleaves, total = [], [], 0
for i, (r, ans) in enumerate(zip(st["items"], answers)):
    req, _ = inference.sealed_request(pol, model, r, SEAL_HASH, PUB64 if V3 else None)
    if V3:  # item 2's answer is encrypted to another item's key: unreadable, so it must score 0 everywhere
        ans = model_encrypts(ans, bytes.fromhex(st["items"][1 if i == 2 else i]["salt"]), i)
    resp = json.dumps({"id": f"chatcmpl-{i}", "choices": [{"index": 0, "message": {"role": "assistant", "content": ans}, "finish_reason": "stop"}]}).encode()
    text = inference.signature_text(model, req, resp)
    sig = acct.sign_message(encode_defunct(text=text))
    signature = {"text": text, "signature": "0x" + sig.signature.hex(), "signing_address": acct.address.lower(), "signature_kind": "provider_tee", "signing_algo": "ecdsa"}
    score = P.scorer_for(pol).score_response(r["item"], e2ee.decrypted_response(resp, bytes.fromhex(r["salt"]), model) if V3 else resp)
    bl = core.benchmark_leaf(i, bytes.fromhex(r["salt"]), r["item"])
    rleaves.append(core.run_leaf(i, bl, core.sha256(req), core.sha256(resp), score)); bleaves.append(bl); total += score
    st["runs"][model]["rows"].append({"i": i, "request_b64": tee.b64(req), "response_b64": tee.b64(resp), "signature": signature})
expected = {"model": model, "n": 3, "total": total, "benchmark_root": core.merkle_root(bleaves).hex(), "policy_hash": P.policy_hash(pol),
            "run_root": core.merkle_root(rleaves).hex(), "signer": acct.address.lower(), **({"seal_block_hash": SEAL_HASH} if V2 else {}),
            **({"unreadable": 1} if V3 else {})}  # item 2's answer is encrypted to another key (scorer v4 counts it)
out = Path(__file__).resolve().parents[1] / f"tests/fixtures/tee-synthetic-round{'-v3' if V3 else '-v2' if V2 else ''}.json"
out.write_text(json.dumps({"round": tee.plaintext(st, model), "expected": expected}, ensure_ascii=False, indent=1) + "\n")
print(f"wrote {out.name}: total {total}/3, signer {acct.address.lower()}")
