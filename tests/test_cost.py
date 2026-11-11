"""The cost bound, the spending limit and measured usage: three different things, and the limit holds under parallel retries."""
import base64
import glob
import json
import threading
from decimal import Decimal
from pathlib import Path

import pytest
import requests

from fuin import cost, inference, owner
from fuin import policy as P

ROOT = Path(__file__).resolve().parents[1]
PRICE = {"x/A": (Decimal("0.0000003"), Decimal("0.0000012"))}   # $0.30 in / $1.20 out per million
CATALOG = [{"modelId": "Qwen/Qwen3.8-27B", "inputCostPerToken": {"amount": 40, "scale": 9, "currency": "USD"},
            "outputCostPerToken": {"amount": 1350, "scale": 9, "currency": "USD"}}]


def test_catalog_prices_are_dollars_per_token(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: CATALOG})())
    i, o = cost.prices(["Qwen/Qwen3.8-27B"])["Qwen/Qwen3.8-27B"]
    assert (i * 10**6, o * 10**6) == (Decimal("0.04"), Decimal("1.35"))   # the figures in docs/COSTS-AND-DEPENDENCIES.md
    with pytest.raises(KeyError):
        cost.prices(["no/such-model"])


def test_the_bound_is_never_below_what_a_published_answer_used():
    seen = 0
    for f in glob.glob(str(ROOT / "examples" / "cert-*.json")):
        c = json.loads(Path(f).read_text())
        cap = c["benchmark"]["policy"]["models"][c["run"]["model_id"]]["max_tokens"]
        for x in c["audit"].get("reveals") or []:
            p, done = cost._usage(x["response_b64"])
            assert p <= len(x["item"]["question"].encode()) + 64 and done <= cap
            seen += 1
    assert seen > 100


def _round(n=12, cap=1000):
    return {"benchmark_id": "r", "owner": "a.testnet", "items": [{"salt": "00", "item": {"question": f"q{i}?", "answer": "1"}} for i in range(n)],
            "policy": {"audit": {"mode": None, "k": 1}, "request": {"template": "fuin-request-v1"}, "models": {"x/A": {"max_tokens": cap, "temperature": 0}}},
            "seal": {"height": 1, "tx": "s", "block_hash": "h"}, "runs": {"x/A": {"signer": "0x1", "rows": [], "attempt_log": []}}}


@pytest.fixture
def calls(monkeypatch):
    """`fuin run` with a model that answers in 200 tokens and fails every call whose number is in `fail`."""
    st, box, lock = _round(), {"sent": [], "fail": set(), "billed": Decimal(0)}, threading.Lock()
    worst = cost.bound("q0?", 1000, PRICE["x/A"])

    def complete(req, extra):
        with lock:
            k = len(box["sent"]); box["sent"].append(int(req))
            failing = k in box["fail"]
            box["billed"] += worst if failing else 20 * PRICE["x/A"][0] + 200 * PRICE["x/A"][1]   # a failed call may be billed in full
        if failing:
            raise requests.ConnectionError("dropped")
        body = {"id": f"c{k}", "choices": [{"finish_reason": "stop"}], "usage": {"prompt_tokens": 20, "completion_tokens": 200}}
        return json.dumps(body).encode(), body

    monkeypatch.setattr(owner, "load", lambda bid: st); monkeypatch.setattr(owner, "save", lambda st: None)
    monkeypatch.setattr(owner, "preflight", lambda st, m: st["runs"][m])
    monkeypatch.setattr(inference, "sealed_request", lambda pol, m, r, h, pub: (str(int(r["item"]["question"][1:-1])).encode(), {}))
    monkeypatch.setattr(inference, "complete", complete)
    monkeypatch.setattr(inference, "fetch_signature", lambda cid, m: {})
    monkeypatch.setattr(inference, "check_signature", lambda *a: None)
    monkeypatch.setattr(P, "scorer_for", lambda pol: type("S", (), {"score_response": staticmethod(lambda item, resp: 1)}))
    monkeypatch.setattr(cost, "prices", lambda models: PRICE)
    return st, box, worst


