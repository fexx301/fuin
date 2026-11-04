"""Build site/index.html: a static results page from committed certificates and recorded `fuin verify --json` output.

Usage: uv run python scripts/build_page.py
The page shows recorded results and how to reproduce them; it does not verify anything in the browser.
Rounds are listed in ROUNDS; each needs examples/cert-<round>-*.json and evidence/*-round-<round>/verify.jsonl.
"""
import base64
import glob
import html
import json
import subprocess
from pathlib import Path

ROUNDS = [r for r in ("near-dev-60-r2", "near-dev-60-r1") if glob.glob(f"evidence/*-round-{r}/verify.jsonl")]
REPO = "https://github.com/fexx301/fuin"
TX = "https://testnet.nearblocks.io/txns/"
e = html.escape


def short(h: str, n: int = 10) -> str:
    return f"{h[:n]}…" if len(h) > n else h


def cert_rows(cert: dict) -> list[dict]:
    items = {it["i"]: it for it in cert["run"]["items"]}
    rows = []
    for x in cert["audit"]["reveals"]:
        ch = json.loads(base64.b64decode(x["response_b64"]))["choices"][0]
        rows.append({"i": x["i"], "q": x["item"]["question"], "expected": x["item"]["answer"],
                     "said": (ch["message"].get("content") or "").strip(), "cut": ch.get("finish_reason") == "length",
                     "score": items[x["i"]]["score"], "src": x["item"].get("source", {}).get("url", "")})
    return rows


def round_section(rid: str) -> str:
    verdicts = {json.loads(l)["cert"]: json.loads(l) for l in open(glob.glob(f"evidence/*-round-{rid}/verify.jsonl")[0])}
    certs = {p: json.loads(Path(p).read_text()) for p in sorted(glob.glob(f"examples/cert-{rid}-*.json"))}
    any_c = next(iter(certs.values()))
    b, a = any_c["benchmark"], any_c["audit"]
    models = sorted(certs, key=lambda p: -certs[p]["run"]["total_score"])
    rows_by = {p: cert_rows(certs[p]) for p in models}
    cap = b["policy"]["models"][certs[models[0]]["run"]["model_id"]]["max_tokens"]

    head = "".join(f"<th>{e(certs[p]['run']['model_id'])}</th>" for p in models)
    summary = []
    for p in models:
        c, v, rows = certs[p], verdicts.get(p, {}), rows_by[p]
        served = ", ".join(sorted({s["model_path"] for s in (v.get("trace") or {}).get("services", []) if s.get("model_path")})) or "—"
        summary.append(
            f"<tr><th scope='row'>{e(c['run']['model_id'])}</th><td class='big'>{c['run']['total_score']}<small>/{b['n']}</small></td>"
            f"<td>{sum(r['score'] for r in rows)}/{len(rows)}</td><td>{sum(r['cut'] for r in rows)}/{len(rows)}</td>"
            f"<td><code>{e(served)}</code></td><td class='verdict {e(v.get('outcome', '?').lower())}'>{e(v.get('outcome', 'not recorded'))}</td></tr>")

    checks = []
    for p in models:
        v = verdicts.get(p, {})
        lis = "".join(f"<li><span class='ok'>pass</span> <b>{e(n)}</b> <span class='detail'>{e(d)}</span></li>" for n, _, d in v.get("checks", []))
        warn = "".join(f"<li class='warn'>{e(w)}</li>" for w in v.get("warnings", []))
        checks.append(f"<details><summary><b>{e(certs[p]['run']['model_id'])}</b> — {e(v.get('outcome', ''))}: {e(v.get('scope', ''))}</summary>"
                      f"<ul class='checks'>{lis}</ul><ul class='warnings'>{warn}</ul>"
                      f"<pre>env -u NEARAI_API_KEY uv run fuin verify {e(p)}</pre></details>")

    reveal_rows = []
    for idx, r0 in enumerate(rows_by[models[0]]):
        cells = []
        for p in models:
            r = rows_by[p][idx]
            said = "cut off before answering" if r["cut"] and not r["said"] else r["said"][:40]
            cells.append(f"<td class='{'hit' if r['score'] else 'miss'}'>{'✓' if r['score'] else '✗'} <span>{e(said)}</span></td>")
        reveal_rows.append(f"<tr><td class='num'>{r0['i']}</td><td>{e(r0['q'])}<br><a href='{e(r0['src'])}'>source</a></td>"
                           f"<td><code>{e(r0['expected'])}</code></td>{''.join(cells)}</tr>")

    txs = (f"seal <a href='{TX}{b['seal_tx']}'>{short(b['seal_tx'])}</a> · "
           + " · ".join(f"commit {e(certs[p]['run']['model_id'].split('/')[-1])} <a href='{TX}{certs[p]['run']['commit_tx']}'>{short(certs[p]['run']['commit_tx'])}</a>" for p in models)
           + f" · close <a href='{TX}{a['close_tx']}'>{short(a['close_tx'])}</a> · seed block {a['seed_height']}")
    return f"""
<section class="round" id="{e(rid)}">
  <h2>Round <code>{e(rid)}</code></h2>
  <p class="meta">{b['n']} sealed questions · reasoning on, <code>max_tokens</code> {cap}, temperature 0 · scorer <code>{e(b['policy']['scorer']['name'])}</code> · audit reveals {a['k']} of {b['n']}</p>
  <table class="summary"><thead><tr><th>Model</th><th>Committed score</th><th>Revealed: correct</th><th>Revealed: cut off at {cap}</th><th>Weights NEAR served</th><th>Verdict</th></tr></thead>
  <tbody>{''.join(summary)}</tbody></table>
  <p class="meta">{txs}</p>
  <h3>Verifier output (recorded)</h3>
  {''.join(checks)}
  <h3>The {a['k']} revealed questions</h3>
  <div class="scroll"><table class="reveals"><thead><tr><th>#</th><th>Question</th><th>Expected</th>{head}</tr></thead><tbody>{''.join(reveal_rows)}</tbody></table></div>
</section>"""


