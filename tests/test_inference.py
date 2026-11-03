import hashlib

from eth_account import Account
from eth_account.messages import encode_defunct

from fuin import inference as I

ACCT = Account.from_key(bytes([7]) * 32)  # throwaway test key, not a real signer
MODEL = "Qwen/Qwen3.8-27B"
SETTINGS = {"max_tokens": 64, "temperature": 0}


def signed(req, resp, model=MODEL, acct=ACCT, kind="provider_tee"):
    text = I.signature_text(model, req, resp)
    s = acct.sign_message(encode_defunct(text=text))
    return {"text": text, "signature": "0x" + s.signature.hex(), "signing_address": acct.address,
            "signing_algo": "ecdsa", "signature_kind": kind}


def test_valid_signature():
    req, resp = I.build_request(MODEL, "q?", "ab" * 32, SETTINGS), b'{"id":"x"}'
    assert I.check_signature(signed(req, resp), MODEL, req, resp, ACCT.address) is None


def test_one_changed_byte_fails():
    req, resp = I.build_request(MODEL, "q?", "ab" * 32, SETTINGS), b'{"id":"x"}'
    sig = signed(req, resp)
    assert I.check_signature(sig, MODEL, req, resp[:-1] + b"]", ACCT.address) == "signature_text_mismatch"
    assert I.check_signature(sig, MODEL, req.replace(b"q?", b"Q?"), resp, ACCT.address) == "signature_text_mismatch"


def test_wrong_signer_and_kind_and_forgery():
    req, resp = b"r", b"s"
    other = Account.from_key(bytes([9]) * 32)
    assert I.check_signature(signed(req, resp, acct=other), MODEL, req, resp, ACCT.address) == "signer_not_attested_for_model"
    assert I.check_signature(signed(req, resp, kind="gateway"), MODEL, req, resp, ACCT.address) == "signature_text_mismatch"
    forged = {**signed(req, resp), "signing_address": other.address}
    assert I.check_signature(forged, MODEL, req, resp, other.address) == "bad_signature"


def test_nonce_blocks_hash_guessing():
    """Without the secret nonce, the right question under the sealed template doesn't give the signed request hash."""
    nonce = "5c" * 32
    signed_req = I.build_request(MODEL, "What is the NEAR yoctoNEAR exponent?", nonce, SETTINGS)
    guess = I.build_request(MODEL, "What is the NEAR yoctoNEAR exponent?", "00" * 32, SETTINGS)
    assert hashlib.sha256(guess).digest() != hashlib.sha256(signed_req).digest()
    assert I.build_request(MODEL, "What is the NEAR yoctoNEAR exponent?", nonce, SETTINGS) == signed_req
