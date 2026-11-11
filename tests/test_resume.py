"""Interrupting seal, commit, close or an in-enclave ask at any point lets the same round finish: one seal, one run,
one close, the original salts and nonces, and no second ask of an item whose ask is still in flight."""
import json

import pytest

from fuin import asker, near, owner, tee
from fuin import policy as P

MODEL = "x/A"


class Crash(BaseException):
    """The process dying: not an Exception, so nothing in the code under test can catch it."""


class Chain:
    """A registry that executes each signed transaction at most once, like the real one."""

    def __init__(self):
        self.signed, self.executed, self.bench, self.crash, self.n = {}, {}, None, None, 0

    def _hit(self, point):
        if self.crash == point:
            self.crash = None
            raise Crash(point)

    def sign(self, signer, contract, method, args, *a, **k):
        self.n += 1
        tx = f"tx{self.n}"
        self.signed[f"sig{self.n}"] = (tx, method, json.loads(args))
        self._hit("after sign")
        return {"tx": tx, "signed_b64": f"sig{self.n}"}

    def send(self, signed_b64, network="testnet"):
        self._hit("before send")
        tx, method, a = self.signed[signed_b64]
        if tx not in self.executed:
            if method == "seal":
                assert self.bench is None, "sealed twice"
                self.bench = {"root": a["root"], "runs": [], "close_height": None}
                self.executed[tx] = ""
            elif method == "commit_run":
                self.bench["runs"].append({"model_id": a["model_id"], "run_index": len(self.bench["runs"]), "run_root": a["run_root"],
                                           "total_score": a["total_score"]})
                self.executed[tx] = str(len(self.bench["runs"]) - 1)
            else:
                assert not self.bench["close_height"], "closed twice"
                self.bench["close_height"] = 9
                self.executed[tx] = ""
        self._hit("after send")
        return tx

    def install(self, monkeypatch):
        monkeypatch.setattr(near, "sign", self.sign)
        monkeypatch.setattr(near, "send", self.send)
        monkeypatch.setattr(near, "known", lambda tx, sender, network="testnet": tx in self.executed)
        monkeypatch.setattr(near, "final_status", lambda tx, sender, *a, **k: {})
        monkeypatch.setattr(near, "view", lambda *a, **k: self.bench)

        def receipt(tx, sender, executor, method, network="testnet"):
            self._hit("before receipt saved")
            return {"block_height": 5, "block_hash": "h", "value": self.executed[tx], "receipt_id": "r", "args": None}
        monkeypatch.setattr(near, "tx_receipt", receipt)


POINTS = ["after sign", "before send", "after send", "before receipt saved"]


@pytest.fixture
def chain(tmp_path, monkeypatch):
    monkeypatch.setattr(owner, "PRIVATE", tmp_path / "private")
    (tmp_path / "suite.jsonl").write_text('{"question": "Q1? Answer with the number only.", "answer": "1", "answer_type": "numeric"}\n'
                                          '{"question": "Q2? Answer with the number only.", "answer": "2", "answer_type": "numeric"}\n')
    c = Chain()
    c.install(monkeypatch)
    c.suite = str(tmp_path / "suite.jsonl")
    return c


def _seal(c):
    return owner.seal(c.suite, "r", "a.testnet", {MODEL: {"max_tokens": 8, "temperature": 0}})


def _rows(st):
    st["runs"][MODEL] = {"rows": [{"i": i, "req_sha256": "11" * 32, "resp_sha256": "22" * 32, "score": i} for i in range(2)]}
    owner.save(st)


@pytest.mark.parametrize("point", POINTS)
def test_an_interrupted_seal_finishes_with_its_original_salts_and_nonces(chain, point):
    chain.crash = point
    with pytest.raises(Crash):
        _seal(chain)
    before = owner.load("r")["items"]
    st = _seal(chain)                                    # the same command again
    assert st["items"] == before and st["seal"]["root"] == chain.bench["root"]
    assert "seal" not in st.get("pending", {}) and sum(m == "seal" for _, m, _ in chain.signed.values()) <= 2
    with pytest.raises(SystemExit, match="already sealed"):
        _seal(chain)


@pytest.mark.parametrize("point", POINTS)
def test_an_interrupted_commit_never_publishes_a_second_run(chain, point):
    _rows(_seal(chain))
    chain.crash = point
    with pytest.raises(Crash):
        owner.commit("r", MODEL)
    st = owner.commit("r", MODEL)
    assert len(chain.bench["runs"]) == 1 and st["runs"][MODEL]["commit"]["run_index"] == 0
    with pytest.raises(SystemExit, match="already committed"):
        owner.commit("r", MODEL)
    assert len(chain.bench["runs"]) == 1


