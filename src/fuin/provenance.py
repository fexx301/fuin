"""Trace a model's serving container from NEAR's attested deployment log to a public compose file.

A model report's measured app_compose runs NEAR's compose-manager, pinned to GITHUB_REPO. The compose-manager
attests its own action log with a second TDX quote (report data = sha256(canonical actions) || nonce). Each
`compose_up` names a git tag, commit, compose file and the file's sha256. We replay the log to find which
services are up, fetch their compose files at the logged commits from the public repo, check the sha256, and read
the services that declare `--served-model-name <model>`: image digest, model path and revision.

Not covered: the container image's build provenance (cosign/SLSA). Credential-free (raw.githubusercontent.com).
"""

import hashlib
import json
import re

import requests
import yaml

from fuin import attestation as A

UP, DOWN = "compose_up", "compose_down"


class TraceInvalid(Exception):
    """Evidence that contradicts itself (hash, nonce, quote or file mismatch)."""


class TraceUnavailable(Exception):
    """The report carries no traceable deployment log, or no deployed service declares the model."""


def canonical_actions(actions: list) -> bytes:
    """compose-manager's canonicalize_actions: sorted keys, compact, UTF-8 (nulls and empty arrays already omitted)."""
    return json.dumps(actions, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _repo(report: dict) -> str:
    m = re.search(r"GITHUB_REPO=https://github\.com/([\w.-]+/[\w.-]+?)(?:\.git)?\s", A._json(A.app_compose(report))["docker_compose_file"])
    if not m:
        raise TraceUnavailable("measured app_compose pins no GITHUB_REPO")
    return m.group(1)


def trace(report: dict, nonce_hex: str, td_model: dict | None = None) -> dict:
    """Returns {"repo", "services": [...], "cm_quote_status"}; raises TraceInvalid, TraceUnavailable or requests errors."""
    cma = report.get("compose_manager_attestation")
    if not cma:
        raise TraceUnavailable("no compose_manager_attestation in the report")
    try:  # the attestation is present, so anything malformed in it is invalid evidence, not a missing trace
        actions = cma["actions"]
        ah = hashlib.sha256(canonical_actions(actions)).hexdigest()
        if ah != cma["actions_hash"] or cma["nonce"].lower() != nonce_hex.lower() or cma["report_data"].lower() != ah + nonce_hex.lower():
            raise TraceInvalid("action log hash, nonce or report data mismatch")
        status, _adv, td = A.verify_quote(cma["quote"])  # RuntimeError (Intel unreachable) propagates as an outage
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise TraceInvalid(f"malformed compose-manager attestation ({type(e).__name__})") from e
    if td["report_data"].lower() != ah + nonce_hex.lower():
        raise TraceInvalid("compose-manager quote does not bind the action log and nonce")
    same_cvm = ("mr_td", "rt_mr0", "rt_mr1", "rt_mr2", "mr_config_id", "rt_mr3")  # OS and application measurements
    if td_model is not None and any(td[k] != td_model[k] for k in same_cvm):
        raise TraceInvalid("compose-manager quote is from a different CVM than the model report")
    repo = _repo(report)

    files: dict[tuple[str, str], dict] = {}

    def compose(a: dict) -> dict:
        key = (a["commit"], a["file"])
        if key not in files:
            r = requests.get(f"https://raw.githubusercontent.com/{repo}/{a['commit']}/{a['file']}", timeout=30)
            r.raise_for_status()
            if a.get("file_sha256") and hashlib.sha256(r.content).hexdigest() != a["file_sha256"]:
                raise TraceInvalid(f"{a['file']}@{a['commit'][:10]} does not match the logged sha256")
            files[key] = {"doc": yaml.safe_load(r.content), "sha_checked": bool(a.get("file_sha256"))}
        return files[key]

    latest: dict[str, dict] = {}  # service -> the last up/down action that touched it
    for a in reversed(actions):
        if a["action"] not in (UP, DOWN):
            continue
        names = a.get("services") or list((compose(a)["doc"].get("services") or {}))
        for n in names:
            latest.setdefault(n, a)

    model = report["model_name"]
    serving = []
    for name, a in latest.items():
        if a["action"] != UP:
            continue
        f = compose(a)
        svc = (f["doc"].get("services") or {}).get(name)
        if not svc:
            continue
        cmd = svc.get("command") or ""
        cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
        if not re.search(rf"--served-model-name\s+{re.escape(model)}(\s|$)", cmd):
            continue
        img = str(svc.get("image", ""))
        m = re.search(r"([a-z0-9][\w./-]*@sha256:[0-9a-f]{64})", img)
        path = re.search(r"--model-path\s+(\S+)", cmd)
        # vLLM takes the weights as a positional Hugging Face cache path; LoRA adapters (other served names) follow
        base_cmd, _, lora_cmd = cmd.partition("--lora-modules")
        hub = re.search(r"models--([\w.-]+)--([\w.-]+)/snapshots/([0-9a-f]+)", path.group(1) if path else base_cmd)
        loras = re.findall(r'"name"\s*:\s*"([^"]+)"', lora_cmd)
        rev = re.search(r"model_revision:([0-9a-f]{7,40})", json.dumps(svc.get("labels", {})))
        serving.append({"service": name, "tag": a["tag"], "commit": a["commit"], "file": a["file"],
                        "file_sha256_checked": f["sha_checked"], "image": m.group(1) if m else img,
                        "model_path": f"{hub.group(1)}/{hub.group(2)}" if hub else (path.group(1) if path else None),
                        "model_revision": hub.group(3) if hub else (rev.group(1) if rev else None), "lora_modules": loras})
    if not serving:
        raise TraceUnavailable(f"no deployed service declares --served-model-name {model}")
    return {"repo": repo, "cm_quote_status": status, "services": sorted(serving, key=lambda s: s["service"])}
