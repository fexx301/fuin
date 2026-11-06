"""OS measurements must be approved, Intel outages must not read as forgeries, and the deployment trace is required.

Offline: a genuine NEAR report (tests/fixtures/qwen-report.json) with a TD report rebuilt from its own fields, so every
other check passes and each test changes exactly one thing. These mirror an external blind review's probes (2026-11-04).
"""
import copy
import json
from pathlib import Path

import pytest

from fuin import attestation as A
from fuin import owner, provenance

REPORT = json.loads((Path(__file__).parent / "fixtures/qwen-report.json").read_text())
POLICY = owner.attestation_policy()
NONCE = REPORT["request_nonce"]


def genuine_td(report=REPORT):
    """The TD report a genuine quote for this report carries, rebuilt from the report and the approved OS measurements."""
    entry = POLICY["models"][report["model_name"]]["compose_hashes"][A.compose_hash(report)]
    signer = bytes.fromhex(report["signing_address"].removeprefix("0x")).ljust(32, b"\0")
    return {**entry["os_measurements"][0],
            "report_data": (signer + bytes.fromhex(NONCE)).hex(),
            "td_attributes": "0000001000000000",
            "mr_config_id": (b"\x01" + bytes.fromhex(A.compose_hash(report)) + bytes(15)).hex(),
            "rt_mr3": A.replay_rtmr3(report["event_log"]).hex()}


def check(monkeypatch, td=None, report=REPORT):
    monkeypatch.setattr(A, "verify_quote", lambda q: ("UpToDate", [], td or genuine_td(report)))
    return A.check_report(report, NONCE, POLICY, use_nras=False)


def test_genuine_report_with_approved_os_is_accepted(monkeypatch):
    assert check(monkeypatch)["outcome"] == ("accepted",)


@pytest.mark.parametrize("field", ["mr_td", "rt_mr0", "rt_mr1", "rt_mr2"])
def test_unapproved_os_measurement_is_not_certified(monkeypatch, field):
    td = genuine_td()
    td[field] = "00" * 48
    res = check(monkeypatch, td)
    assert res["outcome"] == ("cant_certify", "measurement_unapproved") and res["os_approved"] is False


def test_os_image_hash_must_match_the_policy(monkeypatch):
    rep = copy.deepcopy(REPORT)
    rep["info"]["os_image_hash"] = "00" * 32
    assert check(monkeypatch, report=rep)["outcome"] == ("cant_certify", "measurement_unapproved")


def test_intel_outage_is_an_outage_not_a_forgery(monkeypatch):
    def unreachable(raw):
        raise ValueError("Failed to get collateral: error sending request for url (https://api.trustedservices.intel.com/...)")
    monkeypatch.setattr(A, "_collateral", unreachable)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        A.verify_quote(REPORT["intel_quote"])
    res = A.check_report(REPORT, NONCE, POLICY, use_nras=False)
    assert res["outcome"] == ("cant_certify", "evidence_unavailable")


def test_a_dropped_request_to_intel_is_retried_once(monkeypatch):
    # the pilot's first verify lost one request to Intel's PCS and printed CAN'T CERTIFY; a rerun minutes later passed
    calls = []

    def flaky(raw):
        calls.append(1)
        raise ValueError("Failed to get collateral: error sending request for url (https://api.trustedservices.intel.com/...)"
                         if len(calls) == 1 else "Failed to get collateral: Failed to extract certificates from PEM chain")
    monkeypatch.setattr(A, "_collateral", flaky)
    monkeypatch.setattr(A, "_pcs_reachable", lambda: True)
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    with pytest.raises(ValueError, match="quote rejected"):  # the second answer decides, so a real fault is still refused
        A.verify_quote(REPORT["intel_quote"])
    assert len(calls) == 2


def test_broken_certificate_chain_with_intel_reachable_is_invalid(monkeypatch):
    def broken(raw):
        raise ValueError("Failed to get collateral: Failed to extract certificates from PEM chain")
    monkeypatch.setattr(A, "_collateral", broken)
    monkeypatch.setattr(A, "_pcs_reachable", lambda: True)
    with pytest.raises(ValueError):
        A.verify_quote(REPORT["intel_quote"])
    assert A.check_report(REPORT, NONCE, POLICY, use_nras=False)["outcome"] == ("refused", "attestation_invalid")


def test_missing_deployment_attestation_is_untraced():
    rep = {k: v for k, v in REPORT.items() if k != "compose_manager_attestation"}
    with pytest.raises(provenance.TraceUnavailable):
        provenance.trace(rep, NONCE, genuine_td())


@pytest.mark.parametrize("mutate", [
    lambda cma: cma.__setitem__("quote", ""),
    lambda cma: cma.__setitem__("quote", None),
    lambda cma: cma.pop("actions"),
    lambda cma: cma.__setitem__("nonce", 7),
])
def test_malformed_deployment_attestation_is_invalid(mutate):
    rep = copy.deepcopy(REPORT)
    mutate(rep["compose_manager_attestation"])
    with pytest.raises(provenance.TraceInvalid):
        provenance.trace(rep, NONCE, genuine_td())


def test_deployment_quote_from_a_machine_with_another_os_is_invalid(monkeypatch):
    cma = REPORT["compose_manager_attestation"]
    other = {**genuine_td(), "rt_mr1": "11" * 48, "report_data": cma["report_data"]}
    monkeypatch.setattr(A, "verify_quote", lambda q: ("UpToDate", [], other))
    with pytest.raises(provenance.TraceInvalid, match="different CVM"):
        provenance.trace(REPORT, NONCE, genuine_td())
