"""`fuin show` and `fuin status` handle all three kinds of round: sampled, TEE-scored and asked once."""
from pathlib import Path

import pytest

from fuin import cli, owner, tooling
from fuin import policy as P

EX = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("cert, expect", [
    ("cert-near-dev-60-r2-glm-5.3-flash.json", "revealed 23 of 60"),
    ("cert-near-dev-96-r6-glm-5.3-flash.json", "a TEE-scored round reveals nothing"),
    ("cert-near-dev-37-r7-deepseek-v4.1-flash-1017.json", "an asked-once round reveals nothing"),  # used to crash: KeyError scorer_wasm_sha256
])
def test_show_prints_each_kind_of_certificate(cert, expect, capsys):
    assert cli.main(["show", str(EX / cert)]) == 0
    assert expect in capsys.readouterr().out


def test_show_names_the_asker_and_its_counted_retry(capsys):
    cli.main(["show", str(EX / "cert-near-dev-37-r7-deepseek-v4.1-flash-1017.json")])
    out = capsys.readouterr().out
    assert "asker dbbb286b744c… in ask.fuin.testnet/asker" in out and "1 retried ask(s), counted" in out


def _status(tmp_path, monkeypatch, st):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(owner, "_path", lambda bid: tmp_path)
    monkeypatch.setattr(owner, "load", lambda bid: st)
    return tooling.status("r", "certs")


def _round(mode, **runs):
    return {"owner": "a.testnet", "items": [{}] * 2, "policy": {"audit": {"mode": mode, "k": 0 if mode else 1}, "models": ["x/A"]},
            "seal": {"height": 1, "tx": "s"}, "runs": runs}


def test_status_guides_a_sampled_round(tmp_path, monkeypatch):
    st = _round(None)
    out = _status(tmp_path, monkeypatch, st)
    assert "sampled round" in out[0] and out[-1] == "next: uv run --env-file .env fuin run --id r --model x/A"
    st["runs"]["x/A"] = {"rows": [{}] * 2}
    assert _status(tmp_path, monkeypatch, st)[-1] == "next: uv run --env-file .env fuin commit --id r --model x/A"
    st["runs"]["x/A"]["commit"] = {"run_index": 0, "total_score": 1, "tx": "t"}
    assert _status(tmp_path, monkeypatch, st)[-1].startswith("next: uv run --env-file .env fuin close --id r")
    st["close"] = {"height": 9, "tx": "c"}
    assert "waits for a finalized block" in _status(tmp_path, monkeypatch, st)[-1]


def test_status_guides_a_tee_scored_round(tmp_path, monkeypatch):
    st = _round(P.TEE_AUDIT)
    out = _status(tmp_path, monkeypatch, st)
    assert "TEE-scored" in out[0] and out[-1] == "next: uv run --env-file .env fuin run --id r --model x/A"
    st["runs"]["x/A"] = {"rows": [{}] * 2, "commit": {"run_index": 0, "total_score": 1, "tx": "t"}}
    st["close"] = {"height": 9, "tx": "c"}
    assert _status(tmp_path, monkeypatch, st)[-1] == "next: uv run --env-file .env fuin tee-score --id r --model x/A --host gist --out certs"


def test_status_guides_an_asked_once_round_with_fuin_ask_never_fuin_run(tmp_path, monkeypatch):
    st = _round(P.TEE_ASKED)
    out = _status(tmp_path, monkeypatch, st)
    assert "asked-once round" in out[0] and "not asked" in out[2]
    assert out[-1] == "next: uv run --env-file .env fuin ask --id r --model x/A --host gist"          # it used to say `fuin run`
    st["runs"]["x/A"] = {"rows": [{}], "attempt_log": [{}]}
    out = _status(tmp_path, monkeypatch, st)
    assert "never re-asked" in out[2] and out[-1] == "next: uv run --env-file .env fuin ask --id r --model x/A --host gist"
    st["runs"]["x/A"]["rows"] = [{}] * 2
    assert "collects the aggregate" in _status(tmp_path, monkeypatch, st)[-1]
    st["runs"]["x/A"]["tee_asked"] = {"output": {}}
    assert _status(tmp_path, monkeypatch, st)[-1] == "next: uv run fuin ask-check --id r --model x/A --host gist"
    st["runs"]["x/A"]["tee_asked_check"] = {"output": {}}
    assert _status(tmp_path, monkeypatch, st)[-1] == "next: uv run --env-file .env fuin commit --id r --model x/A"
    st["runs"]["x/A"]["commit"] = {"run_index": 0, "total_score": 1, "tx": "t"}
    out = _status(tmp_path, monkeypatch, st)
    assert "asked once in a TEE" in out[2] and "fuin close --id r" in out[-1]
    st["close"] = {"height": 9, "tx": "c"}
    out = _status(tmp_path, monkeypatch, st)
    assert "tee-score" not in out[-1] and "an asked-once round reveals nothing" in out[-1]
    assert not any("fuin run" in line for line in out)
