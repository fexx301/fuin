"""fuin: check | seal | run | commit | close | reveal | status (owner) and verify | show (anyone, no credentials)."""

import argparse
import base64
import hashlib
import json
import sys

from fuin import diagnose, owner, tooling, verify

QWEN = "Qwen/Qwen3.8-27B"
SETTINGS = {"max_tokens": 4096, "temperature": 0}  # user, Nov 3: both models reason, 4096-token cap


def _print_verdict(path: str, res: dict) -> None:
    head = {"VERIFIED": "VERIFIED", "REFUSED": f"REFUSED {res.get('code')}", "CANT_CERTIFY": f"CAN'T CERTIFY {res.get('code')}"}
    print(f"{path}: {head[res['outcome']]}")
    for name, status, detail in res["checks"]:
        print(f"  [{status}] {name}: {detail}")
    if res.get("detail"):
        print(f"  detail: {res['detail']}")
    if res["outcome"] == "VERIFIED":
        print(f"  scope: {res['scope']}")
        for w in res["warnings"]:
            print(f"  warning: {w}")
        print("  limits:")
        for lim in res["limits"]:
            print(f"   - {lim}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fuin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seal"); s.add_argument("suite"); s.add_argument("--id", required=True)
    s.add_argument("--owner", required=True); s.add_argument("--model", action="append", default=None)
    s.add_argument("--max-tokens", type=int, default=SETTINGS["max_tokens"], help="sealed per-model token cap (reasoning included)")
    s.add_argument("--tee", action="store_true", help="zero-reveal round: every item scored inside OutLayer's TEE by the current "
                   "pinned scorer build (sealed in the policy), requests bound to the seal block, nothing revealed")
    s.add_argument("--e2ee", action="store_true", help="request template v3: each question and answer end-to-end encrypted "
                   "between you and the model's attested TEE key, so NEAR's gateway never sees them; requests bound to the seal block")
    for c in ("run", "commit"):
        p = sub.add_parser(c); p.add_argument("--id", required=True); p.add_argument("--model", default=QWEN)
        if c == "run":
            p.add_argument("--parallel", type=int, default=1, help="questions in flight at once (rows are still saved in order)")
    p = sub.add_parser("close"); p.add_argument("--id", required=True)
    p = sub.add_parser("reveal"); p.add_argument("--id", required=True); p.add_argument("--out", default="examples")
    p = sub.add_parser("verify"); p.add_argument("certs", nargs="+"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("check", help="validate a suite and the prerequisites before sealing"); p.add_argument("suite")
    p.add_argument("--owner"); p.add_argument("--model", action="append", default=None)
    p.add_argument("--tee", action="store_true", help="state the disclosure for a zero-reveal (TEE-scored) round")
    p = sub.add_parser("status", help="show where a round stands and the next command"); p.add_argument("--id", required=True)
    p = sub.add_parser("show"); p.add_argument("cert"); p.add_argument("--audit", action="store_true")
    p = sub.add_parser("tee-key", help="make the TEE scorer's in-enclave key for this owner (once per scorer build)")
    p.add_argument("--owner", required=True)
    p = sub.add_parser("tee-score", help="re-score a committed run inside OutLayer's TEE and add the evidence to its certificate")
    p.add_argument("--id", required=True); p.add_argument("--model", required=True); p.add_argument("--out", default="examples")
    p.add_argument("--host", required=True, choices=["fastfs", "gist"],
                   help="where the encrypted run is hosted for the scorer: fastfs (permanent, public) or gist (secret, deleted after)")
    a = ap.parse_args(argv)

    if a.cmd == "check":
        return tooling.print_check(a.suite, a.owner, a.model or [QWEN], tee=a.tee)
    if a.cmd == "status":
        print("\n".join(tooling.status(a.id)))
        return 0
    if a.cmd == "seal":
        res = tooling.check_suite(a.suite)
        if res["errors"]:  # a seal can't be undone: refuse a broken suite
            print("Not sealing: the suite has errors. Run `fuin check` for details.\n" + "\n".join("  ✗ " + e for e in res["errors"][:10]))
            return 1
        print(tooling.disclosure(res["n"], tee=a.tee))
        tee_wasm = None
        if a.tee:
            from fuin import tee
            tee_wasm = tee.tee_policy()["current"]
        owner.seal(a.suite, a.id, a.owner, {m: {**SETTINGS, "max_tokens": a.max_tokens} for m in (a.model or [QWEN])}, tee_wasm=tee_wasm,
                   encrypt=a.e2ee)
    elif a.cmd == "run":
        owner.run(a.id, a.model, a.parallel)
    elif a.cmd == "commit":
        owner.commit(a.id, a.model)
    elif a.cmd == "close":
        owner.close(a.id)
    elif a.cmd == "reveal":
        for p in owner.reveal(a.id, a.out):
            print(p)
    elif a.cmd == "tee-key":
        from fuin import tee
        k = tee.keygen(a.owner)
        print(f"in-TEE key for {a.owner}: pub {k['pub']} (keygen tx {k['transaction_hash']})")
    elif a.cmd == "tee-score":
        from fuin import tee
        st = owner.load(a.id)
        if "commit" not in st["runs"].get(a.model, {}):
            raise SystemExit(f"{a.model} run is not committed yet")
        host = tee.fastfs_host(st["owner"]) if a.host == "fastfs" else tee.gist_host
        ev = tee.score(st, a.model, st["owner"], host)
        st["runs"][a.model]["tee_score"] = ev
        owner.save(st)
        print(f"TEE score {ev['output']['total']}/{ev['output']['n']} matches the commitment (tx {ev['transaction_hash']})")
        from fuin import policy as P
        waiting = [m for m, rn in st["runs"].items() if "commit" in rn and not rn.get("tee_score")]
        if P.is_tee_round(st["policy"]) and waiting:  # a zero-reveal round's certificates need every run's TEE score
            print(f"certificates are written once every run has its TEE score; still to score: {', '.join(waiting)}")
        elif st.get("close"):  # a closed round's certificates are regenerated with the evidence; the sample is re-derived, unchanged
            for p in owner.reveal(a.id, a.out):
                print(p)
    elif a.cmd == "verify":
        outcomes = set()
        for path in a.certs:
            raw = b""
            try:
                raw = open(path, "rb").read()
                cert = json.loads(raw.decode("utf-8"))
            except (OSError, ValueError) as e:
                res = {"outcome": "REFUSED", "code": "certificate_invalid", "detail": str(e), "checks": []}
            else:
                res = verify.verify(cert)
            # the file's hash ties a recorded result to these exact bytes (scripts/build_page.py refuses a mismatch)
            print(json.dumps({"cert": path, "cert_sha256": hashlib.sha256(raw).hexdigest(), **res}, default=list)) if a.json else _print_verdict(path, res)
            outcomes.add(res["outcome"])
        return 1 if "REFUSED" in outcomes else 2 if "CANT_CERTIFY" in outcomes else 0  # REFUSED outranks CAN'T CERTIFY
    elif a.cmd == "show":
        cert = json.loads(open(a.cert, encoding="utf-8").read())
        b, r, au = cert["benchmark"], cert["run"], cert["audit"]
        print(f"{b['id']} · {r['model_id']} run {r['run_index']} · committed total {r['total_score']}/{b['n']}")
        from fuin import policy as P
        if P.is_tee_round(b["policy"]):
            print(f"audit: none · a TEE-scored round reveals nothing: all {b['n']} items stay private and were re-scored inside "
                  f"OutLayer's TEE by scorer {b['policy']['audit']['scorer_wasm_sha256'][:12]}… (fuin verify checks that evidence)")
            return 0
        print(f"audit: D={au['D']} k={au['k']} (target 95%) · revealed {au['k']} of {b['n']}, unrevealed {b['n'] - au['k']}")
        print(f"settings: {b['policy']['models'][r['model_id']]} · scorer {b['policy']['scorer']['name']}")
        items = {it["i"]: it for it in r["items"]}
        rows = []
        for x in au["reveals"]:
            resp = json.loads(base64.b64decode(x["response_b64"]))
            ch = resp["choices"][0]
            rows.append((x, ch.get("finish_reason"), (ch["message"].get("content") or "").strip()))
        cut = sum(f == "length" for _, f, _ in rows)
        right = sum(items[x["i"]]["score"] for x, _, _ in rows)
        print(f"revealed sample: {right}/{len(rows)} correct; {cut}/{len(rows)} cut off at max_tokens (scored 0) — checkable from the revealed bytes")
        bd = diagnose.breakdown(cert)
        print(f"revealed misses: {bd['wrong']} wrong, {bd['format']} format (right value, rejected form), {bd['cut off']} cut off — a reading aid, not a score")
        if a.audit:
            for x, fin, content in rows:
                said = "(cut off before answering)" if fin == "length" and not content else repr(content[:50])
                print(f"  #{x['i']:>2} score {items[x['i']]['score']} · Q: {x['item']['question']}\n       expected {x['item']['answer']!r} · model said {said}"
                      f" · source {x['item'].get('source', {}).get('url', '-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
