"""Signed inference through the NEAR AI Cloud gateway (spec: Protocol step 2).

Exact bytes: each request is built once, sent as-is, and the uncompressed response bytes are kept
before parsing. Signature text is `<model>:<sha256(request)>:<sha256(response)>` (provider_tee, EIP-191).
"""

import hashlib
import json
import os
import time

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

GATEWAY = "https://cloud-api.near.ai"


def _auth() -> dict:
    key = os.environ.get("NEARAI_API_KEY")
    if not key:
        raise SystemExit("NEARAI_API_KEY is not set (put it in .env and run with `uv run --env-file .env`)")
    return {"Authorization": f"Bearer {key}"}


def build_request(model: str, question: str, nonce_hex: str, settings: dict) -> bytes:
    """Sealed request template v1: one user message holding only the question; the nonce rides in `user`."""
    body = {"model": model, "messages": [{"role": "user", "content": question}], "stream": False,
            "user": nonce_hex, **settings}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def complete(request: bytes) -> tuple[bytes, dict]:
    r = requests.post(f"{GATEWAY}/v1/chat/completions", data=request, timeout=180, headers={
        **_auth(), "Content-Type": "application/json", "x-no-aliasing": "true", "Accept-Encoding": "identity"})
    r.raise_for_status()
    return r.content, r.json()


def fetch_signature(chat_id: str, model: str, tries: int = 8) -> dict | None:
    for t in range(tries):
        r = requests.get(f"{GATEWAY}/v1/signature/{chat_id}", params={"model": model, "signing_algo": "ecdsa"},
                         headers=_auth(), timeout=30)
        if r.status_code == 200 and "error_code" not in r.json():
            return r.json()
        time.sleep(1 + t)
    return None


def signature_text(model: str, request: bytes, response: bytes) -> str:
    return f"{model}:{hashlib.sha256(request).hexdigest()}:{hashlib.sha256(response).hexdigest()}"


def check_signature(sig: dict, model: str, request: bytes, response: bytes, signer: str) -> str | None:
    """None if valid, else the spec's reason code."""
    if sig.get("signature_kind") != "provider_tee" or sig.get("signing_algo", "ecdsa") != "ecdsa":
        return "signature_text_mismatch"
    if sig.get("text") != signature_text(model, request, response):
        return "signature_text_mismatch"
    try:
        recovered = Account.recover_message(encode_defunct(text=sig["text"]), signature=sig["signature"])
    except (ValueError, TypeError, KeyError):
        return "bad_signature"
    if recovered.lower() != str(sig.get("signing_address", "")).lower():
        return "bad_signature"
    if recovered.lower() != signer.lower():
        return "signer_not_attested_for_model"
    return None


def model_report(model: str, nonce_hex: str) -> dict:
    """Gateway model report (keyed fetch; embedded in certificates so readers need no key)."""
    r = requests.get(f"{GATEWAY}/v1/attestation/report", params={"model": model, "nonce": nonce_hex, "signing_algo": "ecdsa"},
                     headers=_auth(), timeout=120)
    r.raise_for_status()
    return r.json()
