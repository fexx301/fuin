"""The verifier must return a structured verdict for hostile input, and outages must not hide local tampering.

Offline: every network dependency is replaced by one that fails, as if Intel PCS, NRAS, NEAR RPC, GitHub and the
NEAR AI catalog were all down. Uses a committed real certificate.
"""
import copy
import json
from pathlib import Path

import pytest
import requests

from fuin import attestation, near, provenance, verify

CERT = json.loads((Path(__file__).parents[1] / "examples/cert-near-dev-60-r1-qwen3.8-27b.json").read_text())


@pytest.fixture(autouse=True)
def all_services_down(monkeypatch):
    def down(*a, **k):
        raise near.RpcError("service unavailable (test)")

    def catalog_down(*a, **k):
        raise requests.ConnectionError("catalog unavailable (test)")

    def report_down(*a, **k):
        return {"model": "", "signing_address": "", "outcome": ("cant_certify", "evidence_unavailable")}

    for name in ("rpc", "view", "code_hash", "block", "final_height", "select_seed_block", "tx_receipt", "access_key_count"):
        monkeypatch.setattr(near, name, down)
    monkeypatch.setattr(attestation, "is_tee_model", catalog_down)
    monkeypatch.setattr(attestation, "check_report", report_down)
    monkeypatch.setattr(provenance, "trace", down)


def run(mutate):
    c = copy.deepcopy(CERT)
    mutate(c)
    return verify.verify(c)


def test_untampered_cert_with_services_down_is_not_verified():
    res = run(lambda c: None)
    assert (res["outcome"], res["code"]) == ("CANT_CERTIFY", "evidence_unavailable")
    assert [name for name, _, _ in res["checks"]] == ["rows", "commitments", "policy", "signatures", "reveals"]


@pytest.mark.parametrize("name,mutate,code", [
    ("signature text", lambda c: c["run"]["items"][0]["signature"].__setitem__("text", c["run"]["items"][0]["signature"]["text"] + "x"), "signature_text_mismatch"),
    ("inflated total", lambda c: c["run"].__setitem__("total_score", c["run"]["total_score"] + 1), "total_score_mismatch"),
    ("changed leaf", lambda c: c["run"]["items"][3].__setitem__("benchmark_leaf", "00" * 32), "merkle_root_mismatch"),
    ("edited answer", lambda c: c["audit"]["reveals"][0].__setitem__("response_b64", "e30="), "signature_text_mismatch"),
    ("policy edit", lambda c: c["benchmark"]["policy"]["audit"].__setitem__("k", 5), "policy_mismatch"),
    ("dropped reveal", lambda c: c["audit"]["reveals"].pop(), "reveal_mismatch"),
])
def test_local_tampering_is_refused_during_an_outage(name, mutate, code):
    res = run(mutate)
    assert (res["outcome"], res["code"]) == ("REFUSED", code), name


@pytest.mark.parametrize("name,mutate", [
    ("one-byte salt", lambda c: c["audit"]["reveals"][0].__setitem__("salt", "ab")),
    ("non-hex leaf", lambda c: c["run"]["items"][0].__setitem__("benchmark_leaf", "zz" * 32)),
    ("missing run", lambda c: c.pop("run")),
    ("extra top-level field", lambda c: c.__setitem__("note", 1)),
    ("items not a list", lambda c: c["run"].__setitem__("items", {"0": 1})),
    ("string score", lambda c: c["run"]["items"][0].__setitem__("score", "1")),
    ("bad base64", lambda c: c["audit"]["reveals"][0].__setitem__("request_b64", "@@@")),
    ("proof element short", lambda c: c["audit"]["reveals"][0]["proof_benchmark"].__setitem__(0, "ab")),
    ("nonce wrong type", lambda c: c["audit"]["reveals"][0]["item"].__setitem__("request_nonce", 7)),
    ("negative height", lambda c: c["run"].__setitem__("commit_height", -1)),
    ("signature not a dict", lambda c: c["run"]["items"][0].__setitem__("signature", "0x00")),
    ("reveal index out of range", lambda c: c["audit"]["reveals"][0].__setitem__("i", 10_000)),
    ("evidence not an object", lambda c: c["run"].__setitem__("evidence", "x")),
    ("attempt log not a list", lambda c: c["run"].__setitem__("evidence", {"attempt_log": "x"})),
])
def test_malformed_input_gets_a_structured_refusal(name, mutate):
    res = run(mutate)
    assert res["outcome"] == "REFUSED", (name, res)
    assert res["code"] in ("certificate_invalid", "reveal_mismatch"), (name, res)


def test_non_dict_input():
    for junk in (None, [], "cert", 42):
        res = verify.verify(junk)
        assert (res["outcome"], res["code"]) == ("REFUSED", "certificate_invalid")


def test_unsupported_model_is_not_certified_even_offline():
    res = run(lambda c: c["run"].__setitem__("model_id", "openai/gpt-5.5"))
    assert res["outcome"] == "CANT_CERTIFY" and res["code"] in ("model_not_tee", "policy_unsupported")


def test_an_attestation_entry_missing_a_field_is_refused_before_any_network_call():
    """Found by a blind review: a missing model_name used to crash the verifier (CAN'T CERTIFY verifier_error)."""
    import json as _json
    from pathlib import Path as _Path
    from unittest.mock import patch
    from fuin import verify as _verify
    cert = _json.loads((_Path(__file__).resolve().parents[1] / "examples/cert-near-dev-60-r1-qwen3.8-27b.json").read_text())
    for field in ("model_name", "intel_quote", "event_log", "info"):
        c = _json.loads(_json.dumps(cert))
        del c["run"]["model_report"]["model_attestations"][0][field]
        with patch("requests.get", side_effect=AssertionError("network")), patch("requests.post", side_effect=AssertionError("network")):
            r = _verify.verify(c)
        assert (r["outcome"], r["code"]) == ("REFUSED", "certificate_invalid"), (field, r)
