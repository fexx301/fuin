"""Owner workflow: seal → run → commit → close → reveal (spec: Registry and protocol). State stays in private/<id>/."""

import base64
import hashlib
import json
import os
import re
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import requests

from fuin import attestation, core, e2ee, inference, near
from fuin import POLICY
from fuin import policy as P

PRIVATE = Path("private")
ATTESTATION_POLICY = POLICY / "attestation-v10.json"


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _path(bid: str) -> Path:
    # a round id names a folder under private/: no separators or "..", so it can't reach outside it (review 11)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", bid) or ".." in bid:
        raise SystemExit(f"round id {bid!r}: use 1-64 letters, digits, '.', '_' or '-', starting with a letter or digit")
    return PRIVATE / bid / "state.json"


def load(bid: str) -> dict:
    return json.loads(_path(bid).read_text())


def lock(bid: str):
    """Hold an exclusive lock on one round until the process exits. Two commands writing the same state.json at once
    silently lose runs (each rewrites the whole file), so a second one stops instead."""
    import fcntl
    p = _path(bid).parent / ".lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    f = open(p, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        raise SystemExit(f"another fuin command is writing round {bid}: wait for it to finish. Run models one after another "
                         "(use --parallel for speed within one run).") from None
    return f


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


def _registry_tx(st: dict, key: str, method: str, args: dict, landed) -> dict:
    """Send one registry transaction so that an interruption can neither lose it nor send it twice.

    The transaction is signed, and its hash and signed bytes are saved in private state, before it is sent. A rerun finds
    that pending transaction and looks it up; if the chain doesn't have it, the same signed bytes are sent again, and the
    same bytes can execute at most once. A new transaction is signed only when the pending one can no longer execute and
    `landed()` shows the registry doesn't already hold this step's effect. Returns the successful receipt, with "tx"."""
    acct, pend = near.REGISTRY["account"], st.setdefault("pending", {})
    p = pend.get(key)
    if p and p["args"] != args:
        raise SystemExit(f"{key}: private state holds a pending transaction {p['tx']} with other arguments; nothing was sent. "
                         "Inspect private state before going on.")
    if p and not near.deliver(p, st["owner"]):
        del pend[key]; save(st)  # it expired or its nonce was used: it can never execute
        p = None
    if p is None:
        if landed():
            raise SystemExit(f"{key}: the registry already holds this, but private state has no transaction for it, so nothing "
                             "was sent (a second one would duplicate it). Check `fuin status`, and the owner's transactions in "
                             "an explorer.")
        p = {**near.sign(st["owner"], acct, method, json.dumps(args).encode()), "args": args}
        pend[key] = p; save(st)  # on disk before the chain sees it
        if not near.deliver(p, st["owner"]):
            raise SystemExit(f"{key}: the transaction didn't reach the chain; run the same command again")
    else:
        print(f"{key}: resuming with the transaction signed earlier ({p['tx']})")
    try:
        near.final_status(p["tx"], st["owner"])
        rc = near.tx_receipt(p["tx"], st["owner"], acct, method)
    except near.RpcError as e:
        if "receipt" in str(e):  # it executed and the contract refused it: that verdict is final
            del pend[key]; save(st)
            raise SystemExit(f"{key}: {e}")
        raise
    del pend[key]  # the caller records the receipt and saves once, so the two change together
    return {"tx": p["tx"], **rc}


def _registry_record(st: dict) -> dict | None:
    return near.view(near.REGISTRY["account"], "get_benchmark", {"owner": st["owner"], "benchmark_id": st["benchmark_id"]})


