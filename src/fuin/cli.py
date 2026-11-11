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


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="fuin")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("seal", "evaluate"):
        s = sub.add_parser(c, help="check, seal, run, commit, close, score and verify a round in one resumable command" if c == "evaluate" else None)
        s.add_argument("suite"); s.add_argument("--id", required=True)
        s.add_argument("--owner", required=True); s.add_argument("--model", action="append", default=None)
        s.add_argument("--max-tokens", type=int, default=SETTINGS["max_tokens"], help="sealed per-model token cap (reasoning included)")
        s.add_argument("--tee", action="store_true", help="zero-reveal round: every item scored inside OutLayer's TEE by the current "
                       "pinned scorer build (sealed in the policy), requests bound to the seal block, nothing revealed")
        s.add_argument("--e2ee", action="store_true", help="request template v3: each question and answer end-to-end encrypted "
                       "between you and the model's attested TEE key, so NEAR's gateway never sees them; requests bound to the seal block")
        s.add_argument("--ask", action="store_true", help="zero-reveal round whose model calls are made inside OutLayer's TEE by the "
                       "current pinned asker build in its locked project, each item asked once (sealed in the policy); run `fuin ask`")
    s.add_argument("--host", choices=["fastfs", "gist"], default="gist", help="where a TEE round's ciphertext is hosted (default gist: secret, deleted after)")
    s.add_argument("--parallel", type=int, default=1, help="questions in flight at once when you run the models")
    s.add_argument("--out", default="certs", help="where the certificates are written")
    s.add_argument("--yes", action="store_true", help="don't ask before sealing (a seal can't be undone)")
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
    p.add_argument("--ask", action="store_true", help="check what an asked-once round needs: a stored key for the asker, a model that fits its time limit")
    p.add_argument("--host", choices=["fastfs", "gist"], help="also check the hosting a TEE round will use")
    p.add_argument("--max-tokens", type=int, default=None, help="the token cap you will seal (checked against the asker's time limit)")
    p = sub.add_parser("status", help="show where a round stands and the next command"); p.add_argument("--id", required=True)
    p.add_argument("--out", default="examples", help="where the round's certificates were written (the --out of reveal or tee-score)")
    p = sub.add_parser("show"); p.add_argument("cert"); p.add_argument("--audit", action="store_true")
    p = sub.add_parser("report", help="write a shareable HTML and JSON report for certificates: scores, 95%% intervals, "
                       "what is comparable and what isn't; no private question is shown")
    p.add_argument("certs", nargs="+"); p.add_argument("--out", default="report", help="folder for report.html, report.json and certs/")
    p.add_argument("--recorded", help="a file of `fuin verify --json` lines to use instead of verifying now (matched by each certificate's sha256)")
    p = sub.add_parser("policy-update", help="draft the next attestation policy from fresh reports when NEAR redeploys a model "
                       "(needs a key; writes policy/attestation-v<N+1>.json for review, approves nothing)")
    p.add_argument("--model", action="append", default=None, help="model to check (default: every model in the current policy)")
    p = sub.add_parser("tee-key", help="make the TEE scorer's in-enclave key for this owner (once per scorer build)")
    p.add_argument("--owner", required=True)
    p = sub.add_parser("tee-score", help="re-score a committed run inside OutLayer's TEE and add the evidence to its certificate")
    p.add_argument("--id", required=True); p.add_argument("--model", required=True); p.add_argument("--out", default="examples")
    p.add_argument("--host", required=True, choices=["fastfs", "gist"],
                   help="where the encrypted run is hosted for the scorer: fastfs (permanent, public) or gist (secret, deleted after)")
    p = sub.add_parser("tee-ground", help="check every answer key against its cited near/docs line inside OutLayer's TEE (once per round)")
    p.add_argument("--id", required=True); p.add_argument("--out", default="examples")
    p.add_argument("--host", required=True, choices=["fastfs", "gist"],
                   help="where the encrypted items are hosted for the enclave: fastfs (permanent, public) or gist (secret, deleted after)")
    p = sub.add_parser("ask", help="enclave-asked round: ask every item inside the TEE, then have it attest the run")
    p.add_argument("--id", required=True); p.add_argument("--model", required=True)
    p.add_argument("--host", required=True, choices=["fastfs", "gist"], help="where the encrypted round is hosted for the asker")
    p = sub.add_parser("ask-check", help="enclave-asked round: have the TEE rebuild every request with the true seal block hash")
    p.add_argument("--id", required=True); p.add_argument("--model", required=True); p.add_argument("--out", default="examples")
    p.add_argument("--host", required=True, choices=["fastfs", "gist"])
    return ap


