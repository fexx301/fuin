"""Store the owner's NEAR AI key as an OutLayer secret for an asker project, so the enclave can make the model call.

Run it yourself (the assistant never handles the key):
    uv run --env-file .env python scripts/store_asker_secret.py --project ask.fuin.testnet/asker   # stores NEARAI_API_KEY from .env
    uv run python scripts/store_asker_secret.py --project ask.fuin.testnet/asker --dry-run         # dummy value; stores nothing

What happens:
1. Asks OutLayer (POST /secrets/pubkey: accessor, owner, profile) for the keystore's X25519 public key of the seed
   "project:<project>:<owner>".
   Only the variable NAME is sent there, with an empty value; the key itself is not.
2. Encrypts {"NEARAI_API_KEY": <key>} on this machine to that public key: ECIES v1 as the keystore decrypts it
   (keystore-worker/src/crypto.rs): 0x01 | ephemeral X25519 pub (32) | nonce (12) | ChaCha20-Poly1305 ciphertext+tag,
   key = HKDF-SHA256(shared, info "outlayer-keystore-v1").
3. Calls store_secrets on outlayer.testnet as the owner, readable only by runs of this project, and only when the
   caller is the owner (Whitelist [owner]); the keystore decrypts it inside its TEE for those runs alone.
Prints nothing secret. Undo (removes the stored secret, refunds its deposit):
    near contract call-function as-transaction outlayer.testnet delete_secrets json-args \
      '{"accessor":{"Project":{"project_id":"<the project>"}},"profile":"nearai"}' \
      prepaid-gas '100 Tgas' attached-deposit '0 NEAR' sign-as fuin.testnet network-config testnet sign-with-keychain send
"""
import base64
import json
import math
import os
import sys

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from fuin import near, tee

OWNER, PROFILE, VAR = "fuin.testnet", "nearai", "NEARAI_API_KEY"
PROJECT = sys.argv[sys.argv.index("--project") + 1] if "--project" in sys.argv else "fuin.testnet/fuin-ask-spike"


def ecies_v1(plain: bytes, pub_hex: str) -> bytes:
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(pub_hex)))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"outlayer-keystore-v1").derive(shared)
    nonce = os.urandom(12)
    eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b"\x01" + eph_pub + nonce + ChaCha20Poly1305(key).encrypt(nonce, plain, None)


def main() -> int:
    dry = "--dry-run" in sys.argv
    value = "x" * 64 if dry else os.environ.get(VAR, "")
    if not value:
        print(f"{VAR} is not set: run with --env-file .env", file=sys.stderr)
        return 2
    api = tee.tee_policy()["outlayer"]["api"]
    # the coordinator builds the keystore seed "project:<project>:<owner>" from these fields
    r = requests.post(f"{api}/secrets/pubkey", json={"accessor": {"type": "Project", "project_id": PROJECT}, "owner": OWNER,
                                                     "profile": PROFILE, "secrets_json": json.dumps({VAR: ""})}, timeout=60)
    if r.status_code != 200:
        print(f"keystore pubkey request failed: HTTP {r.status_code} {r.text[:300]}", file=sys.stderr)
        return 1
    pub = r.json()["pubkey"]
    assert len(bytes.fromhex(pub)) == 32, "unexpected pubkey length"
    blob = ecies_v1(json.dumps({VAR: value}).encode(), pub)
    assert blob[0] == 1 and len(blob) == 1 + 32 + 12 + len(json.dumps({VAR: value}).encode()) + 16
    args = {"accessor": {"Project": {"project_id": PROJECT}}, "profile": PROFILE,
            "encrypted_secrets_base64": base64.b64encode(blob).decode(), "access": {"Whitelist": {"accounts": [OWNER]}},
            "vault_id": None}
    contract = tee.tee_policy()["outlayer"]["contract"]
    cost = int(near.view(contract, "estimate_storage_cost", {**args, "owner": OWNER}))
    deposit = f"{math.ceil(cost / 1e18) / 1e6:.6f} NEAR"  # rounded up to the micro-NEAR
    print(f"keystore pubkey {pub[:12]}…; secret encrypted on this machine ({len(blob)} bytes); storage deposit {deposit}")
    if dry:
        print("dry run: nothing stored")
        return 0
    out = tee._near_file(OWNER, contract, "store_secrets", json.dumps(args).encode(), "100 Tgas", deposit)
    ok = "Transaction ID" in out and "Failure" not in out and "panicked" not in out
    print(("stored" if ok else "NOT stored") + f": profile '{PROFILE}' for {PROJECT}, readable only in runs called by {OWNER}")
    if not ok:
        print(out[-400:].replace(value, "<redacted>"), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
