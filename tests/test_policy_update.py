"""fuin policy-update drafts the next attestation policy and approves nothing by itself (network calls stubbed)."""
import json

from fuin import attestation as A, inference, owner, policyupdate, provenance

TD = {"mr_td": "aa" * 48, "rt_mr0": "bb" * 48, "rt_mr1": "cc" * 48, "rt_mr2": "dd" * 48}


def stub(monkeypatch, tmp_path, outcome):
    pol = {"version": "attestation-v6", "note": "base.", "models": {"m": {"compose_hashes": {}}}}
    (tmp_path / "attestation-v6.json").write_text(json.dumps(pol))
    monkeypatch.setattr(owner, "ATTESTATION_POLICY", tmp_path / "attestation-v6.json")
    cand = {"signing_address": "0xABC", "intel_quote": "00", "nvidia_payload": "{}", "info": {"os_image_hash": "ee" * 32}}
    monkeypatch.setattr(inference, "model_report", lambda m, n: {"model_attestations": [cand]})
    monkeypatch.setattr(A, "check_report", lambda c, n, p, use_nras=True: {"outcome": outcome, "compose_hash": "c0" * 32})
    monkeypatch.setattr(A, "verify_quote", lambda q: ("UpToDate", [], TD))
    monkeypatch.setattr(A, "nras_verdict", lambda p: True)
    monkeypatch.setattr(A, "compose_hash", lambda c: "c0" * 32)
    monkeypatch.setattr(A, "image_digests", lambda c: ["x/y@sha256:" + "11" * 32])
    monkeypatch.setattr(provenance, "trace", lambda c, n, td: {"services": [{"service": "s", "tag": "v1", "file": "f.yaml", "image": "img", "model_path": "w"}]})


def test_an_unapproved_but_genuine_configuration_is_drafted_as_the_next_version(monkeypatch, tmp_path):
    stub(monkeypatch, tmp_path, ("cant_certify", "measurement_unapproved"))
    draft, notes = policyupdate.propose(["m"])
    e = draft["models"]["m"]["compose_hashes"]["c0" * 32]
    assert draft["version"] == "attestation-v7" and e["os_measurements"] == [TD] and "f.yaml" in e["evidence"]
    path = policyupdate.write(draft)
    assert path.name == "attestation-v7.json" and owner.ATTESTATION_POLICY.name == "attestation-v6.json"  # nothing switched


def test_bad_or_already_approved_evidence_is_never_drafted(monkeypatch, tmp_path):
    for outcome in [("refused", "attestation_invalid"), ("cant_certify", "evidence_unavailable"), ("accepted",)]:
        stub(monkeypatch, tmp_path, outcome)
        draft, notes = policyupdate.propose(["m"])
        assert draft is None and len(notes) == 1
