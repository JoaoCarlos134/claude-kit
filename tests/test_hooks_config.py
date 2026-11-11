"""The plugin's hooks.json is valid, every script it names exists, and no hook breaks on bad input."""

import json
import re

import pytest
from conftest import HOOKS, run_hook

CONFIG = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
COMMANDS = [h["command"] for groups in CONFIG["hooks"].values() for group in groups for h in group["hooks"]]


def test_every_hook_command_names_an_existing_script():
    assert COMMANDS
    for command in COMMANDS:
        m = re.search(r'\$\{CLAUDE_PLUGIN_ROOT\}/hooks/([\w.]+\.py)', command)
        assert m and (HOOKS / m.group(1)).is_file(), command


def test_events_are_the_ones_the_kit_documents():
    assert set(CONFIG["hooks"]) == {
        "PreToolUse", "SessionStart", "PostModelSwitch", "UserPromptSubmit", "SubagentStart", "Stop"}


SCRIPTS = sorted({
    (m.group(1), m.group(2) or "")
    for c in COMMANDS
    for m in [re.search(r'hooks/([\w.]+\.py)"\s*(\S*)', c)] if m
})


@pytest.mark.parametrize("script, mode", SCRIPTS)
@pytest.mark.parametrize("payload", [[1, 2], None, "x", {"cwd": 5}, {"prompt": 7, "session_id": []}])
def test_bad_input_never_fails(tmp_path, script, mode, payload):
    args = [mode] if mode else []
    code, _, _ = run_hook(script, payload, *args, env={"CLAUDE_KIT_STATE_DIR": str(tmp_path)})
    assert code == 0
