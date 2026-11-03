"""Leak guard: no hidden suite item may appear in tracked files, except as an audited reveal of its own round.

Usage: uv run python scripts/leak_guard.py   (run before every push and before going public; exit 1 on a leak)
Reads hidden suites from private/suites/*.jsonl (gitignored). Prints only item indices, never item text.
A reveal is allowed only in a certificate of the round that sampled it, i.e. its exact (question, request_nonce)
appears in that round's private state and was selected; any other occurrence of the question, its cited source line or
its source anchor is a leak. Limitation: a paraphrase that cites a different line is not caught; review new suites by hand.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

PRIVATE = Path("private")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s.lower())).strip()


hidden = []  # (suite, index, normalized question, anchor, source url)
suites = {}
for suite in sorted((PRIVATE / "suites").glob("*.jsonl")):
    items = [json.loads(line) for line in suite.read_text(encoding="utf-8").splitlines() if line.strip()]
    suites[suite.name] = items
    for i, it in enumerate(items):
        src = it.get("source", {})
        hidden.append((suite.name, i, norm(it["question"]), src.get("anchor", ""), src.get("url", "")))

# A hidden item may appear only as a reveal by the round sealed from its own suite, with that round's nonce for it.
allowed = set()  # (suite, index, request_nonce)
for state in PRIVATE.glob("*/state.json"):
    st = json.loads(state.read_text(encoding="utf-8"))
    for name, items in suites.items():
        if [r["item"]["question"] for r in st["items"]] == [it["question"] for it in items]:
            allowed |= {(name, i, r["item"]["request_nonce"]) for i, r in enumerate(st["items"])}

# Disclosures the owner has acknowledged and counts as disclosed (private: it names hidden items).
ack_file = PRIVATE / "suites" / "acknowledged.json"
acknowledged = {(a["suite"], a["index"]) for a in json.loads(ack_file.read_text())} if ack_file.exists() else set()

tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
leaks = []
for path in tracked:
    p = Path(path)
    if not p.is_file() or p.suffix in {".lock", ".wasm"}:
        continue
    text = p.read_text(encoding="utf-8", errors="ignore")
    flat = norm(text)
    revealed_here = set()  # (suite, index) legitimately revealed in this file
    if p.suffix == ".json":
        try:
            doc = json.loads(text)
            reveals = doc.get("audit", {}).get("reveals", []) if isinstance(doc, dict) else []
        except ValueError:
            reveals = []
        for x in reveals:
            for suite, i, q, _, _ in hidden:
                if norm(x["item"].get("question", "")) == q and (suite, i, x["item"].get("request_nonce")) in allowed:
                    revealed_here.add((suite, i))
    for suite, i, q, anchor, url in hidden:
        if (suite, i) in revealed_here or (suite, i) in acknowledged:
            continue
        if q in flat:
            leaks.append((path, suite, i, "question"))
        elif url and url in text:
            leaks.append((path, suite, i, "same source line"))
        elif anchor and len(anchor) > 12 and anchor in text:
            leaks.append((path, suite, i, "source anchor"))
for leak in leaks:
    print("LEAK", *leak)
print(f"{len(hidden)} hidden items checked against {len(tracked)} tracked files: {len(leaks)} leak(s), "
      f"{len(acknowledged)} acknowledged disclosure(s) skipped")
sys.exit(1 if leaks else 0)
