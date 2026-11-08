"""Fixes from the Nov 8 external review (fuin-review-162a8df): each test names its finding."""
import json
from pathlib import Path

from fuin import core, tooling, verify

CERT = Path(__file__).parent.parent / "examples/cert-near-dev-60-r1-qwen3.8-27b.json"


def _suite(tmp_path, **item):
    base = {"question": "How many? Answer with the number only.", "answer": "4", "answer_type": "numeric",
            "source": {"url": "u", "commit": "e2d2ea173cf462bcf518ecae5650984a221d5183", "path": "a.md", "line": 1, "anchor": "x"}}
    f = tmp_path / "s.jsonl"
    f.write_text(json.dumps({**base, **item}) + "\n")
    return tooling.check_suite(str(f))["errors"]


def test_1_non_finite_or_huge_numbers_are_refused_before_sealing(tmp_path):
    for tol in ("Infinity", "NaN", "1e999999999", "-1"):
        assert _suite(tmp_path, tolerance=tol), tol
    assert _suite(tmp_path, answer="Infinity") and _suite(tmp_path, answer="1e101")
    assert not _suite(tmp_path, tolerance="0.5") and not _suite(tmp_path, answer="1e100")


def test_1_a_revealed_item_with_an_infinite_tolerance_is_refused():
    c = json.loads(CERT.read_text())
    next(x for x in c["audit"]["reveals"] if x["item"]["answer_type"] == "numeric")["item"]["tolerance"] = "Infinity"
    res = verify.verify(c)
    assert (res["outcome"], res["code"]) == ("REFUSED", "certificate_invalid") and "tolerance" in res["detail"]


def test_1_the_rule_itself():
    assert [core.sealed_number_ok(s) for s in ("4", "0.01", "1e100", "Infinity", "NaN", "1e101", "x")] == [True] * 3 + [False] * 4
    assert not core.sealed_number_ok("-1", tolerance=True) and core.sealed_number_ok("-1")
