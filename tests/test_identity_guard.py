"""Tests for plugins/joao-kit/hooks/identity_guard.py, against real temporary git repos.

Run: python -m pytest tests -q
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).parents[1] / "plugins" / "joao-kit" / "hooks" / "identity_guard.py"
NOREPLY = "93523542+JoaoCarlos134@users.noreply.github.com"
WORK = "someone@employer.example"


def run_guard(command, cwd, **env):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    full_env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_KIT_")}
    full_env.update(env)
    out = subprocess.run(
        [sys.executable, str(GUARD)], input=json.dumps(payload),
        capture_output=True, text=True, env=full_env,
    )
    return out.returncode, out.stderr


def make_repo(path, email, remote=None):
    path.mkdir(parents=True, exist_ok=True)
    g = lambda *a: subprocess.run(["git", "-C", str(path), *a], check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    g("config", "user.name", "Test")
    g("config", "user.email", email)
    if remote:
        g("remote", "add", "origin", remote)
    return g


@pytest.mark.parametrize("remote", [
    "https://github.com/JoaoCarlos134/x.git",
    "git@github.com:JoaoCarlos134/x.git",
    None,
])
def test_personal_repo_with_work_email_blocks_commit(tmp_path, remote):
    make_repo(tmp_path / "r", WORK, remote)
    code, err = run_guard('git commit -m "x"', tmp_path / "r")
    assert code == 2
    assert WORK in err


def test_personal_repo_with_noreply_passes(tmp_path):
    make_repo(tmp_path / "r", NOREPLY, "https://github.com/JoaoCarlos134/x.git")
    assert run_guard('git commit -m "x"', tmp_path / "r")[0] == 0


@pytest.mark.parametrize("remote", [
    "https://github.com/some-employer/x.git",
    "https://gitlab.employer.example/team/x.git",
    "https://dev.azure.com/employer/proj/_git/x",
])
def test_repo_owned_by_someone_else_is_left_alone(tmp_path, remote):
    make_repo(tmp_path / "r", WORK, remote)
    assert run_guard('git commit -m "x"', tmp_path / "r")[0] == 0


def test_mixed_remotes_are_not_treated_as_personal(tmp_path):
    g = make_repo(tmp_path / "r", WORK, "https://github.com/JoaoCarlos134/x.git")
    g("remote", "add", "work", "https://github.com/some-employer/x.git")
    assert run_guard('git commit -m "x"', tmp_path / "r")[0] == 0


def test_extra_personal_email_from_env(tmp_path):
    make_repo(tmp_path / "r", "me@gmail.example", "https://github.com/JoaoCarlos134/x.git")
    assert run_guard("git commit -m x", tmp_path / "r")[0] == 2
    code, _ = run_guard("git commit -m x", tmp_path / "r", CLAUDE_KIT_PERSONAL_EMAILS="me@gmail.example")
    assert code == 0


def test_push_blocks_unpushed_commit_with_work_email(tmp_path):
    g = make_repo(tmp_path / "r", WORK, "https://github.com/JoaoCarlos134/x.git")
    g("commit", "-q", "--allow-empty", "-m", "made at work")
    g("config", "user.email", NOREPLY)  # identity fixed later, but the commit still carries WORK
    code, err = run_guard("git push origin main", tmp_path / "r")
    assert code == 2
    assert "unpushed commit" in err


def test_git_dash_c_and_leading_cd_target_the_named_repo(tmp_path):
    make_repo(tmp_path / "bad", WORK, "https://github.com/JoaoCarlos134/x.git")
    make_repo(tmp_path / "good", NOREPLY, "https://github.com/JoaoCarlos134/y.git")
    assert run_guard(f'git -C "{tmp_path / "bad"}" commit -m x', tmp_path / "good")[0] == 2
    assert run_guard(f'cd "{tmp_path / "bad"}" && git commit -m x', tmp_path / "good")[0] == 2


@pytest.mark.parametrize("command", ["git status", "git log --oneline", "ls", "git commit-tree --help"])
def test_other_commands_pass(tmp_path, command):
    make_repo(tmp_path / "r", WORK, "https://github.com/JoaoCarlos134/x.git")
    code, _ = run_guard(command, tmp_path / "r")
    assert code == 0


def test_outside_a_repo_passes(tmp_path):
    assert run_guard("git commit -m x", tmp_path)[0] == 0
