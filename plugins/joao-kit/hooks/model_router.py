"""UserPromptSubmit hook: label each prompt (chore / standard / deep) and flag a model or effort that
doesn't fit it.

A session can't change its own model - no hook output sets it, and the desktop app refuses a session
that re-prices its own turns - so the router routes instead of switching: it tells Claude to hand bulky
chores to haiku-worker, standard implementation to sonnet-worker and the hard step of deep work to
opus-thinker (each gets the project's memory through context_bridge.py), and tells the user when an
`/effort` or `/model` change is the better move, with what the switch would cost.

Free and offline: router_classifier.py scores the user's own words (English and Portuguese, some Spanish and French), no model
call. It labels only what it is fairly sure of and stays silent otherwise (on prompts from a new author it
catches 56% of deep and 64% of chore prompts; its deep and chore labels are right 84-88% of the time,
standard labels 79%).
Silent too when the setup fits, when the prompt is too short, and on event turns Claude Code starts.
The user sees a given hint once per session (again only REPEAT_AFTER prompts later); Claude gets it on
every mismatched prompt, because acting on it is how the routing happens.
"""

import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import router_classifier
    from model_state import (
        EFFORT_RANK, FAMILY_RANK, display, epoch, family, last_turn, switch_cost,
    )
except Exception:  # a half-updated plugin must not break the user's prompt
    if __name__ == "__main__":
        sys.exit(0)
    raise

REPEAT_AFTER = 15
BIG_CONTEXT = 40_000  # below this, doing standard work in place costs little; don't push delegation


def classify(prompt):
    """(tier, signals) with tier in chore/standard/deep, or (None, []) when unclear."""
    return router_classifier.classify(prompt)


def effort_keeps_cache(model):
    """Claude Code keeps the prompt cache across /effort changes only on the newest models
    (Fable 5.1+, Opus 5.5, Sonnet 5.5, Haiku 5.5) with an API key or a subscription."""
    m = (model or "").lower()
    if m in ("opus", "sonnet", "haiku", "fable", "opusplan", "best"):
        return True  # aliases resolve to the newest model of the family
    return bool(re.search(r"(opus|sonnet|haiku)-5-5|(fable|mythos)-5-[1-9]", m))


def session_model(data, state):
    """The session's model: the newer of what the last response used and what SessionStart or
    PostModelSwitch recorded; on a first prompt with neither, ANTHROPIC_MODEL or unknown."""
    turn = last_turn(data.get("transcript_path"))
    recorded, recorded_at = state.get("model"), state.get("model_at", 0)
    if recorded and (not turn or recorded_at >= (epoch(turn["timestamp"]) or 0)):
        return recorded, turn  # set at session start or by a /model switch after the last response
    if turn:
        return turn["model"], turn
    # No guess from settings files: `--model`, the desktop app's picker and per-session choices don't
    # show there (a live -p run with --model haiku read "opus" from settings). A wrong hint is worse than
    # none, so a first prompt stays silent unless Claude Code said which model it is.
    return os.environ.get("ANTHROPIC_MODEL"), None


