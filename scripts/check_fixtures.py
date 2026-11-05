"""Verify every fixture in a manifest and compare with its expected verdict. Exit 1 on any mismatch.

Usage: uv run python scripts/check_fixtures.py examples/tampered/manifest.json
Each fixture runs in a fresh `fuin verify --json` process so env overrides (e.g. an unreachable RPC) stay isolated;
four run at a time (FUIN_REVIEW_WORKERS), and the output keeps the manifest's order.
"""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

manifest = Path(sys.argv[1])
WORKERS = int(os.environ.get("FUIN_REVIEW_WORKERS", "4"))  # independent, network-bound checks; order of output is kept


def check(f):
    env = {**os.environ, **f.get("env", {})}
    env.pop("NEARAI_API_KEY", None)
    p = subprocess.run(["fuin", "verify", "--json", str(manifest.parent / f["file"])], capture_output=True, text=True, env=env)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False, f"FAIL {f['file']}: no verdict ({p.stderr.strip()[-200:]})"
    got = res["outcome"] if res["outcome"] == "VERIFIED" else f"{res['outcome']} {res.get('code')}"
    ok = got == f["expected"]
    return ok, f"{'ok  ' if ok else 'FAIL'} {f['file']}: {got}" + ("" if ok else f" (expected {f['expected']})")


with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    results = list(pool.map(check, json.loads(manifest.read_text())["fixtures"]))
for _, line in results:
    print(line)
sys.exit(0 if all(ok for ok, _ in results) else 1)