def fixtures_section() -> str:
    m = json.loads(Path("examples/tampered/manifest.json").read_text())
    rows = "".join(f"<tr><td><code>{e(f['file'][:-5])}</code></td><td>{e(f['mutation'])}</td><td class='verdict refused'>{e(f['expected'])}</td></tr>" for f in m["fixtures"])
    return f"""
<section id="refusals">
  <h2>What gets refused</h2>
  <p>Each fixture makes one change to a real certificate. The verifier must give exactly this verdict, at the check that catches it.</p>
  <table class="fixtures"><thead><tr><th>Fixture</th><th>What changed</th><th>Verdict</th></tr></thead><tbody>{rows}</tbody></table>
  <pre>uv run python scripts/check_fixtures.py examples/tampered/manifest.json</pre>
</section>"""


def main() -> None:
    logo = Path("assets/fuin-logo.svg").read_text().replace("<svg ", '<svg class="logo" ', 1)
    favicon = base64.b64encode(Path("assets/fuin-mark-small.svg").read_bytes()).decode()
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fūin — sealed benchmark results anyone can check</title>
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{{FAVICON}}">
<style>
:root{{--ink:#192527;--paper:#F2EEE6;--card:#FAF8F3;--rule:#D8D2C5;--muted:#5E6A6C;--seal:#B6382C;--ok:#2E6B48;--warn:#8A5A00}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:48px 24px 96px}}
header{{border-bottom:2px solid var(--ink);padding-bottom:28px}}
header .logo{{width:300px;height:auto;display:block}} .say{{color:var(--muted);font-size:15px;margin:10px 0 0}}
h1{{position:absolute;left:-9999px}}
.lede{{font-size:20px;margin:14px 0 0;max-width:62ch;line-height:1.5}}
h2{{font-size:26px;margin:56px 0 8px}} h3{{font-size:18px;margin:32px 0 8px;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
p{{max-width:72ch}} a{{color:var(--seal)}} code,pre,.num,.detail{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
code{{font-size:.86em;background:#E6E0D3;padding:1px 5px;border-radius:3px}}
pre{{background:var(--ink);color:#F2EEE6;padding:12px 16px;border-radius:6px;overflow:auto;font-size:13.5px}}
table{{width:100%;border-collapse:collapse;font-size:14.5px;margin:12px 0}} th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--rule);vertical-align:top}}
thead th{{font:600 12px/1.3 ui-sans-serif,system-ui;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:2px solid var(--ink)}}
.summary .big{{font-size:30px;font-weight:700}} .summary small{{font-size:15px;color:var(--muted);font-weight:400}}
.verdict{{font:700 13px ui-monospace,monospace}} .verified{{color:var(--ok)}} .refused,.cant_certify{{color:var(--seal)}}
.meta{{color:var(--muted);font-size:14.5px}} .scroll{{overflow-x:auto}}
.reveals td span{{font-family:ui-monospace,monospace;font-size:12.5px;color:var(--muted)}} .hit{{color:var(--ok)}} .miss{{color:var(--seal)}}
details{{border:1px solid var(--rule);border-radius:6px;padding:10px 14px;margin:10px 0;background:var(--card)}} summary{{cursor:pointer}}
.checks,.warnings{{list-style:none;padding:0;margin:10px 0}} .checks li{{padding:4px 0;border-bottom:1px dotted var(--rule)}}
.ok{{font:700 11px ui-monospace,monospace;color:#fff;background:var(--ok);padding:1px 6px;border-radius:3px}} .detail{{font-size:12.5px;color:var(--muted);display:block;margin-left:44px}}
.warn{{color:var(--warn);font-size:14px}} .warn:before{{content:"warning · "}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:28px}} @media (max-width:760px){{.cols{{grid-template-columns:1fr}} header{{grid-template-columns:1fr}}}}
footer{{margin-top:64px;border-top:1px solid var(--rule);padding-top:16px;color:var(--muted);font-size:14px}}
</style></head><body><main>
<header><div>
{{LOGO}}<h1>Fūin</h1>
<p class="say">Fūin · 封印 · pronounced <i>foo-een</i> · Japanese for "seal"</p>
<p class="lede">Private benchmark results that anyone can check without an account and without the test set. The test set is sealed on NEAR before any model runs, every answer is signed by the model's TEE key on NEAR AI Cloud, and a future NEAR block picks which answers are revealed and re-scored.</p>
</div></header>

<section class="cols">
<div><h2>Two bad options</h2><p><b>Publish the test set</b>, and it leaks into the next model's training data. <b>Keep it private</b>, and everyone has to take the owner's word for the scores.</p></div>
<div><h2>What Fūin proves</h2><p>A named model in an attested TEE produced every committed answer, unedited. The set was sealed before the results were committed. The owner couldn't pick the audited items. The revealed answers re-score to the committed scores.</p></div>
</section>

{''.join(round_section(r) for r in ROUNDS)}
{fixtures_section()}

<section id="reproduce">
<h2>Check it yourself</h2>
<p>Everything on this page is recorded output from committed files. Run the same checks; you need no account and no API key:</p>
<pre>git clone {REPO} && cd fuin
./scripts/review.sh        # verifies every certificate, all fixtures and the tests; about 5 minutes</pre>
<p>Limits, printed with every verdict: score correctness is checked on the revealed sample only; instances of a model can share a signing key; the deployment trace is taken at preflight, and image build provenance is not verified; discarded or uncommitted runs can't be seen; the sample assumes NEAR block hashes are unpredictable; reveals permanently disclose their questions; the seal precedes the result commitment, which doesn't prove when inference happened. Testnet only.</p>
</section>
<footer>Built at NEAR HACKATHON 2026 · registry <a href="https://testnet.nearblocks.io/address/registry.fuin.testnet">registry.fuin.testnet</a> (locked: no access keys) · generated from commit <code>{e(commit)}</code> by <code>scripts/build_page.py</code></footer>
</main></body></html>
"""
    page = page.replace("{LOGO}", logo).replace("{FAVICON}", favicon)
    Path("site").mkdir(exist_ok=True)
    Path("site/index.html").write_text(page, encoding="utf-8")
    print("wrote site/index.html", f"({len(page)} bytes; rounds: {', '.join(ROUNDS)})")


if __name__ == "__main__":
    main()
