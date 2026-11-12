"""The secret gist of a TEE round is deleted on a gh with `gist delete --yes` and on an older one without it.

Reported, with this fix, by a pilot user (zkasuran, pull request #2): on gh 2.45.0 the flag is unknown, so every
`tee-score` left its ciphertext gist on the owner's account."""
import json
import subprocess

from fuin import tee


def _gh(knows_yes: bool, fails: bool = False):
    """A stand-in for `gh` that records its calls. Returns (run, calls)."""
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[:3] == ["gh", "gist", "create"]:
            return subprocess.CompletedProcess(cmd, 0, "https://gist.github.com/someone/abc123\n", "")
        if cmd[:2] == ["gh", "api"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"files": {"x.b64": {"raw_url": "https://raw/x"}}}), "")
        assert cmd[:3] == ["gh", "gist", "delete"] and kw.get("stdin") == subprocess.DEVNULL   # a prompt must fail, not hang
        if fails:
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404")
        if "--yes" in cmd and not knows_yes:
            return subprocess.CompletedProcess(cmd, 1, "", "unknown flag: --yes\n\nUsage:  gh gist delete {<id> | <url>} [flags]")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    return run, calls


def _deletes(monkeypatch, capsys, **gh):
    run, calls = _gh(**gh)
    monkeypatch.setattr(tee.subprocess, "run", run)
    url, encoding, delete = tee.gist_host(b"ciphertext")
    assert (url, encoding) == ("https://raw/x", "base64")
    delete()
    return [c[3:] for c in calls if c[:3] == ["gh", "gist", "delete"]], capsys.readouterr().out


def test_a_current_gh_deletes_once_with_yes(monkeypatch, capsys):
    assert _deletes(monkeypatch, capsys, knows_yes=True) == ([["abc123", "--yes"]], "")


def test_an_older_gh_without_the_flag_is_retried_without_it(monkeypatch, capsys):
    assert _deletes(monkeypatch, capsys, knows_yes=False) == ([["abc123", "--yes"], ["abc123"]], "")


def test_a_real_failure_is_not_retried_and_is_never_silent(monkeypatch, capsys):
    tried, out = _deletes(monkeypatch, capsys, knows_yes=True, fails=True)
    assert tried == [["abc123", "--yes"]] and "abc123 was not deleted (HTTP 404)" in out and "--yes" not in out
