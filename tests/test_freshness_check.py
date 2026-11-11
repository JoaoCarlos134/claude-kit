"""Tests for plugins/joao-kit/hooks/freshness_check.py with a local bare repo as the remote."""

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).parents[1] / "plugins" / "joao-kit" / "hooks" / "freshness_check.py"


def g(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def run_hook(cwd, source="startup"):
    out = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps({"cwd": str(cwd), "source": source}),
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout) if out.stdout.strip() else None


def clone_pair(tmp_path):
    """A bare 'GitHub', a clone we work in, and a second clone that pushes from elsewhere."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    clones = []
    for name in ("here", "elsewhere"):
        c = tmp_path / name
        subprocess.run(["git", "clone", "-q", str(remote), str(c)], check=True, capture_output=True)
        g(c, "config", "user.email", "t@users.noreply.github.com")
        g(c, "config", "user.name", "T")
        clones.append(c)
    here, elsewhere = clones
    g(here, "commit", "-q", "--allow-empty", "-m", "first")
    g(here, "push", "-q", "-u", "origin", "main")
    g(elsewhere, "pull", "-q", "origin", "main")
    g(elsewhere, "branch", "-q", "-u", "origin/main")
    return here, elsewhere


def test_in_sync_is_silent(tmp_path):
    here, _ = clone_pair(tmp_path)
    assert run_hook(here) is None


def test_behind_is_reported_after_fetch(tmp_path):
    here, elsewhere = clone_pair(tmp_path)
    g(elsewhere, "commit", "-q", "--allow-empty", "-m", "made on the other machine")
    g(elsewhere, "push", "-q")
    out = run_hook(here)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "1 commit(s) BEHIND origin/main" in ctx
    assert "here" in out["systemMessage"]


def test_ahead_and_diverged(tmp_path):
    here, elsewhere = clone_pair(tmp_path)
    g(here, "commit", "-q", "--allow-empty", "-m", "local only")
    assert "not pushed" in run_hook(here)["systemMessage"]
    g(elsewhere, "commit", "-q", "--allow-empty", "-m", "remote only")
    g(elsewhere, "push", "-q")
    assert "DIVERGED" in run_hook(here)["systemMessage"]


def test_folder_of_repos_checks_each_child(tmp_path):
    here, elsewhere = clone_pair(tmp_path)
    g(elsewhere, "commit", "-q", "--allow-empty", "-m", "x")
    g(elsewhere, "push", "-q")
    msg = run_hook(tmp_path)["systemMessage"]
    assert "here: 1 commit(s) BEHIND" in msg
    assert "elsewhere" not in msg  # in sync


def test_no_upstream_and_local_only(tmp_path):
    here, _ = clone_pair(tmp_path)
    g(here, "checkout", "-q", "-b", "feature")
    assert "no upstream" in run_hook(here)["systemMessage"]
    local = tmp_path / "local"
    subprocess.run(["git", "init", "-q", str(local)], check=True)
    assert run_hook(local) is None


def test_unmerged_branches_are_listed_local_and_github(tmp_path):
    here, elsewhere = clone_pair(tmp_path)
    g(here, "checkout", "-q", "-b", "mine")
    g(here, "commit", "-q", "--allow-empty", "-m", "local work")
    g(here, "checkout", "-q", "main")
    g(elsewhere, "checkout", "-q", "-b", "theirs")
    g(elsewhere, "commit", "-q", "--allow-empty", "-m", "pushed from the other machine")
    g(elsewhere, "push", "-q", "origin", "theirs")
    g(here, "checkout", "-q", "-b", "merged-feature")
    g(here, "commit", "-q", "--allow-empty", "-m", "finished")
    g(here, "checkout", "-q", "main")
    g(here, "merge", "-q", "--ff-only", "merged-feature")
    g(here, "push", "-q")
    out = run_hook(here)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "here: 2 branch(es) with work not on main" in ctx
    assert "mine (1 commit(s), local" in ctx
    assert "theirs (1 commit(s), GitHub" in ctx
    assert "merged-feature" not in ctx  # merged into main
    assert "Unmerged branches: here: 2 branch(es)" in out["systemMessage"]


def test_skips_after_clear_and_outside_repos(tmp_path):
    here, elsewhere = clone_pair(tmp_path)
    g(elsewhere, "commit", "-q", "--allow-empty", "-m", "x")
    g(elsewhere, "push", "-q")
    assert run_hook(here, source="clear") is None
    empty = tmp_path / "empty"
    empty.mkdir()
    assert run_hook(empty) is None
