"""NEAR access: reads over JSON-RPC (finalized), owner writes through near-cli-rs (keys stay in the OS keychain)."""

import base64
import json
import re
import subprocess
import time

import requests

NETWORKS = {"testnet": "https://rpc.testnet.near.org"}
# Verifier's trusted registry configuration (spec: Registry identity is pinned).
REGISTRY = {"network": "testnet", "account": "registry.fuin.testnet",
            "code_hash": "HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef"}


class RpcError(RuntimeError):
    pass


def rpc(method: str, params, network: str = "testnet") -> dict:
    for attempt in range(4):
        try:
            r = requests.post(NETWORKS[network], json={"jsonrpc": "2.0", "id": "fuin", "method": method, "params": params}, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                raise RpcError(f"HTTP {r.status_code}")
            d = r.json()
        except (requests.RequestException, ValueError, RpcError) as e:
            if attempt == 3:
                raise RpcError(f"{method}: {e}") from e
            time.sleep(1 + attempt)
            continue
        if "error" in d:
            raise RpcError(json.dumps(d["error"])[:300])
        return d["result"]
    raise AssertionError("unreachable")


def view(account: str, method: str, args: dict, network: str = "testnet"):
    res = rpc("query", {"request_type": "call_function", "finality": "final", "account_id": account,
                        "method_name": method, "args_base64": base64.b64encode(json.dumps(args).encode()).decode()}, network)
    return json.loads(bytes(res["result"]))


def code_hash(account: str, network: str = "testnet") -> str:
    return rpc("query", {"request_type": "view_account", "finality": "final", "account_id": account}, network)["code_hash"]


def access_key_count(account: str, network: str = "testnet") -> int:
    return len(rpc("query", {"request_type": "view_access_key_list", "finality": "final", "account_id": account}, network)["keys"])


def block(height: int | None = None, network: str = "testnet") -> dict | None:
    """Block header by height, or the latest final block. None if the RPC reports no block at that height."""
    try:
        res = rpc("block", {"block_id": height} if height is not None else {"finality": "final"}, network)
    except RpcError as e:
        if "UNKNOWN_BLOCK" in str(e):
            return None
        raise
    return res["header"]


def final_height(network: str = "testnet") -> int:
    return block(None, network)["height"]


def select_seed_block(threshold: int, network: str = "testnet", wait_s: int = 120) -> dict:
    """First existing finalized block with height >= threshold, proven by its parent height being below the threshold."""
    deadline = time.time() + wait_s
    while final_height(network) < threshold:
        if time.time() > deadline:
            raise RpcError("seed block not final yet")
        time.sleep(2)
    final = final_height(network)
    for h in range(threshold, final + 1):
        hdr = block(h, network)
        if hdr is None:
            continue  # search only; the parent-height check below is the proof
        if hdr["prev_height"] >= threshold:
            raise RpcError(f"block {h} has parent {hdr['prev_height']} >= threshold; an earlier block was missed")
        return hdr
    raise RpcError("no finalized block found at or after the threshold")


def check_seed_block(hdr: dict, threshold: int, network: str = "testnet") -> bool:
    """Is hdr the first existing block with height >= threshold, and final?"""
    return hdr["height"] >= threshold and hdr["prev_height"] < threshold and hdr["height"] <= final_height(network)


def tx_receipt(tx_hash: str, sender: str, executor: str, method: str, network: str = "testnet") -> dict:
    """The successful receipt that executed `method` on `executor`: {block_height, block_hash, value}."""
    res = rpc("EXPERIMENTAL_tx_status", {"tx_hash": tx_hash, "sender_account_id": sender, "wait_until": "FINAL"}, network)
    actions = {r["receipt_id"]: r.get("receipt", {}).get("Action", {}).get("actions", []) for r in res.get("receipts", [])}
    actions[res["transaction_outcome"]["outcome"]["receipt_ids"][0]] = res["transaction"]["actions"]  # first receipt
    for ro in res["receipts_outcome"]:
        out = ro["outcome"]
        if out["executor_id"] != executor:
            continue
        rc = actions.get(ro["id"], [])
        names = [a["FunctionCall"]["method_name"] for a in rc if isinstance(a, dict) and "FunctionCall" in a]
        if method not in names:
            continue
        st = out["status"]
        if "SuccessValue" not in st:
            raise RpcError(f"{method} receipt failed: {json.dumps(st)[:200]}")
        hdr = rpc("block", {"block_id": ro["block_hash"]}, network)["header"]
        val = base64.b64decode(st["SuccessValue"]).decode() if st["SuccessValue"] else ""
        return {"block_height": hdr["height"], "block_hash": ro["block_hash"], "value": val, "receipt_id": ro["id"]}
    raise RpcError(f"no {method} receipt on {executor} in {tx_hash}")


def call(signer: str, contract: str, method: str, args: dict, network: str = "testnet", deposit: str = "0.05 NEAR") -> str:
    """Sign and send a function call with near-cli-rs (keychain key). The registry keeps only its storage cost
    from `deposit` and refunds the rest. Returns the transaction hash."""
    cmd = ["near", "contract", "call-function", "as-transaction", contract, method, "json-args", json.dumps(args),
           "prepaid-gas", "30 Tgas", "attached-deposit", deposit, "sign-as", signer,
           "network-config", network, "sign-with-keychain", "send"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = p.stdout + p.stderr
    m = re.search(r"Transaction ID:\s*([1-9A-HJ-NP-Za-km-z]{43,44})", out)
    if not m:
        panic = re.search(r"Smart contract panicked: ([^\"\n]+)", out)
        raise RpcError(f"{method} rejected by the contract: {panic.group(1)}" if panic else f"{method} not sent: {out[-500:]}")
    return m.group(1)
