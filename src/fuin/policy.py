"""Sealed evaluation policy (spec: Sealed policy) and the verifier's supported set."""

import hashlib
from pathlib import Path

from fuin import core, scorer, scorer_v1

PROTOCOL = "fuin-v1"
TEMPLATE = "fuin-request-v1"  # inference.build_request
PRIVACY = "nonce-in-user-field-v1"
SAMPLER = "fuin-audit-v1"
TEMPLATE_V2 = "fuin-request-v2"  # nonce bound to the seal block (core.seal_bound_nonce)
TEMPLATE_V3 = "fuin-request-v3"  # v2, with the question and answer end-to-end encrypted to the model's TEE (fuin/e2ee.py)
TEE_AUDIT = "tee-scored-v1"  # every item re-scored inside a TEE by a sealed scorer build; nothing revealed
TEE_ASKED = "tee-asked-v1"  # every item asked once by a sealed asker build in a locked OutLayer project; nothing revealed
ALLOWED_SETTINGS = {"max_tokens", "temperature", "chat_template_kwargs"}


def scorer_sha256(mod=scorer) -> str:
    return hashlib.sha256(Path(mod.__file__).read_bytes()).hexdigest()


SCORERS = {(m.NAME, scorer_sha256(m)): m for m in (scorer_v1, scorer)}  # supported, by name and file hash


def scorer_for(policy: dict):
    """The supported scorer module a sealed policy names, or None."""
    sc = policy.get("scorer", {})
    return SCORERS.get((sc.get("name"), sc.get("sha256")))


def make_policy(n: int, models: dict[str, dict], mod=scorer, *, tee_wasm: str | None = None, e2ee: bool = False,
                asker: tuple[str, str] | None = None) -> dict:
    """The sealed policy. With `tee_wasm`, a zero-reveal round: requests use the seal-bound nonce, and every item is scored
    inside a TEE by that exact scorer build (its sha256 is sealed), with no audit sample. With `e2ee`, request template
    v3: the seal-bound nonce, and each question and answer end-to-end encrypted between the owner and the model's TEE."""
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
    if asker:  # (asker build sha256, OutLayer project id): the enclave makes every model call, once per item
        pol["request"] = {"template": TEMPLATE_V2, "privacy_profile": PRIVACY}
        pol["audit"] = {"mode": TEE_ASKED, "k": 0, "asker_wasm_sha256": asker[0], "asker_project": asker[1]}
    if e2ee:
        pol["request"] = {"template": TEMPLATE_V3, "privacy_profile": PRIVACY}
    return pol


def is_e2ee(policy: dict) -> bool:
    return policy.get("request", {}).get("template") == TEMPLATE_V3


def is_seal_bound(policy: dict) -> bool:
    """Templates v2 and v3 bind each request nonce to the seal block's hash."""
    return policy.get("request", {}).get("template") in (TEMPLATE_V2, TEMPLATE_V3)


def is_tee_round(policy: dict) -> bool:
    """A zero-reveal round: every item checked inside a TEE (re-scored, or asked and scored there), none revealed."""
    return isinstance(policy.get("audit"), dict) and policy["audit"].get("mode") in (TEE_AUDIT, TEE_ASKED)


def is_asked_round(policy: dict) -> bool:
    return is_tee_round(policy) and policy["audit"]["mode"] == TEE_ASKED


def policy_hash(policy: dict) -> str:
    return core.sha256(core.jcs(policy)).hex()


def unsupported_reason(policy: dict, n: int, sealed_models: list[str]) -> str | None:
    """None if this verifier supports the sealed policy exactly; else a short reason."""
    try:
        mod = scorer_for(policy)
        tee_wasm = policy["audit"].get("scorer_wasm_sha256") if is_tee_round(policy) and not is_asked_round(policy) else None
        asker = (policy["audit"]["asker_wasm_sha256"], policy["audit"]["asker_project"]) if is_asked_round(policy) else None
        if mod is None or policy != make_policy(n, policy["models"], mod, tee_wasm=tee_wasm, e2ee=is_e2ee(policy), asker=asker):
            return "policy differs from the supported fuin-v1 policy (scorer, template, privacy, score or audit)"
        if sorted(policy["models"]) != sorted(sealed_models):
            return "policy models differ from the sealed model list"
        for m, s in policy["models"].items():
            if not isinstance(s, dict) or set(s) - ALLOWED_SETTINGS:
                return f"unsupported generation settings for {m}"
            # the TEE rebuilds each request from the canonical policy: integer or boolean settings, in sorted order (review 10)
            if is_tee_round(policy) and (list(s) != sorted(s) or not all(type(v) in (int, bool) for v in s.values())):
                return f"a TEE-checked round needs integer or boolean settings in sorted order ({m})"
    except (KeyError, TypeError, AttributeError):
        return "malformed policy"
    return None
