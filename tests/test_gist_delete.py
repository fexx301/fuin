"""gist_host deletes its secret gist on gh versions with and without `gist delete --yes` (gh 2.45.0 has no such flag)."""
import json
import subprocess

from fuin import tee


class FakeGh:
    """Stands in for `gh`: records every call; `delete_flags_ok` says which `gist delete` flags this gh version knows."""
    def __init__(self, delete_flags_ok, delete_fails=False):
        self.calls, self.ok, self.fails = [], delete_flags_ok, delete_fails

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:3] == ["gh", "gist", "create"]:
            return subprocess.CompletedProcess(cmd, 0, "https://gist.github.com/someone/abc123\n", "")
        if cmd[:2] == ["gh", "api"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"files": {"x.b64": {"raw_url": "https://raw/x"}}}), "")
        if cmd[:3] == ["gh", "gist", "delete"]:
            assert kw.get("stdin") == subprocess.DEVNULL  # a prompt must fail, not hang
            if self.fails:
                return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404")
            if "--yes" in cmd and "--yes" not in self.ok:
                return subprocess.CompletedProcess(cmd, 1, "", "unknown flag: --yes\n\nUsage: gh gist delete")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    def deletes(self):
        return [c for c in self.calls if c[:3] == ["gh", "gist", "delete"]]


def _run(monkeypatch, gh):
    monkeypatch.setattr(tee.subprocess, "run", gh)
    url, enc, delete = tee.gist_host(b"ciphertext")
    assert (url, enc) == ("https://raw/x", "base64")
    delete()


def test_gh_with_yes_flag_deletes_once(monkeypatch, capsys):
    gh = FakeGh(delete_flags_ok={"--yes"})
    _run(monkeypatch, gh)
    assert gh.deletes() == [["gh", "gist", "delete", "abc123", "--yes"]]
    assert "warning" not in capsys.readouterr().out


def test_gh_without_yes_flag_retries_without_it(monkeypatch, capsys):
    gh = FakeGh(delete_flags_ok=set())
    _run(monkeypatch, gh)
    assert gh.deletes() == [["gh", "gist", "delete", "abc123", "--yes"], ["gh", "gist", "delete", "abc123"]]
    assert "warning" not in capsys.readouterr().out


def test_a_real_delete_failure_is_not_retried_and_still_warns(monkeypatch, capsys):
    gh = FakeGh(delete_flags_ok={"--yes"}, delete_fails=True)
    _run(monkeypatch, gh)
    assert len(gh.deletes()) == 1
    out = capsys.readouterr().out
    assert "abc123 was not deleted" in out and "HTTP 404" in out
