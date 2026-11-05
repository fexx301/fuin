"""Score the synthetic round (tests/fixtures/tee-synthetic-round.json) inside OutLayer with the current pinned scorer and
write tests/fixtures/tee-synthetic-evidence.json, the real record the offline TEE tests check.

Usage: uv run --env-file .env python scripts/score_tee_fixture.py [ROUND_FIXTURE OUT]   (signs testnet transactions as fuin.testnet)
Defaults: tests/fixtures/tee-synthetic-round.json → tests/fixtures/tee-synthetic-evidence.json.
Synthetic data only, so the ciphertext is hosted permanently on FastFS.
"""
import hashlib
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fuin import tee  # noqa: E402

OWNER = "fuin.testnet"
fx_dir = Path(__file__).resolve().parents[1] / "tests/fixtures"
src, dst = (Path(sys.argv[1]), Path(sys.argv[2])) if len(sys.argv) > 2 else (fx_dir / "tee-synthetic-round.json", fx_dir / "tee-synthetic-evidence.json")
fx = json.loads(src.read_text())
key = tee.keygen(OWNER)
blob, eph_pub, nonce = tee.encrypt(tee.jdump(fx["round"]).encode(), key["pub"])
url, encoding, _ = tee.fastfs_host(OWNER)(blob)
served = requests.get(url, timeout=120).content
tx, input_data, out = tee.execute(OWNER, {"mode": "score", "url": url, "blob_sha256": hashlib.sha256(served).hexdigest(),
                                          "encoding": encoding, "sealed": key["sealed"], "eph_pub": eph_pub, "nonce": nonce})
diff = {k: (out.get(k), v) for k, v in fx["expected"].items() if out.get(k) != v}
assert not diff, f"TEE outcome differs from Python's: {diff}"
ev = {"v": "fuin-tee-evidence-v1", "transaction_hash": tx, "input_data": input_data, "output": out,
      "record": tee.fetch_record(tx), "scorer_url": tee.current_scorer()["url"]}
dst.write_text(json.dumps({"evidence": ev, "expected": fx["expected"]}, indent=1) + "\n")
print(f"task {ev['record']['task_id']}, scorer {ev['record']['wasm_hash'][:12]}…: total {out['total']}/{out['n']} matches Python")
