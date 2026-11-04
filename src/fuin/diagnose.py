"""Classify each revealed miss: cut off, format, or wrong. A reading aid computed from revealed bytes, not a score.

- cut off: generation stopped at max_tokens before a final answer (scored 0 because the answer text is empty).
- format: the strict scorer said 0, but the expected value is in the answer once units, '%', markdown and
          extra words are ignored (e.g. "**10%**" for 10, "1000 TGas" for 1000).
- wrong:  anything else.
"""

import base64
import json
import re
from decimal import Decimal, InvalidOperation

NUM = re.compile(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def lenient_match(item: dict, content: str) -> bool:
    text = re.sub(r"(?<=\d)[,_](?=\d)", "", content)
    if item["answer_type"] == "numeric":
        nums = NUM.findall(text)
        try:
            want = Decimal(item["answer"])
            return len(set(nums)) == 1 and abs(Decimal(nums[0]) - want) <= Decimal(item.get("tolerance", "0"))
        except InvalidOperation:
            return False
    words = {w.casefold() for w in [item["answer"], *item.get("accept", [])]}
    norm = re.sub(r"[`*\"'()]", " ", text).casefold()  # keep _ : method names use it
    return any(re.search(rf"(?<![\w:.]){re.escape(w.strip('()'))}(?![\w])", norm) for w in words)


def classify(item: dict, response_b64: str, score: int) -> str:
    if score == 1:
        return "correct"
    ch = json.loads(base64.b64decode(response_b64))["choices"][0]
    content = (ch["message"].get("content") or "").strip()
    if not content and ch.get("finish_reason") == "length":
        return "cut off"
    return "format" if lenient_match(item, content) else "wrong"


def breakdown(cert: dict) -> dict:
    scores = {it["i"]: it["score"] for it in cert["run"]["items"]}
    out = {"correct": 0, "format": 0, "cut off": 0, "wrong": 0}
    for x in cert["audit"]["reveals"]:
        out[classify(x["item"], x["response_b64"], scores[x["i"]])] += 1
    return out
