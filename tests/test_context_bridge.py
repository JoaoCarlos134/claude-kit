"""Tests for context_bridge.py (SubagentStart): the cheap agents get project memory and a session digest."""

import re
import subprocess

from conftest import assistant, run_hook, user, write_transcript


def g(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def repo(path):
    path.mkdir(parents=True)
    g(path, "init", "-q", "-b", "main")
    g(path, "config", "user.email", "t@users.noreply.github.com")
    g(path, "config", "user.name", "T")
    g(path, "commit", "-q", "--allow-empty", "-m", "first")
    return path


def memory(cfg, project_path, text):
    folder = cfg / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(project_path)) / "memory"
    folder.mkdir(parents=True)
    (folder / "MEMORY.md").write_text(text, encoding="utf-8")


def session(tmp_path, cwd):
    edit = {"type": "tool_use", "name": "Edit", "input": {"file_path": str(cwd / "src" / "app.py")}}
    return write_transcript(tmp_path / "main.jsonl", [
        user("first request: build the export"),
        assistant(content=[edit]),
        user([{"type": "tool_result", "content": "edited"}], toolUseResult={"ok": True}),
        user("<command-name>/effort</command-name>"),
        user('<pasted_content id="p">' + "long log line\n" * 200 + "</pasted_content> second request: "
             "use semicolons in the CSV"),
        {"type": "attachment", "isSidechain": False,
         "attachment": {"type": "queued_command", "prompt": "mid-turn: keep the header row",
                        "origin": {"kind": "human"}}},
        user("This session is being continued from a previous conversation. Summary: SECRET-SUMMARY",
             isCompactSummary=True),
        user("[Request interrupted by user for tool use]"),
    ])


def test_worker_gets_memory_digest_and_git(tmp_path):
    cwd = repo(tmp_path / "proj")
    (cwd / "new.txt").write_text("x")
    cfg = tmp_path / "cfg"
    memory(cfg, cwd, "- [Data rule](data.md) - never commit raw data\n")
    data = {"cwd": str(cwd), "agent_type": "joao-kit:haiku-worker",
            "transcript_path": str(session(tmp_path, cwd))}
    code, out, _ = run_hook("context_bridge.py", data, env={"CLAUDE_CONFIG_DIR": str(cfg)})
    assert code == 0
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
    assert "never commit raw data" in ctx
    assert "first request: build the export" in ctx
    assert "[pasted text] second request: use semicolons in the CSV" in ctx  # own words, not the paste
    assert "long log line" not in ctx
    assert "mid-turn: keep the header row" in ctx
    assert "tool_result" not in ctx and "/effort" not in ctx  # tool output and commands aren't requests
    assert "SECRET-SUMMARY" not in ctx and "Request interrupted" not in ctx
    assert "app.py" in ctx
    assert "Branch: main" in ctx and "new.txt" in ctx


def test_worktree_uses_main_checkout_memory(tmp_path):
    main = repo(tmp_path / "proj")
    wt = tmp_path / "wt"
    g(main, "worktree", "add", "-q", "-b", "side", str(wt))
    cfg = tmp_path / "cfg"
    memory(cfg, main, "- shared memory line\n")
    data = {"cwd": str(wt), "agent_type": "joao-kit:sonnet-worker"}
    _, out, _ = run_hook("context_bridge.py", data, env={"CLAUDE_CONFIG_DIR": str(cfg)})
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "shared memory line" in ctx and "Branch: side" in ctx


def test_reviewer_and_other_agents_get_nothing(tmp_path):
    cwd = repo(tmp_path / "proj")
    for agent in ("joao-kit:work-reviewer", "Explore", "general-purpose", ""):
        code, out, _ = run_hook("context_bridge.py", {"cwd": str(cwd), "agent_type": agent})
        assert code == 0 and out is None


def test_outside_a_repo_with_nothing_to_add_is_silent(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    data = {"cwd": str(empty), "agent_type": "joao-kit:opus-thinker"}
    code, out, _ = run_hook("context_bridge.py", data, env={"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})
    assert code == 0 and out is None
