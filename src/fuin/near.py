"""NEAR access: reads over JSON-RPC (finalized), owner writes through near-cli-rs (keys stay in the OS keychain)."""

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import requests

# rpc.testnet.near.org rate-limits hard (HTTP 429 after ~15 calls); FastNEAR's public testnet RPC did not, Nov 3
# Archival endpoints: a certificate cites blocks and transactions older than a regular node keeps (about two days on
# testnet; seen Nov 5: Nov 3 transactions already gone from the regular endpoints). FUIN_TESTNET_RPC pins one endpoint.
# NEAR's own archival-rpc.testnet.near.org answered only with a deprecation notice on Nov 6 but serves the full history
# again (checked Nov 7: the Nov 3 seal transaction and live blocks), so it is the fallback, tried on retries. A
# rate-limit or deprecation answer from either one moves on to the other instead of ending the check.
ARCHIVAL = ["https://archival-rpc.testnet.fastnear.com", "https://archival-rpc.testnet.near.org"]
NETWORKS = {"testnet": os.environ.get("FUIN_TESTNET_RPC", ARCHIVAL[0])}
# Verifier's trusted registry configuration (spec: Registry identity is pinned).
REGISTRY = {"network": "testnet", "account": "registry.fuin.testnet",
            "code_hash": "HvqaWNNceCX7AMtsanPobAt5mkAE2MsZdP2BURA2cgef"}


class RpcError(RuntimeError):
    pass


def _cached(method: str, params, network: str) -> Path | None:
    """With FUIN_CACHE_DIR set (scripts/review.sh sets it), answers that can never change are kept on disk: finalized
    transactions and anything asked at a fixed block. One review verifies 35 certificates and fixtures that share most of
    the same transactions, and the public RPC rate-limits the repeats. A plain `fuin verify` asks the network every time."""
    d = os.environ.get("FUIN_CACHE_DIR")
    fixed = method == "EXPERIMENTAL_tx_status" or (method in ("block", "query") and isinstance(params, dict) and params.get("block_id") is not None)
    if not d or not fixed:
        return None
    key = hashlib.sha256(json.dumps([NETWORKS.get(network, network), method, params], sort_keys=True).encode()).hexdigest()
    return Path(d) / "rpc" / f"{key}.json"


def _transient(err) -> bool:
    """A JSON-RPC error that says the endpoint is throttling or retired, not that the request is wrong."""
    s = json.dumps(err).upper()
    return (isinstance(err, dict) and err.get("code") == -429) or "DEPRECATED" in s or "TOO_MANY_REQUESTS" in s


def rpc(method: str, params, network: str = "testnet") -> dict:
    cache = _cached(method, params, network)
    if cache is not None and cache.exists():
        return json.loads(cache.read_text())
    attempts = 8  # public RPCs rate-limit (HTTP 429); back off about 1.5 minutes in total before giving up
    pinned = network != "testnet" or "FUIN_TESTNET_RPC" in os.environ
    urls = [NETWORKS[network]] + ([] if pinned else [u for u in ARCHIVAL if u != NETWORKS[network]])  # alternate on retries
    for attempt in range(attempts):
        wait = min(2 ** attempt, 30)
        try:
            r = requests.post(urls[attempt % len(urls)], json={"jsonrpc": "2.0", "id": "fuin", "method": method, "params": params}, timeout=30)
            if r.status_code in (429, 502, 503, 504):
                if r.headers.get("Retry-After", "").isdigit():
                    wait = min(int(r.headers["Retry-After"]), 30)
                raise RpcError(f"HTTP {r.status_code}")
            d = r.json()
            if "error" in d and _transient(d["error"]):  # a throttled or retired endpoint: try the other one
                raise RpcError(json.dumps(d["error"])[:200])
        except (requests.RequestException, ValueError, RpcError) as e:
            if attempt == attempts - 1:
                raise RpcError(f"{method}: {e} (set FUIN_TESTNET_RPC to another testnet RPC to retry elsewhere)") from e
            time.sleep(wait)
            continue
        if "error" in d:
            raise RpcError(json.dumps(d["error"])[:300])
        if cache is not None:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(d["result"]))
            except OSError:
                pass
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
    """The successful receipt that executed `method` on `executor`: {block_height, block_hash, value, receipt_id, args},
    where args are the function call's own JSON arguments as signed."""
    res = rpc("EXPERIMENTAL_tx_status", {"tx_hash": tx_hash, "sender_account_id": sender, "wait_until": "FINAL"}, network)
    actions = {r["receipt_id"]: r.get("receipt", {}).get("Action", {}).get("actions", []) for r in res.get("receipts", [])}
    actions[res["transaction_outcome"]["outcome"]["receipt_ids"][0]] = res["transaction"]["actions"]  # first receipt
    for ro in res["receipts_outcome"]:
        out = ro["outcome"]
        if out["executor_id"] != executor:
            continue
        rc = actions.get(ro["id"], [])
        calls = [a["FunctionCall"] for a in rc if isinstance(a, dict) and "FunctionCall" in a]
        call = next((c for c in calls if c.get("method_name") == method), None)
        if call is None:
            continue
        st = out["status"]
        if "SuccessValue" not in st:
            raise RpcError(f"{method} receipt failed: {json.dumps(st)[:200]}")
        hdr = rpc("block", {"block_id": ro["block_hash"]}, network)["header"]
        val = base64.b64decode(st["SuccessValue"]).decode() if st["SuccessValue"] else ""
        try:
            args = json.loads(base64.b64decode(call.get("args") or ""))
        except ValueError:
            args = None
        return {"block_height": hdr["height"], "block_hash": ro["block_hash"], "value": val, "receipt_id": ro["id"], "args": args}
    raise RpcError(f"no {method} receipt on {executor} in {tx_hash}")


