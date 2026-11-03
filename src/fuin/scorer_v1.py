"""fuin-scorer-v1: deterministic 0/1 scoring. The verifier pins this file's sha256 in the sealed policy.

Extraction: the whole assistant message, trimmed; one trailing '.' and surrounding backticks/quotes removed.
numeric: the extracted text must be one decimal number (',' and '_' between digits ignored);
         score 1 iff |x - answer| <= tolerance (decimal strings, exact arithmetic).
exact:   casefolded extracted text must equal a casefolded entry of `accept` (or `answer`).
"""

import json
import re
from decimal import Decimal, InvalidOperation

NAME = "fuin-scorer-v1"
NUMBER = re.compile(r"[-+]?\d+(\.\d+)?([eE][-+]?\d+)?")


def extract(content: str) -> str:
    s = content.strip()
    s = s[:-1] if s.endswith(".") else s
    return s.strip().strip("`\"'").strip()


def score_text(item: dict, content: str) -> int:
    s = extract(content)
    if item["answer_type"] == "numeric":
        s = re.sub(r"(?<=\d)[,_](?=\d)", "", s)
        if not NUMBER.fullmatch(s):
            return 0
        try:
            return int(abs(Decimal(s) - Decimal(item["answer"])) <= Decimal(item.get("tolerance", "0")))
        except InvalidOperation:
            return 0
    if item["answer_type"] == "exact":
        accept = {a.casefold() for a in [item["answer"], *item.get("accept", [])]}
        return int(s.casefold() in accept)
    raise ValueError(f"unsupported answer_type {item['answer_type']!r}")


def score_response(item: dict, response: bytes) -> int:
    """Score from the exact response bytes; a malformed or empty response scores 0."""
    try:
        content = json.loads(response)["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError):
        return 0
    return score_text(item, content) if isinstance(content, str) else 0
