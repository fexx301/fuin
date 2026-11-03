"""Owner workflow: seal → run → commit → close → reveal (spec: Registry and protocol). State stays in private/<id>/."""

import base64
import hashlib
import json
import os
from pathlib import Path

import requests

from fuin import attestation, core, inference, near
from fuin import policy as P

PRIVATE = Path("private")
ATTESTATION_POLICY = Path(__file__).resolve().parents[2] / "policy" / "attestation-v2.json"


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _path(bid: str) -> Path:
    return PRIVATE / bid / "state.json"


def load(bid: str) -> dict:
    return json.loads(_path(bid).read_text())


def save(st: dict) -> None:
    p = _path(st["benchmark_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(p)  # atomic: never leave half-written owner state


def attestation_policy() -> dict:
    return json.loads(ATTESTATION_POLICY.read_text())


def benchmark_leaves(st: dict) -> list[bytes]:
    return [core.benchmark_leaf(i, bytes.fromhex(r["salt"]), r["item"]) for i, r in enumerate(st["items"])]


def seal(suite_path: str, bid: str, owner: str, models: dict[str, dict]) -> dict:
    if _path(bid).exists():
        raise SystemExit(f"{bid} already exists in private/; seal is once per benchmark id")
    items = []
    for line in Path(suite_path).read_text().splitlines():
        if line.strip():
            q = core.loads_strict(line)
            q["request_nonce"] = os.urandom(32).hex()
            items.append({"item": q, "salt": os.urandom(32).hex()})
    n = len(items)
    pol = P.make_policy(n, models)
    st = {"benchmark_id": bid, "owner": owner, "registry": near.REGISTRY, "items": items, "policy": pol, "runs": {}}
    root = core.merkle_root(benchmark_leaves(st)).hex()
    print(f"Sealing {bid}: n={n}, audit reveals k={pol['audit']['k']} of {n} items per round (D={pol['audit']['D']}).")
    save(st)  # keep salts/nonces before the chain sees the root
    tx = near.call(owner, near.REGISTRY["account"], "seal",
                   {"benchmark_id": bid, "root": root, "n": n, "policy_hash": P.policy_hash(pol), "models": list(models)})
    rc = near.tx_receipt(tx, owner, near.REGISTRY["account"], "seal")
    st["seal"] = {"tx": tx, "height": rc["block_height"], "block_hash": rc["block_hash"], "root": root}
    save(st)
    return st


def run(bid: str, model: str) -> dict:
    st = load(bid)
    settings = st["policy"]["models"][model]
    rn = st["runs"].get(model)
    if rn is None:  # fresh run: preflight report with a new nonce
        nonce = os.urandom(32).hex()
        report = inference.model_report(model, nonce)
        accepted = [c for c in report["model_attestations"]
                    if attestation.check_report(c, nonce, attestation_policy())["outcome"][0].startswith("accepted")]
        if len(accepted) != 1:
            raise SystemExit(f"{model}: need exactly one accepted attestation candidate, got {len(accepted)}")
        rn = st["runs"][model] = {"preflight_nonce": nonce, "model_report": report,
                                  "signer": accepted[0]["signing_address"].lower(), "rows": [], "attempt_log": []}
        save(st)
    if "commit" in rn:
        raise SystemExit(f"{model} run already committed")
    for i in range(len(rn["rows"]), len(st["items"])):  # resume after the last saved row
        r = st["items"][i]
        req = inference.build_request(model, r["item"]["question"], r["item"]["request_nonce"], settings)
        for attempt in range(3):
            try:
                resp, parsed = inference.complete(req)
                break
            except (requests.RequestException, ValueError) as e:
                rn["attempt_log"].append({"i": i, "attempt": attempt, "error": str(e)[:200]})  # retries are recorded, not hidden
                save(st)
        else:
            raise SystemExit(f"item {i}: inference failed 3 times; rerun `fuin run` to resume")
        sig = inference.fetch_signature(parsed["id"], model)
        if sig is None:
            raise SystemExit(f"item {i}: signature unavailable; run incomplete, not certifiable")
        code = inference.check_signature(sig, model, req, resp, rn["signer"])
        if code:
            raise SystemExit(f"item {i}: {code}")
        score = P.scorer_for(st["policy"]).score_response(r["item"], resp)
        rn["rows"].append({"i": i, "request_b64": b64(req), "response_b64": b64(resp), "signature": sig, "score": score})
        save(st)
        print(f"  {i}: score {score}  finish {parsed['choices'][0].get('finish_reason')}", flush=True)
    return st


def run_leaves(st: dict, model: str) -> list[bytes]:
    bl = benchmark_leaves(st)
    return [core.run_leaf(r["i"], bl[r["i"]], hashlib.sha256(base64.b64decode(r["request_b64"])).digest(),
                          hashlib.sha256(base64.b64decode(r["response_b64"])).digest(), r["score"])
            for r in st["runs"][model]["rows"]]


def commit(bid: str, model: str) -> dict:
    st = load(bid)
    rn = st["runs"][model]
    if len(rn["rows"]) != len(st["items"]):
        raise SystemExit("incomplete run cannot be committed as n items")
    root = core.merkle_root(run_leaves(st, model)).hex()
    total = sum(r["score"] for r in rn["rows"])
    tx = near.call(st["owner"], near.REGISTRY["account"], "commit_run",
                   {"benchmark_id": bid, "model_id": model, "run_root": root, "total_score": total})
    rc = near.tx_receipt(tx, st["owner"], near.REGISTRY["account"], "commit_run")
    rn["commit"] = {"tx": tx, "height": rc["block_height"], "block_hash": rc["block_hash"],
                    "run_index": int(rc["value"]), "run_root": root, "total_score": total}
    save(st)
    print(f"Committed {model} run {rn['commit']['run_index']}: {total}/{len(st['items'])}")
    return st


def close(bid: str) -> dict:
    st = load(bid)
    tx = near.call(st["owner"], near.REGISTRY["account"], "close_round", {"benchmark_id": bid})
    rc = near.tx_receipt(tx, st["owner"], near.REGISTRY["account"], "close_round")
    st["close"] = {"tx": tx, "height": rc["block_height"], "block_hash": rc["block_hash"]}
    save(st)
    return st


def round_runs(record: dict) -> list[dict]:
    return sorted(({k: r[k] for k in ("model_id", "run_index", "run_root", "total_score")} for r in record["runs"]),
                  key=lambda r: (r["model_id"], r["run_index"]))


def audit_context(st_or_cert: dict, record: dict, close_block_hash: str) -> dict:
    reg = st_or_cert["registry"]
    return {"network": reg["network"], "registry": reg["account"], "owner": record["owner"],
            "benchmark_id": record["benchmark_id"], "benchmark_root": record["root"], "policy_hash": record["policy_hash"],
            "close_height": record["close_height"], "close_block_hash": close_block_hash, "runs": round_runs(record)}


def reveal(bid: str, out_dir: str) -> list[Path]:
    st = load(bid)
    record = near.view(near.REGISTRY["account"], "get_benchmark", {"owner": st["owner"], "benchmark_id": bid})
    if record is None or record["close_height"] is None:
        raise SystemExit("round not closed on chain")
    seed_hdr = near.select_seed_block(record["close_height"] + 2)
    ctx = audit_context(st, record, st["close"]["block_hash"])
    seed = core.audit_seed(near_b58decode(seed_hdr["hash"]), core.context_hash(ctx))
    n, k = len(st["items"]), st["policy"]["audit"]["k"]
    indices = core.sample_indices(seed, n, k)
    bl = benchmark_leaves(st)
    paths = []
    for model, rn in st["runs"].items():
        if "commit" not in rn:
            continue
        rl = run_leaves(st, model)
        rows = {r["i"]: r for r in rn["rows"]}
        cert = {
            "version": 1,
            "registry": {**near.REGISTRY, "owner": st["owner"]},
            "benchmark": {"id": bid, "root": st["seal"]["root"], "n": n, "models": list(st["policy"]["models"]),
                          "policy": st["policy"], "policy_hash": P.policy_hash(st["policy"]),
                          "seal_tx": st["seal"]["tx"], "seal_height": st["seal"]["height"], "seal_block_hash": st["seal"]["block_hash"]},
            "run": {"model_id": model, "run_index": rn["commit"]["run_index"], "preflight_nonce": rn["preflight_nonce"],
                    "model_report": rn["model_report"],
                    "evidence": {"owner_checked_policy_version": attestation_policy()["version"]},
                    "items": [{"i": i, "benchmark_leaf": bl[i].hex(),
                               "req_sha256": hashlib.sha256(base64.b64decode(rows[i]["request_b64"])).hexdigest(),
                               "resp_sha256": hashlib.sha256(base64.b64decode(rows[i]["response_b64"])).hexdigest(),
                               "score": rows[i]["score"], "signature": rows[i]["signature"]} for i in range(n)],
                    "run_root": rn["commit"]["run_root"], "total_score": rn["commit"]["total_score"],
                    "commit_tx": rn["commit"]["tx"], "commit_height": rn["commit"]["height"], "commit_block_hash": rn["commit"]["block_hash"]},
            "audit": {"D": st["policy"]["audit"]["D"], "target": st["policy"]["audit"]["target"], "k": k,
                      "close_tx": st["close"]["tx"], "close_height": st["close"]["height"], "close_block_hash": st["close"]["block_hash"],
                      "round_runs": round_runs(record), "seed_height": seed_hdr["height"], "seed_block_hash": seed_hdr["hash"],
                      "seed": seed.hex(), "indices": indices,
                      "reveals": [{"i": i, "item": st["items"][i]["item"], "salt": st["items"][i]["salt"],
                                   "request_b64": rows[i]["request_b64"], "response_b64": rows[i]["response_b64"],
                                   "proof_benchmark": [h.hex() for h in core.merkle_proof(bl, i)],
                                   "proof_run": [h.hex() for h in core.merkle_proof(rl, i)]} for i in indices]},
        }
        p = Path(out_dir) / f"cert-{bid}-{model.split('/')[-1].lower()}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(cert, indent=1, ensure_ascii=False) + "\n")
        paths.append(p)
    return paths


B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def near_b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw
