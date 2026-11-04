"""Build site/data.js for the interactive results page (site/index.html + site/app.js).

Usage: uv run python scripts/build_page.py
Bundles, from committed files only: the real certificates (attestation reports trimmed to what the browser checks:
quote, event log, app_compose and nonce; NVIDIA's GPU verdict service blocks browsers, so the page shows the CLI's recorded NRAS result), the recorded
`fuin verify --json` output, the answer-hint fixture, the verifier's supported-policy constants, the fixtures manifest
and the hero's dot map. Loaded with a <script> tag so the page also works from file://.
"""
import glob
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, "src")
from fuin import near, owner  # noqa: E402
from fuin import policy as P  # noqa: E402


def slim(cert: dict) -> dict:
    c = json.loads(json.dumps(cert))
    keep = lambda a: {"signing_address": a["signing_address"], "model_name": a.get("model_name"), "request_nonce": a.get("request_nonce"),
                      "intel_quote": a.get("intel_quote"), "event_log": a.get("event_log"),
                      "info": {"tcb_info": {"app_compose": a.get("info", {}).get("tcb_info", {}).get("app_compose")}}}
    c["run"]["model_report"] = {"model_attestations": [keep(a) for a in cert["run"]["model_report"]["model_attestations"]]}  # GPU payload dropped
    return c


def recorded(rid: str) -> dict:
    out = {}
    for f in glob.glob(f"evidence/*-round-{rid}/verify.jsonl"):
        for line in open(f):
            r = json.loads(line)
            out[Path(r["cert"]).name] = {k: r.get(k) for k in ("outcome", "code", "checks", "warnings", "scope", "trace")}
    return out


def hands() -> dict:
    rows = Path("site/hands-dots.txt").read_text().split("\n")
    w = max(len(r) for r in rows)
    mid = w // 2
    left = max((max(i for i, ch in enumerate(r[:mid]) if ch != " "), j) for j, r in enumerate(rows) if r[:mid].strip())
    right = min((min(i for i, ch in enumerate(r) if ch != " " and i >= mid), j) for j, r in enumerate(rows) if r[mid:].strip())
    return {"rows": rows, "cols": w, "gap": {"x": (left[0] + right[0]) / 2 / w, "y": (left[1] + right[1]) / 2 / len(rows)}}


def main() -> None:
    rounds = []
    for rid in ("near-dev-60-r2", "near-dev-60-r1"):
        rec = recorded(rid)
        certs = []
        for p in sorted(glob.glob(f"examples/cert-{rid}-*.json")):
            c = json.loads(Path(p).read_text())
            certs.append({"file": p, "cert": slim(c), "recorded": rec.get(Path(p).name)})
        certs.sort(key=lambda x: -x["cert"]["run"]["total_score"])
        cap = certs[0]["cert"]["benchmark"]["policy"]["models"][certs[0]["cert"]["run"]["model_id"]]["max_tokens"]
        rounds.append({"id": rid, "cap": cap, "certs": certs})
    data = {
        "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip(),
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "registry": near.REGISTRY,
        "rpc": near.NETWORKS["testnet"],
        "supported": {"protocol": P.PROTOCOL, "template": P.TEMPLATE, "privacy": P.PRIVACY, "sampler": P.SAMPLER,
                      "allowed_settings": sorted(P.ALLOWED_SETTINGS),
                      "scorers": {name: sha for (name, sha) in P.SCORERS}},
        "attested_models": sorted(owner.attestation_policy()["models"]),
        "attestation_policy": {"version": owner.attestation_policy()["version"],
                               "models": {m: sorted(v["compose_hashes"]) for m, v in owner.attestation_policy()["models"].items()}},
        "pccs": "https://pccs.phala.network",
        "rounds": rounds,
        "hint": {"file": "examples/tampered/answer-hint.json", "cert": slim(json.loads(Path("examples/tampered/answer-hint.json").read_text()))},
        "manifest": json.loads(Path("examples/tampered/manifest.json").read_text())["fixtures"],
        "hands": hands(),
    }
    js = "window.FUIN = " + json.dumps(data, separators=(",", ":"), ensure_ascii=False) + ";\n"
    Path("site/data.js").write_text(js, encoding="utf-8")
    print(f"wrote site/data.js ({len(js) // 1024} KB; rounds {', '.join(r['id'] for r in rounds)}; commit {data['commit']})")


if __name__ == "__main__":
    main()
