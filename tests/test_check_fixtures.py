"""The fixture checker retries only outage-shaped results, never a real verdict."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("check_fixtures", Path(__file__).resolve().parents[1] / "scripts/check_fixtures.py")
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)


def test_outages_retry_and_verdicts_do_not():
    nt = {"expected": "CANT_CERTIFY model_not_tee"}
    assert cf.retryable("CANT_CERTIFY policy_unsupported", nt)  # the model catalog didn't answer
    assert cf.retryable("CANT_CERTIFY evidence_unavailable", nt)
    assert not cf.retryable("CANT_CERTIFY model_not_tee", nt)
    assert not cf.retryable("VERIFIED", nt)
    assert not cf.retryable("CANT_CERTIFY policy_unsupported", {"expected": "REFUSED total_score_mismatch"})
    assert not cf.retryable("CANT_CERTIFY evidence_unavailable", {"expected": "CANT_CERTIFY evidence_unavailable", "env": {"X": "1"}})
    assert not cf.retryable("CANT_CERTIFY evidence_unavailable", {"expected": "VERIFIED", "env": {"X": "1"}})
