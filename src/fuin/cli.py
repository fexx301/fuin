"""fuin: seal | run | commit | close | reveal (owner) and verify | show (anyone, no credentials)."""

import argparse
import base64
import json
import sys

from fuin import diagnose, owner, verify

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
    for c in ("run", "commit"):
        p = sub.add_parser(c); p.add_argument("--id", required=True); p.add_argument("--model", default=QWEN)
    p = sub.add_parser("close"); p.add_argument("--id", required=True)
    p = sub.add_parser("reveal"); p.add_argument("--id", required=True); p.add_argument("--out", default="examples")
    p = sub.add_parser("verify"); p.add_argument("certs", nargs="+"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("show"); p.add_argument("cert"); p.add_argument("--audit", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "seal":
        owner.seal(a.suite, a.id, a.owner, {m: {**SETTINGS, "max_tokens": a.max_tokens} for m in (a.model or [QWEN])})
    elif a.cmd == "run":
        owner.run(a.id, a.model)
    elif a.cmd == "commit":
        owner.commit(a.id, a.model)
    elif a.cmd == "close":
        owner.close(a.id)
    elif a.cmd == "reveal":
        for p in owner.reveal(a.id, a.out):
            print(p)
    elif a.cmd == "verify":
        outcomes = set()
        for path in a.certs:
            try:
                cert = json.loads(open(path, encoding="utf-8").read())
            except (OSError, ValueError) as e:
                res = {"outcome": "REFUSED", "code": "certificate_invalid", "detail": str(e), "checks": []}
            else:
                res = verify.verify(cert)
            print(json.dumps({"cert": path, **res}, default=list)) if a.json else _print_verdict(path, res)
            outcomes.add(res["outcome"])
        return 1 if "REFUSED" in outcomes else 2 if "CANT_CERTIFY" in outcomes else 0  # REFUSED outranks CAN'T CERTIFY
    elif a.cmd == "show":
        cert = json.loads(open(a.cert, encoding="utf-8").read())
        b, r, au = cert["benchmark"], cert["run"], cert["audit"]
        print(f"{b['id']} · {r['model_id']} run {r['run_index']} · committed total {r['total_score']}/{b['n']}")
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
