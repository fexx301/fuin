"""Offline checks on a real Qwen report captured 2026-11-03 (network checks run in evidence/)."""

import copy
import json
from pathlib import Path

import pytest

from fuin import attestation as A

REP = json.loads((Path(__file__).parent / "fixtures/qwen-report.json").read_text())


def test_report_data_layout():
    signer, nonce = bytes(range(20)).ljust(32, b"\0"), bytes(range(32, 64))
    assert A.parse_report_data(signer + nonce) == (signer, nonce)
    with pytest.raises(ValueError):
        A.parse_report_data(bytes(63))


def test_tcb_policy():
    assert A.tcb_outcome("UpToDate", []) == "clean"
    assert A.tcb_outcome("UpToDate", ["INTEL-SA-00001"]) == "warning"
    assert A.tcb_outcome("OutOfDate", []) == "warning"
    assert A.tcb_outcome("Revoked", []) == "revoked"


def test_rtmr3_replay_detects_edited_event():
    good = A.replay_rtmr3(REP["event_log"])
    log = copy.deepcopy(REP["event_log"])
    ev = next(e for e in log if e["imr"] == 3 and e["event"] == "compose-hash")
    ev["event_payload"] = "00" * 32
    assert A.replay_rtmr3(log) != good  # IMR3 digests are empty in NEAR reports; replay vs the quote decides
    ev["digest"] = "11" * 48
    with pytest.raises(ValueError):  # a stated digest that disagrees is rejected
        A.replay_rtmr3(log)


def test_compose_hash_matches_event_log():
    ev = next(e for e in REP["event_log"] if e["imr"] == 3 and e["event"] == "compose-hash")
    assert A.compose_hash(REP) == ev["event_payload"]


def test_image_digests_are_clean():
    for d in A.image_digests(REP):
        assert "$" not in d and "@sha256:" in d


def test_compose_manager_action_log_hash_recomputes():
    import hashlib
    from fuin import provenance
    cma = REP["compose_manager_attestation"]
    assert hashlib.sha256(provenance.canonical_actions(cma["actions"])).hexdigest() == cma["actions_hash"]
    tampered = copy.deepcopy(cma["actions"])
    tampered[-1]["tag"] = "v9.9.9"
    assert hashlib.sha256(provenance.canonical_actions(tampered)).hexdigest() != cma["actions_hash"]
