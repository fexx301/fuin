"""TEE-scored runs on OutLayer: the owner side (plaintext, encryption, upload, execution) and the verifier's check.

The TEE scorer (tee/, a wasm32-wasip2 build pinned in policy/tee-v2.json; canonical build tee/build-docker.sh) rebuilds and scores every answer
of one run from the sealed bytes, inside an Intel TDX enclave, and returns only the roots, the total and the signer.
"""

import base64
import hashlib
import json
import re
import struct
import subprocess
import tempfile
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from fuin import POLICY, core, near
from fuin import policy as P

TEE_POLICY = POLICY / "tee-v2.json"


def plaintext(st: dict, model: str) -> dict:
    """The round as the TEE reads it: each item's exact sealed bytes and salt, the canonical policy, the signed rows."""
    rn = st["runs"][model]
    if len(rn["rows"]) != len(st["items"]):
        raise ValueError(f"{model}: run incomplete")
    return {
        "v": "fuin-tee-round-v1",
        "model": model,
        "policy_jcs": core.jcs(st["policy"]).decode(),
        **({"seal_block_hash": st["seal"]["block_hash"]} if P.is_seal_bound(st["policy"]) else {}),
        **({"model_pub": _signer_pub(rn).hex()} if P.is_e2ee(st["policy"]) else {}),  # v3: the key each question was encrypted to
        "items": [{"salt": r["salt"], "item_jcs": core.jcs(r["item"]).decode()} for r in st["items"]],
        "rows": [{"request_b64": x["request_b64"], "response_b64": x["response_b64"], "signature": x["signature"]}
                 for x in sorted(rn["rows"], key=lambda x: x["i"])],
    }


def expected(st: dict, model: str) -> dict:
    """What a faithful TEE scorer must output for this run, from the owner's own records."""
    rn = st["runs"][model]
    out = {"model": model, "n": len(st["items"]), "total": rn["commit"]["total_score"], "benchmark_root": st["seal"]["root"],
           "policy_hash": P.policy_hash(st["policy"]), "run_root": rn["commit"]["run_root"], "signer": rn["signer"]}
    if P.is_seal_bound(st["policy"]):
        out["seal_block_hash"] = st["seal"]["block_hash"]
    return out


def unreadable(st: dict, model: str) -> int:
    """Template v3: answers that came back non-empty but don't decrypt with their item's key (each scored 0)."""
    from fuin import e2ee
    n = 0
    for x in st["runs"][model]["rows"]:
        try:
            content = json.loads(base64.b64decode(x["response_b64"]))["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            continue
        if isinstance(content, str) and content and e2ee.decrypt(content, bytes.fromhex(st["items"][x["i"]]["salt"]), model) is None:
            n += 1
    return n


def _signer_pub(rn: dict) -> bytes:
    from fuin import e2ee
    return e2ee.model_pub(next(c for c in rn["model_report"]["model_attestations"] if c["signing_address"].lower() == rn["signer"]))


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


# ---------------- owner side: encrypt, host, execute ----------------

def tee_policy() -> dict:
    return json.loads(TEE_POLICY.read_text())


def current_scorer() -> dict:
    """The build new TEE scores run on."""
    tp = tee_policy()
    return next(x for x in tp["scorers"] if x["wasm_sha256"] == tp["current"])


def scorer_for_round(policy: dict) -> dict:
    """A zero-reveal round is scored by the build its policy sealed; any other round by the current build."""
    if not P.is_tee_round(policy):
        return current_scorer()
    sealed = policy["audit"]["scorer_wasm_sha256"]
    found = [x for x in tee_policy()["scorers"] if x["wasm_sha256"] == sealed]
    if not found:
        raise SystemExit(f"the round sealed scorer {sealed[:12]}…, which policy/tee-v2.json no longer lists")
    return found[0]


def pinned() -> set[str]:
    """Every scorer build this verifier accepts evidence from."""
    return {x["wasm_sha256"] for x in tee_policy()["scorers"]}


def encrypt(plain: bytes, tee_pub_hex: str) -> tuple[bytes, str, str]:
    """ECIES to the scorer's in-TEE key: X25519, HKDF-SHA256 ("fuin-tee-round-v1"), ChaCha20-Poly1305 (tee/src/main.rs)."""
    eph = X25519PrivateKey.generate()
    shared = eph.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(tee_pub_hex)))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"fuin-tee-round-v1").derive(shared)
    nonce = __import__("os").urandom(12)
    eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return ChaCha20Poly1305(key).encrypt(nonce, plain, None), eph_pub.hex(), nonce.hex()