def seal(suite_path: str, bid: str, owner: str, models: dict[str, dict], tee_wasm: str | None = None, encrypt: bool = False,
         asker: tuple[str, str] | None = None) -> dict:
    suite = [core.loads_strict(line) for line in Path(suite_path).read_text().splitlines() if line.strip()]
    n = len(suite)
    pol = P.make_policy(n, models, tee_wasm=tee_wasm, e2ee=encrypt, asker=asker)
    if _path(bid).exists():
        st = load(bid)
        if "seal" in st:
            raise SystemExit(f"{bid} is already sealed (tx {st['seal']['tx']}); seal is once per benchmark id")
        # an interrupted seal: finish it with the salts and nonces saved then, never new ones
        saved = [{k: v for k, v in x["item"].items() if k != "request_nonce"} for x in st["items"]]
        if saved != suite or st["policy"] != pol or st["owner"] != owner:
            raise SystemExit(f"private/{bid} holds an unfinished seal of a different suite, policy or owner. Finish that one "
                             "with its original arguments, or seal under a new --id.")
        print(f"Resuming the interrupted seal of {bid} with its saved salts and nonces")
        items = st["items"]
    else:
        items = [{"item": {**q, "request_nonce": os.urandom(32).hex()}, "salt": os.urandom(32).hex()} for q in suite]
        st = {"benchmark_id": bid, "owner": owner, "registry": near.REGISTRY, "items": items, "policy": pol, "runs": {}}
    root = core.merkle_root(benchmark_leaves(st)).hex()
    disclosure = (f"asked once per item inside the TEE by asker {asker[0][:12]}… in {asker[1]}, nothing revealed." if asker
                  else f"TEE-scored by scorer {tee_wasm[:12]}…, nothing revealed." if tee_wasm
                  else f"audit reveals k={pol['audit']['k']} of {n} items per round (D={pol['audit']['D']}).")
    print(f"Sealing {bid}: n={n}, {disclosure}" + (" Questions and answers end-to-end encrypted (template v3)." if encrypt else ""))
    save(st)  # keep salts/nonces before the chain sees the root
    rc = _registry_tx(st, "seal", "seal", {"benchmark_id": bid, "root": root, "n": n, "policy_hash": P.policy_hash(pol),
                                           "models": list(models)}, lambda: _registry_record(st) is not None)
    st["seal"] = {"tx": rc["tx"], "height": rc["block_height"], "block_hash": rc["block_hash"], "root": root}
    save(st)
    return st


def preflight(st: dict, model: str) -> dict:
    """The run's record, created on first use: a fresh attestation report with a new nonce, and its one accepted signer."""
    rn = st["runs"].get(model)
    if rn is None:  # fresh run: preflight report with a new nonce
        nonce = os.urandom(32).hex()
        report = inference.model_report(model, nonce)
        checked = [(c, attestation.check_report(c, nonce, attestation_policy())) for c in report["model_attestations"]]
        accepted = [c for c, res in checked if res["outcome"][0].startswith("accepted")]
        if len(accepted) != 1:  # say why for each candidate: an unreachable Intel or NVIDIA service looks nothing like a bad quote
            why = "; ".join(f"{str(c.get('signing_address', '?'))[:12]}: {'/'.join(res['outcome'])}" + (f" ({res['error'][:300]})" if res.get("error") else "")
                            for c, res in checked) or "the report lists no candidates"
            hint = (" A service the check needs was unreachable: see the network list in PILOT.md section 1."
                    if any(res["outcome"][-1] == "evidence_unavailable" for _, res in checked) else "")
            raise SystemExit(f"{model}: need exactly one accepted attestation candidate, got {len(accepted)} ({why}).{hint}")
        rn = st["runs"][model] = {"preflight_nonce": nonce, "model_report": report, "policy_version": attestation_policy()["version"],
                                  "signer": accepted[0]["signing_address"].lower(), "rows": [], "attempt_log": []}
        save(st)
    return rn


