"""Tests for branch_guard.py (Finish on main), with a local bare repo as GitHub."""

import subprocess

from conftest import run_hook


def g(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def setup(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    here = tmp_path / "here"
    subprocess.run(["git", "clone", "-q", str(remote), str(here)], check=True, capture_output=True)
    g(here, "config", "user.email", "t@users.noreply.github.com")
    g(here, "config", "user.name", "T")
    g(here, "commit", "-q", "--allow-empty", "-m", "first")
    g(here, "push", "-q", "-u", "origin", "main")
    return here


def hook(tmp_path, cwd, mode, session="s1", rule="all", **extra):
    payload = {"session_id": session, "cwd": str(cwd), **extra}
    env = {"CLAUDE_KIT_STATE_DIR": str(tmp_path / "state")}
    if rule:
        env["CLAUDE_KIT_BRANCH_RULE"] = rule  # the test remote is a local path, not my GitHub
    code, out, _ = run_hook("branch_guard.py", payload, mode, env=env)
    assert code == 0
    return out


def test_new_branch_with_commits_is_reported_once_per_state(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot")
    g(here, "checkout", "-q", "-b", "feature")
    g(here, "commit", "-q", "--allow-empty", "-m", "work")
    out = hook(tmp_path, here, "check")
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "'feature' has 1 commit(s) not on main (local only)" in ctx
    assert "merge it into main" in ctx
    assert hook(tmp_path, here, "check") is None  # same state: no second reminder
    g(here, "commit", "-q", "--allow-empty", "-m", "more work")
    g(here, "push", "-q", "-u", "origin", "feature")
    later = hook(tmp_path, here, "check")
    assert "2 commit(s) not on main (pushed)" in later["systemMessage"]
    assert "hookSpecificOutput" not in later  # only the first reminder per branch costs Claude a turn


def test_merged_branch_is_silent(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot")
    g(here, "checkout", "-q", "-b", "feature")
    g(here, "commit", "-q", "--allow-empty", "-m", "work")
    g(here, "push", "-q", "origin", "HEAD:main")  # merged the worktree way: fast-forward push to main
    assert hook(tmp_path, here, "check") is None


def test_old_untouched_branch_is_left_to_the_session_start_report(tmp_path):
    here = setup(tmp_path)
    g(here, "checkout", "-q", "-b", "old")
    g(here, "commit", "-q", "--allow-empty", "-m", "earlier session")
    g(here, "checkout", "-q", "main")
    hook(tmp_path, here, "snapshot")
    assert hook(tmp_path, here, "check") is None


def test_resume_keeps_the_first_snapshot(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot")
    g(here, "checkout", "-q", "-b", "feature")
    g(here, "commit", "-q", "--allow-empty", "-m", "work")
    hook(tmp_path, here, "snapshot", source="resume")
    assert "feature" in hook(tmp_path, here, "check")["systemMessage"]


def test_branch_of_another_worktree_belongs_to_that_session(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot", session="main-session")
    wt = tmp_path / "wt"
    g(here, "worktree", "add", "-q", "-b", "parallel", str(wt))
    hook(tmp_path, wt, "snapshot", session="wt-session")
    g(wt, "commit", "-q", "--allow-empty", "-m", "parallel work")
    assert hook(tmp_path, here, "check", session="main-session") is None
    assert "parallel" in hook(tmp_path, wt, "check", session="wt-session")["systemMessage"]


def test_without_snapshot_only_the_current_branch_counts(tmp_path):
    here = setup(tmp_path)
    g(here, "checkout", "-q", "-b", "other")
    g(here, "commit", "-q", "--allow-empty", "-m", "x")
    g(here, "checkout", "-q", "-b", "current")
    g(here, "commit", "-q", "--allow-empty", "-m", "y")
    msg = hook(tmp_path, here, "check", session="no-snapshot")["systemMessage"]
    assert "'current'" in msg and "'other'" not in msg


def test_quiet_while_continuing_or_waiting_on_background_work(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot")
    g(here, "checkout", "-q", "-b", "feature")
    g(here, "commit", "-q", "--allow-empty", "-m", "work")
    assert hook(tmp_path, here, "check", stop_hook_active=True) is None
    assert hook(tmp_path, here, "check", background_tasks=[{"id": "t1", "type": "shell"}]) is None
    assert hook(tmp_path, here, "check") is not None  # still reported once those are over


def test_removed_or_switched_worktree_branch_is_not_this_sessions(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot", session="main-session")
    for name in ("gone", "switched"):
        wt = tmp_path / name
        g(here, "worktree", "add", "-q", "-b", name, str(wt))
        g(wt, "commit", "-q", "--allow-empty", "-m", f"{name} work")
    g(here, "worktree", "remove", str(tmp_path / "gone"))
    g(tmp_path / "switched", "checkout", "-q", "--detach")
    assert hook(tmp_path, here, "check", session="main-session") is None


def test_repo_missing_from_snapshot_counts_only_its_checked_out_branch(tmp_path):
    here = setup(tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True)
    g(other, "config", "user.email", "t@users.noreply.github.com")
    g(other, "config", "user.name", "T")
    g(other, "commit", "-q", "--allow-empty", "-m", "first")
    g(other, "checkout", "-q", "-b", "old-work")
    g(other, "commit", "-q", "--allow-empty", "-m", "earlier")
    g(other, "checkout", "-q", "main")
    hook(tmp_path, here, "snapshot")  # session started in `here`; cwd later moves to `other`
    assert hook(tmp_path, other, "check") is None
    g(other, "checkout", "-q", "-b", "now")
    g(other, "commit", "-q", "--allow-empty", "-m", "this session")
    msg = hook(tmp_path, other, "check")["systemMessage"]
    assert "'now'" in msg and "old-work" not in msg


def test_only_my_repos_unless_told_otherwise(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot", rule=None)
    g(here, "checkout", "-q", "-b", "feature")
    g(here, "commit", "-q", "--allow-empty", "-m", "work")
    assert hook(tmp_path, here, "check", rule=None) is None  # remote is a local path: not my GitHub
    g(here, "remote", "set-url", "origin", "https://github.com/some-employer/x.git")
    assert hook(tmp_path, here, "check", rule=None) is None
    g(here, "remote", "set-url", "origin", "https://github.com/JoaoCarlos134/x.git")
    assert "feature" in hook(tmp_path, here, "check", rule=None)["systemMessage"]


def test_quiet_while_a_scheduled_wakeup_is_pending(tmp_path):
    here = setup(tmp_path)
    hook(tmp_path, here, "snapshot")
    g(here, "checkout", "-q", "-b", "feature")
    g(here, "commit", "-q", "--allow-empty", "-m", "work")
    crons = [{"id": "c1", "schedule": "0 9 * * *", "recurring": True, "prompt": "check"}]
    assert hook(tmp_path, here, "check", session_crons=crons) is None
