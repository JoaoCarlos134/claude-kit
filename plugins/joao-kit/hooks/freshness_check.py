"""SessionStart hook: warn when the repo(s) in front of Claude are not in sync with their remote.

Fetches the upstream of the session's repo - or, when the session starts in a folder of
repos (like a projects folder), of each repo one level down - and reports any repo that is
behind, ahead, diverged or without an upstream. Silent when everything is in sync.

Never changes anything: `git fetch` only updates remote-tracking refs. Fetches run in
parallel with a timeout, and a failed fetch (offline, no auth) is reported, not fatal.
The report goes to Claude as context and, shortened, to the user as a system message.
"""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

FETCH_TIMEOUT = 15


def git(repo, *args, timeout=10):
    try:
        out = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True,
            encoding="utf-8", timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def is_repo(path):
    return os.path.isdir(os.path.join(path, ".git")) or os.path.isfile(os.path.join(path, ".git"))


def repos_for(cwd):
    top = git(cwd, "rev-parse", "--show-toplevel")
    if top:
        return [top]
    try:
        entries = sorted(os.scandir(cwd), key=lambda e: e.name.lower())
    except OSError:
        return []
    return [e.path for e in entries if e.is_dir() and is_repo(e.path)]


def check(repo):
    name = os.path.basename(repo.rstrip("/\\"))
    if not git(repo, "remote"):
        return None  # local-only repo: nothing to be behind
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    remote = upstream.split("/", 1)[0] if upstream else "origin"
    fetched = git(repo, "fetch", "--quiet", remote, timeout=FETCH_TIMEOUT) is not None
    if not upstream:
        return f"{name}: branch '{branch}' has no upstream (not linked to the remote)"
    counts = git(repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
    if not counts:
        return None
    ahead, behind = (int(x) for x in counts.split())
    note = "" if fetched else " (fetch failed - offline or no auth; numbers may be stale)"
    if ahead and behind:
        return f"{name}: DIVERGED from {upstream} - {ahead} local and {behind} remote commits{note}"
    if behind:
        return f"{name}: {behind} commit(s) BEHIND {upstream} - pull before working{note}"
    if ahead:
        return f"{name}: {ahead} commit(s) not pushed to {upstream}{note}"
    return f"{name}: fetch failed, could not confirm it is current" if not fetched else None


def main():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}
    if data.get("source") not in (None, "startup", "resume"):
        return 0  # skip after /clear and compaction: already checked this session
    repos = repos_for(data.get("cwd") or os.getcwd())
    if not repos:
        return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        lines = [r for r in pool.map(check, repos) if r]
    if not lines:
        return 0
    context = (
        "Repository freshness check (joao-kit). Local copies differ from GitHub:\n- "
        + "\n- ".join(lines)
        + "\nBefore relying on local files for a repo listed here, tell the user and offer to "
        "pull (never pull over uncommitted changes, never force anything without asking). "
        "Facts about these projects may be newer on GitHub than on disk."
    )
    print(json.dumps({
        "systemMessage": "Repos out of sync with GitHub: " + "; ".join(lines),
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context},
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
