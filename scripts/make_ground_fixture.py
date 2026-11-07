"""Synthetic grounding cases for the TEE parity test (tee/tests/ground.rs): items and cited files, with what the Python
reference (fuin.tee.ground_round) outputs for each. Edge cases: \\r\\n endings, Python-only line breaks (\\x0c, \\u2028)
that must not split a line, stripped characters, accept alternatives, out-of-range lines, non-ASCII text.

Usage: uv run python scripts/make_ground_fixture.py  (writes tests/fixtures/tee-ground-cases.json)"""
import json
import pathlib

from fuin import core, tee

C = "e2d2ea173cf462bcf518ecae5650984a221d5183"
FILES = {
    "a.md": "first line\r\nThe method is `nft_transfer`, see below\r\nfee: 1,000 yocto\r\n",
    "dir/b-1.mdx": "x\x0cstill line one with **storage_deposit** and more\nline two: ünïcödé ✓ 42\nlast",
}


def item(i, answer, path, line, accept=None):
    it = {"question": f"q{i}", "answer": answer, "answer_type": "exact",
          "source": {"url": "ignored", "commit": C, "path": path, "line": line, "anchor": "ignored"}, "request_nonce": f"{i:064x}"}
    if accept is not None:
        it["accept"] = accept
    return it


rounds = [
    [item(0, "nft_transfer", "a.md", 2), item(1, "1000", "a.md", 3), item(2, "storage_deposit", "dir/b-1.mdx", 1),
     item(3, "and more", "dir/b-1.mdx", 1), item(4, "ünïcödé ✓", "dir/b-1.mdx", 2), item(5, "nft_transfer", "a.md", 3),
     item(6, "x", "a.md", 9), item(7, "x", "a.md", 0), item(8, "nft_transfer", "a.md", 2, ["nft_transfer_call"]),
     item(9, "first", "a.md", 1, ["line", "first line"]), item(10, "", "a.md", 4), item(11, "last", "dir/b-1.mdx", 3, [])],
    [item(0, "42", "dir/b-1.mdx", 2)],
]
cases = []
for r in rounds:
    salts = [f"{i + 1:064x}" for i in range(len(r))]
    cases.append({"items": [{"salt": s, "item_jcs": core.jcs(it).decode()} for it, s in zip(r, salts)],
                  "expected": tee.ground_round(r, salts, FILES)})
out = pathlib.Path(__file__).resolve().parent.parent / "tests/fixtures/tee-ground-cases.json"
out.write_text(json.dumps({"files": FILES, "cases": cases}, ensure_ascii=False, indent=1) + "\n")
print(out, [c["expected"]["flags"] for c in cases])
