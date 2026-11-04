import json

from fuin import tooling


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
