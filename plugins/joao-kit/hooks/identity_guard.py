"""PreToolUse guard: personal repos only ever get the personal git identity.

Blocks a `git commit` or `git push` that Claude runs in a personal repository when
the identity involved is not a personal one. It is an allowlist, not a blocklist:
no employer's domain is named anywhere, so it keeps working after a job change.

Personal repository  = every remote points at one of PERSONAL_GITHUB_USERS on
                       github.com, or the repo has no remote yet.
Personal identity    = an address ending in @users.noreply.github.com, or one listed
                       in the env var CLAUDE_KIT_PERSONAL_EMAILS (comma separated).

Repos owned by anyone else (an employer's GitHub org, GitLab, Azure DevOps...) are
left alone, so work commits keep working with the work identity.

Override the account list with CLAUDE_KIT_GITHUB_USERS (comma separated).
Exit code 2 blocks the tool call and shows stderr to Claude.
"""

import json
import os
import re
import shlex
import subprocess
import sys

PERSONAL_GITHUB_USERS = ["JoaoCarlos134"]
NOREPLY_SUFFIX = "@users.noreply.github.com"
GIT_ACTION = re.compile(r"\bgit\b(?:\s+-C\s+(?:\"[^\"]*\"|'[^']*'|\S+))?\s+(commit|push)(?![\w-])")


def git(repo, *args):
    out = subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8"
    )
    return out.stdout.strip() if out.returncode == 0 else None


def target_dir(command, cwd):
    """Repo the command acts on: `git -C <dir>`, a leading `cd <dir>`, or cwd."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for i, tok in enumerate(tokens[:-1]):
        if tok == "git" and tokens[i + 1] == "-C" and i + 2 < len(tokens):
            return os.path.join(cwd, tokens[i + 2])
    if len(tokens) >= 2 and tokens[0] in ("cd", "Set-Location", "pushd"):
        return os.path.join(cwd, tokens[1].rstrip(";&"))
    return cwd


def personal_users():
    env = os.environ.get("CLAUDE_KIT_GITHUB_USERS")
    users = env.split(",") if env else PERSONAL_GITHUB_USERS
    return [u.strip().lower() for u in users if u.strip()]


def is_personal_repo(repo):
    lines = (git(repo, "remote", "-v") or "").splitlines()
    urls = {line.split()[1] for line in lines if len(line.split()) >= 2}
    if not urls:
        return True
    pattern = re.compile(r"github\.com[:/]+([^/]+)/", re.I)
    users = set(personal_users())
    for url in urls:
        m = pattern.search(url)
        if not m or m.group(1).lower() not in users:
            return False
    return True


def is_personal_email(email):
    extra = os.environ.get("CLAUDE_KIT_PERSONAL_EMAILS", "")
    allowed = {e.strip().lower() for e in extra.split(",") if e.strip()}
    email = (email or "").strip().lower()
    return email.endswith(NOREPLY_SUFFIX) or email in allowed


def problems(repo, action):
    found = []
    if action == "commit":
        email = git(repo, "config", "user.email")
        if not is_personal_email(email):
            found.append(f"git identity here is '{email or '<unset>'}', not a personal one")
    else:
        log = git(repo, "log", "--branches", "--not", "--remotes", "--format=%h %ae %ce")
        for line in (log or "").splitlines():
            sha, *emails = line.split()
            bad = [e for e in emails if not is_personal_email(e)]
            if bad:
                found.append(f"unpushed commit {sha} carries {', '.join(sorted(set(bad)))}")
    return found


def main():
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {}).get("command") or ""
    match = GIT_ACTION.search(command)
    if not match:
        return 0
    repo = target_dir(command, data.get("cwd") or os.getcwd())
    if git(repo, "rev-parse", "--git-dir") is None or not is_personal_repo(repo):
        return 0
    found = problems(repo, match.group(1))
    if not found:
        return 0
    print(
        "Blocked by joao-kit identity guard: this is a personal repository and "
        + "; ".join(found)
        + ".\nPersonal repos must only use the personal identity (GitHub noreply address). "
        "Fix with `git config user.email <noreply address>` in this repo (or the global "
        "includeIf rule from claude-kit/git/setup-identity.sh); for unpushed commits, "
        "rewrite them with `git commit --amend --reset-author` or git filter-repo. "
        "Ask the user before rewriting anything.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