def run(bid: str, model: str, parallel: int = 1, max_spend: float | None = None) -> dict:
    from fuin import cost
    st = load(bid)
    if P.is_asked_round(st["policy"]):
        raise SystemExit("this round's answers are asked inside the enclave: use `fuin ask`")
    rn = preflight(st, model)
    if "commit" in rn:
        raise SystemExit(f"{model} run already committed")

    e2ee_on = P.is_e2ee(st["policy"])  # template v3: questions and answers encrypted to the attested signer's key
    pub64 = e2ee.model_pub(next(c for c in rn["model_report"]["model_attestations"] if c["signing_address"].lower() == rn["signer"])) if e2ee_on else None

    budget, pr = cost.budget(st, max_spend)  # --max-spend: every attempt reserves its bound before it is sent
    cap = st["policy"]["models"][model]["max_tokens"]

    def answer(i: int) -> tuple[dict | None, list[dict], str | None]:
        """One item: (row or None, attempt-log entries, error). Runs in a worker thread; shares only the locked budget."""
        r, log = st["items"][i], []
        req, extra = inference.sealed_request(st["policy"], model, r, st.get("seal", {}).get("block_hash"), pub64)
        worst = cost.bound(r["item"]["question"], cap, pr[model]) if budget else None
        for attempt in range(cost.ATTEMPTS):
            if budget and not budget.reserve(worst):  # a stop at the limit is not a failed attempt: nothing goes in the log
                return None, log, budget.stop(f"item {i}")
            try:
                resp, parsed = inference.complete(req, extra)
                if budget:  # a finished call counts at its measured tokens; a failed one stays at its bound
                    u = parsed.get("usage") or {}
                    budget.settle(worst, (u.get("prompt_tokens") or 0) * pr[model][0] + (u.get("completion_tokens") or 0) * pr[model][1])
                break
            except (requests.RequestException, ValueError) as e:
                log.append({"i": i, "attempt": attempt, "error": str(e)[:200]})  # retries are recorded, not hidden
        else:
            return None, log, f"item {i}: inference failed 3 times; rerun `fuin run` to resume"
        sig = inference.fetch_signature(parsed["id"], model)
        if sig is None:
            return None, log, f"item {i}: signature unavailable; run incomplete, not certifiable"
        code = inference.check_signature(sig, model, req, resp, rn["signer"])
        if code:
            return None, log, f"item {i}: {code}"
        readable = e2ee.decrypted_response(resp, bytes.fromhex(r["salt"]), model) if e2ee_on else resp
        score = P.scorer_for(st["policy"]).score_response(r["item"], readable)
        row = {"i": i, "request_b64": b64(req), "response_b64": b64(resp), "signature": sig, "score": score}
        print(f"  {i}: score {score}  finish {parsed['choices'][0].get('finish_reason')}", flush=True)
        return row, log, None

    n, width = len(st["items"]), max(1, parallel)
    # answers that completed after an earlier failure are signed and checked: kept as pending and used on resume, not re-asked
    done = {int(i): row for i, row in rn.get("pending", {}).items()}
    nxt, failed = len(rn["rows"]), None  # rolling window: a new question starts as soon as any finishes
    with ThreadPoolExecutor(max_workers=width) as pool:
        inflight = {}
        while inflight or (failed is None and nxt < n):
            while failed is None and nxt < n and len(inflight) < width:
                if nxt not in done:
                    inflight[pool.submit(answer, nxt)] = nxt
                nxt += 1
            finished, _ = wait(inflight, return_when=FIRST_COMPLETED)
            for f in finished:
                i = inflight.pop(f)
                row, log, err = f.result()
                rn["attempt_log"].extend(log)
                if err and (failed is None or i < failed[0]):
                    failed = (i, err)
                elif not err:
                    done[i] = row
            while len(rn["rows"]) in done and (failed is None or len(rn["rows"]) < failed[0]):
                rn["rows"].append(done.pop(len(rn["rows"])))  # save strictly in index order
            rn["pending"] = {str(i): row for i, row in sorted(done.items())}
            save(st)
    if failed:
        raise SystemExit(failed[1] + (f" ({len(done)} later answers kept for the resume)" if done else ""))
    rn.pop("pending", None)
    save(st)
    return st


def row_shas(r: dict) -> tuple[str, str]:
    """A row's request and response sha256: from its bytes, or as recorded for an enclave-asked row (no bytes left the enclave)."""
    if "request_b64" in r:
        return (hashlib.sha256(base64.b64decode(r["request_b64"])).hexdigest(), hashlib.sha256(base64.b64decode(r["response_b64"])).hexdigest())
    return r["req_sha256"], r["resp_sha256"]


def run_leaves(st: dict, model: str) -> list[bytes]:
    bl = benchmark_leaves(st)
    return [core.run_leaf(r["i"], bl[r["i"]], bytes.fromhex(row_shas(r)[0]), bytes.fromhex(row_shas(r)[1]), r["score"])
            for r in st["runs"][model]["rows"]]


def commit(bid: str, model: str) -> dict:
    st = load(bid)
    rn = st["runs"][model]
    if len(rn["rows"]) != len(st["items"]):
        raise SystemExit("incomplete run cannot be committed as n items")
    if "commit" in rn:  # the registry numbers every commit, so a second one would publish a duplicate run
        raise SystemExit(f"{model} is already committed (run {rn['commit']['run_index']}, tx {rn['commit']['tx']})")
    root = core.merkle_root(run_leaves(st, model)).hex()
    total = sum(r["score"] for r in rn["rows"])
    same = lambda: any(r["model_id"] == model and r["run_root"] == root and r["total_score"] == total
                       for r in (_registry_record(st) or {}).get("runs", []))
    rc = _registry_tx(st, f"commit {model}", "commit_run",
                      {"benchmark_id": bid, "model_id": model, "run_root": root, "total_score": total}, same)
    rn["commit"] = {"tx": rc["tx"], "height": rc["block_height"], "block_hash": rc["block_hash"],
                    "run_index": int(rc["value"]), "run_root": root, "total_score": total}
    save(st)
    print(f"Committed {model} run {rn['commit']['run_index']}: {total}/{len(st['items'])}")
    return st


