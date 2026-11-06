"""Request template v3 (fuin/e2ee.py): the model's side is simulated with a throwaway key, using the scheme NEAR documents
and the probe confirmed (evidence/2026-11-05-e2ee-probe/)."""
import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from eth_keys import keys as eth_keys

from fuin import e2ee

MODEL = "z-ai/glm-5.3-flash"
SALT = bytes(range(32))
X962 = (serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
model_key = ec.generate_private_key(ec.SECP256K1())
PUB64 = model_key.public_key().public_bytes(*X962)[1:]


def model_decrypts(blob_hex):  # what the model's TEE does with the request content
    b = bytes.fromhex(blob_hex)
    return AESGCM(e2ee._kdf(model_key, e2ee._pub(b[1:65]))).decrypt(b[65:77], b[77:], None).decode()


def model_encrypts(text, client_pub64):  # what the model's TEE does with its answer
    eph, nonce = ec.generate_private_key(ec.SECP256K1()), os.urandom(12)
    ct = AESGCM(e2ee._kdf(eph, e2ee._pub(client_pub64))).encrypt(nonce, text.encode(), None)
    return (eph.public_key().public_bytes(*X962) + nonce + ct).hex()


def test_the_model_reads_the_question_and_encryption_is_reproducible():
    blob = e2ee.encrypt_question("What is 6 x 7?", SALT, MODEL, PUB64)
    assert model_decrypts(blob) == "What is 6 x 7?"
    assert e2ee.encrypt_question("What is 6 x 7?", SALT, MODEL, PUB64) == blob  # a verifier with the salt rebuilds it
    assert e2ee.encrypt_question("What is 6 x 7?", bytes(32), MODEL, PUB64) != blob
    assert e2ee.encrypt_question("What is 6 x 7?", SALT, "Qwen/Qwen3.8-27B", PUB64) != blob


def test_the_answer_decrypts_with_the_items_client_key():
    resp = json.dumps({"choices": [{"message": {"role": "assistant", "content": model_encrypts("42", e2ee.client_pub(SALT, MODEL))}}]}).encode()
    assert json.loads(e2ee.decrypted_response(resp, SALT, MODEL))["choices"][0]["message"]["content"] == "42"


def test_an_unreadable_answer_scores_0_whatever_the_item_accepts():
    from fuin import scorer
    for content in ("42", "zz", model_encrypts("42", e2ee.client_pub(bytes(32), MODEL))):  # plaintext, not hex, another key
        resp = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        readable = e2ee.decrypted_response(resp, SALT, MODEL)
        assert json.loads(readable)["choices"][0]["message"]["content"] is None
        assert scorer.score_response({"answer": "x", "answer_type": "exact", "accept": [""]}, readable) == 0  # not "" == ""


def test_the_model_key_must_be_the_attested_signers():
    addr = eth_keys.PublicKey(PUB64).to_address()
    assert e2ee.model_pub({"signing_public_key": PUB64.hex(), "signing_address": addr}) == PUB64
    with pytest.raises(ValueError):
        e2ee.model_pub({"signing_public_key": PUB64.hex(), "signing_address": "0x" + "11" * 20})
