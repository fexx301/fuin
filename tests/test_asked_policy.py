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