def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    if a.cmd == "check":
        return tooling.print_check(a.suite, a.owner, a.model or [QWEN], mode="ask" if a.ask else "tee" if a.tee else "sampled",
                                   host=a.host, max_tokens=a.max_tokens)
    if a.cmd == "status":
        print("\n".join(tooling.status(a.id, a.out)))
        return 0
    held = owner.lock(a.id) if a.cmd in ("run", "commit", "close", "tee-score", "tee-ground", "reveal", "ask", "ask-check", "evaluate") else None  # noqa: F841 (held until exit)
    return evaluate(a) if a.cmd == "evaluate" else _dispatch(a)


def evaluate(a) -> int:
    """One guided, resumable command for a whole round: check, explain the kind of round, seal, then whatever
    `fuin status` names next, until the certificates verify. Run it again after any interruption."""
    import requests
    from fuin import near, policy as P
    if a.tee and a.ask:
        raise SystemExit("--tee and --ask are two kinds of zero-reveal round: pick one")
    mode, models = "ask" if a.ask else "tee" if a.tee else "sampled", a.model or [QWEN]
    sealed = owner.load(a.id) if owner._path(a.id).exists() else None
    if sealed and "seal" in sealed:  # a rerun follows what was sealed; flags that disagree with it are refused, not ignored
        pol = sealed["policy"]
        was = "ask" if P.is_asked_round(pol) else "tee" if P.is_tee_round(pol) else "sampled"
        differs = [what for what, differ in (("kind of round", (a.tee or a.ask) and mode != was), ("models", a.model and set(a.model) != set(pol["models"])),
                                             ("owner", a.owner != sealed["owner"])) if differ]
        if differs:
            raise SystemExit(f"{a.id} is already sealed with a different {' and '.join(differs)} ({was} round, owner {sealed['owner']}, "
                             f"models {', '.join(pol['models'])}). A seal can't be changed: rerun without those flags to finish it, or use a new --id.")
        print(f"Resuming {a.id}: sealed at height {sealed['seal']['height']}; the suite file is not read again.")
    else:
        if tooling.print_check(a.suite, a.owner, models, mode=mode, host=a.host, max_tokens=a.max_tokens):
            return 1
        print("\n".join(tooling.explain(mode, a.e2ee, a.host)))
        if not a.yes:
            if not sys.stdin.isatty():
                raise SystemExit("A seal can't be undone, and there is no terminal to confirm on: add --yes to go ahead.")
            if input(f"Seal {a.id} and run {', '.join(models)}? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Nothing was sealed.")
                return 1
    try:
        if not (sealed and "seal" in sealed):
            _dispatch(_parser().parse_args(["seal", a.suite, "--id", a.id, "--owner", a.owner, "--max-tokens", str(a.max_tokens),
                                            *(x for m in models for x in ("--model", m)), *(["--tee"] if a.tee else []),
                                            *(["--ask"] if a.ask else []), *(["--e2ee"] if a.e2ee else [])]))
        seen = None
        while True:
            _, step = tooling.progress(a.id, a.out)
            if not isinstance(step, tuple) or step == seen:  # guidance, not a command, or a step that changed nothing
                print(f"Stopped at: {tooling.render(step)}")
                return 1
            seen, argv = step, list(step[1])
            if "--host" in argv:
                argv[argv.index("--host") + 1] = a.host
            if argv[0] == "run":
                argv += ["--parallel", str(a.parallel)]
            print(f"== fuin {' '.join(argv)}", flush=True)
            if argv[0] == "verify":  # the last step: keyless, like anyone else's check
                return _dispatch(_parser().parse_args(argv))
            _dispatch(_parser().parse_args(argv))
    except (requests.RequestException, near.RpcError) as e:
        print(f"A network call failed ({type(e).__name__}: {str(e)[:160]}). Nothing is lost: run the same command again and it resumes.")
        return 3
    except RuntimeError as e:  # a TEE task or a model call that failed; what was saved stays saved
        print(f"A step failed: {str(e)[:300]}\nRun the same command again: it resumes from what is saved.")
        return 3


