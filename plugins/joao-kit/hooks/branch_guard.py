"""Finish on main: branches worked on in a session get merged into main before the session ends.

Two modes, one per hook event:

  branch_guard.py snapshot   SessionStart: record the time and every local branch tip of the repo(s)
                             in front of Claude, once per session (a resume keeps the first snapshot).
  branch_guard.py check      Stop: find branches this session worked on that still hold commits not
                             on main, and remind Claude to merge them and push main, or say why not.

"Worked on in this session" = the branch's tip moved since the snapshot AND that tip is in this
worktree's own HEAD reflog since the session started (each worktree has its own HEAD reflog). So
commits another session made from another worktree never count, even after that worktree is removed
or switches branch. A repo with no snapshot (session started elsewhere, repo cloned mid-session) is
judged only by the branch checked out in it.

Only in my own repositories (identity_guard.is_personal_repo: remotes on my GitHub accounts, or no
remote); repos that merge through pull requests elsewhere are left alone. Set
CLAUDE_KIT_BRANCH_RULE=all to apply it everywhere.

Claude Code has no "session is ending" moment Claude can act on (SessionEnd can't make Claude do
anything), so the check runs when a turn ends. Only the first reminder per branch makes Claude take
another step (it costs a full-context call); later ones for new commits are a one-line notice to the
user. Nothing fires while a stop hook is already continuing the turn, or while background work or a
scheduled wake-up will resume the session.
"""

import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from freshness_check import default_branch, git, not_on_main, repos_for  # noqa: E402
from identity_guard import is_personal_repo  # noqa: E402

STATE_MAX_AGE_DAYS = 14
CLOCK_SLACK = 2  # seconds: reflog times are whole seconds


def state_dir():
    return os.environ.get("CLAUDE_KIT_STATE_DIR") or os.path.join(tempfile.gettempdir(), "joao-kit")


def state_path(session_id):
    safe = re.sub(r"[^\w-]", "_", session_id or "unknown")
    return os.path.join(state_dir(), "branches-" + safe + ".json")


def load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, state):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def tips(repo):
    out = git(repo, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
    return dict(line.split(" ", 1) for line in (out or "").splitlines() if " " in line)


def norm(path):
    return os.path.normcase(os.path.realpath(path))


def applies(repo):
    return os.environ.get("CLAUDE_KIT_BRANCH_RULE", "").lower() == "all" or is_personal_repo(repo)


def checked_out_elsewhere(repo):
    """Branches checked out in the repo's other worktrees - other sessions' work."""
    here = norm(git(repo, "rev-parse", "--show-toplevel") or repo)
    others, path = set(), None
    for line in (git(repo, "worktree", "list", "--porcelain") or "").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/") and path and norm(path) != here:
            others.add(line[len("branch refs/heads/"):])
    return others


def head_shas_since(repo, since):
    """Commits HEAD pointed at in this worktree since `since` (unix time), or None without a reflog."""
    out = git(repo, "reflog", "show", "--format=%H %gd", "--date=unix", "HEAD")
    if out is None:
        return None
    shas = set()
    for line in out.splitlines():
        m = re.match(r"([0-9a-f]{7,64}) HEAD@\{(\d+)\}", line)
        if m and int(m.group(2)) >= since - CLOCK_SLACK:
            shas.add(m.group(1))
    return shas


def cleanup():
    cutoff = time.time() - STATE_MAX_AGE_DAYS * 86400
    try:
        for entry in os.scandir(state_dir()):
            if entry.name.endswith(".json") and entry.stat().st_mtime < cutoff:
                os.remove(entry.path)
    except OSError:
        pass


def snapshot(data):
    path = state_path(data.get("session_id"))
    state = load(path)
    if "tips" in state:
        return 0  # resumed session: branches made earlier in it still count as this session's
    cwd = data.get("cwd") or os.getcwd()
    state["started"] = time.time()
    state["tips"] = {norm(r): tips(r) for r in repos_for(cwd)}
    save(path, state)
    cleanup()
    return 0


def pushed(repo, branch, sha):
    remote = git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")
    if not remote:
        return "local only"
    return "pushed" if remote == sha else "partly pushed"


def unfinished(data, state):
    """[(repo name, branch, sha, commits not on main, push state, main)] for this session's work."""
    cwd = data.get("cwd") or os.getcwd()
    snap = state.get("tips") if isinstance(state.get("tips"), dict) else {}
    started = state.get("started") or 0
    found = []
    for repo in repos_for(cwd):
        default = default_branch(repo)
        if not default or not applies(repo):
            continue
        head = git(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
        elsewhere = checked_out_elsewhere(repo)
        before = snap.get(norm(repo))
        recent = head_shas_since(repo, started) if before is not None and started else None
        for branch, sha in tips(repo).items():
            if branch == default or branch in elsewhere:
                continue
            if before is None:
                touched = branch == head  # no snapshot for this repo: judge only the branch in front of us
            else:
                touched = before.get(branch) != sha and (recent is None or sha in recent)
            if not touched:
                continue
            ahead = not_on_main(repo, f"refs/heads/{branch}", default)
            if ahead:
                name = os.path.basename(repo.rstrip("/\\"))
                found.append((name, branch, sha, ahead, pushed(repo, branch, sha), default))
    return found


def check(data):
    if (data.get("stop_hook_active") or data.get("background_tasks") or data.get("session_crons")
            or data.get("agent_id")):
        return 0
    path = state_path(data.get("session_id"))
    state = load(path)
    found = unfinished(data, state)
    signature = sorted(f"{name}:{branch}:{sha}" for name, branch, sha, *_ in found)
    if not found or signature == state.get("reported"):
        return 0
    state["reported"] = signature
    nudged = set(state.get("nudged") or [])
    fresh = [f for f in found if f"{f[0]}:{f[1]}" not in nudged]
    state["nudged"] = sorted(nudged | {f"{f[0]}:{f[1]}" for f in found})
    save(path, state)
    listed = "; ".join(f"{name}: '{branch}' has {ahead} commit(s) not on {default} ({where})"
                       for name, branch, _, ahead, where, default in found)
    out = {"systemMessage": "Unmerged branch work: " + listed}
    if fresh:  # first time for one of these branches: have Claude act on the rule
        out["hookSpecificOutput"] = {"hookEventName": "Stop", "additionalContext": (
            f"[joao-kit Finish on main] Branches worked on in this session are not merged into main: "
            f"{listed}. If the work on a branch is finished and the project's tests pass (no tests is no "
            "reason to wait), merge it into main now and push main if there is a remote (fast-forward, or "
            "a merge commit - no squash, no force-push; from a worktree, `git push origin HEAD:main` after "
            "merging origin/main in), then delete the branch on GitHub. "
            "If it is not finished or can't be merged yet (conflicts, failing tests, waiting on the user), "
            "say so in one line naming the branch, and merge it when it is done. Later commits on these "
            "branches only notify the user.")}
    print(json.dumps(out))
    return 0


def main(argv):
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except ValueError:
        return 0
    if not isinstance(data, dict):
        return 0
    mode = argv[1] if len(argv) > 1 else "check"
    return snapshot(data) if mode == "snapshot" else check(data)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:  # a reminder is never worth breaking the session
        sys.exit(0)
