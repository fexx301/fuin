"""Verify every fixture in a manifest and compare with its expected verdict. Exit 1 on any mismatch.

Usage: uv run python scripts/check_fixtures.py examples/tampered/manifest.json
Each fixture runs in a fresh `fuin verify --json` process so env overrides (e.g. an unreachable RPC) stay isolated.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

manifest = Path(sys.argv[1])
fails = 0
for f in json.loads(manifest.read_text())["fixtures"]:
    env = {**os.environ, **f.get("env", {})}
    env.pop("NEARAI_API_KEY", None)
    p = subprocess.run(["fuin", "verify", "--json", str(manifest.parent / f["file"])], capture_output=True, text=True, env=env)
    try:
        res = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        print(f"FAIL {f['file']}: no verdict ({p.stderr.strip()[-200:]})")
        fails += 1
        continue
    got = res["outcome"] if res["outcome"] == "VERIFIED" else f"{res['outcome']} {res.get('code')}"
    ok = got == f["expected"]
    fails += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {f['file']}: {got}" + ("" if ok else f" (expected {f['expected']})"))
sys.exit(1 if fails else 0)
