"""fuin run --parallel: rows saved in index order despite out-of-order completion; failures keep earlier rows; resumable."""
import json
import random
import threading
import time

import pytest
import requests

from fuin import inference, owner
from fuin import policy as P


def make_state(tmp_path, n):
    items = [{"item": {"question": f"q{i}? Answer with the number only.", "answer": str(i), "answer_type": "numeric", "request_nonce": "ab" * 32}, "salt": "cd" * 32} for i in range(n)]
    st = {"benchmark_id": "t", "owner": "o.testnet", "items": items, "policy": P.make_policy(n, {"m": {"max_tokens": 64, "temperature": 0}}),
          "runs": {"m": {"preflight_nonce": "00" * 32, "model_report": {}, "signer": "0xabc", "rows": [], "attempt_log": []}}}
    owner.save(st)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    state = {"fail_at": None, "flaky": set()}
    asked, cv = set(), threading.Condition()

    def complete(req, extra=None):
        q = json.loads(req)["messages"][0]["content"]; i = int(q[1:q.index("?")])
        with cv:
            asked.add(i); cv.notify_all()
        time.sleep(random.random() * 0.02)  # finish out of order
        if i in state["flaky"]:
            state["flaky"].discard(i); raise requests.ConnectionError("blip")
        if i == state["fail_at"]:
            with cv:  # fail only once the next item is in flight; otherwise the test raced the rolling window (about 1 run in 12)
                cv.wait_for(lambda: i + 1 in asked, timeout=5)
            raise requests.ConnectionError("down")
        body = json.dumps({"id": f"c{i}", "choices": [{"finish_reason": "stop", "message": {"content": str(i)}}]}).encode()
        return body, json.loads(body)

    monkeypatch.setattr(inference, "complete", complete)
    monkeypatch.setattr(inference, "fetch_signature", lambda cid, m: {"text": cid})
    monkeypatch.setattr(inference, "check_signature", lambda *a: None)
    return state


def test_parallel_rows_in_order_and_scored(fake, tmp_path):
    make_state(tmp_path, 23)
    owner.run("t", "m", parallel=4)
    rows = owner.load("t")["runs"]["m"]["rows"]
    assert [r["i"] for r in rows] == list(range(23)) and all(r["score"] == 1 for r in rows)


def test_failure_keeps_earlier_groups_logs_retries_and_resumes(fake, tmp_path):
    make_state(tmp_path, 10)
    fake["flaky"] = {1}          # one transient error: retried and logged, not fatal
    fake["fail_at"] = 6          # item 6 fails three times: run stops
    with pytest.raises(SystemExit):
        owner.run("t", "m", parallel=4)
    rn = owner.load("t")["runs"]["m"]
    assert [r["i"] for r in rn["rows"]] == [0, 1, 2, 3, 4, 5]  # every row before the failing item is kept, in order
    assert any(e["i"] == 1 for e in rn["attempt_log"]) and sum(e["i"] == 6 for e in rn["attempt_log"]) == 3
    assert "7" in rn["pending"] and not any(e["attempt"] == "discarded" for e in rn["attempt_log"])  # item 7 finished: kept
    fake["fail_at"] = None
    asked = []
    base = inference.complete
    inference.complete = lambda req, extra=None: (asked.append(json.loads(req)["messages"][0]["content"][:3]), base(req))[1]
    owner.run("t", "m", parallel=4)                            # resume
    rn = owner.load("t")["runs"]["m"]
    assert [r["i"] for r in rn["rows"]] == list(range(10)) and "pending" not in rn
    assert "q7?" not in asked and "q6?" in asked  # the kept answer is used as is; only unanswered items are asked


def test_a_second_command_on_the_same_round_stops_instead_of_losing_runs(tmp_path, monkeypatch):
    # four parallel `fuin run`s on one round erased two models' runs (each rewrote state.json); now the second one stops
    monkeypatch.chdir(tmp_path)
    held = owner.lock("t")
    with pytest.raises(SystemExit, match="another fuin command is writing round t"):
        owner.lock("t")
    held.close()
    owner.lock("t").close()  # free again once the first command ends


def test_one_slow_item_does_not_stall_the_window(fake, monkeypatch, tmp_path):
    make_state(tmp_path, 12)
    base = inference.complete

    def slow_first(req, extra=None):
        if json.loads(req)["messages"][0]["content"].startswith("q0?"):
            time.sleep(0.6)  # item 0 reasons for a long time
        return base(req)

    monkeypatch.setattr(inference, "complete", slow_first)
    t = time.time()
    owner.run("t", "m", parallel=4)
    assert time.time() - t < 1.0  # batch-and-wait would take ≥0.6 s per batch containing a slow item; rolling overlaps it
    assert [r["i"] for r in owner.load("t")["runs"]["m"]["rows"]] == list(range(12))
