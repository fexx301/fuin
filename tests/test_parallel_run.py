"""fuin run --parallel: rows saved in index order despite out-of-order completion; failures keep earlier rows; resumable."""
import json
import random
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

    def complete(req):
        q = json.loads(req)["messages"][0]["content"]; i = int(q[1:q.index("?")])
        time.sleep(random.random() * 0.02)  # finish out of order
        if i in state["flaky"]:
            state["flaky"].discard(i); raise requests.ConnectionError("blip")
        if i == state["fail_at"]:
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
    assert [r["i"] for r in rn["rows"]] == [0, 1, 2, 3]       # first group saved; the failing group isn't
    assert any(e["i"] == 1 for e in rn["attempt_log"]) and sum(e["i"] == 6 for e in rn["attempt_log"]) == 3
    fake["fail_at"] = None
    owner.run("t", "m", parallel=4)                            # resume
    assert [r["i"] for r in owner.load("t")["runs"]["m"]["rows"]] == list(range(10))
