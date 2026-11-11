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
            p, done = cost._usage(x["response_b64"])   # every published answer carries its token count
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


def test_an_answer_that_is_discarded_is_logged_and_still_counts_after_a_rerun(calls, monkeypatch):
    st, box, worst = calls
    monkeypatch.setattr(inference, "fetch_signature", lambda cid, m: None)      # the answer came back; its signature never did
    with pytest.raises(SystemExit, match="signature unavailable"):
        owner.run("r", "x/A", parallel=1, max_spend=float(worst * 3))
    rn = st["runs"]["x/A"]
    assert rn["rows"] == [] and "answer discarded" in rn["attempt_log"][0]["error"]
    assert cost.spent(st, PRICE) == worst                                            # the billed call is not forgotten
    for _ in range(10):
        try:
            owner.run("r", "x/A", parallel=1, max_spend=float(worst * 3))
        except SystemExit:
            pass
    assert len(box["sent"]) == 3 and box["billed"] <= worst * 3                      # reruns can't walk past the limit


def test_an_answer_with_no_token_count_is_counted_at_its_bound_not_as_free():
    st = _round(n=1)
    blank = base64.b64encode(json.dumps({"id": "c", "choices": []}).encode()).decode()
    st["runs"]["x/A"] = {"rows": [{"i": 0, "response_b64": blank}], "attempt_log": []}
    assert cost.spent(st, PRICE) == cost.bound("q0?", 1000, PRICE["x/A"]) and cost.usage_cost(None, PRICE["x/A"]) is None
    b = cost.Budget(Decimal(1), Decimal(0))
    b.reserve(Decimal("0.4")); b.settle(Decimal("0.4"), None)
    assert (b.spent, b.held) == (Decimal("0.4"), Decimal(0))


def test_the_stop_message_says_whether_money_was_spent_or_only_held_for_calls_in_flight():
    b = cost.Budget(Decimal("0.012"), Decimal("0.0001"))
    assert b.reserve(Decimal("0.0055")) and b.reserve(Decimal("0.0055")) and not b.reserve(Decimal("0.0055"))
    msg = b.stop("item 2")
    assert "$0.012 reached: $0.0001 spent and $0.0110 held for calls in flight" in msg and "or a lower --parallel" in msg
    b.settle(Decimal("0.0055"), Decimal("0.0001")); b.settle(Decimal("0.0055"))
    assert "held" not in b.stop("item 3") and "--parallel" not in b.stop("item 3")


def test_a_run_killed_after_a_billed_call_cannot_forget_it(calls, monkeypatch):
    # from a reviewer (Nov 11): six interrupted attempts passed the limit while recorded spend stayed at zero
    st, box, worst = calls
    complete = inference.complete

    def interrupted(req, extra):
        complete(req, extra)                                   # NEAR AI answered, and bills ...
        raise SystemExit("interrupted before the response was saved")   # ... and the process dies before the answer is on disk

    monkeypatch.setattr(inference, "complete", interrupted)
    for _ in range(6):
        with pytest.raises(SystemExit):
            owner.run("r", "x/A", parallel=1, max_spend=float(worst))
    rn = st["runs"]["x/A"]
    assert len(box["sent"]) == 1 and box["billed"] <= worst    # the first call used the whole limit; no rerun sent another
    assert cost.spent(st, PRICE) == worst and "interrupted" in rn["attempt_log"][0]["error"]   # recorded, and reported with the certificate
    assert "in_flight" not in rn


def test_a_call_is_noted_before_it_is_sent_and_cleared_with_its_answer(calls, monkeypatch):
    st, box, worst = calls
    seen, complete = [], inference.complete
    monkeypatch.setattr(inference, "complete", lambda req, extra: (seen.append(list(st["runs"]["x/A"].get("in_flight", []))), complete(req, extra))[1])
    owner.run("r", "x/A", parallel=1, max_spend=1.0)
    assert seen[0] == [{"i": 0, "attempt": 0}] and all(len(x) == 1 for x in seen)   # on record while in flight
    assert "in_flight" not in st["runs"]["x/A"] and st["runs"]["x/A"]["attempt_log"] == []   # a finished run leaves nothing behind
    st["runs"]["x/A"]["in_flight"] = [{"i": 3, "attempt": 0}]
    assert cost.spent(st, PRICE) > worst                                               # an unresolved call counts at its bound


def test_settlement_counts_the_actual_cost_even_above_what_was_held():
    # from a reviewer (Nov 11): settle() recorded min(actual, reserved)
    b = cost.Budget(Decimal("1"), Decimal("0"))
    assert b.reserve(Decimal("0.4"))
    b.settle(Decimal("0.4"), Decimal("0.8"))
    assert b.spent == Decimal("0.8") and b.held == 0
    assert not b.reserve(Decimal("0.3")) and b.reserve(Decimal("0.2"))      # later calls stop where the true spend says


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
