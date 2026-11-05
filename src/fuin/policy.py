"""Sealed evaluation policy (spec: Sealed policy) and the verifier's supported set."""

import hashlib
from pathlib import Path

from fuin import core, scorer, scorer_v1

PROTOCOL = "fuin-v1"
TEMPLATE = "fuin-request-v1"  # inference.build_request
PRIVACY = "nonce-in-user-field-v1"
SAMPLER = "fuin-audit-v1"
TEMPLATE_V2 = "fuin-request-v2"  # nonce bound to the seal block (core.seal_bound_nonce)
TEE_AUDIT = "tee-scored-v1"  # every item re-scored inside a TEE by a sealed scorer build; nothing revealed
ALLOWED_SETTINGS = {"max_tokens", "temperature", "chat_template_kwargs"}


def scorer_sha256(mod=scorer) -> str:
    return hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()


SCORERS = {(m.NAME, scorer_sha256(m)): m for m in (scorer_v1, scorer)}  # supported, by name and file hash


def scorer_for(policy: dict):
    """The supported scorer module a sealed policy names, or None."""
    sc = policy.get("scorer", {})
    return SCORERS.get((sc.get("name"), sc.get("sha256")))


def make_policy(n: int, models: dict[str, dict], mod=scorer, *, tee_wasm: str | None = None) -> dict:
    """The sealed policy. With `tee_wasm`, a zero-reveal round: requests use the seal-bound nonce, and every item is scored
    inside a TEE by that exact scorer build (its sha256 is sealed), with no audit sample."""
    d, k = core.audit_size(n)
    pol = {
        "protocol": PROTOCOL,
        "models": models,
        "request": {"template": TEMPLATE, "privacy_profile": PRIVACY},
        "scorer": {"name": mod.NAME, "sha256": scorer_sha256(mod)},
        "score": {"values": [0, 1], "aggregate": "sum", "denominator": n},
        "audit": {"D": d, "target": {"numerator": 95, "denominator": 100}, "k": k, "sampler": SAMPLER},
    }
    if tee_wasm:
        pol["request"] = {"template": TEMPLATE_V2, "privacy_profile": PRIVACY}
        pol["audit"] = {"mode": TEE_AUDIT, "k": 0, "scorer_wasm_sha256": tee_wasm}
    return pol


def is_tee_round(policy: dict) -> bool:
    return isinstance(policy.get("audit"), dict) and policy["audit"].get("mode") == TEE_AUDIT


def policy_hash(policy: dict) -> str:
    return core.sha256(core.jcs(policy)).hex()


def unsupported_reason(policy: dict, n: int, sealed_models: list[str]) -> str | None:
    """None if this verifier supports the sealed policy exactly; else a short reason."""
    try:
        mod = scorer_for(policy)
        tee_wasm = policy["audit"].get("scorer_wasm_sha256") if is_tee_round(policy) else None
        if mod is None or policy != make_policy(n, policy["models"], mod, tee_wasm=tee_wasm):
            return "policy differs from the supported fuin-v1 policy (scorer, template, privacy, score or audit)"
        if sorted(policy["models"]) != sorted(sealed_models):
            return "policy models differ from the sealed model list"
        for m, s in policy["models"].items():
            if not isinstance(s, dict) or set(s) - ALLOWED_SETTINGS:
                return f"unsupported generation settings for {m}"
    except (KeyError, TypeError, AttributeError):
        return "malformed policy"
    return None
