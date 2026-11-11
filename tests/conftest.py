"""Shared helpers: run a hook script as Claude Code does, and write fake transcripts."""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOKS = Path(__file__).parents[1] / "plugins" / "joao-kit" / "hooks"
sys.path.insert(0, str(HOOKS))


def run_hook(script, payload, *args, env=None):
    """Run a hook with the payload on stdin as UTF-8 bytes; return (exit code, parsed JSON or None, stdout)."""
    full_env = {k: v for k, v in os.environ.items()
                if not k.startswith(("CLAUDE_KIT_", "ANTHROPIC_MODEL", "CLAUDE_CONFIG_DIR"))}
    full_env.update(env or {})
    out = subprocess.run(
        [sys.executable, str(HOOKS / script), *args], input=json.dumps(payload).encode("utf-8"),
        capture_output=True, env=full_env,
    )
    text = out.stdout.decode("utf-8")
    return out.returncode, (json.loads(text) if text.lstrip().startswith("{") else None), text


def assistant(model="claude-opus-5-5", effort="high", fresh=2, read=150_000, written=5_000, output=800,
              ttl="1h", sidechain=False, content=None, timestamp="2026-11-11T20:00:00.000Z"):
    split = {"ephemeral_1h_input_tokens": written if ttl == "1h" else 0,
             "ephemeral_5m_input_tokens": written if ttl == "5m" else 0}
    return {"type": "assistant", "isSidechain": sidechain, "effort": effort, "perTurnEffort": effort,
            "timestamp": timestamp,
            "message": {"model": model, "content": content or [{"type": "text", "text": "ok"}],
                        "usage": {"input_tokens": fresh, "cache_read_input_tokens": read,
                                  "cache_creation_input_tokens": written, "output_tokens": output,
                                  "cache_creation": split}}}


def user(text, **extra):
    return {"type": "user", "isSidechain": False, "message": {"role": "user", "content": text}, **extra}


def write_transcript(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    return path
