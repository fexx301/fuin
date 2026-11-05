"""The README lists every limit the verifier prints, word for word."""
from pathlib import Path

from fuin import tee, verify


def test_every_printed_limit_is_in_the_readme_word_for_word():
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    for limit in verify.LIMITS + [verify.SEAL_BOUND_LIMIT, verify.E2EE_LIMIT, verify.E2EE_KEY_LIMIT, tee.TEE_LIMIT]:
        assert "- " + limit in readme, limit[:60]
