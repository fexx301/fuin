"""Enclave-asked rounds (audit mode tee-asked-v1): the owner side.

The asker (ask/, a wasm32-wasip2 build pinned in policy/tee-v2.json `askers`) runs as an OutLayer project whose owner
account holds no keys, so its code and its storage can't be changed or wiped. For each sealed item it records the ask,
makes the one model call itself with the owner's NEAR AI key (an OutLayer secret), checks and scores the signed answer
and records it final; a second ask returns the recorded answer. No question, answer or response body leaves the enclave:
the owner gets each answer's hashes, score and signature, and the aggregate task attests the run's roots and total.
"""

import hashlib
import json
from pathlib import Path

import requests

from fuin import core, owner, tee
from fuin import policy as P


def askers() -> list[dict]:
    return tee.tee_policy().get("askers", [])


def asker_for(policy: dict) -> dict:
    a = policy["audit"]
    found = [x for x in askers() if x["wasm_sha256"] == a["asker_wasm_sha256"] and x["project"] == a["asker_project"]]
    if not found:
        raise SystemExit(f"the round sealed asker {a['asker_wasm_sha256'][:12]}… in {a['asker_project']}, which policy/tee-v2.json doesn't list")
    return found[0]


def secrets_ref(st: dict) -> dict:
    return {"profile": "nearai", "account_id": st["owner"]}


def keygen(owner_id: str, ak: dict) -> dict:
    """The asker's in-enclave key for this owner (sealed under the project's key: only the locked project's code opens it)."""
    # one per (owner, build, project): the secret is sealed under the project's key, so another project can't open it
    path = Path("private") / f"ask-key-{owner_id}-{ak['wasm_sha256'][:12]}-{ak['project'].replace('/', '_')}.json"
    if path.exists():
        return json.loads(path.read_text())
    tx, input_data, out = tee.execute(owner_id, {"mode": "keygen"}, ak, project=ak["project"])
    if "pub" not in out:
        raise RuntimeError(f"asker keygen failed: {out}")
    key = {"owner": owner_id, "wasm_sha256": ak["wasm_sha256"], "project": ak["project"], "pub": out["pub"], "sealed": out["sealed"],
           "transaction_hash": tx}
    path.write_text(json.dumps(key, indent=1))
    return key


def plaintext(st: dict, model: str, rn: dict) -> dict:
    """The sealed round as the asker reads it: tee.plaintext's fields without rows (the enclave makes them)."""
    return {"v": "fuin-tee-round-v1", "model": model, "policy_jcs": core.jcs(st["policy"]).decode(),
            **({"seal_block_hash": st["seal"]["block_hash"]} if P.is_seal_bound(st["policy"]) else {}),
            **({"model_pub": tee._signer_pub(rn).hex()} if P.is_e2ee(st["policy"]) else {}),
            "items": [{"salt": r["salt"], "item_jcs": core.jcs(r["item"]).decode()} for r in st["items"]]}


def _check_item(out: dict, st: dict, model: str, i: int, signer: str) -> dict:
    """An ask's output, checked before it is kept: this round, this item, this signer, a valid provider_tee signature."""
    from eth_account import Account
    from eth_account.messages import encode_defunct
    if out.get("v") != "fuin-ask-item-v1" or (out.get("model"), out.get("i"), out.get("benchmark_root")) != (model, i, st["seal"]["root"]):
        raise RuntimeError(f"item {i}: unexpected asker output {str(out)[:200]}")
    text = f"{model}:{out['req_sha256']}:{out['resp_sha256']}"
    who = Account.recover_message(encode_defunct(text=text), signature=out["signature"]).lower()
    if who != signer or str(out["signing_address"]).lower() != signer or out["score"] not in (0, 1):
        raise RuntimeError(f"item {i}: signature doesn't recover to the preflighted signer")
    return {"i": i, "req_sha256": out["req_sha256"], "resp_sha256": out["resp_sha256"], "score": out["score"],
            "unreadable": bool(out.get("unreadable")), "attempts": out.get("attempts"),
            "signature": {"text": text, "signature": out["signature"], "signing_address": out["signing_address"],
                          "signature_kind": "provider_tee", "signing_algo": "ecdsa"}}


