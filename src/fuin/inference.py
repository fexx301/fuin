"""Signed inference through the NEAR AI Cloud gateway (spec: Protocol step 2).

Exact bytes: each request is built once, sent as-is, and the uncompressed response bytes are kept
before parsing. Signature text is `<model>:<sha256(request)>:<sha256(response)>` (provider_tee, EIP-191).
"""

import hashlib
import json
import os
import socket
import time

import requests
from eth_account import Account
from eth_account.messages import encode_defunct

GATEWAY = "https://cloud-api.near.ai"


class _KeepAlive(requests.adapters.HTTPAdapter):
    """TCP keepalive probes every 15 s after 30 s idle: a non-streaming answer can take minutes with no bytes on the wire,
    and NATs and mobile networks drop connections that look idle (round 4's and 5's 'Connection reset by peer')."""

    def init_poolmanager(self, *args, **kwargs):
        opts = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1), (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
        idle = getattr(socket, "TCP_KEEPIDLE", getattr(socket, "TCP_KEEPALIVE", None))  # Linux / macOS name
        opts += [(socket.IPPROTO_TCP, o, v) for o, v in ((idle, 30), (getattr(socket, "TCP_KEEPINTVL", None), 15),
                                                          (getattr(socket, "TCP_KEEPCNT", None), 8)) if o is not None]
        kwargs["socket_options"] = opts
        super().init_poolmanager(*args, **kwargs)


def _auth() -> dict:
    key = os.environ.get("NEARAI_API_KEY")
    if not key:
        raise SystemExit("NEARAI_API_KEY is not set (put it in .env and run with `uv run --env-file .env`)")
    return {"Authorization": f"Bearer {key}"}


def request_nonce(policy: dict, item: dict, seal_block_hash: str | None) -> str:
    """The nonce the sealed template puts in `user`: the item's own (v1) or one bound to the seal block (v2)."""
    from fuin import core
    if policy["request"]["template"] in ("fuin-request-v2", "fuin-request-v3"):
        return core.seal_bound_nonce(item["request_nonce"], seal_block_hash)
    return item["request_nonce"]


def sealed_request(policy: dict, model: str, row: dict, seal_block_hash: str | None, pub64: bytes | None = None) -> tuple[bytes, dict]:
    """The exact request bytes the sealed template prescribes for one item ({"item", "salt"}), and its extra headers.
    Template v3 encrypts the question to the model's attested key (pub64) with randomness derived from the salt."""
    from fuin import e2ee
    item, settings = row["item"], policy["models"][model]
    nonce = request_nonce(policy, item, seal_block_hash)
    if policy["request"]["template"] == "fuin-request-v3":
        salt = bytes.fromhex(row["salt"])
        return build_request(model, e2ee.encrypt_question(item["question"], salt, model, pub64), nonce, settings), e2ee.headers(salt, model, pub64)
    return build_request(model, item["question"], nonce, settings), {}


def build_request(model: str, question: str, nonce_hex: str, settings: dict) -> bytes:
    """Sealed request template v1: one user message holding only the question; the nonce rides in `user`."""
    body = {"model": model, "messages": [{"role": "user", "content": question}], "stream": False,
            "user": nonce_hex, **settings}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def complete(request: bytes, extra_headers: dict | None = None) -> tuple[bytes, dict]:
    # long reasoning (up to max_tokens) under parallel load can take many minutes; a short read timeout
    # abandons answers NEAR keeps generating (and bills), so wait long enough for the cap to be reached
    with requests.Session() as s:
        s.mount("https://", _KeepAlive())
        r = s.post(f"{GATEWAY}/v1/chat/completions", data=request, timeout=(30, 1200), headers={
            **_auth(), "Content-Type": "application/json", "x-no-aliasing": "true", "Accept-Encoding": "identity", **(extra_headers or {})})
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
