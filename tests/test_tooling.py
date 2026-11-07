import json

from fuin import owner, tooling
from fuin import policy as P


def write(tmp_path, rows):
    p = tmp_path / "s.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return str(p)


GOOD = {"question": "What is the NEP number of the FT standard? Answer with the number only.", "answer": "141", "answer_type": "numeric"}


def test_good_suite(tmp_path):
    r = tooling.check_suite(write(tmp_path, [GOOD, {**GOOD, "question": "Which method receives ft_transfer_call? Answer with the name only.", "answer": "ft_on_transfer", "answer_type": "exact"}]))
    assert r["n"] == 2 and not r["errors"] and not r["warnings"]


def test_errors(tmp_path):
    r = tooling.check_suite(write(tmp_path, [GOOD, GOOD, {**GOOD, "question": "x? Answer with the number only.", "answer": "four"},
                                             {**GOOD, "question": "y? Answer with the number only.", "request_nonce": "00"}, {"question": "z", "answer": "", "answer_type": "other"}]))
    text = " ".join(r["errors"])
    assert "duplicate question" in text and "not a decimal" in text and "request_nonce" in text and "answer_type" in text and "non-empty" in text


def test_warnings(tmp_path):
    src = {"url": "https://example/doc#L1"}
    r = tooling.check_suite(write(tmp_path, [{**GOOD, "source": src}, {**GOOD, "question": "Other? Answer with the number only.", "answer": "148", "source": src},
                                             {"question": "Is it true? Answer true or false.", "answer": "true", "answer_type": "exact"},
                                             {"question": "What is ft_on_transfer for", "answer": "ft_on_transfer", "answer_type": "exact"}]))
    text = " ".join(r["warnings"])
    assert "same source line" in text and "appears in the question" in text and "what form to answer" in text
    assert not any("line 3" in w for w in r["warnings"])  # an offered choice is not a leak


def test_unreadable_and_empty(tmp_path):
    assert tooling.check_suite(str(tmp_path / "missing.jsonl"))["errors"]
    (tmp_path / "e.jsonl").write_text("\n")
    assert tooling.check_suite(str(tmp_path / "e.jsonl"))["errors"] == ["the suite has no items"]


def test_disclosure_text():
    assert "k=23 (38.3%)" in tooling.disclosure(60) and "k=29 (2.9%)" in tooling.disclosure(1000)


def test_status_unsealed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = tooling.status("nope")
    assert "not sealed" in out[0] and out[-1].startswith("next: uv run fuin check")


def test_status_private_round_points_to_tee_score_then_the_certificates(tmp_path, monkeypatch):
    # the pilot's `fuin status` looked only in examples/ and said `reveal` on a private (TEE-scored) round
    monkeypatch.chdir(tmp_path)
    st = {"owner": "a.testnet", "items": [{}] * 3, "policy": {"audit": {"mode": P.TEE_AUDIT, "k": 0}, "models": ["x/A", "x/B"]},
          "seal": {"height": 1, "tx": "s"}, "close": {"height": 9, "tx": "c"},
          "runs": {m: {"rows": [{}] * 3, "commit": {"run_index": 0, "total_score": 2, "tx": "t"}} for m in ("x/A", "x/B")}}
    st["runs"]["x/A"]["tee_score"] = {"output": {}}
    monkeypatch.setattr(owner, "_path", lambda bid: tmp_path)
    monkeypatch.setattr(owner, "load", lambda bid: st)
    out = tooling.status("p", "pc")
    assert "nothing revealed" in out[0] and "x/B" in out[3] and "not TEE-scored yet" in out[3]
    assert out[-1] == "next: uv run --env-file .env fuin tee-score --id p --model x/B --host gist --out pc"
    st["runs"]["x/B"]["tee_score"] = {"output": {}}
    assert "reveals nothing" in tooling.status("p", "pc")[-1]
    (tmp_path / "pc").mkdir()
    (tmp_path / "pc" / "cert-p-a.json").write_text("{}")
    out = tooling.status("p", "pc")
    assert "certificates in pc/: cert-p-a.json" in out[-3] and "fuin tee-ground --id p" in out[-2]  # grounding offered, optional
    assert out[-1] == "next: env -u NEARAI_API_KEY uv run fuin verify pc/cert-p-a.json"


def test_an_accepted_answer_that_trims_to_nothing_is_an_error(tmp_path):
    ex = {"question": "Name it. Answer with the name only.", "answer": "ft_on_transfer", "answer_type": "exact"}
    for accept in ([""], [" "], ["**"], ["."]):
        r = tooling.check_suite(write(tmp_path, [{**ex, "accept": accept}]))
        assert any("empty once the scorer trims it" in e for e in r["errors"]), accept
    assert not tooling.check_suite(write(tmp_path, [{**ex, "accept": ["ft on transfer"]}]))["errors"]
