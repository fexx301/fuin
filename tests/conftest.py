import pytest


@pytest.fixture(autouse=True)
def _no_rpc_cache(monkeypatch):
    """scripts/review.sh exports FUIN_CACHE_DIR; a cached RPC answer would hide an outage a test simulates."""
    monkeypatch.delenv("FUIN_CACHE_DIR", raising=False)
