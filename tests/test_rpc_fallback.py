"""A throttled or retired endpoint answers with a JSON-RPC error; the client moves on to the other archival endpoint."""
from fuin import near


class R:
    def __init__(self, body, status=200):
        self.body, self.status_code, self.headers = body, status, {}

    def json(self):
        return self.body


def test_a_deprecation_answer_falls_through_to_the_other_endpoint(monkeypatch):
    seen = []

    def post(url, json, timeout):
        seen.append(url)
        if url == near.ARCHIVAL[0]:
            return R({"jsonrpc": "2.0", "error": {"code": -429, "message": "THIS ENDPOINT IS DEPRECATED!"}})
        return R({"jsonrpc": "2.0", "result": {"ok": 1}})
    monkeypatch.delenv("FUIN_TESTNET_RPC", raising=False)
    monkeypatch.setitem(near.NETWORKS, "testnet", near.ARCHIVAL[0])
    monkeypatch.setattr(near.requests, "post", post)
    monkeypatch.setattr(near.time, "sleep", lambda s: None)
    assert near.rpc("block", {"finality": "final"}) == {"ok": 1}
    assert seen == near.ARCHIVAL[:2]


def test_a_real_rpc_error_is_returned_not_retried(monkeypatch):
    calls = []
    monkeypatch.delenv("FUIN_TESTNET_RPC", raising=False)
    monkeypatch.setattr(near.requests, "post", lambda url, json, timeout: calls.append(url) or R({"error": {"name": "HANDLER_ERROR", "cause": {"name": "UNKNOWN_TRANSACTION"}}}))
    try:
        near.rpc("EXPERIMENTAL_tx_status", {"tx_hash": "x", "sender_account_id": "a.testnet"})
        raise AssertionError("expected RpcError")
    except near.RpcError:
        pass
    assert len(calls) == 1
