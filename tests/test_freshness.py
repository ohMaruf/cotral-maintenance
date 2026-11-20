import subprocess
from pathlib import Path

import pytest

from cotral_maintenance import freshness
from cotral_maintenance.freshness import StaleCheckoutError, check_up_to_date


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
                           "-c", "protocol.file.allow=always", *args],
                          cwd=cwd, capture_output=True, text=True, check=True).stdout


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "commit", "-qm", name)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    git(tmp_path, "init", "-q", "--bare", "origin.git")
    git(tmp_path, "clone", "-q", "origin.git", "other")
    other = tmp_path / "other"
    commit(other, "a")
    git(other, "push", "-q", "origin", "HEAD:main")
    git(tmp_path, "clone", "-q", "origin.git", "here")
    here = tmp_path / "here"
    monkeypatch.setattr(freshness, "REPO", here)
    return other, here


def test_up_to_date(repos):
    check_up_to_date()


def test_behind_refuses(repos):
    other, _ = repos
    commit(other, "b")
    git(other, "push", "-q", "origin", "HEAD:main")
    with pytest.raises(StaleCheckoutError, match="1 commit\\(s\\) behind"):
        check_up_to_date()


def test_diverged_refuses(repos):
    other, here = repos
    commit(other, "b")
    git(other, "push", "-q", "origin", "HEAD:main")
    commit(here, "c")
    with pytest.raises(StaleCheckoutError, match="diverged"):
        check_up_to_date()


def test_ahead_runs(repos, caplog):
    _, here = repos
    commit(here, "c")
    check_up_to_date()
    assert "ahead" in caplog.text


def test_unreachable_remote_only_warns(repos, caplog):
    _, here = repos
    git(here, "remote", "set-url", "origin", str(here.parent / "gone.git"))
    check_up_to_date()
    assert "cannot fetch" in caplog.text


def test_not_a_checkout_only_warns(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(freshness, "REPO", tmp_path)
    check_up_to_date()
    assert "not a git checkout" in caplog.text


def test_submodule_off_pin_refuses(repos, tmp_path):
    other, here = repos
    git(tmp_path, "init", "-q", "data")
    commit(tmp_path / "data", "d1")
    git(here, "submodule", "add", "-q", str(tmp_path / "data"), "inputs")
    git(here, "commit", "-qm", "inputs")
    git(here, "push", "-q", "origin", "HEAD:main")
    check_up_to_date()
    commit(here / "inputs", "d2")
    with pytest.raises(StaleCheckoutError, match="submodule inputs"):
        check_up_to_date()
