"""`fuin evaluate` runs a whole round by doing whatever `fuin status` names next, for all three kinds of round."""
import pytest
import requests

from fuin import cli, cost, owner, tooling
from fuin import policy as P

MODELS = ["x/A", "x/B"]


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A round whose commands only change state, the way the real ones do. Returns (state holder, commands run)."""
    box, ran, state_file = {}, [], tmp_path / "private" / "r" / "state.json"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(owner, "_path", lambda bid: state_file)
    monkeypatch.setattr(owner, "load", lambda bid: box["st"])
    monkeypatch.setattr(tooling, "print_check", lambda *a, **k: 0)
    monkeypatch.setattr(cost, "measured", lambda st: [])  # it reads NEAR AI's price list: no network in tests

    def certs(out):
        (tmp_path / out).mkdir(exist_ok=True)
        for m in MODELS:
            (tmp_path / out / f"cert-r-{m[-1].lower()}.json").write_text("{}")

    def dispatch(a):
        ran.append(a.cmd + (f" {a.model[-1]}" if a.cmd in ("run", "ask", "ask-check", "commit", "tee-score") else ""))
        if box.get("fail") == a.cmd:
            box.pop("fail")
            raise requests.ConnectionError("reset by peer")
        st = box.get("st")
        if a.cmd == "seal":
            mode = P.TEE_ASKED if a.ask else P.TEE_AUDIT if a.tee else None
            box["st"] = {"owner": a.owner, "items": [{}] * 2, "policy": {"audit": {"mode": mode, "k": 0 if mode else 1}, "request": {"template": "fuin-request-v1"},
                                    "models": {m: {"max_tokens": a.max_tokens, "temperature": 0} for m in a.model}},
                         "seal": {"height": 1, "tx": "s"}, "runs": {}}
            state_file.parent.mkdir(parents=True, exist_ok=True); state_file.write_text("{}")
        elif a.cmd == "run":
            st["runs"][a.model] = {"rows": [{}] * 2}
        elif a.cmd == "ask":
            st["runs"][a.model] = {"rows": [{}] * 2, "tee_asked": {"output": {}}, "tee_asked_check": {"output": {}}}
        elif a.cmd == "ask-check":
            st["runs"][a.model]["tee_asked_check"] = {"output": {}}
        elif a.cmd == "commit":
            st["runs"][a.model]["commit"] = {"run_index": 0, "total_score": 1, "tx": "t"}
        elif a.cmd == "close":
            st["close"] = {"height": 9, "tx": "c"}
        elif a.cmd == "tee-score":
            st["runs"][a.model]["tee_score"] = {"output": {}}
            if all(rn.get("tee_score") for rn in st["runs"].values()):
                certs(a.out)
        elif a.cmd == "reveal":
            certs(a.out)
        return 0

    monkeypatch.setattr(cli, "_dispatch", dispatch)
    return box, ran


ARGS = ["evaluate", "suite.jsonl", "--id", "r", "--owner", "a.testnet", "--model", "x/A", "--model", "x/B", "--yes"]


@pytest.mark.parametrize("flags, expect", [
    ([], "seal, run A, commit A, run B, commit B, close, reveal, verify"),
    (["--tee"], "seal, run A, commit A, run B, commit B, close, tee-score A, tee-score B, verify"),
    (["--ask"], "seal, ask A, commit A, ask B, commit B, close, reveal, verify"),
])
def test_each_kind_of_round_runs_from_nothing_to_verified(world, flags, expect):
    box, ran = world
    assert cli.main(ARGS + flags) == 0
    assert ", ".join(ran) == expect


def test_a_rerun_after_a_network_failure_resumes_and_repeats_nothing_finished(world, capsys):
    box, ran = world
    box["fail"] = "close"
    assert cli.main(ARGS + ["--tee"]) == 3
    assert "run the same command again" in capsys.readouterr().out and ran[-1] == "close"
    del ran[:]
    assert cli.main(ARGS + ["--tee"]) == 0
    assert ", ".join(ran) == "close, tee-score A, tee-score B, verify"   # no second seal, run or commit
    assert "a TEE-scored round sealed at height 1, not encrypted, token cap 4096" in capsys.readouterr().out   # what was sealed, said back


def test_half_finished_states_are_picked_up(world):
    box, ran = world
    cli.main(ARGS + ["--ask"])
    st = box["st"]
    # the aggregate was collected but the process died before the seal check (seen on Nov 11)
    st["runs"]["x/B"].pop("tee_asked_check"); st["runs"]["x/B"].pop("commit"); st.pop("close")
    del ran[:]
    assert cli.main(ARGS) == 0 and ", ".join(ran) == "ask-check B, commit B, close, verify"
    # closed, but the certificates were never written
    for f in (owner._path("r").parents[2] / "certs").glob("*.json"):
        f.unlink()
    del ran[:]
    assert cli.main(ARGS) == 0 and ", ".join(ran) == "reveal, verify"


def test_flags_that_disagree_with_the_seal_are_refused(world):
    box, ran = world
    cli.main(ARGS + ["--tee"])
    with pytest.raises(SystemExit, match="already sealed with a different kind of round"):
        cli.main(ARGS + ["--ask"])
    with pytest.raises(SystemExit, match="different models"):
        cli.main(ARGS[:6] + ["--model", "x/C", "--yes"])


def test_no_terminal_and_no_yes_seals_nothing(world, monkeypatch):
    box, ran = world
    monkeypatch.setattr("sys.stdin", type("S", (), {"isatty": lambda self: False})())
    with pytest.raises(SystemExit, match="add --yes"):
        cli.main(ARGS[:-1])
    assert ran == []


def test_the_host_and_parallel_flags_reach_the_steps(world, monkeypatch):
    box, ran = world
    seen = []
    inner = cli._dispatch
    monkeypatch.setattr(cli, "_dispatch", lambda a: (seen.append((a.cmd, getattr(a, "host", None), getattr(a, "parallel", None))), inner(a))[1])
    cli.main(ARGS + ["--tee", "--host", "fastfs", "--parallel", "4"])
    assert ("run", None, 4) in seen and ("tee-score", "fastfs", None) in seen


def test_the_spending_limit_reaches_run_and_ask_and_may_be_raised_on_a_rerun(world, monkeypatch):
    box, ran = world
    seen, inner = [], cli._dispatch
    monkeypatch.setattr(cli, "_dispatch", lambda a: (seen.append((a.cmd, getattr(a, "max_spend", None))), inner(a))[1])
    box["fail"] = "close"
    cli.main(ARGS + ["--max-spend", "0.5"])
    cli.main(ARGS + ["--max-spend", "2"])          # the limit isn't sealed: a higher one on the rerun is accepted
    assert ("run", 0.5) in seen and ("commit", None) in seen


def test_the_spending_limit_reaches_the_asks_of_an_asked_once_round(world, monkeypatch):
    box, ran = world
    seen, inner = [], cli._dispatch
    monkeypatch.setattr(cli, "_dispatch", lambda a: (seen.append((a.cmd, getattr(a, "max_spend", None))), inner(a))[1])
    cli.main(ARGS + ["--ask", "--max-spend", "1"])
    assert ("ask", 1.0) in seen


def test_check_flags_an_untested_model_and_a_cap_measured_too_long():
    msgs = tooling._ask_prerequisites(None, ["deepseek-ai/DeepSeek-V4.1-Flash-1017"], 4096)
    assert msgs[0][0] is True
    assert tooling._ask_prerequisites(None, ["deepseek-ai/DeepSeek-V4.1-Flash-1017"], 8192)[0][0] is False
    assert tooling._ask_prerequisites(None, ["Qwen/Qwen3.8-27B"], 4096)[0][0] is None   # a warning, never a pass
    assert tooling._ask_prerequisites(None, ["z-ai/glm-5.3-flash"], 4096)[0][0] is True     # finished round 8 at this cap
    assert tooling._ask_prerequisites(None, ["z-ai/glm-5.3-flash"], 8192)[0][0] is None     # never measured at 8,192: a warning, not a refusal
