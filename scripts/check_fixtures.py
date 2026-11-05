"""Verify every fixture in a manifest and compare with its expected verdict. Exit 1 on any mismatch.

Usage: uv run python scripts/check_fixtures.py examples/tampered/manifest.json
Each fixture runs in a fresh `fuin verify --json` process so env overrides (e.g. an unreachable RPC) stay isolated;
four run at a time (FUIN_REVIEW_WORKERS), and the output keeps the manifest's order. A public service's rate limit is an
outage, not a verdict: a fixture that comes back CAN'T CERTIFY evidence_unavailable when it expects something else is
retried after a pause, at most twice, and the line says so.
"""
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

manifest = Path(sys.argv[1])
WORKERS = int(os.environ.get("FUIN_REVIEW_WORKERS", "4"))  # independent, network-bound checks; order of output is kept


def verdict(f):
    env = {**os.environ, **f.get("env", {})}
    env.pop("NEARAI_API_KEY", None)
    p = subprocess.run(["fuin", "verify", "--json", str(manifest.parent / f["file"])], capture_output=True, text=True, env=env)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None, p.stderr.strip()[-200:]
    return (res["outcome"] if res["outcome"] == "VERIFIED" else f"{res['outcome']} {res.get('code')}"), ""


def check(f):
    got, err = verdict(f)
    retries = 0
    while got == "CANT_CERTIFY evidence_unavailable" != f["expected"] and not f.get("env") and retries < 2:
        retries += 1
        time.sleep(60)
        got, err = verdict(f)
    if got is None:
        return False, f"FAIL {f['file']}: no verdict ({err})"
    ok = got == f["expected"]
    note = f" (after {retries} retry for a public-service outage)" if retries else ""
    return ok, f"{'ok  ' if ok else 'FAIL'} {f['file']}: {got}{note}" + ("" if ok else f" (expected {f['expected']})")


with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    results = list(pool.map(check, json.loads(manifest.read_text())["fixtures"]))
for _, line in results:
    print(line)
sys.exit(0 if all(ok for ok, _ in results) else 1)