def close(bid: str) -> dict:
    st = load(bid)
    if "close" in st:
        raise SystemExit(f"{bid} is already closed (tx {st['close']['tx']})")
    rc = _registry_tx(st, "close", "close_round", {"benchmark_id": bid},
                      lambda: bool((_registry_record(st) or {}).get("close_height")))
    st["close"] = {"tx": rc["tx"], "height": rc["block_height"], "block_hash": rc["block_hash"]}
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


def cert_name(model: str, models: list[str]) -> str:
    """The model's part of a certificate file name: its last path segment, or its whole id when another model in the round
    shares that segment, so one certificate can't overwrite another (review 12)."""
    last = model.split("/")[-1].lower()
    clash = sum(m.split("/")[-1].lower() == last for m in models) > 1
    return model.replace("/", "--").lower() if clash else last


def reveal(bid: str, out_dir: str) -> list[Path]:
    st = load(bid)
    record = near.view(near.REGISTRY["account"], "get_benchmark", {"owner": st["owner"], "benchmark_id": bid})
    if record is None or record["close_height"] is None:
        raise SystemExit("round not closed on chain")
    tee_round = P.is_tee_round(st["policy"])
    n, k = len(st["items"]), st["policy"]["audit"]["k"]
    if tee_round:  # no sample: every committed run must carry its TEE score
        need = "tee_asked" if P.is_asked_round(st["policy"]) else "tee_score"
        missing = [m for m, rn in st["runs"].items() if "commit" in rn and not rn.get(need)]
        if missing:
            raise SystemExit(f"zero-reveal round: run `fuin {'ask' if need == 'tee_asked' else 'tee-score'}` for {', '.join(missing)} first")
        seed_hdr, seed, indices = None, None, []
    else:
        seed_hdr = near.select_seed_block(record["close_height"] + 2)
        ctx = audit_context(st, record, st["close"]["block_hash"])
        seed = core.audit_seed(near_b58decode(seed_hdr["hash"]), core.context_hash(ctx))
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
                    "evidence": {"owner_checked_policy_version": rn.get("policy_version", "not recorded"),
                                 # owner-reported, not verifiable: failed inference attempts before each saved row
                                 "attempt_log": rn.get("attempt_log", []),
                                 **({"tee_score": rn["tee_score"]} if rn.get("tee_score") else {}),
                                 **({"tee_asked": rn["tee_asked"]} if rn.get("tee_asked") else {}),
                                 **({"tee_asked_check": rn["tee_asked_check"]} if rn.get("tee_asked_check") else {}),
                                 **({"tee_ground": st["tee_ground"]} if st.get("tee_ground") else {})},
                    "items": [{"i": i, "benchmark_leaf": bl[i].hex(),
                               "req_sha256": row_shas(rows[i])[0], "resp_sha256": row_shas(rows[i])[1],
                               "score": rows[i]["score"], "signature": rows[i]["signature"]} for i in range(n)],
                    "run_root": rn["commit"]["run_root"], "total_score": rn["commit"]["total_score"],
                    "commit_tx": rn["commit"]["tx"], "commit_height": rn["commit"]["height"], "commit_block_hash": rn["commit"]["block_hash"]},
            "audit": (({"mode": st["policy"]["audit"]["mode"], "k": 0} if tee_round else
                        {"D": st["policy"]["audit"]["D"], "target": st["policy"]["audit"]["target"], "k": k})
                      | {"close_tx": st["close"]["tx"], "close_height": st["close"]["height"], "close_block_hash": st["close"]["block_hash"],
                         "round_runs": round_runs(record)}
                      | ({} if tee_round else {"seed_height": seed_hdr["height"], "seed_block_hash": seed_hdr["hash"], "seed": seed.hex()})
                      | {"indices": indices,
                         "reveals": [{"i": i, "item": st["items"][i]["item"], "salt": st["items"][i]["salt"],
                                      "request_b64": rows[i]["request_b64"], "response_b64": rows[i]["response_b64"],
                                      "proof_benchmark": [h.hex() for h in core.merkle_proof(bl, i)],
                                      "proof_run": [h.hex() for h in core.merkle_proof(rl, i)]} for i in indices]}),
        }
        p = Path(out_dir) / f"cert-{bid}-{cert_name(model, list(st['runs']))}.json"
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
