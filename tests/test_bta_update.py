"""bta_update.py against throwaway local repositories (no network)."""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bta_update  # noqa: E402


def run(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def commit(repo, path, text, message):
    full = os.path.join(repo, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)
    run(repo, "add", path)
    run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    origin = str(tmp_path / "origin")
    os.makedirs(origin)
    run(origin, "init", "-q", "-b", "main")
    commit(origin, "README.md", "one\n", "First")
    user = str(tmp_path / "user")
    run(str(tmp_path), "clone", "-q", origin, user)
    monkeypatch.setattr(bta_update, "REPO_URL", origin)
    return origin, user


def test_up_to_date(repos):
    _, user = repos
    s = bta_update.scan(user)
    assert s["kind"] == "checkout" and s["behind"] == 0 and not s["error"]


def test_behind_lists_commits_and_steps(repos):
    origin, user = repos
    commit(origin, "runtime/a.cpp", "x\n", "Runtime fixes")
    commit(origin, "tools/rdna2spirv.py", "y\n", "Shader fixes")
    commit(origin, "docs/b.md", "z\n", "Docs")
    s = bta_update.scan(user)
    assert s["behind"] == 3 and [c[2] for c in s["new_commits"]] == ["Docs", "Shader fixes", "Runtime fixes"]
    assert s["steps"] == ["shaders", "runtime"]
    ok, msg = bta_update.update(user)
    assert ok, msg
    assert bta_update.scan(user, do_fetch=False)["behind"] == 0
    assert os.path.isfile(os.path.join(user, "runtime", "a.cpp"))


def test_docs_only_needs_no_rebuild(repos):
    origin, user = repos
    commit(origin, "docs/b.md", "z\n", "Docs")
    assert bta_update.scan(user)["steps"] == []


def test_local_changes_refused_then_kept(repos):
    origin, user = repos
    commit(origin, "runtime/a.cpp", "x\n", "Runtime fixes")
    with open(os.path.join(user, "README.md"), "w", encoding="utf-8") as f:
        f.write("mine\n")
    s = bta_update.scan(user)
    assert s["local"] == ["README.md"]
    ok, _ = bta_update.update(user)
    assert not ok
    ok, msg = bta_update.update(user, keep_local=True)
    assert ok and "put back" in msg
    assert open(os.path.join(user, "README.md"), encoding="utf-8").read() == "mine\n"


def test_own_commits_never_lost(repos):
    origin, user = repos
    commit(origin, "runtime/a.cpp", "x\n", "Runtime fixes")
    commit(user, "mine.txt", "m\n", "Mine")
    s = bta_update.scan(user)
    assert s["ahead"] == 1 and s["behind"] == 1
    head = bta_update.commit_info(user)["hash"]
    ok, _ = bta_update.update(user)
    assert not ok and bta_update.commit_info(user)["hash"] == head


def test_rebuild_after_build_recorded(repos):
    origin, user = repos
    built = bta_update.commit_info(user)["hash"]
    commit(origin, "runtime/a.cpp", "x\n", "Runtime fixes")
    bta_update.scan(user)
    bta_update.update(user)
    s = bta_update.scan(user, built={"runtime": built, "shaders": built}, do_fetch=False)
    assert s["rebuild"] == ["runtime"]


def test_not_a_checkout(tmp_path):
    assert bta_update.scan(str(tmp_path), do_fetch=False)["kind"] == "no-checkout"