def _near_file(signer: str, contract: str, method: str, args: bytes, gas: str, deposit: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=".args") as f:
        f.write(args); f.flush()
        cmd = ["near", "contract", "call-function", "as-transaction", contract, method, "file-args", f.name, "prepaid-gas", gas,
               "attached-deposit", deposit, "sign-as", signer, "network-config", "testnet", "sign-with-keychain", "send"]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    return p.stdout + p.stderr


def fastfs_upload(signer: str, data: bytes, ext: str, mime: str) -> str:
    """Publish bytes on FastFS the way outlayer-cli does: a deliberately failing `__fastdata_fastfs` call whose arguments
    FastNEAR indexes (Borsh: Simple below 1 MiB, Partial chunks above). Returns the URL once it serves these exact bytes."""
    h = hashlib.sha256(data).hexdigest()
    path, mime_b = f"{h}.{ext}".encode(), mime.encode()
    s = lambda b: struct.pack("<I", len(b)) + b
    ch = 1 << 20
    if len(data) <= ch:
        payloads = [b"\x00" + s(path) + b"\x01" + s(mime_b) + s(data)]
    else:
        nonce = (int(time.time()) - 1_769_000_000) & 0xFFFFFFFF
        payloads = [b"\x01" + s(path) + struct.pack("<II", off, len(data)) + s(mime_b) + s(data[off:off + ch]) + struct.pack("<I", nonce)
                    for off in range(0, len(data), ch)]
    for p in payloads:
        _near_file(signer, signer, "__fastdata_fastfs", p, "1 Tgas", "0 NEAR")
    url = f"https://test.fastfs.io/{signer}/{signer}/{h}.{ext}"
    for _ in range(30):
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == h:
            return url
        time.sleep(6)
    raise RuntimeError(f"FastFS doesn't serve {url} yet")


def _output_from_chain(tx: str, signer: str) -> dict:
    st = near.rpc("EXPERIMENTAL_tx_status", {"tx_hash": tx, "sender_account_id": signer, "wait_until": "FINAL"})
    failed = None
    for r in st["receipts_outcome"]:
        val = r["outcome"]["status"].get("SuccessValue")
        if val:
            out = json.loads(base64.b64decode(val))
            out = json.loads(out) if isinstance(out, str) else out
            if isinstance(out, dict) and ("v" in out or "error" in out):
                return out
        failed = failed or next((x for x in r["outcome"].get("logs", []) if "Execution promise failed" in x or "Execution failed" in x), None)
    raise RuntimeError(f"OutLayer execution failed in {tx}: {failed[:200]}" if failed else f"no OutLayer output in {tx}")


def execute(signer: str, input_obj: dict, sc: dict | None = None, project: str | None = None, secrets_ref: dict | None = None
            ) -> tuple[str, str, dict]:
    """request_execution on OutLayer with a pinned build: by URL, or as the active version of `project` (the asker, which
    needs project storage and the owner's NEAR AI key as `secrets_ref`). Returns (tx hash, exact input string, output)."""
    tp, sc = tee_policy(), sc or current_scorer()
    input_data = jdump(input_obj)
    source = ({"Project": {"project_id": project, "version_key": sc["wasm_sha256"]}} if project else
              {"WasmUrl": {"url": sc["url"], "hash": sc["wasm_sha256"], "build_target": "wasm32-wasip2"}})
    args = {"source": source, "resource_limits": {"max_instructions": 100_000_000_000, "max_memory_mb": 512, "max_execution_seconds": 180},
            "input_data": input_data, "response_format": "Json", **({"secrets_ref": secrets_ref} if secrets_ref else {})}
    out = _near_file(signer, tp["outlayer"]["contract"], "request_execution", json.dumps(args).encode(), "300 Tgas", "0.1 NEAR")
    m = re.search(r"Transaction ID:\s*([1-9A-HJ-NP-Za-km-z]{43,44})", out)
    if not m:
        raise RuntimeError(f"request_execution not sent: {out[-400:]}")
    result = _output_from_chain(m.group(1), signer)
    if "error" in result:
        raise RuntimeError(f"TEE scorer refused: {result['error']}")
    return m.group(1), input_data, result


