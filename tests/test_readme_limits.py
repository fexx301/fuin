"""docs/LIMITS.md lists every limit the verifier prints, word for word."""
from pathlib import Path

from fuin import tee, verify


def test_every_printed_limit_is_in_the_readme_word_for_word():
    readme = (Path(__file__).resolve().parents[1] / "docs" / "LIMITS.md").read_text()
    for limit in verify.LIMITS + [verify.ZERO_REVEAL_LIMIT, verify.SEAL_BOUND_LIMIT, verify.E2EE_LIMIT, verify.E2EE_KEY_LIMIT, verify.E2EE_KEY_LIMIT_COUNTED, tee.TEE_LIMIT, verify.ASKED_LIMIT, verify.GROUND_LIMIT, verify.ZERO_REVEAL_GROUNDED_LIMIT]:
        assert "- " + limit in readme, limit[:60]
