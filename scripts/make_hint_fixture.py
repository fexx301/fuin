"""Build the 'answer hint' fixture from a real round: a dishonest owner appends the expected answer to the prompt.

The model signs the hinted request and the owner commits it honestly on chain, so every signature, root and registry
check passes; only rebuilding the revealed request from the sealed template catches it (request_policy_mismatch).
Signs testnet transactions as OWNER and makes one gateway completion. Usage:
  uv run --env-file .env python scripts/make_hint_fixture.py OWNER BENCHMARK_ID OUT_DIR
"""
import json
import sys
import tempfile
from pathlib import Path

from fuin import inference, owner

who, bid, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
# Must not be a question from any hidden suite (scripts/leak_guard.py checks); this one is already public in evidence/.
item = {"question": "What is the smallest unit of NEAR called? Answer with one word.",
        "answer": "yoctoNEAR", "accept": ["yocto"], "answer_type": "exact", "fixture": "answer-hint: not a benchmark item"}
with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
    f.write(json.dumps(item) + "\n")
model = "z-ai/glm-5.3-flash"
if not (owner.PRIVATE / bid / "state.json").exists():  # resumable: the seal is once per id
    owner.seal(f.name, bid, who, {model: {"max_tokens": 4096, "temperature": 0}})

honest = inference.build_request
inference.build_request = lambda m, q, n, s: honest(m, q + " (Hint: the answer is yoctoNEAR.)", n, s)  # the cheat
try:
    owner.run(bid, model)
finally:
    inference.build_request = honest
owner.commit(bid, model)
owner.close(bid)
[cert] = owner.reveal(bid, str(out))
target = out / "answer-hint.json"
cert.replace(target)
m = json.loads((out / "manifest.json").read_text())
m["fixtures"] = [x for x in m["fixtures"] if x["file"] != "answer-hint.json"] + [{
    "file": "answer-hint.json", "expected": "REFUSED request_policy_mismatch",
    "mutation": f"real round {bid}: the owner appended the answer to the prompt; signed by the model and committed on chain"}]
(out / "manifest.json").write_text(json.dumps(m, indent=1) + "\n")
print("wrote", target)
