"""Trace a model's serving container from NEAR's attested deployment log to a public compose file.

A model report's measured app_compose runs NEAR's compose-manager, pinned to GITHUB_REPO. The compose-manager
attests its own action log with a second TDX quote (report data = sha256(canonical actions) || nonce). Each
`compose_up` names a git tag, commit, compose file and the file's sha256. We replay the log to find which
services are up, fetch their compose files at the logged commits from the public repo, check the sha256, and read
the services that declare `--served-model-name <model>`: image digest, model path and revision.

Build provenance (build_provenance): where NEAR publishes SLSA v1 provenance for a serving image (a sigstore bundle
attached to the image digest as an OCI referrer), it is verified against sigstore's public-good trust root and must come
from a GitHub Actions workflow in NEAR AI's organisation. Credential-free (raw.githubusercontent.com, Docker Hub,
sigstore's TUF repository).
"""

import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests
import yaml

from fuin import POLICY
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


def served_as(cmd: str, model: str) -> dict | None:
    """How a serving command serves `model`: under its own name ({"adapter": None}), as a LoRA adapter on the service's
    base weights ({"adapter": {"path", "weights", "revision"}}, weights and revision only when the path is a pinned
    Hugging Face snapshot), or not at all (None). vLLM declares adapters with --lora-modules JSON, SGLang with
    --lora-paths name=path."""
    if re.search(rf"--served-model-name\s+{re.escape(model)}(\s|$)", cmd):
        return {"adapter": None}
    path = None
    for obj in re.findall(r"\{[^{}]*\}", cmd.partition("--lora-modules")[2]):
        if re.search(rf'"name"\s*:\s*"{re.escape(model)}"', obj):
            p = re.search(r'"path"\s*:\s*"([^"]+)"', obj)
            path = p.group(1) if p else "?"
            break
    if path is None:
        m = re.search(rf"--lora-paths\s+(?:\S+=\S+\s+)*?{re.escape(model)}=(\S+)", cmd)
        path = m.group(1) if m else None
    if path is None:
        return None
    hub = re.search(r"models--([\w.-]+)--([\w.-]+)/snapshots/([0-9a-f]+)", path)
    return {"adapter": {"path": path, "weights": f"{hub.group(1)}/{hub.group(2)}" if hub else None, "revision": hub.group(3) if hub else None}}


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
        how = served_as(cmd, model)
        if how is None:
            continue
        img = str(svc.get("image", ""))
        m = re.search(r"([a-z0-9][\w./-]*@sha256:[0-9a-f]{64})", img)
        path = re.search(r"--model-path\s+(\S+)", cmd)
        # vLLM takes the weights as a positional Hugging Face cache path; LoRA adapters (other served names) follow
        base_cmd, _, lora_cmd = cmd.partition("--lora-modules")
        hub = re.search(r"models--([\w.-]+)--([\w.-]+)/snapshots/([0-9a-f]+)", path.group(1) if path else base_cmd)
        loras = [n for n in re.findall(r'"name"\s*:\s*"([^"]+)"', lora_cmd) if n != model]
        rev = re.search(r"model_revision:([0-9a-f]{7,40})", json.dumps(svc.get("labels", {}))) or re.search(r"--revision\s+([0-9a-f]{7,40})", cmd)
        pos = re.match(r"\s*(?:vllm\s+serve\s+)?([\w.-]+/[\w.-]+)(\s|$)", cmd)  # vLLM can also take the repo id as its first argument
        serving.append({"service": name, "tag": a["tag"], "commit": a["commit"], "file": a["file"],
                        "file_sha256_checked": f["sha_checked"], "image": m.group(1) if m else img,
                        "model_path": f"{hub.group(1)}/{hub.group(2)}" if hub else (path.group(1) if path else (pos.group(1) if pos else None)),
                        "model_revision": hub.group(3) if hub else (rev.group(1) if rev else None), "lora_modules": loras,
                        "adapter": how["adapter"]})
    if not serving:
        raise TraceUnavailable(f"no deployed service serves {model}, by --served-model-name or as a LoRA adapter")
    loose = unpinned(serving)
    if loose:
        raise TraceUnavailable(f"service {loose} isn't pinned: its image digest, weights, weights revision and compose sha256 are all required")
    return {"repo": repo, "cm_quote_status": status, "services": sorted(serving, key=lambda s: s["service"])}

def unpinned(serving: list[dict]) -> str | None:
    """The first serving service whose trace doesn't pin what ran, or None. A trace has to pin it: a mutable image tag,
    unknown weights or an unchecked compose file shows nothing (review 3). site/verify.js applies the same rule."""
    for x in serving:
        if not (re.fullmatch(r"[a-z0-9][\w./-]*@sha256:[0-9a-f]{64}", x["image"]) and x["model_path"] and x["model_revision"] and x["file_sha256_checked"]):
            return x["service"]
    return None


# ---------------- build provenance: SLSA v1 that NEAR publishes for its images ----------------

