"""Fixes from the Nov 8 external review (fuin-review-162a8df): each test names its finding."""
import json
from pathlib import Path

from fuin import core, tooling, verify

CERT = Path(__file__).parent.parent / "examples/cert-near-dev-60-r1-qwen3.8-27b.json"


def _suite(tmp_path, **item):
    base = {"question": "How many? Answer with the number only.", "answer": "4", "answer_type": "numeric",
            "source": {"url": "u", "commit": "e2d2ea173cf462bcf518ecae5650984a221d5183", "path": "a.md", "line": 1, "anchor": "x"}}
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps({**base, **item}) + "\n")
    return tooling.check_suite(str(f))["errors"]


def test_1_non_finite_or_huge_numbers_are_refused_before_sealing(tmp_path):
    for tol in ("Infinity", "NaN", "1e999999999", "-1"):
        assert _suite(tmp_path, tolerance=tol), tol
    assert _suite(tmp_path, answer="Infinity") and _suite(tmp_path, answer="1e101")
    assert not _suite(tmp_path, tolerance="0.5") and not _suite(tmp_path, answer="1e100")


def test_1_a_revealed_item_with_an_infinite_tolerance_is_refused():
    c = json.loads(CERT.read_text())
    next(x for x in c["audit"]["reveals"] if x["item"]["answer_type"] == "numeric")["item"]["tolerance"] = "Infinity"
    res = verify.verify(c)
    assert (res["outcome"], res["code"]) == ("REFUSED", "certificate_invalid") and "tolerance" in res["detail"]


def test_1_the_rule_itself():
    assert [core.sealed_number_ok(s) for s in ("4", "0.01", "1e100", "Infinity", "NaN", "1e101", "x")] == [True] * 3 + [False] * 4
    assert not core.sealed_number_ok("-1", tolerance=True) and core.sealed_number_ok("-1")


def test_2_malformed_nested_evidence_is_refused_not_a_crash():
    import copy
    base = json.loads(CERT.read_text())
    for field, value in (("event_log", ["not-a-dict"]), ("nvidia_payload", "[]"), ("nvidia_payload", "{"), ("signing_address", "0xzz"),
                         ("intel_quote", "zz"), ("event_log", [{"imr": 3}] * 1001)):
        c = copy.deepcopy(base)
        c["run"]["model_report"]["model_attestations"][0][field] = value
        res = verify.verify(c)
        assert (res["outcome"], res["code"]) == ("REFUSED", "certificate_invalid"), (field, res)
        assert field in res["detail"]


def test_2_every_published_certificate_still_passes_the_form_check():
    for f in sorted((CERT.parent).glob("cert-*.json")):
        verify._validate(json.loads(f.read_text()))


def test_3_a_trace_must_pin_image_weights_revision_and_compose_hash():
    from fuin import provenance
    ok = {"service": "s", "image": "nearaidev/vllm@sha256:" + "ab" * 32, "model_path": "Qwen/Qwen3.8-27B", "model_revision": "1bae0e10",
          "file_sha256_checked": True}
    assert provenance.unpinned([ok]) is None
    for k, v in (("image", "nearaidev/vllm:latest"), ("model_path", None), ("model_revision", None), ("file_sha256_checked", False)):
        assert provenance.unpinned([ok, {**ok, "service": "t", k: v}]) == "t", k


def test_5_nvidia_verdict_token_is_verified_not_just_decoded(monkeypatch):
    import base64 as b
    import time
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, utils
    from fuin import attestation as A
    key = ec.generate_private_key(ec.SECP384R1())
    monkeypatch.setattr(A, "_NRAS_KEYS", {"k1": key.public_key()})
    enc = lambda o: b.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
    now, nonce = time.time(), "ab" * 32

    def token(alg="ES384", kid="k1", signer=key, **claims):
        c = {"iss": A.NRAS_ISSUER, "nbf": now - 10, "exp": now + 3600, "eat_nonce": nonce, "x-nvidia-overall-att-result": True, **claims}
        head, body = enc({"alg": alg, "kid": kid}), enc(c)
        r, s = utils.decode_dss_signature(signer.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA384())))
        return f"{head}.{body}." + b.urlsafe_b64encode(r.to_bytes(48, "big") + s.to_bytes(48, "big")).rstrip(b"=").decode()

    assert A.nras_token_ok(token(), nonce)
    assert not A.nras_token_ok(token(), "cd" * 32)                                   # another report's nonce
    assert not A.nras_token_ok(token(**{"x-nvidia-overall-att-result": False}), nonce)
    assert not A.nras_token_ok(token(iss="https://evil.example"), nonce)
    assert not A.nras_token_ok(token(exp=now - 3600), nonce)                         # expired
    assert not A.nras_token_ok(token(signer=ec.generate_private_key(ec.SECP384R1())), nonce)  # not NVIDIA's key
    assert not A.nras_token_ok(token(alg="none"), nonce) and not A.nras_token_ok("x.y", nonce)
    h, c, s = token().split(".")
    forged = enc({**json.loads(b.urlsafe_b64decode(c + "==")), "x-nvidia-overall-att-result": True, "eat_nonce": "cd" * 32})
    assert not A.nras_token_ok(f"{h}.{forged}.{s}", "cd" * 32)                       # claims edited after signing


def test_10_tee_rounds_seal_only_settings_the_tee_can_rebuild():
    from fuin import policy as P
    M = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
    ok = P.make_policy(37, {M: {"max_tokens": 4096, "temperature": 0}}, tee_wasm="11" * 32)
    assert P.unsupported_reason(ok, 37, [M]) is None
    for settings in ({"temperature": 0.5, "max_tokens": 4096}, {"max_tokens": 4096, "temperature": 0.5},
                     {"chat_template_kwargs": {"enable_thinking": False}, "max_tokens": 4096}):
        assert P.unsupported_reason(P.make_policy(37, {M: settings}, tee_wasm="11" * 32), 37, [M]), settings
    assert P.unsupported_reason(P.make_policy(37, {M: {"temperature": 0.5, "max_tokens": 4096}}), 37, [M]) is None  # sampled: unchanged


def test_10_every_published_policy_is_still_supported():
    for f in sorted(CERT.parent.glob("cert-*.json")):
        b = json.loads(f.read_text())["benchmark"]
        from fuin import policy as P
        assert P.unsupported_reason(b["policy"], b["n"], b["models"]) is None, f.name


def test_8_more_items_than_any_verifier_accepts_is_refused_before_sealing(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "MAX_ITEMS", 1)
    f = tmp_path / "s.jsonl"
    item = lambda i: {"question": f"Q{i}? Answer with the number only.", "answer": str(i), "answer_type": "numeric",
                      "source": {"url": "u", "commit": "e2d2ea173cf462bcf518ecae5650984a221d5183", "path": "a.md", "line": i, "anchor": "x"}}
    f.write_text("".join(json.dumps(item(i)) + "\n" for i in (1, 2)))
    assert any("at most 1" in e for e in tooling.check_suite(str(f))["errors"])


def test_13_an_empty_round_is_a_clear_error():
    import pytest
    from fuin import policy as P
    with pytest.raises(ValueError, match="at least one item"):
        P.make_policy(0, {"m": {"max_tokens": 1}})


def test_11_a_round_id_cannot_leave_private():
    import pytest
    from fuin import owner
    for bad in ("../../x", "a/b", "..", "-x", "a*b", "", "x" * 65):
        with pytest.raises(SystemExit):
            owner._path(bad)
    assert owner._path("near-dev-37-r7").name == "state.json"
