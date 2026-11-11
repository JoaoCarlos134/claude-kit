"""SessionStart hook: warn when the repo(s) in front of Claude are not in sync with their remote.

Fetches the upstream of the session's repo - or, when the session starts in a folder of
repos (like a projects folder), of each repo one level down - and reports any repo that is
behind, ahead, diverged or without an upstream. It also lists branches (local or on GitHub)
holding commits that are not on main, so a new session sees work already in flight instead
of doing it twice. Silent when everything is in sync and merged.

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
BRANCHES_SHOWN = 5


def git(repo, *args, timeout=10):
    try:
        out = subprocess.run(
            ["git", "-C", repo, *args], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
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


def default_branch(repo):
    """The branch work should end up on: origin's HEAD, else a local main or master."""
    ref = git(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if ref and "/" in ref:
        return ref.split("/", 1)[1]
    for name in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    return None


def not_on_main(repo, ref, default):
    """Commits in `ref` that are on neither the local nor the remote default branch."""
    base = [f"refs/heads/{default}"]
    if git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{default}"):
        base.append(f"refs/remotes/origin/{default}")
    if not git(repo, "rev-parse", "--verify", "--quiet", base[0]):
        base = base[1:]
    if not base:
        return 0
    count = git(repo, "rev-list", "--count", ref, "--not", *base)
    return int(count) if count and count.isdigit() else 0


def open_branches(repo):
    """Line naming the branches whose work is not on main yet, newest first, or None."""
    default = default_branch(repo)
    if not default:
        return None
    refs = git(repo, "for-each-ref", "--sort=-committerdate",
               "--format=%(refname) %(committerdate:short)", "refs/heads", "refs/remotes/origin")
    found = {}
    for line in (refs or "").splitlines():
        ref, _, date = line.partition(" ")
        local = ref.startswith("refs/heads/")
        name = ref[len("refs/heads/"):] if local else ref[len("refs/remotes/origin/"):]
        if name in (default, "HEAD"):
            continue
        ahead = not_on_main(repo, ref, default)
        if not ahead:
            continue
        entry = found.setdefault(name, {"ahead": 0, "date": date, "where": set()})
        entry["ahead"] = max(entry["ahead"], ahead)
        entry["where"].add("local" if local else "GitHub")
    if not found:
        return None
    shown = [
        f"{n} ({e['ahead']} commit(s), {' + '.join(sorted(e['where']))}, {e['date']})"
        for n, e in list(found.items())[:BRANCHES_SHOWN]
    ]
    more = f", +{len(found) - BRANCHES_SHOWN} more" if len(found) > BRANCHES_SHOWN else ""
    name = os.path.basename(repo.rstrip("/\\"))
    return f"{name}: {len(found)} branch(es) with work not on {default}: " + ", ".join(shown) + more


def check(repo):
    name = os.path.basename(repo.rstrip("/\\"))
    if not git(repo, "remote"):
        return None  # local-only repo: nothing to be behind
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    upstream = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    remote = upstream.split("/", 1)[0] if upstream else "origin"
    # --prune drops remote-tracking refs of branches deleted on GitHub, so they stop being listed
    fetched = git(repo, "fetch", "--quiet", "--prune", remote, timeout=FETCH_TIMEOUT) is not None
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
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("cwd"), (str, type(None))):
        data["cwd"] = None
    if data.get("source") not in (None, "startup", "resume"):
        return 0  # skip after /clear and compaction: already checked this session
    repos = repos_for(data.get("cwd") or os.getcwd())
    if not repos:
        return 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda r: (check(r), open_branches(r)), repos))  # fetch, then branches
    lines = [sync for sync, _ in results if sync]
    branches = [b for _, b in results if b]
    if not lines and not branches:
        return 0
    context, shown = [], []
    if lines:
        context.append(
            "Repository freshness check (joao-kit). Local copies differ from GitHub:\n- "
            + "\n- ".join(lines)
            + "\nBefore relying on local files for a repo listed here, tell the user and offer to "
            "pull (never pull over uncommitted changes, never force anything without asking). "
            "Facts about these projects may be newer on GitHub than on disk.")
        shown.append("Repos out of sync with GitHub: " + "; ".join(lines))
    if branches:
        context.append(
            "Open branches (joao-kit) - work not merged into main yet:\n- " + "\n- ".join(branches)
            + "\nBefore starting work that may overlap one of these, look at what it holds (git log "
            "main..<branch>) so the same work isn't done twice. Finished ones belong on main (the "
            "'Finish on main' rule); offer to merge them, and ask before deleting any.")
        shown.append("Unmerged branches: " + "; ".join(b.split(" with work")[0] for b in branches))
    print(json.dumps({
        "systemMessage": " | ".join(shown),
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "\n\n".join(context)},
    }))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # a freshness warning is never worth breaking the session start
        sys.exit(0)
