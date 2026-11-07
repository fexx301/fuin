"""An installed fuin (uv tool install) carries the verifier's policies; a checkout reads them from policy/."""
from fuin import POLICY, owner, provenance, tee


def test_every_pinned_policy_file_resolves():
    assert POLICY.is_dir()
    for f in (owner.ATTESTATION_POLICY, provenance.SIGSTORE_ROOT, tee.TEE_POLICY):
        assert f.exists() and f.parent == POLICY, f
