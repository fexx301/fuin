"""fuin policy-update: draft the verifier's next attestation policy when NEAR redeploys a model.

For each model, fetch a fresh report (fresh nonce) and check every candidate under the current policy. A candidate whose
evidence holds (Intel quote, signer and nonce binding, RTMR3 replay, NVIDIA's NRAS verdict) but whose application or OS
isn't approved yet goes into policy/attestation-v<N+1>.json, with what a reviewer needs: compose hash, OS measurements,
os_image_hash, image digests and the deployment trace. Nothing is approved automatically: the verifier keeps using
owner.ATTESTATION_POLICY until a person has reviewed the draft and points that constant at it.
"""
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from fuin import attestation as A
from fuin import inference, owner, provenance


def propose(models: list[str]) -> tuple[dict | None, list[str]]:
    """The draft policy (None if nothing new) and one line per candidate saying what happened to it."""
    current = owner.attestation_policy()
    draft, notes, added = json.loads(json.dumps(current)), [], []
    for model in models:
        nonce = os.urandom(32).hex()
        report = inference.model_report(model, nonce)
        for c in report.get("model_attestations", []):
            res = A.check_report(c, nonce, current, use_nras=False)
            outcome = tuple(res["outcome"])
            if outcome[0].startswith("accepted"):
                notes.append(f"{model}: {res['compose_hash'][:12]}… already approved")
                continue
            if outcome != ("cant_certify", "measurement_unapproved"):  # bad or unavailable evidence is never proposed
                notes.append(f"{model}: {str(c.get('signing_address'))[:10]}… not proposed: {' '.join(outcome)}" + (f" ({res['error']})" if res.get("error") else ""))
                continue
            status, _adv, td = A.verify_quote(c["intel_quote"])
            if not A.nras_verdict(c["nvidia_payload"]):
                notes.append(f"{model}: NVIDIA's NRAS refused the GPU evidence; not proposed")
                continue
            ch = A.compose_hash(c)
            os_seen = {k: td[k] for k in ("mr_td", "rt_mr0", "rt_mr1", "rt_mr2")}
            entries = draft["models"].setdefault(model, {"compose_hashes": {}})["compose_hashes"]
            entry = entries.setdefault(ch, {
                "source": f"{inference.GATEWAY}/v1/attestation/report?model={model}",
                "fetched_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                "os_image_hash": (c.get("info") or {}).get("os_image_hash"), "os_measurements": [],
                "image_digests": A.image_digests(c), "signing_address_seen": c["signing_address"].lower(),
                "quote_status": status, "evidence": ""})
            if os_seen in entry["os_measurements"]:
                continue
            entry["os_measurements"].append(os_seen)
            try:
                tr = provenance.trace(c, nonce, td)
                entry["evidence"] = "; ".join(f"{s['service']} @{s['tag']} {s['file']} image {s['image']} weights {s['model_path']}"
                                              for s in tr["services"])
            except Exception as e:  # noqa: BLE001 — the reviewer sees why the trace failed instead of a silent gap
                entry["evidence"] = f"deployment trace failed: {type(e).__name__}: {str(e)[:160]}"
            added.append(f"{model} {ch[:8]}")
            notes.append(f"{model}: proposed compose {ch[:12]}… on OS {td['mr_td'][:12]}…, quote {status}, NRAS true")
    if not added:
        return None, notes
    n = int(re.search(r"(\d+)$", current["version"]).group(1)) + 1
    draft["version"] = f"attestation-v{n}"
    draft["note"] = (current.get("note", "") + f" v{n} (drafted by fuin policy-update, "
                     f"{datetime.now(UTC).strftime('%Y-%m-%d')}; review before use) adds {', '.join(added)}.").strip()
    return draft, notes


def write(draft: dict) -> Path:
    path = Path(owner.ATTESTATION_POLICY).with_name(f"{draft['version']}.json")
    if path.exists():
        raise SystemExit(f"{path} already exists; review or remove it first")
    path.write_text(json.dumps(draft, indent=2, ensure_ascii=False) + "\n")
    return path
