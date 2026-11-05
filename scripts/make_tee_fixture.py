"""Write tests/fixtures/tee-synthetic-round.json: a 3-item round with made-up questions, signed by a throwaway key
the way NEAR AI's TEE signs, plus the outcome the Python reference computes. The Rust scorer's tests must reproduce it
and refuse each tampering. Deterministic; contains nothing from a real suite."""
import json, sys
from pathlib import Path
from eth_account import Account
from eth_account.messages import encode_defunct
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fuin import core, inference, tee  # noqa: E402
from fuin import policy as P  # noqa: E402

model = "z-ai/glm-5.3-flash"
acct = Account.from_key(bytes([7]) * 32)  # throwaway, not attested anywhere
items = [{"question": "Synthetic: what is 6 x 7? Answer with the number only.", "answer": "42", "answer_type": "numeric", "request_nonce": "11" * 32},
         {"question": "Synthetic: name the colour of a clear daytime sky. One word.", "answer": "blue", "answer_type": "exact", "accept": ["light blue"], "request_nonce": "22" * 32},
         {"question": "Synthetic: 1,000 plus 2,500? Number only.", "answer": "3500", "answer_type": "numeric", "tolerance": "0", "request_nonce": "33" * 32}]
answers = ["**42**", "Blue.", "3,500"]
pol = P.make_policy(3, {model: {"max_tokens": 64, "temperature": 0}})
st = {"policy": pol, "items": [{"item": it, "salt": f"{i + 1:02x}" * 32} for i, it in enumerate(items)], "runs": {model: {"rows": []}}}
bleaves, rleaves, total = [], [], 0
for i, (r, ans) in enumerate(zip(st["items"], answers)):
    req = inference.build_request(model, r["item"]["question"], r["item"]["request_nonce"], pol["models"][model])
    resp = json.dumps({"id": f"chatcmpl-{i}", "choices": [{"index": 0, "message": {"role": "assistant", "content": ans}, "finish_reason": "stop"}]}).encode()
    text = inference.signature_text(model, req, resp)
    sig = acct.sign_message(encode_defunct(text=text))
    signature = {"text": text, "signature": "0x" + sig.signature.hex(), "signing_address": acct.address.lower(), "signature_kind": "provider_tee", "signing_algo": "ecdsa"}
    score = P.scorer_for(pol).score_response(r["item"], resp)
    bl = core.benchmark_leaf(i, bytes.fromhex(r["salt"]), r["item"])
    rleaves.append(core.run_leaf(i, bl, core.sha256(req), core.sha256(resp), score)); bleaves.append(bl); total += score
    st["runs"][model]["rows"].append({"i": i, "request_b64": tee.b64(req), "response_b64": tee.b64(resp), "signature": signature})
expected = {"model": model, "n": 3, "total": total, "benchmark_root": core.merkle_root(bleaves).hex(), "policy_hash": P.policy_hash(pol),
            "run_root": core.merkle_root(rleaves).hex(), "signer": acct.address.lower()}
out = Path(__file__).resolve().parents[1] / "tests/fixtures/tee-synthetic-round.json"
out.write_text(json.dumps({"round": tee.plaintext(st, model), "expected": expected}, ensure_ascii=False, indent=1) + "\n")
print(f"wrote {out.name}: total {total}/3, signer {acct.address.lower()}")