@pytest.mark.parametrize("point", POINTS)
def test_an_interrupted_close_finishes(chain, point):
    _rows(_seal(chain))
    owner.commit("r", MODEL)
    chain.crash = point
    with pytest.raises(Crash):
        owner.close("r")
    assert owner.close("r")["close"]["height"] == 5 and chain.bench["close_height"] == 9
    with pytest.raises(SystemExit, match="already closed"):
        owner.close("r")


def test_a_sent_transaction_is_reused_not_signed_again(chain):
    _rows(_seal(chain))
    chain.crash = "after send"
    with pytest.raises(Crash):
        owner.commit("r", MODEL)
    signed = chain.n
    owner.commit("r", MODEL)
    assert chain.n == signed                             # the rerun signed nothing new


def test_a_commit_the_registry_already_holds_is_not_sent_again(chain):
    # state from before pending transactions were saved: the run is on chain, the receipt was lost
    st = _seal(chain)
    _rows(st)
    owner.commit("r", MODEL)
    st = owner.load("r")
    del st["runs"][MODEL]["commit"]
    owner.save(st)
    with pytest.raises(SystemExit, match="already holds this"):
        owner.commit("r", MODEL)
    assert len(chain.bench["runs"]) == 1


def test_a_seal_with_a_different_suite_does_not_reuse_the_saved_one(chain, tmp_path):
    chain.crash = "before send"
    with pytest.raises(Crash):
        _seal(chain)
    (tmp_path / "other.jsonl").write_text('{"question": "Other? Answer with the number only.", "answer": "3", "answer_type": "numeric"}\n')
    with pytest.raises(SystemExit, match="different suite"):
        owner.seal(str(tmp_path / "other.jsonl"), "r", "a.testnet", {MODEL: {"max_tokens": 8, "temperature": 0}})


def _asked(monkeypatch, tmp_path):
    monkeypatch.setattr(owner, "PRIVATE", tmp_path / "private")
    st = {"benchmark_id": "r", "owner": "a.testnet", "items": [{}], "policy": {"audit": {"mode": P.TEE_ASKED}},
          "runs": {MODEL: {"rows": [], "attempt_log": [], "signer": "0xabc"}}}
    monkeypatch.setattr(asker, "_check_item", lambda out, st, model, i, signer: {"i": i, "score": out["score"], "attempts": out["a"]})
    return st


def test_an_ask_interrupted_in_flight_is_waited_for_not_asked_again(monkeypatch, tmp_path):
    st, sent = _asked(monkeypatch, tmp_path), []

    def sign_ask():
        sent.append(len(sent))
        return {"tx": f"ask{len(sent)}", "signed_b64": "s"}

    def dies(p, signer):
        raise Crash("the process died while the enclave was still asking")
    monkeypatch.setattr(tee, "outcome", dies)
    with pytest.raises(Crash):
        asker.ask_item(st, MODEL, 0, sign_ask)
    assert owner.load("r")["runs"][MODEL]["pending_ask"]["tx"] == "ask1"   # on disk before the enclave saw it
    waited = []
    monkeypatch.setattr(tee, "outcome", lambda p, signer: waited.append(p["tx"]) or {"score": 1, "a": 1})
    st = owner.load("r")
    row = asker.ask_item(st, MODEL, 0, sign_ask)
    assert sent == [0] and waited == ["ask1"] and row["ask_tx"] == "ask1"   # one ask signed in all
    assert "pending_ask" not in st["runs"][MODEL] and len(st["runs"][MODEL]["rows"]) == 1


def test_a_network_failure_keeps_the_ask_in_flight(monkeypatch, tmp_path):
    st = _asked(monkeypatch, tmp_path)

    def offline(p, signer):
        raise near.RpcError("HTTP 503")
    monkeypatch.setattr(tee, "outcome", offline)
    with pytest.raises(SystemExit, match="the ask in flight is kept"):
        asker.ask_item(st, MODEL, 0, lambda: {"tx": "ask1", "signed_b64": "s"})
    assert st["runs"][MODEL]["pending_ask"]["tx"] == "ask1" and st["runs"][MODEL]["attempt_log"] == []


def test_a_failed_ask_is_logged_and_the_next_attempt_is_a_new_ask(monkeypatch, tmp_path):
    st, n = _asked(monkeypatch, tmp_path), []

    def outcome(p, signer):
        if p["tx"] == "ask1":
            raise RuntimeError("OutLayer execution failed")
        return {"score": 0, "a": 2}
    monkeypatch.setattr(tee, "outcome", outcome)
    row = asker.ask_item(st, MODEL, 0, lambda: n.append(1) or {"tx": f"ask{len(n)}", "signed_b64": "s"})
    assert row["ask_tx"] == "ask2" and len(st["runs"][MODEL]["attempt_log"]) == 1
