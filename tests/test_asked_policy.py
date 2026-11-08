"""Enclave-asked rounds (tee-asked-v1): the sealed policy and the verifier's support check."""
from fuin import policy as P

ASK = ("dbbb286b744cb646535609f875f7dc65c3b6cf718c274481c9ae95dec7f62a77", "ask.fuin.testnet/asker")
M = {"deepseek-ai/DeepSeek-V4.1-Flash-1017": {"max_tokens": 4096, "temperature": 0}}


def test_asked_policy_is_zero_reveal_and_supported():
    pol = P.make_policy(37, M, e2ee=True, asker=ASK)
    assert pol["audit"] == {"mode": P.TEE_ASKED, "k": 0, "asker_wasm_sha256": ASK[0], "asker_project": ASK[1]}
    assert pol["request"]["template"] == P.TEMPLATE_V3 and P.is_tee_round(pol) and P.is_asked_round(pol)
    assert P.unsupported_reason(pol, 37, list(M)) is None
    assert P.make_policy(37, M, asker=ASK)["request"]["template"] == P.TEMPLATE_V2  # seal-bound even without e2ee


def test_a_tee_scored_round_is_not_an_asked_round():
    pol = P.make_policy(37, M, tee_wasm="11" * 32)
    assert P.is_tee_round(pol) and not P.is_asked_round(pol)


def test_an_audit_that_isnt_the_canonical_asked_audit_is_unsupported():
    # any (build, project) pair is a well-formed policy; whether it is pinned is the TEE check's job (check_asked_local)
    for edit in (lambda a: a.update(k=1), lambda a: a.update(extra=True), lambda a: a.pop("asker_project")):
        pol = P.make_policy(37, M, e2ee=True, asker=ASK)
        edit(pol["audit"])
        assert P.unsupported_reason(pol, 37, list(M)) is not None


# ---- the verifier's offline check of a real enclave-asked certificate (round 7) ----
import hashlib
import json
from pathlib import Path

import pytest

from fuin import tee

CERT = Path(__file__).parent.parent / "examples/cert-near-dev-37-r7-deepseek-v4.1-flash-1017.json"


def _cert():
    return json.loads(CERT.read_text())


def test_real_asked_aggregate_passes_offline():
    c = _cert()
    got = tee.check_asked_local(c["run"]["evidence"]["tee_asked"], c)
    assert (got["project"], got["retried"], got["unreadable"]) == ("ask.fuin.testnet/asker", 1, 0)


def _rehashed(mutate):
    c = _cert()
    ev = c["run"]["evidence"]["tee_asked"]
    mutate(ev["output"])
    ev["record"]["output_hash"] = hashlib.sha256(tee._sorted_compact(ev["output"]).encode()).hexdigest()
    return ev, c


@pytest.mark.parametrize("mutate", [lambda o: o.update(retried=-1), lambda o: o.update(retried="0"), lambda o: o.update(v="fuin-tee-score-v1"),
                                    lambda o: o.update(run_root="00" * 32), lambda o: o.update(signer="0x" + "00" * 20)])
def test_inconsistent_aggregates_are_refused(mutate):
    with pytest.raises(tee.TeeRefused):
        tee.check_asked_local(*_rehashed(mutate))


def test_aggregate_from_another_build_or_project_is_refused():
    for k, v in (("wasm_hash", "11" * 32), ("project_id", "someone.testnet/asker")):
        c = _cert()
        c["run"]["evidence"]["tee_asked"]["record"][k] = v
        with pytest.raises(tee.TeeRefused):
            tee.check_asked_local(c["run"]["evidence"]["tee_asked"], c)


def test_real_asked_check_passes_offline_and_a_changed_root_is_refused():
    c = _cert()
    assert tee.check_asked_check_local(c["run"]["evidence"]["tee_asked_check"], c)["pin"] in tee.tee_policy()["asked_checkers"]
    ev = c["run"]["evidence"]["tee_asked_check"]
    ev["output"]["run_root"] = "00" * 32
    ev["record"]["output_hash"] = hashlib.sha256(tee._sorted_compact(ev["output"]).encode()).hexdigest()
    with pytest.raises(tee.TeeRefused):
        tee.check_asked_check_local(ev, c)
