"""Model attestation report checks (spec: Attestation acceptance policy).

Credential-free: needs network access to Intel PCS (quote collateral) and NVIDIA NRAS (GPU verdict).
"""

import asyncio
import base64
import hashlib
import inspect
import json
import time
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


async def _collateral(quote: bytes):
    r = dcap_qvl.get_collateral(dcap_qvl.INTEL_PCS_URL, quote)
    return await r if inspect.isawaitable(r) else r


def _pcs_reachable() -> bool:
    try:
        requests.get(f"{dcap_qvl.INTEL_PCS_URL.rstrip('/')}/tdx/certification/v4/qe/identity", timeout=15)
        return True
    except requests.RequestException:
        return False


def verify_quote(quote_hex: str):
    """Returns (status, advisory_ids, td_report dict).

    Raises ValueError/TypeError for a malformed or invalid quote, and RuntimeError when Intel's collateral can't be
    fetched for a well-formed quote: an outage, not evidence of tampering. (The combined dcap call raised ValueError
    for both, so an Intel outage was refused as an invalid quote.)"""
    raw = bytes.fromhex(quote_hex)
    dcap_qvl.parse_quote(raw)
    for attempt in (1, 2):  # one retry: a single dropped request to Intel would otherwise read as an outage (the pilot hit one)
        try:
            collateral = asyncio.run(_collateral(raw))
            break
        except ValueError as e:  # an outage only if the request failed or Intel doesn't answer; otherwise the quote is at fault
            dropped = any(m in str(e) for m in ("error sending request", "timed out", "dns error"))
            if dropped and attempt == 1:
                time.sleep(3)
                continue
            if dropped or not _pcs_reachable():
                raise RuntimeError(f"Intel collateral unavailable: {str(e)[:160]}") from e
            raise ValueError(f"quote rejected at the collateral step: {str(e)[:160]}") from e
    res = dcap_qvl.verify(raw, collateral, int(time.time()))
    rep = json.loads(res.to_json())["report"]
    td = rep.get("TD10") or rep.get("TD15")
    if td is None:
        raise ValueError("not a TDX quote")
    return res.status, list(res.advisory_ids), td


NRAS_ISSUER = "https://nras.attestation.nvidia.com"
NRAS_JWKS = "https://nras.attestation.nvidia.com/.well-known/jwks.json"
_NRAS_KEYS: dict = {}  # NVIDIA's signing keys by kid, fetched once per process


def _b64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _nras_key(kid: str):
    """NVIDIA's ES384 (P-384) public key for this kid, from its published key set."""
    from cryptography.hazmat.primitives.asymmetric import ec
    if kid not in _NRAS_KEYS:
        r = requests.get(NRAS_JWKS, timeout=30)
        r.raise_for_status()
        for k in r.json().get("keys", []):
            if k.get("kty") == "EC" and k.get("crv") == "P-384":
                _NRAS_KEYS[k["kid"]] = ec.EllipticCurvePublicNumbers(
                    int.from_bytes(_b64u(k["x"]), "big"), int.from_bytes(_b64u(k["y"]), "big"), ec.SECP384R1()).public_key()
    return _NRAS_KEYS.get(kid)


