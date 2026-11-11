"""`fuin report`: a shareable HTML and JSON report for certificates you hold.

It reads only the certificates and each one's verification result. It never needs, and never shows, private questions:
nothing from a certificate's revealed sample is rendered. Scores are compared only between VERIFIED certificates of the
same sealed round with the same model settings; everything else is listed with the reason it isn't comparable.
The report is a reading aid. The certificates, copied next to it, are the evidence, and `fuin verify` checks them.
"""

import hashlib
import json
import math
from datetime import UTC, datetime
from html import escape
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fuin import policy as P

HEAD = {"VERIFIED": "VERIFIED", "REFUSED": "REFUSED", "CANT_CERTIFY": "CAN'T CERTIFY"}


def wilson(k: int, n: int) -> tuple[float, float]:
    """95% score interval for a proportion; the same formula as the results chart (site/app.js)."""
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c, m = (p + z * z / (2 * n)) / d, (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return max(0.0, c - m), min(1.0, c + m)


def _fuin_version() -> str:
    try:
        return version("fuin")
    except PackageNotFoundError:
        return "unknown"


def entry(name: str, raw: bytes, cert: dict, res: dict, checked: dict) -> dict:
    """One certificate's row: what it claims, how it was run, and what the verifier said. No question text."""
    b, r = cert["benchmark"], cert["run"]
    pol, ev, n, k = b["policy"], r.get("evidence") or {}, b["n"], r["total_score"]
    asked, tee_round = P.is_asked_round(pol), P.is_tee_round(pol)
    tee_out = ((ev.get("tee_asked") if asked else ev.get("tee_score")) or {}).get("output") or {}
    log = ev.get("attempt_log")
    lo, hi = wilson(k, n)
    return {
        "file": f"certs/{name}", "sha256": hashlib.sha256(raw).hexdigest(),
        "benchmark_id": b["id"], "benchmark_root": b["root"], "policy_hash": b.get("policy_hash"), "n": n,
        "model": r["model_id"], "run_index": r["run_index"], "total": k, "share": k / n, "interval_95": [lo, hi],
        "kind": "asked once" if asked else "TEE-scored" if tee_round else "sampled",
        "settings": {**pol["models"][r["model_id"]], "request_template": pol["request"]["template"], "end_to_end_encrypted": P.is_e2ee(pol),
                     "scorer": f"{pol['scorer']['name']} {pol['scorer']['sha256'][:12]}", "revealed_per_round": pol["audit"].get("k", 0)},
        # a count is shown only where a TEE attested it; "not attested" is never printed as 0
        "retried_in_tee": tee_out.get("retried") if asked else None,
        "unreadable_in_tee": tee_out.get("unreadable"),
        "owner_reported_failed_attempts": None if log is None else len(log),
        "verification": {"outcome": res["outcome"], "code": res.get("code"), "detail": res.get("detail"), **checked,
                         "limits": list(res.get("limits") or []), "warnings": list(res.get("warnings") or [])},
    }


FIELDS = [("benchmark_root", "they are different sealed rounds, and nothing in a certificate shows two rounds hold the same questions"),
          ("kind", "the kind of round differs"), ("n", "the number of questions differs"), ("max_tokens", "the token cap differs"),
          ("temperature", "the temperature differs"), ("request_template", "the request template differs"), ("scorer", "the scorer differs")]


def _key(e: dict) -> dict:
    s = e["settings"]
    return {"benchmark_root": e["benchmark_root"], "kind": e["kind"], "n": e["n"], "max_tokens": s.get("max_tokens"),
            "temperature": s.get("temperature"), "request_template": s["request_template"], "scorer": s["scorer"]}


def _reading(members: list[dict]) -> list[str]:
    """What the intervals do and don't separate, top model against each other one."""
    if len(members) < 2:
        return ["One verified result in this group: there is nothing here to compare it with."]
    top, out = members[0], []
    for e in members[1:]:
        apart = top["interval_95"][0] > e["interval_95"][1]
        out.append(f"{top['model']} ({top['total']}/{top['n']}) and {e['model']} ({e['total']}/{e['n']}): "
                   + ("the 95% intervals don't overlap: on this question set the first scored higher by more than the uncertainty shown."
                      if apart else "the 95% intervals overlap, so this question set doesn't separate them."))
    return out


def build(entries: list[dict]) -> dict:
    """The whole report as data: verified results grouped where comparable, the reasons other groups aren't, the rest."""
    ok = [e for e in entries if e["verification"]["outcome"] == "VERIFIED"]
    groups: list[dict] = []
    for e in ok:
        g = next((g for g in groups if g["key"] == _key(e)), None)
        if g is None:
            groups.append(g := {"key": _key(e), "benchmark_id": e["benchmark_id"], "members": []})
        g["members"].append(e)
    for i, g in enumerate(groups):
        g["id"] = i + 1
        g["members"].sort(key=lambda e: (-e["total"], e["model"]))
        g["reading"] = _reading(g["members"])
    apart = [{"a": a["id"], "b": b["id"], "because": [why for f, why in FIELDS if a["key"][f] != b["key"][f]]}
             for i, a in enumerate(groups) for b in groups[i + 1:]]
    return {"v": "fuin-report-v1", "generated_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), "fuin_version": _fuin_version(),
            "certificates": len(entries), "verified": len(ok), "groups": groups, "not_comparable": apart,
            "not_verified": [e for e in entries if e["verification"]["outcome"] != "VERIFIED"],
            "notes": ["Scores are compared only between VERIFIED certificates of one sealed round with the same model settings.",
                      "Intervals are 95% Wilson score intervals for the share of this question set answered correctly.",
                      "A sampled round's certificate carries its own revealed sample; this report shows none of it.",
                      "This report is a reading aid. Check the certificates yourself: pip install fuin, then fuin verify certs/*.json."]}


# ---- HTML -------------------------------------------------------------------------------------------------------------

CSS = """
:root{--ground:#f6f3ec;--card:#fffdf8;--line:#ddd8cc;--ink:#1b1b1a;--muted:#5d625f;--seal:#b6382c;--pass:#2f7a52;--warn:#8a6412;--track:#e7e2d6;--band:#1b1b1a}
@media (prefers-color-scheme:dark){:root{--ground:#161616;--card:#1f1f1e;--line:#2c2c2a;--ink:#f2eee6;--muted:#9a9f9c;--seal:#d04a3b;--pass:#5fa37a;--warn:#c99a3e;--track:#2a2a28;--band:#f2eee6}}
*{box-sizing:border-box}body{margin:0;background:var(--ground);color:var(--ink);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:40px 20px 64px}h1{font-size:28px;margin:0 0 6px}h2{font-size:20px;margin:40px 0 4px}h3{font-size:15px;margin:22px 0 8px}
p{margin:8px 0}.sub{color:var(--muted);font-size:14px}code,.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;font-size:.86em}
a{color:var(--ink);text-decoration-color:var(--seal);text-underline-offset:3px}
.box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:16px 0}
.row{display:grid;grid-template-columns:minmax(120px,240px) 1fr 132px;gap:6px 14px;align-items:center;padding:7px 0}
.row .name{font-size:14px;overflow-wrap:anywhere}.row .num{font-variant-numeric:tabular-nums;font-size:14px;text-align:right}
.track{position:relative;height:14px;background:var(--track);border-radius:3px}
.fill{position:absolute;inset:0 auto 0 0;background:var(--seal);border-radius:3px}
.band{position:absolute;top:-4px;bottom:-4px;border-left:2px solid var(--band);border-right:2px solid var(--band)}
.band::after{content:"";position:absolute;left:0;right:0;top:50%;border-top:2px solid var(--band)}
.key{font-size:12.5px;color:var(--muted);margin-top:8px}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13.5px;margin-top:8px}
th,td{text-align:left;padding:7px 10px 7px 0;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap}.ok{color:var(--pass);font-weight:600}.bad{color:var(--seal);font-weight:600}.cant{color:var(--warn);font-weight:600}
ul{padding-left:20px;margin:8px 0}li{margin:4px 0}details{margin:8px 0}summary{cursor:pointer;color:var(--muted)}
@media (max-width:640px){.row{grid-template-columns:1fr 96px}.row .name{grid-column:1/-1}}
"""


def _pc(x: float) -> str:
    return f"{round(100 * x)}%"


def _count(x, how: str) -> str:
    return "not attested" if x is None else f"{x} ({how})"


def _verdict(v: dict) -> str:
    cls = {"VERIFIED": "ok", "REFUSED": "bad"}.get(v["outcome"], "cant")
    return f'<span class="{cls}">{escape(HEAD[v["outcome"]])}</span>' + (f' <code>{escape(str(v["code"]))}</code>' if v.get("code") else "")


def _cert_link(e: dict) -> str:
    return f'<a href="{escape(e["file"], quote=True)}">{escape(e["file"].split("/")[-1])}</a><br><span class="mono sub">sha256 {escape(e["sha256"][:16])}…</span>'


def html(rep: dict) -> str:
    out = ["<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
           "<title>Fūin report</title><style>", CSS, "</style></head><body><main>",
           "<h1>Fūin report</h1>",
           f'<p class="sub">{rep["certificates"]} certificate{"" if rep["certificates"] == 1 else "s"}, {rep["verified"]} verified · '
           f'made {escape(rep["generated_utc"])} with fuin {escape(rep["fuin_version"])}</p>',
           '<div class="box"><strong>Check it yourself.</strong> This page is a reading aid; the certificates next to it are the evidence. '
           'With no account and no test set: <code>pip install fuin</code>, then <code>fuin verify certs/*.json</code>. '
           "Each certificate's sha256 is listed below, so you can tell the files are the ones this report read. "
           "No private question appears here.</div>"]
    for g in rep["groups"]:
        m0, k = g["members"][0], g["key"]
        out.append(f'<h2>{escape(g["benchmark_id"])}</h2><p class="sub">Group {g["id"]} · {escape(k["kind"])} round · {k["n"]} questions · '
                   f'{k["max_tokens"]:,}-token cap · temperature {k["temperature"]} · {escape(k["request_template"])}'
                   f'{" (end-to-end encrypted)" if m0["settings"]["end_to_end_encrypted"] else ""} · scorer {escape(k["scorer"])} · '
                   f'sealed set <span class="mono">{escape(k["benchmark_root"][:16])}…</span></p><div class="box">')
        for e in g["members"]:
            lo, hi = e["interval_95"]
            out.append(f'<div class="row"><div class="name">{escape(e["model"])}</div>'
                       f'<div class="track" role="img" aria-label="{escape(e["model"], quote=True)}: {e["total"]} of {e["n"]} correct, {_pc(e["share"])}; '
                       f'95% interval {_pc(lo)} to {_pc(hi)}"><div class="fill" style="width:{100 * e["share"]:.2f}%"></div>'
                       f'<div class="band" style="left:{100 * lo:.2f}%;width:{100 * (hi - lo):.2f}%"></div></div>'
                       f'<div class="num">{e["total"]}/{e["n"]} · {_pc(e["share"])}</div></div>')
        out.append('<div class="key">Bar: share answered correctly. Bracket: 95% interval.</div></div>')
        out.append("<ul>" + "".join(f"<li>{escape(s)}</li>" for s in g["reading"]) + "</ul>")
        out.append('<div class="scroll"><table><tr><th>Model</th><th>Score</th><th>95% interval</th><th>Retried asks</th><th>Unreadable answers</th>'
                   "<th>Owner-reported failed attempts</th><th>Verification</th><th>Certificate</th></tr>")
        for e in g["members"]:
            lo, hi = e["interval_95"]
            v = e["verification"]
            out.append(f'<tr><td>{escape(e["model"])}<br><span class="sub">run {e["run_index"]}</span></td><td class="n">{e["total"]}/{e["n"]}</td>'
                       f'<td class="n">{_pc(lo)} – {_pc(hi)}</td><td>{_count(e["retried_in_tee"], "counted in the TEE")}</td>'
                       f'<td>{_count(e["unreadable_in_tee"], "counted in the TEE")}</td>'
                       f'<td>{"not recorded" if e["owner_reported_failed_attempts"] is None else str(e["owner_reported_failed_attempts"]) + " (not verifiable)"}</td>'
                       f'<td>{_verdict(v)}<br><span class="sub">{escape(v["how"])} {escape(v["at"])}</span></td><td>{_cert_link(e)}</td></tr>')
        out.append("</table></div>")
        lim = g["members"][0]["verification"]["limits"]
        if lim:
            out.append("<details><summary>Limits the verifier prints for this group's certificates</summary><ul>"
                       + "".join(f"<li>{escape(x)}</li>" for x in lim) + "</ul></details>")
    if rep["not_comparable"]:
        many = len(rep["not_comparable"]) > 6  # a long list folds away; the rule above it stays visible
        out.append("<h2>What isn't comparable</h2><p>Scores from different groups shouldn't be set side by side. Each group is one sealed "
                   "round with one set of model settings; nothing in a certificate shows that two rounds hold the same questions.</p>"
                   + ("<details><summary>Every pair of groups, and what differs</summary><ul>" if many else "<ul>"))
        for x in rep["not_comparable"]:
            out.append(f'<li>Group {x["a"]} and group {x["b"]}: {escape("; ".join(x["because"]))}.</li>')
        out.append("</ul></details>" if many else "</ul>")
    if rep["not_verified"]:
        out.append("<h2>Not verified</h2><p class=\"sub\">These certificates are left out of every comparison. CAN'T CERTIFY with "
                   "<code>evidence_unavailable</code> means a public service didn't answer: verify again.</p>"
                   '<div class="scroll"><table><tr><th>Certificate</th><th>Claims</th><th>Verification</th></tr>')
        for e in rep["not_verified"]:
            v = e["verification"]
            out.append(f'<tr><td>{_cert_link(e)}</td><td>{escape(e["model"])} on {escape(e["benchmark_id"])}: {e["total"]}/{e["n"]} (unverified)</td>'
                       f'<td>{_verdict(v)}<br><span class="sub">{escape(str(v.get("detail") or ""))}</span></td></tr>')
        out.append("</table></div>")
    out.append("<h2>How to read this</h2><ul>" + "".join(f"<li>{escape(n)}</li>" for n in rep["notes"]) + "</ul></main></body></html>")
    return "".join(out)


def write(paths: list[str], out_dir: str, verdict) -> tuple[dict, list[Path]]:
    """Read the certificates, get each one's verdict from `verdict(raw, cert)`, and write DIR/report.html, DIR/report.json
    and DIR/certs/ (copies, so the folder can be shared as it is)."""
    out, entries = Path(out_dir), []
    (out / "certs").mkdir(parents=True, exist_ok=True)
    for p in paths:
        raw, name = Path(p).read_bytes(), Path(p).name
        if (out / "certs" / name).exists() and (out / "certs" / name).read_bytes() != raw:  # two files with one name
            name = f"{Path(p).stem}-{hashlib.sha256(raw).hexdigest()[:8]}.json"
        (out / "certs" / name).write_bytes(raw)
        try:
            cert = json.loads(raw.decode("utf-8"))
            res, checked = verdict(raw, cert)
            entries.append(entry(name, raw, cert, res, checked))
        except (ValueError, KeyError, TypeError) as e:  # not a certificate: listed as such, never compared
            entries.append({"file": f"certs/{name}", "sha256": hashlib.sha256(raw).hexdigest(), "model": "unreadable file", "benchmark_id": "?",
                            "total": 0, "n": 0, "verification": {"outcome": "REFUSED", "code": "certificate_invalid",
                                                                  "detail": f"{type(e).__name__}: {str(e)[:120]}"}})
    rep = build(entries)
    (out / "report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    (out / "report.html").write_text(html(rep), encoding="utf-8")
    return rep, [out / "report.html", out / "report.json"]