def test_the_limit_holds_under_parallel_calls_and_retries_and_a_higher_one_finishes(calls):
    st, box, worst = calls
    box["fail"] = {1, 2, 6}
    limit = float(worst * 5)                      # room for five calls in flight or failed at their bound
    with pytest.raises(SystemExit, match="spending limit"):
        owner.run("r", "x/A", parallel=4, max_spend=limit)
    rn = st["runs"]["x/A"]
    assert box["billed"] <= Decimal(str(limit))    # what NEAR AI could have billed never passed the limit
    assert all("limit" not in x["error"] for x in rn["attempt_log"]) and len(rn["attempt_log"]) == 3   # a stop is not a failed attempt
    assert cost.spent(st, PRICE) <= Decimal(str(limit))
    kept = len(rn["rows"]) + len(rn.get("pending", {}))
    assert 0 < kept < 12
    box["fail"] = set()
    owner.run("r", "x/A", parallel=4, max_spend=1.0)     # the same command, a higher limit
    assert [r["i"] for r in rn["rows"]] == list(range(12))
    answered = [i for k, i in enumerate(box["sent"]) if k not in {1, 2, 6}]
    assert sorted(answered) == list(range(12))             # every question answered exactly once: nothing asked again


def test_spend_is_recomputed_from_saved_state_so_a_rerun_cannot_reset_it(calls):
    st, box, worst = calls
    limit = float(worst * 2)
    with pytest.raises(SystemExit, match="spending limit"):
        owner.run("r", "x/A", parallel=1, max_spend=limit)
    first = len(box["sent"])
    for _ in range(30):                              # hammering the same command at the same limit
        try:
            owner.run("r", "x/A", parallel=1, max_spend=limit)
        except SystemExit:
            pass
    assert first > 0 and box["billed"] <= Decimal(str(limit)) and len(st["runs"]["x/A"]["rows"]) < 12


def test_no_price_means_no_calls_when_a_limit_is_set(calls, monkeypatch):
    st, box, _ = calls
    monkeypatch.setattr(cost, "prices", lambda models: (_ for _ in ()).throw(requests.ConnectionError("catalog down")))
    with pytest.raises(SystemExit, match="price list can't be read"):
        owner.run("r", "x/A", parallel=2, max_spend=1.0)
    assert box["sent"] == []


def test_an_asked_rounds_spend_counts_each_ask_once_at_its_bound():
    st = _round(n=3)
    st["policy"]["audit"] = {"mode": P.TEE_ASKED, "k": 0}
    st["runs"]["x/A"] = {"rows": [{"i": 0, "attempts": 1}, {"i": 1, "attempts": 3}],            # the TEE's count for item 1 ...
                         "attempt_log": [{"i": 1, "attempt": 0, "error": "timeout"}, {"i": 1, "attempt": 1, "error": "timeout"},   # ... already covers these
                                         {"i": 2, "attempt": 0, "error": "timeout"}],
                         "pending_ask": {"i": 2, "tx": "t"}}
    worst = cost.bound("q0?", 1000, PRICE["x/A"])
    assert cost.spent(st, PRICE) == worst * (1 + 3 + 1 + 1)


def test_the_printed_bound_and_fees_stay_apart_and_say_what_they_are(monkeypatch):
    monkeypatch.setattr(cost, "prices", lambda models: PRICE)
    out = "\n".join(cost.estimate(["q?"] * 40, {"x/A": 4096}, "ask"))
    assert "a bound, not a forecast and not a bill" in out and "at most $0.20 if all 40 answers used the whole 4,096-token cap" in out
    assert "only --max-spend caps the total" in out and "NEAR testnet, free from the faucet" in out and "43 TEE tasks" in out
    monkeypatch.setattr(cost, "prices", lambda models: (_ for _ in ()).throw(requests.ConnectionError("down")))
    assert "prices not available right now" in "\n".join(cost.estimate(["q?"], {"x/A": 4096}, "sampled"))


def test_measured_usage_is_tokens_from_the_answers_and_never_a_guess_for_an_asked_round(monkeypatch):
    monkeypatch.setattr(cost, "prices", lambda models: PRICE)
    st = _round(n=2)
    resp = base64.b64encode(json.dumps({"usage": {"prompt_tokens": 20, "completion_tokens": 200}}).encode()).decode()
    st["runs"]["x/A"] = {"rows": [{"i": 0, "response_b64": resp}, {"i": 1, "response_b64": resp}], "attempt_log": [{"i": 1, "attempt": 0, "error": "x"}]}
    out = "\n".join(cost.measured(st))
    assert "2 answers, 40 prompt + 400 completion tokens" in out and "1 failed attempt left no token count" in out and "not a bill" in out
    st["policy"]["audit"] = {"mode": P.TEE_ASKED, "k": 0}
    st["runs"]["x/A"] = {"rows": [{"i": 0, "attempts": 2}], "attempt_log": []}
    assert "not available, because an asked-once round's answers never leave the enclave; 2 asks counted by the TEE" in "\n".join(cost.measured(st))
