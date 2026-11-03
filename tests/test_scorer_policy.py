from fuin import policy as P
from fuin import scorer as S

NUM = {"answer_type": "numeric", "answer": "1000"}
EX = {"answer_type": "exact", "answer": "yoctoNEAR", "accept": ["yocto"]}


def test_numeric():
    assert S.score_text(NUM, "1000") == 1
    assert S.score_text(NUM, " 1,000. ") == 1
    assert S.score_text(NUM, "`1000`") == 1
    assert S.score_text(NUM, "**1000**") == 1
    assert S.score_text(NUM, "\n\n1000") == 1
    assert S.score_text(NUM, "1e3") == 1
    assert S.score_text(NUM, "300") == 0
    assert S.score_text(NUM, "1000 TGas") == 0  # the sealed instruction says number only
    assert S.score_text({**NUM, "answer": "0.5", "tolerance": "0.01"}, "0.509") == 1


def test_exact():
    assert S.score_text(EX, "YoctoNEAR.") == 1
    assert S.score_text(EX, "yocto") == 1
    assert S.score_text(EX, "**yoctoNEAR**") == 1
    assert S.score_text(EX, "nano") == 0


def test_score_response_malformed_is_zero():
    assert S.score_response(NUM, b'{"choices":[{"message":{"content":"1000"}}]}') == 1
    assert S.score_response(NUM, b"not json") == 0
    assert S.score_response(NUM, b'{"choices":[]}') == 0


def test_policy_supported_and_tamper():
    m = {"Qwen/Qwen3.8-27B": {"max_tokens": 64, "temperature": 0}}
    p = P.make_policy(5, m)
    assert p["audit"]["k"] == 5 and P.unsupported_reason(p, 5, list(m)) is None
    assert P.unsupported_reason({**p, "audit": {**p["audit"], "k": 2}}, 5, list(m))
    assert P.unsupported_reason({**p, "scorer": {"name": S.NAME, "sha256": "00" * 32}}, 5, list(m))
    assert P.unsupported_reason(P.make_policy(5, {"x": {"tools": []}}), 5, ["x"])
    assert P.unsupported_reason(p, 5, ["other"])
    assert P.policy_hash(p) != P.policy_hash(P.make_policy(6, m))
    from fuin import scorer_v1
    old = P.make_policy(5, m, scorer_v1)  # the thin-path round sealed v1; still supported
    assert P.unsupported_reason(old, 5, list(m)) is None and P.scorer_for(old) is scorer_v1
    assert scorer_v1.score_text(NUM, "**1000**") == 0 and S.score_text(NUM, "**1000**") == 1
