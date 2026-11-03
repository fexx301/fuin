"""fuin: seal | run | commit | close | reveal (owner) and verify | show (anyone, no credentials)."""

import argparse
import base64
import json
import sys

from fuin import owner, verify

QWEN = "Qwen/Qwen3.8-27B"
SETTINGS = {"max_tokens": 64, "temperature": 0, "chat_template_kwargs": {"enable_thinking": False}}


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
    for c in ("run", "commit"):
        p = sub.add_parser(c); p.add_argument("--id", required=True); p.add_argument("--model", default=QWEN)
    p = sub.add_parser("close"); p.add_argument("--id", required=True)
    p = sub.add_parser("reveal"); p.add_argument("--id", required=True); p.add_argument("--out", default="examples")
    p = sub.add_parser("verify"); p.add_argument("certs", nargs="+"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("show"); p.add_argument("cert"); p.add_argument("--audit", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "seal":
        owner.seal(a.suite, a.id, a.owner, {m: SETTINGS for m in (a.model or [QWEN])})
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
        worst = 0
        for path in a.certs:
            try:
                cert = json.loads(open(path, encoding="utf-8").read())
            except (OSError, ValueError) as e:
                res = {"outcome": "REFUSED", "code": "certificate_invalid", "detail": str(e), "checks": []}
            else:
                res = verify.verify(cert)
            print(json.dumps({"cert": path, **res}, default=list)) if a.json else _print_verdict(path, res)
            worst = max(worst, {"VERIFIED": 0, "CANT_CERTIFY": 2, "REFUSED": 1}[res["outcome"]])
        return worst
    elif a.cmd == "show":
        cert = json.loads(open(a.cert, encoding="utf-8").read())
        b, r, au = cert["benchmark"], cert["run"], cert["audit"]
        print(f"{b['id']} · {r['model_id']} run {r['run_index']} · committed total {r['total_score']}/{b['n']}")
        print(f"audit: D={au['D']} k={au['k']} (target 95%) · disclosed {au['k']} of {b['n']}, hidden {b['n'] - au['k']}")
        if a.audit:
            items = {it["i"]: it for it in r["items"]}
            for x in au["reveals"]:
                content = json.loads(base64.b64decode(x["response_b64"]))["choices"][0]["message"]["content"]
                print(f"  #{x['i']} score {items[x['i']]['score']} · Q: {x['item']['question']}\n      expected {x['item']['answer']!r} · model said {content.strip()[:60]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
