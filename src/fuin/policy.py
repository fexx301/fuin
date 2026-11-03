"""Sealed evaluation policy (spec: Sealed policy) and the verifier's supported set."""

import hashlib
from pathlib import Path

from fuin import core, scorer

PROTOCOL = "fuin-v1"
TEMPLATE = "fuin-request-v1"  # inference.build_request
PRIVACY = "nonce-in-user-field-v1"
SAMPLER = "fuin-audit-v1"
ALLOWED_SETTINGS = {"max_tokens", "temperature", "chat_template_kwargs"}


def scorer_sha256() -> str:
    return hashlib.sha256(Path(scorer.__file__).read_bytes()).hexdigest()


def make_policy(n: int, models: dict[str, dict]) -> dict:
    d, k = core.audit_size(n)
    return {
        "protocol": PROTOCOL,
        "models": models,
        "request": {"template": TEMPLATE, "privacy_profile": PRIVACY},
        "scorer": {"name": scorer.NAME, "sha256": scorer_sha256()},
        "score": {"values": [0, 1], "aggregate": "sum", "denominator": n},
        "audit": {"D": d, "target": {"numerator": 95, "denominator": 100}, "k": k, "sampler": SAMPLER},
    }


def policy_hash(policy: dict) -> str:
    return core.sha256(core.jcs(policy)).hex()


def unsupported_reason(policy: dict, n: int, sealed_models: list[str]) -> str | None:
    """None if this verifier supports the sealed policy exactly; else a short reason."""
    try:
        if policy != make_policy(n, policy["models"]):
            return "policy differs from the supported fuin-v1 policy (scorer, template, privacy, score or audit)"
        if sorted(policy["models"]) != sorted(sealed_models):
            return "policy models differ from the sealed model list"
        for m, s in policy["models"].items():
            if not isinstance(s, dict) or set(s) - ALLOWED_SETTINGS:
                return f"unsupported generation settings for {m}"
    except (KeyError, TypeError, AttributeError):
        return "malformed policy"
    return None
