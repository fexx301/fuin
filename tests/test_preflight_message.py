"""A failed preflight says why for each candidate (a pilot lost an hour to 'got 0 accepted attestation candidates' when
WSL couldn't resolve Intel's PCS host)."""
import pytest

from fuin import attestation, inference, owner


def test_preflight_failure_names_each_candidates_outcome_and_error(monkeypatch):
    monkeypatch.setattr(owner, "load", lambda bid: {"policy": {"models": {"m": {}}}, "runs": {}})
    monkeypatch.setattr(owner, "attestation_policy", lambda: {"version": "x"})
    monkeypatch.setattr(inference, "model_report", lambda m, n: {"model_attestations": [{"signing_address": "0xabc"}]})
    monkeypatch.setattr(attestation, "check_report", lambda c, n, p: {"error": "PCS: Name or service not known",
                                                                       "outcome": ("cant_certify", "evidence_unavailable")})
    with pytest.raises(SystemExit, match=r"got 0 \(0xabc: cant_certify/evidence_unavailable \(PCS: Name or service not known\)\)\. A service"):
        owner.run("b", "m")
