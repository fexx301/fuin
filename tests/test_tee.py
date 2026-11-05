"""TEE score checks against a real OutLayer record: the synthetic 3-item round scored inside OutLayer's TDX enclave
(tests/fixtures/tee-synthetic-evidence.json). Offline: the local half. The network half runs in scripts/review.sh."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from fuin import tee

FX = json.loads((Path(__file__).parent / "fixtures/tee-synthetic-evidence.json").read_text())
EXP = FX["expected"]


def cert():
    return {"registry": {"owner": "fuin.testnet"},
            "benchmark": {"n": EXP["n"], "root": EXP["benchmark_root"], "policy_hash": EXP["policy_hash"], "seal_block_hash": "11" * 22,
                          "policy": {"request": {"template": "fuin-request-v1"}, "audit": {"k": 3}}},
            "run": {"model_id": EXP["model"], "total_score": EXP["total"], "run_root": EXP["run_root"],
                    "items": [{"signature": {"signing_address": EXP["signer"]}}] * EXP["n"]}}


def ev():
    return copy.deepcopy(FX["evidence"])


def rehash(e):  # an attacker who also fixes the record's output hash
    e["record"]["output_hash"] = hashlib.sha256(tee._sorted_compact(e["output"]).encode()).hexdigest()
    return e


def test_genuine_record_passes_the_local_checks():
    assert tee.check_local(ev(), cert())["task"] == FX["evidence"]["record"]["task_id"]


def test_edited_output_breaks_the_attested_output_hash():
    e = ev(); e["output"]["total"] += 1
    with pytest.raises(tee.TeeRefused, match="tee_score_invalid"):
        tee.check_local(e, cert())


def test_output_that_contradicts_the_certificate_is_refused():
    c = cert(); c["run"]["total_score"] += 1
    with pytest.raises(tee.TeeRefused, match="tee_score_mismatch"):
        tee.check_local(ev(), c)


def test_rehashed_forgery_still_contradicts_the_certificate():
    e = ev(); e["output"]["run_root"] = "00" * 32
    with pytest.raises(tee.TeeRefused, match="tee_score_mismatch"):
        tee.check_local(rehash(e), cert())


def test_another_scorer_build_is_not_certified():
    e = ev(); e["record"]["wasm_hash"] = "11" * 32
    with pytest.raises(tee.TeeUnapproved):
        tee.check_local(e, cert())


def test_tampered_evidence_naming_an_unpinned_build_is_still_refused():
    e = ev(); e["record"]["wasm_hash"] = "11" * 32; e["output"]["total"] += 1
    with pytest.raises(tee.TeeRefused, match="tee_score_invalid"):
        tee.check_local(e, cert())


def test_run_by_another_account_is_refused():
    e = ev(); e["record"]["caller_account_id"] = "someone.testnet"
    with pytest.raises(tee.TeeRefused, match="tee_score_invalid"):
        tee.check_local(e, cert())


def test_input_not_the_one_attested_is_refused():
    e = ev(); e["input_data"] = e["input_data"].replace('"score"', '"score" ')
    with pytest.raises(tee.TeeRefused, match="tee_score_invalid"):
        tee.check_local(e, cert())


def test_task_hash_is_outlayers_v1_preimage():
    rec = FX["evidence"]["record"]
    assert len(tee.task_hash_v1(rec)) == 64 and rec["timestamp"] >= tee.V1_CUTOFF
