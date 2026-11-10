"""Every count the docs and the page state (rounds, certificates, answers, fixtures) matches the artifacts it describes."""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDS = {"seven": 7, "twenty": 20, "nineteen": 19}


def _num(s):
    s = s.lower()
    return WORDS[s] if s in WORDS else int(s.replace(",", ""))


def test_doc_counts_match_the_artifacts():
    certs = [json.loads(p.read_text()) for p in ROOT.glob("examples/cert-*.json")]
    sizes = {c["benchmark"]["id"]: c["benchmark"]["n"] for c in certs}
    by_round = [sizes[r] for r in sorted(sizes, key=lambda r: int(r.rsplit("-r", 1)[1]))]
    fixtures = json.loads((ROOT / "examples/tampered/manifest.json").read_text())["fixtures"]
    kinds = Counter(f["expected"].split()[0] for f in fixtures)
    want = {
        r"(\d+) `ok` lines": len(fixtures),
        r"(\d+) tamper fixtures": len(fixtures),
        r"all (\d+) fixtures": len(fixtures),
        r"(\d+) tests of tampering": len(fixtures),
        r"(?<!other )\b(\d+) (?:real )?certificates": len(certs),
        r"The other (\d+) certificates": len(certs) - 1,
        r"all (\w+) totals": len(certs),
        r"(?:covering ([\d,]+) answers|([\d,]+) TEE-checked answers)": sum(c["benchmark"]["n"] for c in certs),
        r"\(([\d,]+) in all\)": sum(c["benchmark"]["n"] for c in certs),
        r"(\w+) (?:independent |verified )?rounds(?: of private)?\b": len(sizes),
        r"(\d+) are REFUSED": kinds["REFUSED"],
        r"(\d+) are CAN'T CERTIFY": kinds["CANT_CERTIFY"],
    }
    lists = r"rounds of private (?:NEAR-developer )?questions \(([\d, and]+)\)|test sets \(([\d, and]+) items\)"
    text = {p: p.read_text() for p in [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "CHANGELOG.md", ROOT / "site/index.html", *ROOT.glob("docs/*.md")]}
    for pattern, expected in want.items():
        found = [(p.name, m.group(m.lastindex)) for p, t in text.items() for m in re.finditer(pattern, t)]
        found = [(n, g) for n, g in found if g.lower() in WORDS or g[0].isdigit()]
        assert found, pattern  # a pattern that no longer matches anything would hide a stale count
        for name, got in found:
            assert _num(got) == expected, f"{name}: {pattern} says {got}, artifacts say {expected}"
    found = [m.group(m.lastindex) for t in text.values() for m in re.finditer(lists, t)]
    assert found
    for got in found:
        assert [int(x) for x in re.findall(r"\d+", got)] == by_round, got


def test_every_fixture_has_a_row_in_refusals():
    refusals = (ROOT / "docs/REFUSALS.md").read_text()
    fixtures = json.loads((ROOT / "examples/tampered/manifest.json").read_text())["fixtures"]
    missing = [f["file"] for f in fixtures if Path(f["file"]).stem not in refusals]
    assert not missing, missing