SLSA_V1 = "https://slsa.dev/provenance/v1"
GITHUB_OIDC = "https://token.actions.githubusercontent.com"
NEAR_BUILDERS = "https://github.com/nearai/"  # NEAR AI's GitHub organisation
# raw sigstore bundles by image digest, re-verified on every use; best-effort, so a read-only home only costs a re-download
BUNDLE_CACHE = Path(os.environ.get("FUIN_CACHE_DIR") or Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "fuin") / "slsa"
# sigstore's public-good trusted root (Fulcio, Rekor, CT logs, TSA), pinned like the attestation policies: no TUF fetch and
# no writes outside the clone. Source: tuf-repo-cdn.sigstore.dev, 2026-11-05.
SIGSTORE_ROOT = POLICY / "sigstore-trusted-root.json"


_VERIFIER = None  # sigstore's trust root, fetched once per process


class ProvenanceInvalid(Exception):
    """A provenance bundle exists for the image but fails verification (signature, identity or subject)."""


def _registry(repo: str):
    tok = requests.get("https://auth.docker.io/token", params={"service": "registry.docker.io", "scope": f"repository:{repo}:pull"},
                       timeout=30).json()["token"]
    return {"Authorization": f"Bearer {tok}"}, f"https://registry-1.docker.io/v2/{repo}"


def _slsa_bundle(repo: str, digest: str) -> bytes | None:
    """The newest SLSA v1 sigstore bundle attached to the image as an OCI referrer, or None. The bytes are cached by
    digest (they never change and anonymous registry reads are rate-limited); they are verified again on every use."""
    cached = BUNDLE_CACHE / f"{digest.replace(':', '-')}.json"
    if cached.exists() and (cached.stat().st_size or time.time() - cached.stat().st_mtime < 86400):  # "none" expires daily
        return cached.read_bytes() or None
    auth, base = _registry(repo)
    accept = {"Accept": "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json"}
    r = requests.get(f"{base}/referrers/{digest}", headers={**auth, **accept}, timeout=30)
    found = [m for m in r.json().get("manifests", []) if (m.get("annotations") or {}).get("dev.sigstore.bundle.predicateType") == SLSA_V1] \
        if r.status_code == 200 else []
    if r.status_code not in (200, 404):
        r.raise_for_status()
    blob = b""
    if found:
        newest = max(found, key=lambda m: m["annotations"].get("org.opencontainers.image.created", ""))
        man = requests.get(f"{base}/manifests/{newest['digest']}", headers={**auth, **accept}, timeout=30)
        man.raise_for_status()
        b = requests.get(f"{base}/blobs/{man.json()['layers'][0]['digest']}", headers=auth, timeout=60)
        b.raise_for_status()
        blob = b.content
    try:
        BUNDLE_CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(blob)  # an empty file records "no provenance published" for this digest
    except OSError:
        pass
    return blob or None


def build_provenance(image: str) -> dict | None:
    """Verify the SLSA v1 provenance NEAR publishes for a Docker Hub image digest against sigstore's public-good trust
    root: signed by a GitHub Actions workflow in NEAR AI's organisation, logged in Rekor, and about exactly this digest.
    Returns the builder workflow and source commit; None if the image has none; raises ProvenanceInvalid if a bundle
    fails; registry or sigstore outages raise requests errors."""
    m = re.fullmatch(r"(?:docker\.io/)?([a-z0-9][\w.-]*(?:/[\w.-]+)?)@(sha256:[0-9a-f]{64})", image)
    if not m:
        return None
    repo, digest = (m.group(1) if "/" in m.group(1) else "library/" + m.group(1)), m.group(2)
    blob = _slsa_bundle(repo, digest)
    if blob is None:
        return None
    from cryptography import x509
    from sigstore.models import Bundle, TrustedRoot
    from sigstore.verify import Verifier, policy
    try:
        bundle = Bundle.from_json(blob)
        global _VERIFIER
        _VERIFIER = _VERIFIER or Verifier(trusted_root=TrustedRoot.from_file(str(SIGSTORE_ROOT)))
        _, payload = _VERIFIER.verify_dsse(bundle, policy.OIDCIssuerV2(GITHUB_OIDC))
        san = bundle.signing_certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        builder = (san.get_values_for_type(x509.UniformResourceIdentifier) or [""])[0]
        st = json.loads(payload)
    except Exception as e:  # noqa: BLE001 — any failure of a present bundle is invalid evidence, never "fine"
        raise ProvenanceInvalid(f"{type(e).__name__}: {str(e)[:160]}") from e
    if not builder.startswith(NEAR_BUILDERS):
        raise ProvenanceInvalid(f"built by {builder}, outside NEAR AI's GitHub organisation")
    if st.get("predicateType") != SLSA_V1 or digest.split(":")[1] not in [s.get("digest", {}).get("sha256") for s in st.get("subject", [])]:
        raise ProvenanceInvalid("the provenance is about another image")
    bd = st["predicate"]["buildDefinition"]
    wf = (bd.get("externalParameters") or {}).get("workflow") or {}
    commit = next((d["digest"]["gitCommit"] for d in bd.get("resolvedDependencies", []) if "gitCommit" in d.get("digest", {})), None)
    return {"builder": builder, "repository": wf.get("repository"), "workflow": wf.get("path"), "ref": wf.get("ref"), "commit": commit}
