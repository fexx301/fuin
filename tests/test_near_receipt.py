"""near.tx_receipt reads the signed call arguments (offline: the RPC answer is a fixture)."""
def test_tx_receipt_returns_the_signed_call_arguments(monkeypatch):
    """The verifier compares a seal or commit's signed arguments with the certificate, not only the contract's state."""
    import base64 as _b64
    import json as _json
    from fuin import near
    args = {"benchmark_id": "b", "model_id": "m", "run_root": "ab" * 32, "total_score": 3}
    res = {"transaction": {"actions": [{"FunctionCall": {"method_name": "commit_run", "args": _b64.b64encode(_json.dumps(args).encode()).decode()}}]},
           "transaction_outcome": {"outcome": {"receipt_ids": ["r1"]}}, "receipts": [],
           "receipts_outcome": [{"id": "r1", "block_hash": "h", "outcome": {"executor_id": "registry.fuin.testnet", "status": {"SuccessValue": ""}}}]}
    monkeypatch.setattr(near, "rpc", lambda method, params, network="testnet": res if method == "EXPERIMENTAL_tx_status" else {"header": {"height": 7}})
    rc = near.tx_receipt("tx", "o.testnet", "registry.fuin.testnet", "commit_run")
    assert rc["args"] == args and rc["block_height"] == 7
