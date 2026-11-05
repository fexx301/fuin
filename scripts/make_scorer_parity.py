"""Write tests/fixtures/scorer-parity.json: generated answers scored by the sealed Python scorers (v1 and v2).

scripts/test_site_verifier.mjs re-scores every case in the browser port and requires identical results, so the
browser can't refuse a genuine certificate over a Unicode edge (case folding, whitespace, digits) the real answers
don't happen to contain. Deterministic (seeded); rerun after changing either scorer's port.
"""
import json
import random
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fuin import scorer, scorer_v1  # noqa: E402

rng = random.Random(20261104)
SPACE = [chr(c) for c in range(0x110000) if chr(c).isspace()] + ["﻿", "​", "᠎"]  # last 3: not Python whitespace
FOLD = ["ß", "ẞ", "µ", "ſ", "ς", "Σ", "ﬁ", "ﬀ", "İ", "ı", "ǰ", "ŉ", "ᾳ", "Ꭰ", "ꭰ", "K", "Å", "ϐ", "ϑ"]
DIGITS = ["٣", "３", "३", "৩", "𝟑", "߃"]  # Unicode decimal digits for 3
WORDS = ["Straße", "STRASSE", "near-sdk", "LookupMap", "ﬁle", "FILE", "µs", "μs", "ΣΟΦΟΣ", "σοφος", "Kelvin", "Ångström"]
WRAP = ["`", '"', "'", "*", "_", "**", "__", "``"]


def noise(s):
    for _ in range(rng.randint(0, 2)):
        w = rng.choice(WRAP)
        s = w + s + w if rng.random() < 0.6 else w + s
    if rng.random() < 0.3:
        s += "."
    return rng.choice(SPACE) * rng.randint(0, 2) + s + rng.choice(SPACE) * rng.randint(0, 2)


cases = []
for _ in range(1500):  # exact answers
    ans = rng.choice(WORDS + FOLD)
    said = rng.choice([ans, ans.upper(), ans.lower(), ans.casefold(), rng.choice(WORDS + FOLD), ans.swapcase()])
    item = {"answer_type": "exact", "answer": ans, **({"accept": [rng.choice(WORDS)]} if rng.random() < 0.3 else {})}
    cases.append({"item": item, "content": noise(said)})
for _ in range(1500):  # numeric answers
    n = rng.choice(["3", "1000000", "0.5", "-2", "1e6", "42", "10.0"])
    said = rng.choice([n, n + "0", "1,000,000", "1_000_000", "3.0", "+3", "٣", "３", "३", "1" + rng.choice(DIGITS),
                       rng.choice(DIGITS) + ".5", "3 ", "3.", "0x3", "3e0", "1 000 000", "1,00,000"])
    item = {"answer_type": "numeric", "answer": n, **({"tolerance": rng.choice(["0", "0.5", "1"])} if rng.random() < 0.4 else {})}
    cases.append({"item": item, "content": noise(said)})

for c in cases:
    c["v1"] = scorer_v1.score_text(c["item"], c["content"])
    c["v2"] = scorer.score_text(c["item"], c["content"])
out = Path(__file__).resolve().parents[1] / "tests/fixtures/scorer-parity.json"
out.write_text(json.dumps({"python_unicode": unicodedata.unidata_version, "cases": cases}, ensure_ascii=False) + "\n")
print(f"wrote {len(cases)} cases ({sum(c['v2'] for c in cases)} score 1 under v2) to {out}")