def fetch_record(tx: str) -> dict:
    """OutLayer's attestation record for an execution (embedded in the certificate; verification never calls this API)."""
    url = f"{tee_policy()['outlayer']['api']}/attestations/by-tx/{tx}"
    for _ in range(20):
        r = requests.get(url, timeout=60)
        if r.status_code == 200:
            return r.json()
        time.sleep(6)
    raise RuntimeError(f"no attestation record at {url}: HTTP {r.status_code}")


def keygen(owner: str, sc: dict | None = None) -> dict:
    """One in-TEE keypair per scorer build and owner; the sealed secret only that build, called by `owner`, can open."""
    sc = sc or current_scorer()
    path = Path("private") / f"tee-key-{owner}-{sc['wasm_sha256'][:12]}.json"
    if path.exists():
        return json.loads(path.read_text())
    tx, input_data, out = execute(owner, {"mode": "keygen"}, sc)
    key = {"owner": owner, "wasm_sha256": sc["wasm_sha256"], "pub": out["pub"], "sealed": out["sealed"],
           "transaction_hash": tx, "input_data": input_data, "output": out, "record": fetch_record(tx)}
    path.write_text(json.dumps(key, indent=1))
    return key


def fastfs_host(owner: str):
    """Permanent and public: the ciphertext stays on testnet; its privacy then rests on OutLayer's key service."""
    return lambda blob: (fastfs_upload(owner, blob, "bin", "application/octet-stream"), "raw", None)


