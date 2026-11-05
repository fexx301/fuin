"""Request template v3: the question and the answer travel end-to-end encrypted between the owner and the model's TEE.

NEAR AI Cloud's E2EE on the model's attested secp256k1 key (headers X-Signing-Algo: ecdsa, X-Client-Pub-Key,
X-Model-Pub-Key): ECDH, HKDF-SHA256 (no salt, info "ecdsa_encryption", 32 bytes), AES-256-GCM, wire format
hex(ephemeral public key, 65 bytes ‖ nonce, 12 bytes ‖ ciphertext and tag). The model signs the encrypted bytes it
received and returned (evidence/2026-11-05-e2ee-probe/), so the signature check is unchanged.

Every random value derives from the item's secret salt, so whoever holds the salt (the verifier of a revealed item, the
TEE scorer) re-encrypts the question byte for byte, which pins exactly what the model decrypted, and decrypts the
answer. The gateway sees ciphertext for both.
"""
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from eth_keys import keys as eth_keys

from fuin.core import sha256

N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141  # secp256k1 group order
_X962 = (serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
MIN_BLOB = 65 + 12 + 16  # ephemeral key, nonce, GCM tag


def _seed(salt: bytes, model: str) -> bytes:
    return sha256(b"fuin-e2ee-v1", salt, model.encode())


def _secret(tag: bytes, salt: bytes, model: str) -> ec.EllipticCurvePrivateKey:
    x = int.from_bytes(sha256(tag, _seed(salt, model)), "big") % (N - 1) + 1  # a valid scalar in [1, N-1]
    return ec.derive_private_key(x, ec.SECP256K1())


def _kdf(priv: ec.EllipticCurvePrivateKey, pub: ec.EllipticCurvePublicKey) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"ecdsa_encryption").derive(priv.exchange(ec.ECDH(), pub))


def _pub(pub64: bytes) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), b"\x04" + pub64)


def model_pub(attestation: dict) -> bytes:
    """The model's 64-byte secp256k1 public key from its attestation report, checked against the attested address."""
    pub64 = bytes.fromhex(str(attestation["signing_public_key"]).removeprefix("0x")[-128:])
    if eth_keys.PublicKey(pub64).to_address().lower() != str(attestation["signing_address"]).lower():
        raise ValueError("signing_public_key is not the attested signer's key")
    return pub64


def client_pub(salt: bytes, model: str) -> bytes:
    return _secret(b"fuin-e2ee-client-v1", salt, model).public_key().public_bytes(*_X962)[1:]


def encrypt_question(question: str, salt: bytes, model: str, pub64: bytes) -> str:
    eph = _secret(b"fuin-e2ee-eph-v1", salt, model)
    nonce = sha256(b"fuin-e2ee-nonce-v1", _seed(salt, model))[:12]
    ct = AESGCM(_kdf(eph, _pub(pub64))).encrypt(nonce, question.encode(), None)
    return (eph.public_key().public_bytes(*_X962) + nonce + ct).hex()


def decrypt(blob_hex: str, salt: bytes, model: str) -> str | None:
    """A field the model encrypted to this item's client key; None if it isn't such a ciphertext."""
    if not isinstance(blob_hex, str) or len(blob_hex) % 2 or any(c not in "0123456789abcdefABCDEF" for c in blob_hex):
        return None  # strict hex only (bytes.fromhex would also skip whitespace), as the Rust and browser scorers read it
    try:
        b = bytes.fromhex(blob_hex)
        if len(b) < MIN_BLOB:
            return None
        key = _kdf(_secret(b"fuin-e2ee-client-v1", salt, model), _pub(b[1:65]) if b[0] == 4 else None)
        return AESGCM(key).decrypt(b[65:77], b[77:], None).decode("utf-8")
    except Exception:  # bad hex, not a curve point, failed tag or not UTF-8: not readable, so it scores 0
        return None


def decrypted_response(resp: bytes, salt: bytes, model: str) -> bytes:
    """The response with its answer decrypted, for the scorer: content becomes the plaintext, or "" when the content
    can't be decrypted (an unreadable answer scores 0). Anything that isn't a chat completion passes through unchanged."""
    try:
        j = json.loads(resp)
        msg = j["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        return resp
    if isinstance(msg, dict) and isinstance(msg.get("content"), str) and msg["content"]:
        msg["content"] = decrypt(msg["content"], salt, model) or ""
    return json.dumps(j, ensure_ascii=False, separators=(",", ":")).encode()


def headers(salt: bytes, model: str, pub64: bytes) -> dict:
    return {"X-Signing-Algo": "ecdsa", "X-Client-Pub-Key": client_pub(salt, model).hex(), "X-Model-Pub-Key": pub64.hex()}
