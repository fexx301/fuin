"""Check every suite item's source: the cited line of near/docs at the pinned commit contains the item's anchor.

Usage: uv run python scripts/check_suite_sources.py SUITE.jsonl
Also lists items whose answer does not appear literally in the anchor (after removing ',' '`' '*'),
so a human reviews those derivations (e.g. 1e24 -> 24).
"""
import json
import re
import sys

import requests

cache: dict[str, list[str]] = {}
bad, review = [], []
items = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
for i, it in enumerate(items):
    s = it["source"]
    key = f"{s['commit']}/{s['path']}"
    if key not in cache:
        r = requests.get(f"https://raw.githubusercontent.com/near/docs/{key}", timeout=30)
        r.raise_for_status()
        cache[key] = r.text.splitlines()
    line = cache[key][s["line"] - 1] if 0 < s["line"] <= len(cache[key]) else ""
    if s["anchor"] not in line:
        bad.append((i, s["path"], s["line"], s["anchor"]))
    flat = re.sub(r"[,`*]", "", s["anchor"])
    if it["answer"] not in flat:
        review.append((i, it["answer"], s["anchor"]))
print(f"{len(items)} items, {len(cache)} source files at {items[0]['source']['commit'][:8]}")
print(f"anchor not on cited line: {len(bad)}")
for b in bad:
    print("  BAD", b)
print(f"answer not literal in anchor (review the derivation): {len(review)}")
for r in review:
    print("  REVIEW", r)
sys.exit(1 if bad else 0)
