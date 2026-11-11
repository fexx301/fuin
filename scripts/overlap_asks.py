"""Rehearsal driver for the asker's record protocol on OutLayer's real storage: K asks of ONE item in ONE transaction,
so they reach the enclave together, which `fuin ask` never does. Prints what each ask returned and the record's count.

    uv run --env-file .env python scripts/overlap_asks.py ROUND MODEL ITEM [K]     (owner only: signs a testnet tx)

What to read from it (ask/src/record.rs): an ask that lost its claim made no model call; "record changed during the
ask" made one that was not kept. The final record's `attempts` must be at least 1 + the number of those.
"""
import base64
import hashlib
import json
import subprocess
import sys

import requests

from fuin import asker, near, owner, tee


def main() -> int:
    bid, model, i, k = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 2
    st = owner.load(bid)
    ak, rn = asker.asker_for(st["policy"]), owner.preflight(st, model)
    key = asker.keygen(st["owner"], ak)
    blob, eph_pub, nonce = tee.encrypt(tee.jdump(asker.plaintext(st, model, rn)).encode(), key["pub"])
    url = tee.fastfs_upload(st["owner"], blob, "bin", "application/octet-stream")
    inp = {"mode": "ask", "url": url, "blob_sha256": hashlib.sha256(requests.get(url, timeout=120).content).hexdigest(), "encoding": "raw",
           "sealed": key["sealed"], "eph_pub": eph_pub, "nonce": nonce, "i": i, "signer": rn["signer"]}
    # the same arguments as tee.request, K times in one transaction (a transaction's gas limit is 300 Tgas in all)
    args = json.dumps({"source": {"Project": {"project_id": ak["project"], "version_key": ak["wasm_sha256"]}},
                       "resource_limits": {"max_instructions": 100_000_000_000, "max_memory_mb": 512, "max_execution_seconds": 180},
                       "input_data": tee.jdump(inp), "response_format": "Json", "secrets_ref": asker.secrets_ref(st)})
    contract = tee.tee_policy()["outlayer"]["contract"]
    cmd = ["near", "transaction", "construct-transaction", st["owner"], "receiver-id", contract]
    for _ in range(k):
        cmd += ["add-action", "function-call", "request_execution", "json-args", args, "prepaid-gas", f"{300 // k} Tgas",
                "attached-deposit", "0.1 NEAR"]
    out = subprocess.run(cmd + ["skip", "network-config", "testnet", "sign-with-keychain", "send"], capture_output=True, text=True, timeout=900)
    tx = next((w.strip() for line in (out.stdout + out.stderr).splitlines() if "Transaction ID" in line for w in [line.split(":")[-1]]), None)
    if not tx:
        print((out.stdout + out.stderr)[-800:])
        return 1
    print(f"tx {tx}: {k} asks of item {i}")
    for r in near.final_status(tx, st["owner"])["receipts_outcome"]:
        val = r["outcome"]["status"].get("SuccessValue")
        logs = [x for x in r["outcome"].get("logs", []) if "xecution" in x and "ailed" in x]
        if val:
            try:
                o = json.loads(base64.b64decode(val))
                o = json.loads(o) if isinstance(o, str) else o
            except ValueError:
                continue
            if isinstance(o, dict) and ("v" in o or "error" in o):
                print("  ", o.get("error") or f"final: score {o['score']}, attempts {o['attempts']}")
        for x in logs:
            print("   failed:", x[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
