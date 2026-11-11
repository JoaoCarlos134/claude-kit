"""SubagentStart hook: give the model-pinned joao-kit agents the project's memory and the session's gist.

Subagents start fresh: they load the CLAUDE.md files, but not the project's auto memory and nothing from
the conversation that called them. That keeps them cheap - and is what makes a cheap model get things
wrong. This hook closes the gap for haiku-worker, sonnet-worker and opus-thinker only; work-reviewer is
left out on purpose, it reviews with no session context so it doesn't share the session's assumptions.

What it adds, a couple of thousand tokens read at the subagent's own price (the parent's cache is not
touched):
- the project's auto-memory index (MEMORY.md, as the main session gets it) and the folder its files live in;
- a digest of the main session: the user's recent requests, files edited so far, branch and git status.
"""

import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_state import config_dir  # noqa: E402

AGENTS = ("haiku-worker", "sonnet-worker", "opus-thinker")
TAIL_BYTES = 8_000_000
RECENT_REQUESTS = 5
REQUEST_CHARS = 600
MEMORY_CHARS = 6_000
MAX_FILES = 15
STATUS_LINES = 20
NOT_A_REQUEST = re.compile(
    r"^\s*(<(command-|local-command|system-reminder|task-notification|side-sessions-event"
    r"|ci-monitor-event|bash-|scheduled-task)|\[Request interrupted"
    r"|This session is being continued from a previous conversation)")
PASTED = re.compile(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", re.S)


def request_text(text):
    """The user's own words: pasted documents collapsed, cut to REQUEST_CHARS."""
    text = re.sub(r"\s+", " ", PASTED.sub(" [pasted text] ", text)).strip()
    return text if len(text) <= REQUEST_CHARS else text[:REQUEST_CHARS] + " [...]"


def git(repo, *args):
    try:
        out = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.rstrip() if out.returncode == 0 else None


def slug(path):
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def memory_index(cwd):
    """(folder, MEMORY.md text) of the project's auto memory, trying the cwd and the repo's roots."""
    candidates = [cwd]
    top = git(cwd, "rev-parse", "--show-toplevel")
    common = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if top:
        candidates.append(os.path.normpath(top))
    if common:  # worktrees share the main checkout's memory
        candidates.append(os.path.dirname(os.path.normpath(common)))
    for path in candidates:
        folder = os.path.join(config_dir(), "projects", slug(path), "memory")
        try:
            with open(os.path.join(folder, "MEMORY.md"), encoding="utf-8") as fh:
                return folder, fh.read(MEMORY_CHARS)
        except OSError:
            continue
    return None, None


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def session_digest(transcript_path, cwd):
    """(recent user requests, files edited) from the main session's transcript."""
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            data = fh.read()
    except (OSError, TypeError):
        return [], []
    requests, files = [], []
    for raw in data.splitlines():
        if b'"user"' not in raw and b'"tool_use"' not in raw and b'"queued_command"' not in raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if row.get("isSidechain") or row.get("isMeta") or row.get("isCompactSummary"):
            continue  # compaction summaries look like user rows but aren't requests
        msg = row.get("message") or {}
        attached = row.get("attachment") if isinstance(row.get("attachment"), dict) else {}
        if row.get("type") == "user" and not row.get("toolUseResult"):
            text = text_of(msg.get("content")).strip()
            if text and not NOT_A_REQUEST.match(text):
                requests.append(request_text(text))
        elif (row.get("type") == "attachment" and attached.get("type") == "queued_command"
              and (attached.get("origin") or {}).get("kind", "human") == "human"):
            text = (attached.get("prompt") or "").strip()  # a message the user sent mid-turn
            if text and not NOT_A_REQUEST.match(text):
                requests.append(request_text(text))
        elif row.get("type") == "assistant" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") in ("Edit", "Write", "MultiEdit", "NotebookEdit")):
                    path = (block.get("input") or {}).get("file_path") or (block.get("input") or {}).get(
                        "notebook_path")
                    if path:
                        try:
                            path = os.path.relpath(path, cwd)
                        except ValueError:
                            pass  # another drive on Windows
                        if path in files:
                            files.remove(path)
                        files.append(path)
    return requests[-RECENT_REQUESTS:], files[-MAX_FILES:]


def build(data):
    cwd = data.get("cwd") or os.getcwd()
    parts = ["[joao-kit context bridge] Background from the main session, so you work with the project's "
             "memory and what was already decided. Your task is only what the delegation prompt asks."]
    folder, index = memory_index(cwd)
    if index:
        parts.append(f"## Project memory (index; files in {folder} - Read one when its line matters)\n"
                     + index.strip())
    requests, files = session_digest(data.get("transcript_path"), cwd)
    if requests:
        parts.append("## The user's recent requests in the main session (oldest first)\n"
                     + "\n".join(f"- {r}" for r in requests))
    if files:
        parts.append("## Files edited in the main session so far\n" + "\n".join(f"- {f}" for f in files))
    branch = git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        status = (git(cwd, "status", "--short") or "").splitlines()
        more = f"\n(+{len(status) - STATUS_LINES} more)" if len(status) > STATUS_LINES else ""
        parts.append(f"## Git\nBranch: {branch}\n" + ("\n".join(status[:STATUS_LINES]) + more
                                                       if status else "Working tree clean."))
    return "\n\n".join(parts) if len(parts) > 1 else None


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except ValueError:
        return 0
    agent = (data.get("agent_type") or "").split(":")[-1]
    if agent not in AGENTS:
        return 0
    context = build(data)
    if context:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SubagentStart", "additionalContext": context}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # missing context is better than a failed delegation
        sys.exit(0)
