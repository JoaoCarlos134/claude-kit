"""Live model state of a Claude Code session, read from its transcript - and what a switch would cost.

Used two ways:
- as a module by model_router.py (the UserPromptSubmit hook), with the transcript path the hook gets;
- as a script by the pick-model skill, which renders `python model_state.py <session_id> <effort>`
  into its prompt. As a script it always exits 0 and prints `state=missing ...` when it can't tell,
  because a failing command would abort the skill.

Prices are list prices per million tokens from the claude-api skill (cached 2026-11-03). On a Claude
subscription they are usage-limit units rather than dollars; the ratios between models still hold.
When models or prices change, update PRICES here and the table in skills/pick-model/SKILL.md together.
"""

import calendar
import glob
import json
import os
import re
import sys
import time

TAIL_BYTES = 4_000_000  # transcripts grow to many MB; the last response is near the end

# family -> (input, output, cache read) in USD per million tokens, current generation
PRICES = {
    "haiku": (0.10, 0.50, 0.01),  # Haiku 5.5, prompts up to 100K tokens; cache read assumed 10%
    "sonnet": (2.00, 10.00, 0.10),  # Sonnet 5.5
    "opus": (4.00, 20.00, 0.20),  # Opus 5.5
    "fable": (8.00, 40.00, 0.20),  # Fable 5.2
}
FAMILY_RANK = {"haiku": 0, "sonnet": 1, "opus": 2, "fable": 3}
EFFORT_RANK = {"low": 0, "medium": 1, "high": 2, "xhigh": 3, "max": 4}
CACHE_WRITE = {"5m": 1.25, "1h": 2.0}  # multiple of the input price
TTL_SECONDS = {"5m": 300, "1h": 3600}


def family(model):
    m = (model or "").lower()
    if "mythos" in m:
        return "fable"
    return next((f for f in FAMILY_RANK if f in m), None)


def display(model):
    """claude-opus-5-5 -> Opus 5.5; an alias like 'opus' -> Opus."""
    m = re.match(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:\D|$)", (model or "").lower())
    if m:
        return m.group(1).capitalize() + " " + m.group(2) + (f".{m.group(3)}" if m.group(3) else "")
    fam = family(model)
    return fam.capitalize() if fam else (model or "unknown model")


def last_turn(transcript_path):
    """Model, effort and token usage of the last main-conversation response, or None."""
    try:
        with open(transcript_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - TAIL_BYTES))
            data = fh.read()
    except (OSError, TypeError):
        return None
    for raw in reversed(data.splitlines()):
        if b'"assistant"' not in raw:
            continue
        try:
            row = json.loads(raw)
        except ValueError:
            continue  # the first line of the tail is usually cut
        msg = row.get("message") or {}
        usage = msg.get("usage") or {}
        if row.get("type") != "assistant" or row.get("isSidechain") or not usage:
            continue
        if not family(msg.get("model")):
            continue  # synthetic entries (errors, interruptions) carry no real model
        fresh = usage.get("input_tokens") or 0
        read = usage.get("cache_read_input_tokens") or 0
        written = usage.get("cache_creation_input_tokens") or 0
        prompt = fresh + read + written
        split = usage.get("cache_creation") or {}
        ttl = "1h" if split.get("ephemeral_1h_input_tokens") else "5m" if split.get(
            "ephemeral_5m_input_tokens") else None
        return {
            "model": msg["model"],
            "effort": row.get("perTurnEffort") or row.get("effort"),
            "context_tokens": prompt + (usage.get("output_tokens") or 0),
            "cache_hit_pct": round(100 * read / prompt) if prompt else 0,
            "ttl": ttl,
            "timestamp": row.get("timestamp"),
        }
    return None


LONG_PROMPT = 100_000
LONG_INPUT = {"haiku": 0.50}  # Haiku 5.5 charges more for prompts over 100K tokens


def switch_cost(context_tokens, to_family, ttl="1h"):
    """Rough cost of the first turn after a switch: the whole context written to the new model's cache."""
    if to_family not in PRICES:
        return None
    price = PRICES[to_family][0]
    if context_tokens > LONG_PROMPT:
        price = LONG_INPUT.get(to_family, price)
    return context_tokens * price / 1e6 * CACHE_WRITE.get(ttl or "5m", 1.25)


def epoch(timestamp):
    """Unix time of a transcript timestamp (UTC, e.g. 2026-11-11T20:11:47.355Z), or None."""
    try:
        return calendar.timegm(time.strptime(timestamp[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return None


def seconds_since(timestamp):
    t = epoch(timestamp)
    return None if t is None else max(0, time.time() - t)


def config_dir():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")


def find_transcript(session_id=None, cwd=None):
    projects = os.path.join(config_dir(), "projects")
    if session_id and re.fullmatch(r"[\w-]+", session_id):
        hits = glob.glob(os.path.join(projects, "*", session_id + ".jsonl"))
        if hits:
            return hits[0]
    if cwd:  # newest transcript of this folder: Claude Code names the folder after the path
        folder = os.path.join(projects, re.sub(r"[^A-Za-z0-9]", "-", cwd))
        files = glob.glob(os.path.join(folder, "*.jsonl"))
        if files:
            return max(files, key=os.path.getmtime)
    return None


def report(session_id=None, effort=None, cwd=None):
    path = find_transcript(session_id, cwd or os.getcwd())
    turn = last_turn(path) if path else None
    if not turn:
        return ("state=missing (no transcript response found) - in the desktop app read model and effort "
                "with get_session('self'); otherwise use the status line or ask the user. "
                f"effort={effort or 'unknown'}")
    fam = family(turn["model"])
    effort = effort if effort in EFFORT_RANK else turn["effort"] or "unknown"
    ttl = turn["ttl"] or "5m"
    ctx = turn["context_tokens"]
    age = seconds_since(turn["timestamp"])
    warm = age is None or age < TTL_SECONDS[ttl]
    lines = [
        f"model={turn['model']} ({display(turn['model'])}) effort={effort} context={ctx // 1000}k "
        f"cache_hit={turn['cache_hit_pct']}% cache_ttl={ttl} "
        + (f"last_response={int(age // 60)}min_ago" if age is not None else ""),
    ]
    if warm and ctx:
        costs = " | ".join(
            f"{f} ${switch_cost(ctx, f, ttl):.2f}" for f in PRICES if f != fam)
        lines.append(f"switch_re-cache (API list price, first turn on the new model): {costs}")
    else:
        lines.append("cache cold or empty: a model switch costs nothing extra right now")
    return "\n".join(lines)


def main(argv):
    session_id = argv[1] if len(argv) > 1 and not argv[1].startswith("$") else None
    effort = argv[2] if len(argv) > 2 else None
    try:
        print(report(session_id, effort))
    except Exception as exc:  # never fail: a non-zero exit would abort the skill that renders this
        print(f"state=missing (error: {exc})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