# Owner writes are signed first and sent second. A transaction's hash is the sha256 of its unsigned bytes, so it is known,
# and can be saved, before anything reaches the chain: an interrupted command can then look its transaction up instead of
# losing it, and re-send the same signed bytes, which can execute at most once (see owner._registry_tx).
def sign(signer: str, contract: str, method: str, args: bytes, gas: str = "30 Tgas", deposit: str = "0.05 NEAR",
         network: str = "testnet") -> dict:
    """Sign a function call with near-cli-rs (keychain key) without sending it: {"tx": hash, "signed_b64": the signed bytes}."""
    from fuin import core
    with tempfile.NamedTemporaryFile(suffix=".args") as f:
        f.write(args); f.flush()
        cmd = ["near", "contract", "call-function", "as-transaction", contract, method, "file-args", f.name, "prepaid-gas", gas,
               "attached-deposit", deposit, "sign-as", signer, "network-config", network, "sign-with-keychain", "display"]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    out = p.stdout + p.stderr
    m = re.search(r"Signed transaction \(serialized as base64\):\s*([A-Za-z0-9+/=]+)", out)
    if not m:
        raise RpcError(f"{method} not signed: {out[-500:]}")
    raw = base64.b64decode(m.group(1))
    body = raw[:-65] if raw[-65] == 0 else raw[:-66]  # the signature ends the bytes: a type byte, then 64 (ed25519) or 65 (secp256k1)
    return {"tx": core.b58encode(hashlib.sha256(body).digest()), "signed_b64": m.group(1)}


def send(signed_b64: str, network: str = "testnet") -> str:
    """Broadcast a signed transaction and return its hash. Sending the same bytes again is safe: they execute at most once."""
    return rpc("broadcast_tx_async", [signed_b64], network)


def known(tx: str, sender: str, network: str = "testnet") -> bool:
    """Whether the chain has this transaction at all (in any state)."""
    try:
        rpc("tx", {"tx_hash": tx, "sender_account_id": sender, "wait_until": "NONE"}, network)
        return True
    except RpcError as e:
        if "UNKNOWN_TRANSACTION" in str(e):
            return False
        raise


def deliver(p: dict, sender: str, network: str = "testnet", wait_s: int = 90) -> bool:
    """Make sure a signed transaction is on the chain, sending it only if the chain doesn't have it yet. False when it
    didn't appear within `wait_s`: it expired, or another transaction used its nonce, so it can never execute."""
    if known(p["tx"], sender, network):
        return True
    try:
        got = send(p["signed_b64"], network)
    except RpcError as e:
        if "Expired" in str(e) or "InvalidNonce" in str(e):
            return False
        raise
    if got != p["tx"]:
        raise RpcError(f"the chain names this transaction {got}, not {p['tx']}")
    deadline = time.time() + wait_s
    while not known(p["tx"], sender, network):
        if time.time() > deadline:
            return False
        time.sleep(2)
    return True


def final_status(tx: str, sender: str, network: str = "testnet", wait_s: int = 420) -> dict:
    """The transaction's status once every receipt has executed and is final. An OutLayer task can take minutes."""
    deadline = time.time() + wait_s
    while True:
        try:
            return rpc("EXPERIMENTAL_tx_status", {"tx_hash": tx, "sender_account_id": sender, "wait_until": "FINAL"}, network)
        except RpcError as e:
            if not ("TIMEOUT" in str(e).upper() or "UNKNOWN_TRANSACTION" in str(e)) or time.time() > deadline:
                raise
            time.sleep(3)


def call(signer: str, contract: str, method: str, args: dict, network: str = "testnet", deposit: str = "0.05 NEAR") -> str:
    """Sign and send a function call, and return its hash once the chain has it. The registry keeps only its storage cost
    from `deposit` and refunds the rest."""
    p = sign(signer, contract, method, json.dumps(args).encode(), deposit=deposit, network=network)
    if not deliver(p, signer, network):
        raise RpcError(f"{method} not sent: the chain never showed {p['tx']}")
    final_status(p["tx"], signer, network)
    return p["tx"]
