"""Build provenance policy (provenance.build_provenance): who built the image and which image the statement is about.
sigstore's own signature, certificate-chain and transparency-log checks are its library's; review.sh runs them live."""
import json

import pytest

from fuin import provenance as P

DIGEST = "ab" * 32
IMG = f"docker.io/nearaidev/vllm@sha256:{DIGEST}"


class FakeCert:
    def __init__(self, uri):
        from cryptography import x509
        self.extensions = type("E", (), {"get_extension_for_class": lambda _, cls: type("X", (), {
            "value": x509.SubjectAlternativeName([x509.UniformResourceIdentifier(uri)])})()})()


def stub(monkeypatch, builder, subject_digest, predicate=P.SLSA_V1):
    statement = {"predicateType": predicate, "subject": [{"name": "docker.io/nearaidev/vllm", "digest": {"sha256": subject_digest}}],
                 "predicate": {"buildDefinition": {
                     "externalParameters": {"workflow": {"repository": "https://github.com/nearai/cvm-compose-files",
                                                         "path": ".github/workflows/publish.yaml", "ref": "refs/heads/main"}},
                     "resolvedDependencies": [{"digest": {"gitCommit": "c0ffee" * 6 + "c0ff"}}]}}}
    bundle = type("B", (), {"signing_certificate": FakeCert(builder)})()
    monkeypatch.setattr(P, "_slsa_bundle", lambda repo, digest: b"{}")
    import sigstore.models, sigstore.verify
    monkeypatch.setattr(sigstore.models.Bundle, "from_json", staticmethod(lambda raw: bundle))
    monkeypatch.setattr(P, "_VERIFIER", type("V", (), {"verify_dsse": lambda self, b, pol: ("application/vnd.in-toto+json", json.dumps(statement).encode())})())


def test_a_near_built_image_reports_its_workflow_and_commit(monkeypatch):
    stub(monkeypatch, "https://github.com/nearai/cvm-compose-files/.github/workflows/publish.yaml@refs/heads/main", DIGEST)
    bp = P.build_provenance(IMG)
    assert bp["workflow"] == ".github/workflows/publish.yaml" and bp["commit"].startswith("c0ffee")


def test_provenance_about_another_image_is_invalid(monkeypatch):
    stub(monkeypatch, "https://github.com/nearai/cvm-compose-files/.github/workflows/publish.yaml@refs/heads/main", "cd" * 32)
    with pytest.raises(P.ProvenanceInvalid, match="another image"):
        P.build_provenance(IMG)


def test_a_build_outside_near_ais_organisation_is_invalid(monkeypatch):
    stub(monkeypatch, "https://github.com/someone-else/fork/.github/workflows/publish.yaml@refs/heads/main", DIGEST)
    with pytest.raises(P.ProvenanceInvalid, match="outside NEAR AI"):
        P.build_provenance(IMG)


def test_an_image_without_a_digest_or_without_provenance_has_none(monkeypatch):
    assert P.build_provenance("nearaidev/vllm:latest") is None
    monkeypatch.setattr(P, "_slsa_bundle", lambda repo, digest: None)
    assert P.build_provenance(IMG) is None