def nras_token_ok(jwt: str, nonce: str, now: float | None = None) -> bool:
    """NVIDIA's verdict token: ES384-signed by a key in NVIDIA's key set, issued by NRAS, inside its validity window,
    bound to this report's nonce (eat_nonce), with an explicit overall pass (review 5)."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    try:
        h64, c64, s64 = jwt.split(".")
        header, claims, sig = json.loads(_b64u(h64)), json.loads(_b64u(c64)), _b64u(s64)
    except ValueError:
        return False
    key = _nras_key(header.get("kid", "")) if header.get("alg") == "ES384" else None
    if key is None or len(sig) != 96:
        return False
    try:
        key.verify(utils.encode_dss_signature(int.from_bytes(sig[:48], "big"), int.from_bytes(sig[48:], "big")),
                   f"{h64}.{c64}".encode(), ec.ECDSA(hashes.SHA384()))
    except InvalidSignature:
        return False
    now = time.time() if now is None else now
    return (claims.get("iss") == NRAS_ISSUER and claims.get("nbf", 0) <= now + 300 and claims.get("exp", 0) >= now - 300
            and str(claims.get("eat_nonce", "")).lower() == nonce.lower() and claims.get("x-nvidia-overall-att-result") is True)


def nras_verdict(nvidia_payload, nonce: str | None = None) -> bool:
    """POST the GPU evidence unchanged to NVIDIA NRAS; True only on a verified overall pass for this nonce (the
    evidence's own nonce unless given)."""
    body = nvidia_payload if isinstance(nvidia_payload, str) else json.dumps(nvidia_payload)
    r = requests.post(NRAS_URL, data=body, headers={"Content-Type": "application/json"}, timeout=60)
    r.raise_for_status()
    return nras_token_ok(r.json()[0][1], nonce if nonce is not None else str(_json(nvidia_payload).get("nonce", "")))


def tcb_outcome(status: str, advisories: list[str]) -> str:
    """The TCB rule from the Oct 24 design (README, "When it was written"): clean / warning / revoked."""
    if status == "Revoked":
        return "revoked"
    return "clean" if status == "UpToDate" and not advisories else "warning"


def check_report(report: dict, nonce_hex: str, policy: dict, *, use_nras: bool = True) -> dict:
    """Check one model report under an attestation policy. Returns per-check results and an outcome.

    outcome: "accepted", "accepted_with_warning", ("refused", code) or ("cant_certify", code).
    """
    if not all(isinstance(report.get(k), str) for k in ("model_name", "signing_address", "intel_quote")):
        # NEAR also serves models from partners' own TEEs (Chutes, Tinfoil) with their own evidence format; Fūin checks only NEAR's
        return {"model": report.get("model_name") or report.get("model"), "signing_address": str(report.get("signing_address", "")).lower(),
                "error": f"attested by {report.get('provider') or 'another scheme'}, in a format Fūin doesn't verify",
                "outcome": ("cant_certify", "policy_unsupported")}
    checks: dict = {"model": report["model_name"], "signing_address": report["signing_address"].lower()}
    nonce = nonce_hex.lower()
    try:
        status, advisories, td = verify_quote(report["intel_quote"])
    except (ValueError, KeyError, TypeError) as e:
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
    # the OS the application runs on (firmware, kernel, initrd, cmdline) must be an approved measurement too; MRCONFIGID and
    # RTMR3 only identify the application, and an unapproved OS could fake those extends
    entry = accepted[checks["compose_hash"]]
    os_seen = {k: td[k] for k in ("mr_td", "rt_mr0", "rt_mr1", "rt_mr2")}
    checks["os_approved"] = (os_seen in entry.get("os_measurements", [])
                             and (report.get("info") or {}).get("os_image_hash") == entry.get("os_image_hash"))
    if not checks["os_approved"]:
        return {**checks, "os_seen": os_seen, "outcome": ("cant_certify", "measurement_unapproved")}
    if use_nras:
        try:
            checks["nras_ok"] = nras_verdict(report["nvidia_payload"], nonce)
        except (requests.RequestException, ValueError, KeyError, IndexError) as e:
            return {**checks, "error": f"NRAS: {e}", "outcome": ("cant_certify", "evidence_unavailable")}
        if not checks["nras_ok"]:
            return {**checks, "outcome": ("refused", "attestation_invalid")}
    checks["tcb"] = tcb
    return {**checks, "td": td, "outcome": ("accepted",) if tcb == "clean" else ("accepted_with_warning",)}


def is_tee_model(model_id: str, catalog: dict | None = None) -> bool:
    """Catalog says verifiable + attestationSupported; external models (OpenAI, Anthropic, ...) don't."""
    catalog = catalog or requests.get(CATALOG_URL, timeout=30).json()
    for m in catalog["models"]:
        if m.get("modelId") == model_id:
            md = m.get("metadata", {})
            return bool(md.get("verifiable") and md.get("attestationSupported"))
    return False