def run(bid: str, model: str, host, tries: int = 3) -> dict:
    """Ask every item of this model's run inside the enclave, then have the enclave attest the run (aggregate)."""
    st = owner.load(bid)
    if not P.is_asked_round(st["policy"]):
        raise SystemExit("not an enclave-asked round (seal it with --ask)")
    if "seal" not in st:
        raise SystemExit("round not sealed yet")
    ak = asker_for(st["policy"])
    rn = owner.preflight(st, model)
    if "commit" in rn:
        raise SystemExit(f"{model} run already committed")
    key = keygen(st["owner"], ak)
    blob, eph_pub, nonce = tee.encrypt(tee.jdump(plaintext(st, model, rn)).encode(), key["pub"])
    url, encoding, cleanup = host(blob)  # one hosted ciphertext for every ask and the aggregate; deleted at the end
    try:
        served = requests.get(url, timeout=120).content
        base = {"url": url, "blob_sha256": hashlib.sha256(served).hexdigest(), "encoding": encoding, "sealed": key["sealed"],
                "eph_pub": eph_pub, "nonce": nonce}
        done = {r["i"] for r in rn["rows"]}
        for i in range(len(st["items"])):
            if i in done:
                continue
            for attempt in range(tries):  # a pending ask (nothing left the enclave) may be retried; the enclave counts it
                try:
                    tx, _, out = tee.execute(st["owner"], {"mode": "ask", **base, "i": i, "signer": rn["signer"]}, ak,
                                             project=ak["project"], secrets_ref=secrets_ref(st))
                    if "error" in out:
                        raise RuntimeError(out["error"])
                    row = _check_item(out, st, model, i, rn["signer"])
                    row["ask_tx"] = tx
                    break
                except RuntimeError as e:
                    rn["attempt_log"].append({"i": i, "attempt": attempt, "error": str(e)[:200]})
                    owner.save(st)
                    print(f"  {i}: attempt {attempt + 1} failed: {str(e)[:120]}", flush=True)
            else:
                raise SystemExit(f"item {i}: {tries} asks failed; rerun `fuin ask` to resume (a recorded answer is never re-asked)")
            rn["rows"].append(row)
            owner.save(st)
            print(f"  {i}: score {row['score']} (attempt {row['attempts']})", flush=True)
        tx, input_data, out = tee.execute(st["owner"], {"mode": "aggregate", **base}, ak, project=ak["project"])
    finally:
        if cleanup:
            cleanup()
    want = expected(st, model, rn)
    diff = {k: (out.get(k), v) for k, v in want.items() if out.get(k) != v}
    if out.get("v") != "fuin-tee-asked-v1" or diff:
        raise RuntimeError(f"asker aggregate differs from the asked rows: {out.get('error') or diff}")
    rn["tee_asked"] = {"v": "fuin-tee-asked-evidence-v1", "transaction_hash": tx, "input_data": input_data, "output": out,
                       "record": tee.fetch_record(tx), "scorer_url": ak["url"]}
    owner.save(st)
    rn["tee_asked_check"] = check(st, model, host)
    owner.save(st)
    return st


def check(st: dict, model: str, host) -> dict:
    """Have the scorer rebuild every request of the asked run with the true seal block hash (mode asked-check): each must
    equal the request the model signed, so every recorded ask came after the seal, and the roots must equal the run's."""
    rn = st["runs"][model]
    tp = tee.tee_policy()
    sc = next(x for x in reversed(tp["scorers"]) if x["wasm_sha256"] in tp.get("asked_checkers", []))
    rows = sorted(rn["rows"], key=lambda r: r["i"])
    plain = {**plaintext(st, model, rn), "signer": rn["signer"],
             "asked": [{"req_sha256": r["req_sha256"], "resp_sha256": r["resp_sha256"], "score": r["score"]} for r in rows]}
    tx, input_data, out = tee._sealed_task(st["owner"], host, sc, "asked-check", plain)
    want = {k: v for k, v in expected(st, model, rn).items() if k not in ("retried", "unreadable")}
    diff = {k: (out.get(k), v) for k, v in want.items() if out.get(k) != v}
    if out.get("v") != "fuin-tee-asked-check-v1" or diff:
        raise RuntimeError(f"asked-check differs from the asked run: {out.get('error') or diff}")
    return {"v": "fuin-tee-asked-check-evidence-v1", "transaction_hash": tx, "input_data": input_data, "output": out,
            "record": tee.fetch_record(tx), "scorer_url": sc["url"]}


def expected(st: dict, model: str, rn: dict) -> dict:
    """What a faithful aggregate must output, from the asked rows (the commit uses the same rows)."""
    rows = sorted(rn["rows"], key=lambda r: r["i"])
    bl = owner.benchmark_leaves(st)
    rl = [core.run_leaf(r["i"], bl[r["i"]], bytes.fromhex(r["req_sha256"]), bytes.fromhex(r["resp_sha256"]), r["score"]) for r in rows]
    out = {"model": model, "n": len(st["items"]), "total": sum(r["score"] for r in rows), "benchmark_root": st["seal"]["root"],
           "policy_hash": P.policy_hash(st["policy"]), "run_root": core.merkle_root(rl).hex(), "signer": rn["signer"],
           "retried": sum(max(0, (r.get("attempts") or 1) - 1) for r in rows)}
    if P.is_seal_bound(st["policy"]):
        out["seal_block_hash"] = st["seal"]["block_hash"]
    if P.is_e2ee(st["policy"]):
        out["unreadable"] = sum(1 for r in rows if r.get("unreadable"))
    return out