def gist_host(blob: bytes):
    """A secret gist under the gh-authenticated account, deleted as soon as the scorer has fetched it. The attestation binds
    only the ciphertext's hash, so deleting it doesn't affect verification."""
    with tempfile.NamedTemporaryFile("w", suffix=".b64", delete=False) as f:
        f.write(base64.b64encode(blob).decode())
    url = subprocess.run(["gh", "gist", "create", f.name, "--desc", "fuin TEE round ciphertext (deleted after scoring)"],
                         capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    gid = url.rstrip("/").rsplit("/", 1)[-1]
    raw = json.loads(subprocess.run(["gh", "api", f"gists/{gid}"], capture_output=True, text=True, check=True).stdout)
    raw_url = next(iter(raw["files"].values()))["raw_url"]
    Path(f.name).unlink()

    def delete():  # the round promises the gist is deleted, so a failed delete must not pass silently
        r = subprocess.run(["gh", "gist", "delete", gid, "--yes"], capture_output=True, text=True)
        if r.returncode:
            print(f"warning: secret gist {gid} was not deleted ({r.stderr.strip()[:200]}); delete it with: gh gist delete {gid} --yes")
    return raw_url, "base64", delete


def score(st: dict, model: str, owner: str, host) -> dict:
    """Encrypt one run to the scorer's in-TEE key, host the ciphertext, have OutLayer re-score it, and return the
    evidence for the certificate. `host(bytes) -> (url, encoding, cleanup)`: fastfs_host (permanent) or gist_host (deleted)."""
    sc = scorer_for_round(st["policy"])
    tx, input_data, out = _sealed_task(owner, host, sc, "score", plaintext(st, model))
    want = expected(st, model)
    if "unreadable" in out:  # scorer v4+ counts answers that don't decrypt; the owner's own count must agree
        want["unreadable"] = unreadable(st, model)
    diff = {k: (out.get(k), v) for k, v in want.items() if out.get(k) != v}
    if diff:
        raise RuntimeError(f"TEE outcome differs from the run's commitments: {diff}")
    return {"v": "fuin-tee-evidence-v1", "transaction_hash": tx, "input_data": input_data, "output": out,
            "record": fetch_record(tx), "scorer_url": sc["url"]}


def _sealed_task(owner: str, host, sc: dict, mode: str, plain: dict) -> tuple[str, str, dict]:
    """Encrypt a plaintext to the build's in-TEE key, host the ciphertext, run `mode` on it, clean up the host."""
    key = keygen(owner, sc)
    blob, eph_pub, nonce = encrypt(jdump(plain).encode(), key["pub"])
    url, encoding, cleanup = host(blob)
    try:
        served = requests.get(url, timeout=120).content
        return execute(owner, {"mode": mode, "url": url, "blob_sha256": hashlib.sha256(served).hexdigest(),
                               "encoding": encoding, "sealed": key["sealed"], "eph_pub": eph_pub, "nonce": nonce}, sc)
    finally:
        if cleanup:
            cleanup()


# ---------------- answer-key grounding (mode `ground`; tee/src/lib.rs ground_round mirrors this exactly) ----------------

GROUND_REPO = "near/docs"  # hard-coded in the enclave too; forks share GitHub's object store, so commits are pinned as well


def ground_sources(items: list[dict]) -> tuple[str, list[str]]:
    """The one commit a round cites and its distinct files in first-use order; refuses what can't be fetched safely."""
    commit, paths = None, []
    for i, it in enumerate(items):
        src = it.get("source") if isinstance(it.get("source"), dict) else {}
        c, p = src.get("commit"), src.get("path")
        if not (isinstance(c, str) and re.fullmatch(r"[0-9a-f]{40}", c)):
            raise ValueError(f"item {i}: source commit must be 40 lowercase hex")
        if not (isinstance(p, str) and re.fullmatch(r"[A-Za-z0-9._/-]+", p) and not p.startswith("/") and ".." not in p):
            raise ValueError(f"item {i}: unsupported source path")
        if (commit := commit or c) != c:
            raise ValueError("sources must cite one commit")
        if p not in paths:
            paths.append(p)
    if commit is None:
        raise ValueError("n must be >= 1")
    return commit, paths


def ground_round(items: list[dict], salts: list[str], files: dict[str, str]) -> dict:
    """An item is grounded when its answer and every `accept` alternative appear in its cited line (split on \\n, a
    trailing \\r dropped, ',' '`' '*' removed; a numeric key must not touch another digit, from scorer v8); otherwise it
    is flagged (bit i, most significant first), not refused."""
    commit, _ = ground_sources(items)
    flags, flagged = bytearray((len(items) + 7) // 8), 0
    for i, it in enumerate(items):
        lines = [x[:-1] if x.endswith("\r") else x for x in files[it["source"]["path"]].split("\n")]
        k = it["source"].get("line")
        line = re.sub(r"[,`*]", "", lines[k - 1]) if type(k) is int and 1 <= k <= len(lines) else ""
        accept = [] if it.get("accept") is None else it["accept"]
        if not isinstance(it.get("answer"), str) or not isinstance(accept, list) or not all(isinstance(a, str) for a in accept):
            raise ValueError(f"item {i}: answer and accept must be strings")
        found = (lambda a: a in line) if it.get("answer_type") != "numeric" else (  # from scorer v8: not inside a longer number
            lambda a: re.search(r"(?<![0-9.])" + re.escape(a) + r"(?![0-9]|\.[0-9])", line) is not None)
        if not all(found(a) for a in [it["answer"], *accept]):
            flags[i // 8] |= 0x80 >> (i % 8)
            flagged += 1
    leaves = [core.benchmark_leaf(i, bytes.fromhex(salt), it) for i, (it, salt) in enumerate(zip(items, salts))]
    return {"v": "fuin-tee-ground-v1", "repo": GROUND_REPO, "commit": commit, "n": len(items),
            "benchmark_root": core.merkle_root(leaves).hex(), "flagged": flagged, "flags": flags.hex()}


def fetch_sources(items: list[dict]) -> dict[str, str]:
    commit, paths = ground_sources(items)
    out = {}
    for p in paths:
        r = requests.get(f"https://raw.githubusercontent.com/{GROUND_REPO}/{commit}/{p}", timeout=60)
        r.raise_for_status()
        out[p] = r.content.decode("utf-8")
    return out


def grounder() -> dict:
    """The build answer keys are grounded with: the newest pinned build that has the ground mode."""
    tp = tee_policy()
    return next(x for x in reversed(tp["scorers"]) if x["wasm_sha256"] in tp["grounders"])


def ground(st: dict, owner: str, host) -> dict:
    """Have the enclave fetch every cited near/docs line and flag answer keys that don't appear in it. One task per round,
    bound to the sealed benchmark root, so it can run after the round and leaves every sealed score untouched."""
    items, salts = [r["item"] for r in st["items"]], [r["salt"] for r in st["items"]]
    sc = grounder()
    tx, input_data, out = _sealed_task(owner, host, sc, "ground",
                                       {"v": "fuin-tee-items-v1", "items": [{"salt": s, "item_jcs": core.jcs(it).decode()}
                                                                            for it, s in zip(items, salts)]})
    want = {**ground_round(items, salts, fetch_sources(items)), "blob_sha256": out.get("blob_sha256")}
    if out != want or want["benchmark_root"] != st["seal"]["root"]:
        raise RuntimeError(f"TEE grounding differs from the owner's: {out} vs {want}")
    return {"v": "fuin-tee-ground-evidence-v1", "transaction_hash": tx, "input_data": input_data, "output": out,
            "record": fetch_record(tx), "scorer_url": sc["url"]}


# ---------------- verifier side ----------------

V1_CUTOFF = 1_769_784_939  # OutLayer attestations from 2026-01-30 commit to the extended (V1) task-hash fields
TEE_LIMIT = ("A TEE score trusts Intel TDX, OutLayer's worker-measurement approvals (worker.outlayer.testnet, checked at the "
             "execution's block) and its key service. Each accepted scorer build is pinned by sha256 and rebuilds with "
             "tee/build-docker.sh, on any host with Docker, from tee/ at the commit policy/tee-v2.json records.")


class TeeRefused(Exception):
    """Invalid or contradictory TEE evidence (REFUSED, code in args[0])."""


class TeeUnapproved(Exception):
    """Genuine-looking evidence the verifier's pins don't cover (CAN'T CERTIFY)."""


def _need(cond, code="tee_score_invalid"):
    if not cond:
        raise TeeRefused(code)


def _sorted_compact(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def task_hash_v1(rec: dict) -> str:
    """OutLayer's task hash (outlayer-verify preimage.rs, format V1): field order fixed, strings as UTF-8, integers
    little-endian, absent optional fields contributing nothing."""
    h = hashlib.sha256()
    h.update(rec["task_type"].encode())
    h.update(struct.pack("<q", rec["task_id"]))
    for k in ("repo_url", "commit_hash", "build_target", "wasm_hash", "input_hash"):
        if rec.get(k) is not None:
            h.update(rec[k].encode())
    h.update(rec["output_hash"].encode())
    if rec.get("block_height") is not None:
        h.update(struct.pack("<Q", rec["block_height"]))
    for k in ("caller_account_id", "project_id", "secrets_ref"):
        if rec.get(k) is not None:
            h.update(rec[k].encode())
    h.update(struct.pack("<q", rec["timestamp"]))
    if rec.get("attached_usd") is not None:
        h.update(rec["attached_usd"].encode())
    return h.hexdigest()


def _check_record(ev, cert: dict, version: str, mode: str) -> tuple[dict, dict]:
    """The checks a TEE score and a TEE grounding share: the record binds this input and output to this owner."""
    _need(isinstance(ev, dict) and ev.get("v") == version)
    _need(all(isinstance(ev.get(k), str) for k in ("transaction_hash", "input_data", "scorer_url")))
    rec, out = ev.get("record"), ev.get("output")
    _need(isinstance(rec, dict) and isinstance(out, dict))
    _need(isinstance(rec.get("tdx_quote"), str) and isinstance(rec.get("task_id"), int) and isinstance(rec.get("timestamp"), int)
          and all(isinstance(rec.get(k), str) for k in ("task_type", "output_hash", "input_hash", "wasm_hash")))
    _need(rec["input_hash"] == hashlib.sha256(ev["input_data"].encode()).hexdigest())
    _need(rec["output_hash"] == hashlib.sha256(_sorted_compact(out).encode()).hexdigest())
    _need(rec.get("transaction_hash") == ev["transaction_hash"] and rec["task_type"] == "execute" and rec.get("build_target") == "wasm32-wasip2")
    _need(rec.get("caller_account_id") == cert["registry"]["owner"])
    try:
        inp = json.loads(ev["input_data"])
    except ValueError:
        raise TeeRefused("tee_score_invalid") from None
    _need(isinstance(inp, dict) and inp.get("mode") == mode and inp.get("blob_sha256") == out.get("blob_sha256"))
    return rec, out


def _pinned(rec: dict, pins: set[str]) -> str:
    # last, so tampered evidence is refused even when it also names an unpinned build
    pin = rec["wasm_hash"]
    if pin not in pins or rec.get("executed_wasm_sha256", pin) != pin:
        raise TeeUnapproved("tee_unapproved")
    return pin


def check_local(ev, cert: dict) -> dict:
    """Every TEE score check that needs no network. Raises TeeRefused / TeeUnapproved; returns details for the check line."""
    rec, out = _check_record(ev, cert, "fuin-tee-evidence-v1", "score")
    sealed_pin = cert["benchmark"]["policy"]["audit"].get("scorer_wasm_sha256") if P.is_tee_round(cert["benchmark"]["policy"]) else None
    if sealed_pin is not None and rec["wasm_hash"] != sealed_pin:  # a zero-reveal round sealed which scorer build scores it
        raise TeeRefused("tee_score_mismatch")
    _need(out.get("v") == "fuin-tee-score-v1", "tee_score_mismatch")
    _run_fields(out, cert, "tee_score_mismatch")
    return {"task": rec["task_id"], "pin": _pinned(rec, pinned()), "unreadable": out.get("unreadable")}


def _run_fields(out: dict, cert: dict, code: str) -> None:
    """A TEE result for one run (a re-score or an asker's aggregate) equals the certificate's run, field by field."""
    b, r = cert["benchmark"], cert["run"]
    signers = {it["signature"]["signing_address"].lower() for it in r["items"]}
    _need((out.get("model"), out.get("n"), out.get("total"), out.get("benchmark_root"), out.get("policy_hash"), out.get("run_root"))
          == (r["model_id"], b["n"], r["total_score"], b["root"], b["policy_hash"], r["run_root"]) and {out.get("signer")} == signers, code)
    v2 = P.is_seal_bound(b["policy"])  # each nonce was rebuilt from this block hash
    _need(out.get("seal_block_hash") == (b["seal_block_hash"] if v2 else None), code)
    if "unreadable" in out:  # scorer v4+: only end-to-end-encrypted rounds have answers that can fail to decrypt
        u = out["unreadable"]
        _need(P.is_e2ee(b["policy"]) and type(u) is int and 0 <= u <= b["n"], code)


def check_asked_local(ev, cert: dict) -> dict:
    """An enclave-asked run's aggregate, offline: from the asker build and project the round sealed, and equal to the run."""
    rec, out = _check_record(ev, cert, "fuin-tee-asked-evidence-v1", "aggregate")
    a = cert["benchmark"]["policy"]["audit"]
    if (rec["wasm_hash"], rec.get("project_id")) != (a["asker_wasm_sha256"], a["asker_project"]):
        raise TeeRefused("tee_asked_mismatch")  # another build, or the same code in another project (other storage)
    _need(out.get("v") == "fuin-tee-asked-v1" and type(out.get("retried")) is int and out["retried"] >= 0, "tee_asked_mismatch")
    _run_fields(out, cert, "tee_asked_mismatch")
    pins = {(x["wasm_sha256"], x["project"]) for x in tee_policy().get("askers", [])}
    if (rec["wasm_hash"], rec.get("project_id")) not in pins or rec.get("executed_wasm_sha256", rec["wasm_hash"]) != rec["wasm_hash"]:
        raise TeeUnapproved("tee_unapproved")
    return {"task": rec["task_id"], "pin": rec["wasm_hash"], "project": rec["project_id"], "unreadable": out.get("unreadable"),
            "retried": out["retried"]}


def check_asked_lock(cert: dict) -> str:
    """The network half of "asked once": at the seal block the project's owner account had no keys and no code, and the
    project's only version was the sealed asker. Nobody could then delete the project (wiping its records) or change its
    code, and every ask came after the seal (its nonce is bound to the seal block)."""
    a, h = cert["benchmark"]["policy"]["audit"], cert["benchmark"]["seal_height"]
    proj, acct = a["asker_project"], a["asker_project"].split("/")[0]
    q = lambda kind, **kw: near.rpc("query", {"request_type": kind, "block_id": h, **kw})
    keys = q("view_access_key_list", account_id=acct)["keys"]
    code = q("view_account", account_id=acct)["code_hash"]
    _need(keys == [] and code == "11111111111111111111111111111111", "tee_asked_unlocked")
    view = lambda method, args: json.loads(bytes(q("call_function", account_id=tee_policy()["outlayer"]["contract"], method_name=method,
                                                   args_base64=base64.b64encode(json.dumps(args).encode()).decode())["result"]))
    project = view("get_project", {"project_id": proj})
    versions = view("list_versions", {"project_id": proj, "from_index": 0, "limit": 10})
    _need(isinstance(project, dict) and project.get("owner") == acct and project.get("active_version") == a["asker_wasm_sha256"]
          and [v.get("wasm_hash") for v in versions] == [a["asker_wasm_sha256"]], "tee_asked_unlocked")
    return f"{proj} was locked at the seal (block {h}): its owner had no keys and no code, and its only version was the sealed asker"


def check_ground_local(ev, cert: dict) -> dict:
    """The offline half of a grounding: bound to this round's sealed root, a well-formed flag set, a pinned build and
    a pinned near/docs commit (a fork's commit would be served under near/docs too)."""
    rec, out = _check_record(ev, cert, "fuin-tee-ground-evidence-v1", "ground")
    b, n = cert["benchmark"], cert["benchmark"]["n"]
    _need(out.get("v") == "fuin-tee-ground-v1" and out.get("repo") == GROUND_REPO, "tee_ground_mismatch")
    _need((out.get("n"), out.get("benchmark_root")) == (n, b["root"]), "tee_ground_mismatch")
    f, flagged = out.get("flags"), out.get("flagged")
    _need(isinstance(f, str) and re.fullmatch(r"[0-9a-f]*", f) is not None and len(f) == (n + 7) // 8 * 2 and type(flagged) is int,
          "tee_ground_mismatch")
    bits = int(f or "0", 16)
    _need(bin(bits).count("1") == flagged and bits & ((1 << (len(f) * 4 - n)) - 1) == 0, "tee_ground_mismatch")
    pin = _pinned(rec, set(tee_policy()["grounders"]))
    if out.get("commit") not in tee_policy()["ground_commits"]:
        raise TeeUnapproved("tee_unapproved")
    flagged_at = [i for i in range(n) if bits >> (len(f) * 4 - 1 - i) & 1]
    return {"task": rec["task_id"], "pin": pin, "commit": out["commit"], "flagged": flagged_at}


def check_remote(ev, cert: dict) -> str:
    """The network half: the OutLayer quote, its task hash, worker approval at the execution's block, the chain record.
    Outages raise RuntimeError / requests / RPC errors, which the verifier defers to CAN'T CERTIFY."""
    from fuin import attestation as A  # local import: attestation pulls in the TDX verifier
    rec, tp = ev["record"], tee_policy()
    try:
        quote_hex = base64.b64decode(rec["tdx_quote"], validate=True).hex()
    except ValueError:
        raise TeeRefused("tee_attestation_invalid") from None
    try:
        status, _adv, td = A.verify_quote(quote_hex)
    except (ValueError, TypeError) as e:
        raise TeeRefused("tee_attestation_invalid") from e
    _need(status != "Revoked" and int(td["td_attributes"][:2], 16) & 1 == 0, "tee_attestation_invalid")
    if rec["timestamp"] < V1_CUTOFF:
        raise TeeUnapproved("tee_unapproved")
    rd = td["report_data"].lower()
    _need(rd[:64] == task_hash_v1(rec) and set(rd[64:]) <= {"0"}, "tee_attestation_invalid")
    m = {"mrtd": td["mr_td"], "rtmr0": td["rt_mr0"], "rtmr1": td["rt_mr1"], "rtmr2": td["rt_mr2"], "rtmr3": td["rt_mr3"]}
    res = near.rpc("query", {"request_type": "call_function", "block_id": rec["block_height"], "account_id": tp["outlayer"]["register"],
                             "method_name": "is_measurements_approved",
                             "args_base64": base64.b64encode(json.dumps({"measurements": m}).encode()).decode()})
    if json.loads(bytes(res["result"])) is not True:
        raise TeeUnapproved("tee_unapproved")
    owner_id = cert["registry"]["owner"]
    st = near.rpc("EXPERIMENTAL_tx_status", {"tx_hash": ev["transaction_hash"], "sender_account_id": owner_id, "wait_until": "FINAL"})
    tx = st["transaction"]
    _need(tx["signer_id"] == owner_id and tx["receiver_id"] == tp["outlayer"]["contract"])
    call = tx["actions"][0].get("FunctionCall", {}) if tx["actions"] else {}
    _need(call.get("method_name") == "request_execution")
    args = json.loads(base64.b64decode(call["args"]))
    _need(args.get("input_data") == ev["input_data"] and args.get("source", {}).get("WasmUrl", {}).get("hash") == rec["wasm_hash"])
    outs = []
    for x in st["receipts_outcome"]:
        val = x["outcome"]["status"].get("SuccessValue")
        if val:
            try:
                o = json.loads(base64.b64decode(val))
                outs.append(json.loads(o) if isinstance(o, str) else o)
            except ValueError:
                continue
    _need(ev["output"] in outs)
    return f"quote {status}, task hash bound, worker approved at block {rec['block_height']}, request and result on chain"