def advise(tier, model, effort, context, ttl, signals):
    """(key, user_hint, claude_hint) for a setup that doesn't fit the tier, else None."""
    fam = family(model)
    if fam not in FAMILY_RANK:
        return None
    er = EFFORT_RANK.get(effort, -1)
    name = display(model) + (f" · {effort}" if effort else "")
    fresh = context == 0
    why = f"signals: {', '.join(signals)}" if signals else "keywords"
    keeps = "keeps the cache" if effort_keeps_cache(model) or fresh else "re-reads the context once"

    def cost(to):
        if fresh:
            return "free now - nothing cached yet"
        return f"re-sends ~{context // 1000}k tokens, about ${switch_cost(context, to, ttl):.2f} at list price"

    def note(kind, text):
        return (f"[joao-kit pick-model] This prompt reads as {kind} ({why}). Session: {name}, "
                f"~{context // 1000}k tokens of context. {text} Don't mention this note unless you act "
                "on it; the pick-model skill has the full rules.")

    if tier == "chore" and fam in ("opus", "fable"):
        switch = (f" `/model haiku` is {cost('haiku')} if the whole session is chores." if fresh else "")
        effort_tip = f"; `/effort low` {keeps}" if er != EFFORT_RANK["low"] else ""
        return (f"chore:{fam}",
                f"pick-model: chore on {name} -> bulky work goes to haiku-worker{effort_tip}.{switch}",
                note("a CHORE", "If it takes more than a couple of tool calls or touches many files, "
                     "delegate it to the joao-kit:haiku-worker agent with a complete brief (files, exact "
                     "change, how to check) and verify its report; one or two quick edits, do here."))
    if tier == "chore" and fam == "sonnet" and (context >= BIG_CONTEXT or er >= EFFORT_RANK["high"]):
        # Sonnet is the default; Haiku is ~20x cheaper, so bulky chores in a big session still move
        delegate = context >= BIG_CONTEXT
        tips = (["bulky work goes to haiku-worker"] if delegate else []) + (
            [f"`/effort low` {keeps}"] if er >= EFFORT_RANK["high"] else [])
        return (f"chore:sonnet:{effort}:{delegate}",
                f"pick-model: chore on {name} -> " + "; ".join(tips) + ".",
                note("a CHORE", "If it takes more than a couple of tool calls or touches many files, "
                     "delegate it to the joao-kit:haiku-worker agent with a complete brief (files, exact "
                     "change, how to check) and verify its report; one or two quick edits, do here.")
                if delegate else None)
    if tier == "standard" and (fam == "fable" or (fam == "opus" and er >= EFFORT_RANK["xhigh"])):
        delegate = context >= BIG_CONTEXT or fam == "fable"
        return (f"standard:{fam}:{effort}",
                f"pick-model: standard coding on {name} -> "
                + ("sonnet-worker can implement it; " if delegate else "")
                + f"`/effort medium` {keeps}.",
                note("STANDARD implementation", "If it is a self-contained change (one module and its "
                     "test), delegate the implementation to the joao-kit:sonnet-worker agent with the "
                     "goal, files, constraints and test command, then review its diff here; keep design "
                     "decisions here.") if delegate else None)
    if tier == "standard" and fam == "haiku":
        return ("standard:haiku",
                f"pick-model: coding task on {name} -> sonnet-worker can do it; `/model sonnet` "
                f"{cost('sonnet')}.",
                note("STANDARD implementation", "This session runs on Haiku. Delegate the "
                     "implementation to the joao-kit:sonnet-worker agent, and tell the user `/model "
                     "sonnet` is better if the rest of the session looks like this."))
    if tier == "standard" and fam == "sonnet" and er == EFFORT_RANK["low"]:
        return ("standard:sonnet:low",
                f"pick-model: coding task at effort low -> `/effort medium` {keeps}.", None)
    if tier == "deep" and fam in ("haiku", "sonnet"):
        return (f"deep:{fam}",
                f"pick-model: deep task on {name} -> opus-thinker can take the hard step; `/model "
                f"opus` for the whole session {cost('opus')}.",
                note("DEEP work", "Send the hard step (diagnosis, plan, methodology or security check) "
                     "to the joao-kit:opus-thinker agent with a precise question, then implement its plan "
                     "here. If the whole session will be like this, tell the user `/model opus` is worth "
                     "it" + (" - switching now costs nothing extra." if fresh else ".")))
    if tier == "deep" and fam == "opus" and er == EFFORT_RANK["low"]:
        return ("deep:opus:low", f"pick-model: deep task at effort low -> `/effort high` {keeps}.",
                None)
    return None


def state_path(session_id):
    root = os.environ.get("CLAUDE_KIT_STATE_DIR") or os.path.join(tempfile.gettempdir(), "joao-kit")
    safe = re.sub(r"[^\w-]", "_", session_id or "unknown")
    return os.path.join(root, f"router-{safe}.json")


def load_state(session_id):
    try:
        with open(state_path(session_id), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(session_id, state):
    path = state_path(session_id)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except OSError:
        pass


def should_show(state, key):
    """Count this prompt; True when the user hasn't seen this hint in the last REPEAT_AFTER prompts."""
    n = state.get("n", 0) + 1
    shown = state.setdefault("shown", {})
    show = key is not None and (key not in shown or n - shown[key] >= REPEAT_AFTER)
    if show:
        shown[key] = n
    state["n"] = n
    return show


def record_model(data, field):
    """SessionStart gives `model`, PostModelSwitch gives `to_model`: remember it with the time."""
    model = data.get(field)
    if model and family(model):
        state = load_state(data.get("session_id"))
        state["model"], state["model_at"] = model, time.time()
        save_state(data.get("session_id"), state)
    return 0


def main(argv):
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    except ValueError:
        return 0
    mode = argv[1] if len(argv) > 1 else "prompt"
    if mode == "session-start":
        return record_model(data, "model")
    if mode == "model-switch":
        return record_model(data, "to_model")
    if data.get("agent_id"):
        return 0  # inside a subagent: its model was already chosen
    state = load_state(data.get("session_id"))
    tier, signals = classify(data.get("prompt") or "")
    advice = None
    if tier:
        model, turn = session_model(data, state)
        effort = (data.get("effort") or {}).get("level") or (turn or {}).get("effort")
        context = (turn or {}).get("context_tokens", 0)
        advice = advise(tier, model, effort, context, (turn or {}).get("ttl"), signals)
    show = should_show(state, advice[0] if advice else None)
    save_state(data.get("session_id"), state)
    if not advice:
        return 0
    _, user_hint, claude_hint = advice
    out = {}
    if show:
        out["systemMessage"] = user_hint
    if claude_hint:
        out["hookSpecificOutput"] = {"hookEventName": "UserPromptSubmit", "additionalContext": claude_hint}
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception:  # a routing hint is never worth breaking the user's prompt
        sys.exit(0)