def _dispatch(a) -> int:
    if a.cmd == "seal":
        res = tooling.check_suite(a.suite)
        if res["errors"]:  # a seal can't be undone: refuse a broken suite
            print("Not sealing: the suite has errors. Run `fuin check` for details.\n" + "\n".join("  ✗ " + e for e in res["errors"][:10]))
            return 1
        print(tooling.disclosure(res["n"], tee=a.tee or a.ask, asked=a.ask))
        tee_wasm, ask_with = None, None
        if a.tee and a.ask:
            raise SystemExit("--tee and --ask are two kinds of zero-reveal round: pick one")
        if a.tee:
            from fuin import tee
            tee_wasm = tee.tee_policy()["current"]
        if a.ask:
            from fuin import asker
            if not asker.askers():
                raise SystemExit("policy/tee-v2.json pins no asker build")
            ask_with = (asker.askers()[-1]["wasm_sha256"], asker.askers()[-1]["project"])
        owner.seal(a.suite, a.id, a.owner, {m: {**SETTINGS, "max_tokens": a.max_tokens} for m in (a.model or [QWEN])}, tee_wasm=tee_wasm,
                   encrypt=a.e2ee, asker=ask_with)
    elif a.cmd == "ask":
        from fuin import asker, tee
        st = owner.load(a.id)
        host = tee.fastfs_host(st["owner"]) if a.host == "fastfs" else tee.gist_host
        st = asker.run(a.id, a.model, host)
        o = st["runs"][a.model]["tee_asked"]["output"]
        print(f"every item asked once inside the TEE: {o['total']}/{o['n']}, {o['retried']} retried asks "
              f"(aggregate tx {st['runs'][a.model]['tee_asked']['transaction_hash']}); next: fuin commit")
    elif a.cmd == "ask-check":
        from fuin import asker, tee
        st = owner.load(a.id)
        host = tee.fastfs_host(st["owner"]) if a.host == "fastfs" else tee.gist_host
        ev = st["runs"][a.model]["tee_asked_check"] = asker.check(st, a.model, host)
        owner.save(st)
        print(f"every request rebuilt with the seal block's hash matches the signed one (task {ev['record']['task_id']})")
        if st.get("close"):
            for path in owner.reveal(a.id, a.out):
                print(path)
    elif a.cmd == "run":
        owner.run(a.id, a.model, a.parallel)
    elif a.cmd == "commit":
        owner.commit(a.id, a.model)
    elif a.cmd == "close":
        owner.close(a.id)
    elif a.cmd == "reveal":
        for p in owner.reveal(a.id, a.out):
            print(p)
    elif a.cmd == "policy-update":
        from fuin import policyupdate
        draft, notes = policyupdate.propose(a.model or sorted(owner.attestation_policy()["models"]))
        print("\n".join(notes))
        if draft is None:
            print("nothing new: every candidate is already approved or was not proposed")
        else:
            path = policyupdate.write(draft)
            print(f"wrote {path} for review; the verifier keeps using {owner.ATTESTATION_POLICY.name} until "
                  "owner.ATTESTATION_POLICY points at the reviewed file")
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
    elif a.cmd == "tee-ground":
        from fuin import policy as P, tee
        st = owner.load(a.id)
        if "seal" not in st:
            raise SystemExit("round not sealed yet")
        host = tee.fastfs_host(st["owner"]) if a.host == "fastfs" else tee.gist_host
        st["tee_ground"] = ev = tee.ground(st, st["owner"], host)
        owner.save(st)
        o = ev["output"]
        print(f"answer keys grounded in the TEE: {o['n'] - o['flagged']}/{o['n']} appear in their cited line; "
              f"{o['flagged']} flagged (tx {ev['transaction_hash']})")
        if st.get("close") and all("commit" not in rn or rn.get("tee_score") or rn.get("tee_asked") or not P.is_tee_round(st["policy"]) for rn in st["runs"].values()):
            for path in owner.reveal(a.id, a.out):  # certificates regenerated with the grounding; nothing else changes
                print(path)
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
    elif a.cmd == "report":
        import os
        from datetime import UTC, datetime
        from fuin import report
        stamp = lambda t: datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%d %H:%M UTC")
        rec = {}
        if a.recorded:
            lines = (json.loads(x) for x in open(a.recorded, encoding="utf-8") if x.strip())
            rec = {d["cert_sha256"]: d for d in lines if "cert_sha256" in d}  # older records name no bytes: they never match

        def verdict(raw: bytes, cert: dict):
            d = rec.get(hashlib.sha256(raw).hexdigest())
            if d:  # a result recorded for these exact bytes
                return d, {"how": "recorded result, file dated", "at": stamp(os.path.getmtime(a.recorded))}
            return verify.verify(cert), {"how": "checked", "at": stamp(datetime.now(UTC).timestamp())}

        rep, files = report.write(a.certs, a.out, verdict)
        print(f"{rep['certificates']} certificates, {rep['verified']} verified, {len(rep['groups'])} comparable group(s)")
        for f in files:
            print(f)
        bad = {e["verification"]["outcome"] for e in rep["not_verified"]}
        return 1 if "REFUSED" in bad else 2 if bad else 0
    elif a.cmd == "show":
        cert = json.loads(open(a.cert, encoding="utf-8").read())
        b, r, au = cert["benchmark"], cert["run"], cert["audit"]
        print(f"{b['id']} · {r['model_id']} run {r['run_index']} · committed total {r['total_score']}/{b['n']}")
        from fuin import policy as P
        if P.is_tee_round(b["policy"]):
            print(tooling.zero_reveal_line(cert))
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
