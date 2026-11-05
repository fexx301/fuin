"""TEE-scored runs on OutLayer: the owner side (plaintext, encryption, upload, execution) and the verifier's check.

The TEE scorer (tee/, a reproducible wasm32-wasip2 build pinned in policy/tee-v1.json) rebuilds and scores every answer
of one run from the sealed bytes, inside an Intel TDX enclave, and returns only the roots, the total and the signer.
"""

import base64
import json
from pathlib import Path

from fuin import core
from fuin import policy as P

TEE_POLICY = Path(__file__).resolve().parents[2] / "policy" / "tee-v1.json"


def plaintext(st: dict, model: str) -> dict:
    """The round as the TEE reads it: each item's exact sealed bytes and salt, the canonical policy, the signed rows."""
    rn = st["runs"][model]
    if len(rn["rows"]) != len(st["items"]):
        raise ValueError(f"{model}: run incomplete")
    return {
        "v": "fuin-tee-round-v1",
        "model": model,
        "policy_jcs": core.jcs(st["policy"]).decode(),
        "items": [{"salt": r["salt"], "item_jcs": core.jcs(r["item"]).decode()} for r in st["items"]],
        "rows": [{"request_b64": x["request_b64"], "response_b64": x["response_b64"], "signature": x["signature"]}
                 for x in sorted(rn["rows"], key=lambda x: x["i"])],
    }


def expected(st: dict, model: str) -> dict:
    """What a faithful TEE scorer must output for this run, from the owner's own records."""
    rn = st["runs"][model]
    return {"model": model, "n": len(st["items"]), "total": rn["commit"]["total_score"], "benchmark_root": st["seal"]["root"],
            "policy_hash": P.policy_hash(st["policy"]), "run_root": rn["commit"]["run_root"], "signer": rn["signer"]}


def b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def jdump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
