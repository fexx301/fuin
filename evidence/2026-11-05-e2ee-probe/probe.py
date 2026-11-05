"""E2EE probe (2026-11-05). Does NEAR AI Cloud's end-to-end encryption on ECDSA keys (the docs' "legacy" path,
X-Signing-Algo: ecdsa) keep Fūin's evidence intact?

With the question encrypted to the model's attested secp256k1 key:
 1. does the gateway carry only ciphertext for the question and the answer;
 2. does the answer come back encrypted to our key, and decrypt;
 3. does /v1/signature still return a provider_tee signature over sha256(exact request bytes):sha256(exact response
    bytes) that recovers to the attested signer?

Run: uv run --env-file .env python evidence/2026-11-05-e2ee-probe/probe.py [model]
One completion on a synthetic question. Writes result.json next to this file; never prints or stores the API key.
"""
import base64
import json
import os
import secrets
import sys
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from eth_keys import keys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from fuin import attestation, inference, owner  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "z-ai/glm-5.3-flash"
QUESTION = "Synthetic: what is 6 x 7? Answer with the number only."
X962 = (serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def kdf(shared: bytes) -> bytes:  # docs: HKDF-SHA256, no salt, info "ecdsa_encryption", 32 bytes
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"ecdsa_encryption").derive(shared)


def encrypt(pub64: bytes, plain: bytes) -> str:  # [ephemeral public (65)][nonce (12)][AES-256-GCM ciphertext+tag], hex
    eph = ec.generate_private_key(ec.SECP256K1())
    key = kdf(eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), b"\x04" + pub64)))
    nonce = os.urandom(12)
    return (eph.public_key().public_bytes(*X962) + nonce + AESGCM(key).encrypt(nonce, plain, None)).hex()


def decrypt(priv, blob_hex: str) -> bytes:
    b = bytes.fromhex(blob_hex)
    key = kdf(priv.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), b[:65])))
    return AESGCM(key).decrypt(b[65:77], b[77:], None)


nonce = secrets.token_hex(32)
report = inference.model_report(MODEL, nonce)
accepted = [c for c in report["model_attestations"]
            if attestation.check_report(c, nonce, owner.attestation_policy())["outcome"][0].startswith("accepted")]
assert accepted, "no model attestation accepted by the verifier's policy"
att = accepted[0]
pub64 = bytes.fromhex(att["signing_public_key"].removeprefix("0x")[-128:])
assert keys.PublicKey(pub64).to_address().lower() == att["signing_address"].lower(), "public key is not the attested signer's"

client = ec.generate_private_key(ec.SECP256K1())
client_pub64 = client.public_key().public_bytes(*X962)[1:]
req = json.dumps({"model": MODEL, "messages": [{"role": "user", "content": encrypt(pub64, QUESTION.encode())}], "stream": False,
                  "user": secrets.token_hex(32), "max_tokens": 2048, "temperature": 0}, separators=(",", ":")).encode()
r = requests.post(f"{inference.GATEWAY}/v1/chat/completions", data=req, timeout=(30, 600), headers={
    **inference._auth(), "Content-Type": "application/json", "x-no-aliasing": "true", "Accept-Encoding": "identity",
    "X-Signing-Algo": "ecdsa", "X-Client-Pub-Key": client_pub64.hex(), "X-Model-Pub-Key": pub64.hex()})
print("HTTP", r.status_code)
resp = r.content
out = {"model": MODEL, "attested_signer": att["signing_address"].lower(), "http_status": r.status_code,
       "request_b64": base64.b64encode(req).decode(), "response_b64": base64.b64encode(resp).decode(),
       "question_plaintext_in_request": QUESTION.encode() in req}
if r.ok:
    msg = r.json()["choices"][0]["message"]
    for field in ("content", "reasoning_content"):
        v = msg.get(field)
        if not v:
            continue
        try:
            out[f"{field}_decrypted"] = decrypt(client, v).decode()
            out[f"{field}_was_ciphertext"] = True
        except (ValueError, TypeError) as e:
            out[f"{field}_was_ciphertext"] = False
            out[f"{field}_error"] = type(e).__name__
    sig = inference.fetch_signature(r.json()["id"], MODEL)
    out["signature"] = sig
    out["signature_check"] = "valid" if sig and inference.check_signature(sig, MODEL, req, resp, att["signing_address"]) is None else (
        inference.check_signature(sig, MODEL, req, resp, att["signing_address"]) if sig else "no signature")
else:
    out["error_body"] = r.text[:500]
Path(__file__).with_name("result.json").write_text(json.dumps(out, indent=1) + "\n")
print(json.dumps({k: v for k, v in out.items() if not k.endswith("_b64") and k != "signature"}, indent=1)[:1500])
