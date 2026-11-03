"""Model attestation report checks (spec: Attestation acceptance policy).

Credential-free: needs network access to Intel PCS (quote collateral) and NVIDIA NRAS (GPU verdict).
"""

import asyncio
import base64
import hashlib
import inspect
import json
import re
import struct

import dcap_qvl
import requests

NRAS_URL = "https://nras.attestation.nvidia.com/v3/attest/gpu"
CATALOG_URL = "https://cloud-api.near.ai/v1/model/list"
IMAGE_RE = re.compile(r"image:\s*\S*?([a-z0-9][\w./-]*@sha256:[0-9a-f]{64})")


def _json(v):
    return json.loads(v) if isinstance(v, str) else v


def app_compose(report: dict) -> str:
    return _json(report["info"])["tcb_info"]["app_compose"]


def compose_hash(report: dict) -> str:
    return hashlib.sha256(app_compose(report).encode()).hexdigest()


def image_digests(report: dict) -> list[str]:
    compose = _json(app_compose(report))
    return sorted(set(IMAGE_RE.findall(compose.get("docker_compose_file", ""))))


def replay_rtmr3(event_log) -> bytes:
    rtmr = bytes(48)
    for ev in _json(event_log):
        if ev.get("imr") != 3:
            continue
        digest = hashlib.sha384(
            struct.pack("<I", ev["event_type"]) + b":" + ev["event"].encode() + b":" + bytes.fromhex(ev["event_payload"])
        ).digest()
        if ev.get("digest") and bytes.fromhex(ev["digest"]) != digest:
            raise ValueError("event log digest mismatch")
        rtmr = hashlib.sha384(rtmr + digest).digest()
    return rtmr


def parse_report_data(report_data: bytes) -> tuple[bytes, bytes]:
    """64 bytes: signer (20-byte address, zero-padded to 32) || 32-byte client nonce."""
    if len(report_data) != 64:
        raise ValueError("report data must be 64 bytes")
    return report_data[:32], report_data[32:]


async def _verify(quote: bytes):
    r = dcap_qvl.get_collateral_and_verify(quote, dcap_qvl.INTEL_PCS_URL)
    return await r if inspect.isawaitable(r) else r


def verify_quote(quote_hex: str):
    """Returns (status, advisory_ids, td_report dict). Raises on forged/invalid quotes."""
    res = asyncio.run(_verify(bytes.fromhex(quote_hex)))
    rep = json.loads(res.to_json())["report"]
    td = rep.get("TD10") or rep.get("TD15")
    if td is None:
        raise ValueError("not a TDX quote")
    return res.status, list(res.advisory_ids), td


def nras_verdict(nvidia_payload) -> bool:
    """POST the GPU evidence unchanged to NVIDIA NRAS; True only on an explicit overall pass."""
    body = nvidia_payload if isinstance(nvidia_payload, str) else json.dumps(nvidia_payload)
    r = requests.post(NRAS_URL, data=body, headers={"Content-Type": "application/json"}, timeout=60)
    r.raise_for_status()
    jwt = r.json()[0][1]
    claims = json.loads(base64.urlsafe_b64decode(jwt.split(".")[1] + "=="))
    return claims.get("x-nvidia-overall-att-result") is True


def tcb_outcome(status: str, advisories: list[str]) -> str:
    """User's TCB policy (2026-10-27): clean / warning / revoked."""
    if status == "Revoked":
        return "revoked"
    return "clean" if status == "UpToDate" and not advisories else "warning"


def check_report(report: dict, nonce_hex: str, policy: dict, *, use_nras: bool = True) -> dict:
    """Check one model report under an attestation policy. Returns per-check results and an outcome.

    outcome: "accepted", "accepted_with_warning", ("refused", code) or ("cant_certify", code).
    """
    checks: dict = {"model": report["model_name"], "signing_address": report["signing_address"].lower()}
    nonce = nonce_hex.lower()
    try:
        status, advisories, td = verify_quote(report["intel_quote"])
    except (ValueError, KeyError) as e:
        return {**checks, "error": str(e), "outcome": ("refused", "attestation_invalid")}
    except RuntimeError as e:  # collateral service unreachable
        return {**checks, "error": str(e), "outcome": ("cant_certify", "evidence_unavailable")}
    signer_rd, nonce_rd = parse_report_data(bytes.fromhex(td["report_data"]))
    signer = bytes.fromhex(report["signing_address"].removeprefix("0x"))
    checks.update(
        quote_status=status,
        advisories=advisories,
        signing_algo_ok=report.get("signing_algo") == "ecdsa",
        report_data_signer_ok=signer_rd == signer.ljust(32, b"\0"),
        report_data_nonce_ok=nonce_rd.hex() == nonce,
        request_nonce_ok=str(report.get("request_nonce", "")).lower() == nonce,
        debug_off=int(td["td_attributes"][:2], 16) & 1 == 0,
        mrconfigid_ok=bytes.fromhex(td["mr_config_id"]) == b"\x01" + bytes.fromhex(compose_hash(report)) + bytes(15),
        gpu_nonce_ok=str(_json(report["nvidia_payload"]).get("nonce", "")).lower() == nonce,
    )
    try:
        checks["rtmr3_ok"] = replay_rtmr3(report["event_log"]).hex() == td["rt_mr3"]
    except ValueError:
        checks["rtmr3_ok"] = False
    bad = [k for k, v in checks.items() if k.endswith(("_ok", "_off")) and v is not True]
    if bad:
        return {**checks, "failed": bad, "outcome": ("refused", "attestation_invalid")}
    tcb = tcb_outcome(status, advisories)
    if tcb == "revoked":
        return {**checks, "outcome": ("refused", "tcb_revoked")}
    accepted = policy.get("models", {}).get(report["model_name"], {}).get("compose_hashes", {})
    checks["compose_hash"] = compose_hash(report)
    if checks["compose_hash"] not in accepted:
        return {**checks, "outcome": ("cant_certify", "measurement_unapproved")}
    if use_nras:
        try:
            checks["nras_ok"] = nras_verdict(report["nvidia_payload"])
        except (requests.RequestException, ValueError, KeyError, IndexError) as e:
            return {**checks, "error": f"NRAS: {e}", "outcome": ("cant_certify", "evidence_unavailable")}
        if not checks["nras_ok"]:
            return {**checks, "outcome": ("refused", "attestation_invalid")}
    checks["tcb"] = tcb
    return {**checks, "outcome": ("accepted",) if tcb == "clean" else ("accepted_with_warning",)}


def is_tee_model(model_id: str, catalog: dict | None = None) -> bool:
    """Catalog says verifiable + attestationSupported; external models (OpenAI, Anthropic, ...) don't."""
    catalog = catalog or requests.get(CATALOG_URL, timeout=30).json()
    for m in catalog["models"]:
        if m.get("modelId") == model_id:
            md = m.get("metadata", {})
            return bool(md.get("verifiable") and md.get("attestationSupported"))
    return False
