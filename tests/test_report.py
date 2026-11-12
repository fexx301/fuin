"""`fuin report`: scores with their intervals, compared only where comparable, with no private question shown."""
import copy
import glob
import hashlib
import json
from pathlib import Path

from fuin import cli, report

ROOT = Path(__file__).resolve().parents[1]
CERTS = sorted(glob.glob(str(ROOT / "examples" / "cert-*.json")))
NOW = {"how": "checked", "at": "2026-11-11 12:00 UTC"}
OK = {"outcome": "VERIFIED", "limits": ["a limit <b>printed</b> verbatim"], "warnings": []}


def _recorded(tmp_path) -> Path:
    """Every recorded `fuin verify --json` line in evidence/, in one file (the published results, so no network)."""
    out = tmp_path / "verify.jsonl"
    out.write_text("".join(Path(f).read_text() for f in sorted(glob.glob(str(ROOT / "evidence" / "*" / "verify.jsonl")))))
    return out


def _entry(path: str, res=OK, **change):
    raw = Path(path).read_bytes()
    cert = json.loads(raw)
    for k, v in change.items():
        cert["run" if k in ("model_id",) else "benchmark"][k] = v
    return report.entry(Path(path).name, raw, cert, res, NOW)


def test_the_interval_is_the_results_charts_formula():
    # the numbers site/app.js's wilson() gives for the same inputs
    for (k, n), want in {(19, 37): (0.3589463722598092, 0.6655384667278896), (0, 3): (0, 0.5615060804490177),
                         (3, 3): (0.43849391955098227, 1), (32, 60): (0.40893208671135106, 0.65372298459012)}.items():
        got = report.wilson(k, n)
        assert abs(got[0] - want[0]) < 1e-12 and abs(got[1] - want[1]) < 1e-12


def test_published_certificates_group_by_sealed_round(tmp_path):
    assert cli.main(["report", *CERTS, "--out", str(tmp_path / "r"), "--recorded", str(_recorded(tmp_path))]) == 0
    rep = json.loads((tmp_path / "r" / "report.json").read_text())
    assert (rep["certificates"], rep["verified"], len(rep["groups"]), rep["not_verified"]) == (len(CERTS), len(CERTS), 8, [])
    r7 = next(g for g in rep["groups"] if g["benchmark_id"] == "near-dev-37-r7")["members"][0]
    assert (r7["kind"], r7["retried_in_tee"], r7["unreadable_in_tee"]) == ("asked once", 1, 0)
    r2 = next(g for g in rep["groups"] if g["benchmark_id"] == "near-dev-60-r2")
    assert [e["total"] for e in r2["members"]] == sorted((e["total"] for e in r2["members"]), reverse=True)
    assert r2["members"][0]["retried_in_tee"] is None and "don't overlap" in r2["reading"][0]
    assert len(rep["not_comparable"]) == 28 and all(x["because"] for x in rep["not_comparable"])
    # the folder is shareable as it is: every certificate copied, byte for byte, under the name the report links
    for g in rep["groups"]:
        for e in g["members"]:
            assert hashlib.sha256((tmp_path / "r" / e["file"]).read_bytes()).hexdigest() == e["sha256"]


def test_no_revealed_question_or_answer_reaches_the_report(tmp_path):
    cli.main(["report", *CERTS, "--out", str(tmp_path / "r"), "--recorded", str(_recorded(tmp_path))])
    page, data = (tmp_path / "r" / "report.html").read_text(), (tmp_path / "r" / "report.json").read_text()
    shown = 0
    for c in CERTS:
        for x in json.loads(Path(c).read_text())["audit"].get("reveals") or []:
            shown += 1
            assert x["item"]["question"] not in page and x["item"]["question"] not in data
    assert shown > 50 and "not attested" in page  # sampled rounds were in the set; a missing count is never printed as 0


def test_only_verified_results_are_compared():
    refused = {"outcome": "REFUSED", "code": "merkle_root_mismatch", "detail": "run root", "checks": []}
    rep = report.build([_entry(CERTS[0]), _entry(CERTS[1], res=refused)])
    assert [len(g["members"]) for g in rep["groups"]] == [1] and rep["not_verified"][0]["verification"]["code"] == "merkle_root_mismatch"
    page = report.html(rep)
    assert "REFUSED" in page and "left out of every comparison" in page


def test_one_round_with_two_token_caps_is_two_groups_with_the_reason():
    a = _entry(CERTS[0])
    b = copy.deepcopy(_entry(CERTS[1]))
    b["benchmark_root"], b["settings"]["max_tokens"] = a["benchmark_root"], a["settings"]["max_tokens"] // 2
    b["kind"], b["n"], b["settings"]["request_template"], b["settings"]["scorer"] = a["kind"], a["n"], a["settings"]["request_template"], a["settings"]["scorer"]
    rep = report.build([a, b])
    assert len(rep["groups"]) == 2 and rep["not_comparable"][0]["because"] == ["the token cap differs"]


def test_text_from_a_certificate_is_escaped():
    raw = Path(CERTS[0]).read_bytes()
    cert = json.loads(raw)
    evil = "<script>alert(1)</script>"
    cert["benchmark"]["policy"]["models"][evil] = cert["benchmark"]["policy"]["models"][cert["run"]["model_id"]]
    cert["run"]["model_id"], cert["benchmark"]["id"] = evil, '"><img src=x onerror=1>'
    page = report.html(report.build([report.entry('x"y.json', raw, cert, OK, NOW)]))
    assert "<script>alert" not in page and "<img src=x" not in page and "<b>printed</b>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_a_file_that_is_not_a_certificate_is_listed_not_crashed_on(tmp_path):
    bad = tmp_path / "notes.json"
    bad.write_text("{}")
    assert cli.main(["report", str(bad), CERTS[0], "--out", str(tmp_path / "r"), "--recorded", str(_recorded(tmp_path))]) == 1
    rep = json.loads((tmp_path / "r" / "report.json").read_text())
    assert rep["verified"] == 1 and rep["not_verified"][0]["verification"]["code"] == "certificate_invalid"
