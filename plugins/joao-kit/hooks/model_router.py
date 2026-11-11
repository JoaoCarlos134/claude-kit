"""UserPromptSubmit hook: label each prompt (chore / standard / deep) and flag a model or effort that
doesn't fit it.

A session can't change its own model - no hook output sets it, and the desktop app refuses a session
that re-prices its own turns - so the router routes instead of switching: it tells Claude to hand bulky
chores to haiku-worker, standard implementation to sonnet-worker and the hard step of deep work to
opus-thinker (each gets the project's memory through context_bridge.py), and tells the user when an
`/effort` or `/model` change is the better move, with what the switch would cost.

Free and offline: keyword heuristics in English and Portuguese, no model call. Silent when the setup
fits, when the prompt is too short or unclear to judge, and on event turns Claude Code starts by itself.
The user sees a given hint once per session (again only REPEAT_AFTER prompts later); Claude gets it on
every mismatched prompt, because acting on it is how the routing happens.
"""

import json
import os
import re
import sys
import tempfile
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model_state import (  # noqa: E402
    EFFORT_RANK, FAMILY_RANK, display, epoch, family, last_turn, switch_cost,
)

REPEAT_AFTER = 15
BIG_CONTEXT = 40_000  # below this, doing standard work in place costs little; don't push delegation
CHORE_MAX_WORDS = 80

# (pattern, weight) on lower-case text without accents. Verbs that name the job weigh 1; nouns that
# only say "this is about code" weigh 0.5; signs of deep work weigh 2, so one is enough to win.
# Questions ("what is", "why", "o que e", "explain") get no label on purpose: they are answered in
# place, and "what is the best way to model X" is no chore. Bare "convert" is out too ("convert the
# training loop" is a refactor); data-format conversion is caught by "to csv/json/...".
CHORE = [(p, 1) for p in [
    r"\brenam(e|ing)\b", r"\brenome(ar|ie|ia)\b", r"\btypos?\b", r"\bspelling\b", r"\bortografi",
    r"\berros? de digitacao\b", r"\bre-?format", r"\bformat(ting|e|ar|acao)?\b", r"\bindent",
    r"\btranslat", r"\btraduz", r"\btraducao\b", r"\bextract\b",
    r"\bextra(ir|ia)\b", r"\bsort\b", r"\borden(ar|e)\b", r"\bbump\b", r"\bsummari[sz]e\b",
    r"\bresum(a|ir|o)\b", r"\blist (all|the|every)\b", r"\blist(e|ar)\b", r"\bcapitali[sz]",
    r"\b(upper|lower)case\b", r"\bmaiuscul", r"\bminuscul", r"\bregex\b",
    r"\bcommit (this|these|it|that|the changes|everything)\b", r"\bfa[cz]a (o )?commit\b",
    r"\bcommit(a|e)\b", r"\bgit (status|log|pull|push)\b", r"\bcopy\b", r"\bcopi(ar|e)\b",
    r"\bmove (the|this|these) files?\b", r"\b(to|into|para) (csv|json|yaml|markdown|md|tabela)\b",
    r"\b(add|update) (a |the )?(badge|link|date|year|copyright)s?\b", r"\bcount (the|how)\b",
]]
STANDARD = [(p, 1) for p in [
    r"\bimplement", r"\bimplement(ar|e)\b", r"\badicion(ar|e)\b", r"\bcri(ar|e) (um|uma)\b",
    r"\badd (a |an |the )?(new )?([\w-]+ )?(feature|endpoint|option|flag|command|test|button|page|component"
    r"|column|filter|field|parameter|argument|check)", r"\bbugs?\b", r"\bcorrig(ir|a|e)\b",
    r"\bconsert", r"\berrors?\b", r"\berros?\b(?! de digitacao)", r"\bfail(s|ing|ed|ure)?\b",
    r"\bfalh(a|ando|ou)\b", r"\bbroken\b", r"\bcrash", r"\bwrite (a |the )?tests?\b",
    r"\bunit tests?\b", r"\btestes?\b", r"\brefactor", r"\brefator", r"\bdebug", r"\bdepur",
    r"\bupdate (the )?(readme|docs|documentation|roadmap|claude\.md)\b",
    r"\breview (this|the|my)\b", r"\brevis(ar|e|ao)\b",
]] + [(p, 0.5) for p in [
    r"\bfunctions?\b", r"\bfuncao\b", r"\bendpoint\b", r"\bcomponents?\b", r"\bscripts?\b",
    r"\bcli\b", r"\bstreamlit\b", r"\breact\b", r"\bmodule\b", r"\bmodulo\b", r"\bclass\b",
]]
DEEP = [(p, 2) for p in [
    r"\barchitect", r"\barquitet", r"\bsystem design\b",
    r"\bdesign (the|a|an|our|my) (system|architecture|schema|api|pipeline|data model|database)\b",
    r"\brefactor(ing)? (the whole|across|all|entire|everything|the codebase|the project)\b",
    r"\brefatora(r|cao)? (todo|toda|geral|completa)\b", r"\bmethodolog", r"\bmetodolog",
    r"\bleakage\b", r"\bvazamento\b", r"\bdata leak", r"\bbenchmark design\b",
    r"\bexperiment(al)? design\b", r"\bdesenho experimental\b", r"\bablation\b", r"\bsecurity\b",
    r"\bseguranca\b", r"\bvulnerab", r"\bthreat model", r"\baudit\b", r"\bauditori",
    r"\broot cause\b", r"\bcausa raiz\b", r"\bintermittent", r"\bintermitente\b", r"\bflaky\b",
    r"\brace condition\b", r"\bdeadlock\b", r"\bconcurren", r"\bconcorrencia\b", r"\bmemory leak\b",
    r"\bstrateg", r"\bestrategi", r"\btrade-?offs?\b", r"\bpros (and|e) contras?\b",
    r"\bcompar(e|ar|ing) (the )?(approaches|options|alternatives|abordagens|alternativas|opcoes)\b",
    r"\bthesis\b", r"\btese\b", r"\bdissertac", r"\btcc\b", r"\bmestrado\b", r"\brebuttal\b",
    r"\bresposta aos revisores\b", r"\bmigrat(e|ion)\b", r"\bmigra(r|cao)\b", r"\bproof\b",
    r"\bderiv(e|ation|ar)\b", r"\bstatistical(ly)?\b", r"\bestatistic", r"\bsignifican",
    r"\bdiverged\b", r"\breconcil", r"\bfrom scratch\b", r"\bdo zero\b", r"\bend[- ]to[- ]end\b",
    r"\bwhole (repo|codebase|project|system)\b", r"\bplan (the|a|an|out|how)\b", r"\bplanej",
]]
EVENT_PROMPT = re.compile(
    r"^\s*<(side-sessions-event|ci-monitor-event|task-notification|system-reminder|command-name"
    r"|local-command|bash-input|bash-stdout|scheduled-task)")
PASTED = re.compile(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", re.S)
# Opens with a question word ("can you ..." / "pode ..." requests are not questions here).
QUESTION = re.compile(
    r"^\s*(what|what's|whats|why|how|where|when|which|who|is|are|does|do|did|explain|o que|por ?que"
    r"|como|onde|quando|qual|quais|explique|me explique)\b")


def plain(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def classify(prompt):
    """(tier, signals) with tier in chore/standard/deep, or (None, []) when unclear."""
    if not prompt or prompt.lstrip().startswith("/") or EVENT_PROMPT.match(prompt):
        return None, []
    own = PASTED.sub(" ", prompt)  # judge the user's own words, not pasted documents
    text = plain(own)
    words = len(text.split())
    if words < 3:
        return None, []  # "ok", "yes do it", "continue": keep going on the current setup
    scores, signals = {}, {}
    for tier, table in (("chore", CHORE), ("standard", STANDARD), ("deep", DEEP)):
        scores[tier], signals[tier] = 0, []
        for pattern, weight in table:
            m = re.search(pattern, text)
            if m:
                scores[tier] += weight
                signals[tier].append(m.group(0).strip())
    c, s, d = scores["chore"], scores["standard"], scores["deep"]
    if QUESTION.match(text):  # answered in place; only a deep question is worth flagging
        return ("deep", signals["deep"][:3]) if d >= 2 else (None, [])
    if d >= 2 and d >= s and d >= c:
        return "deep", signals["deep"][:3]
    if c > s and words <= CHORE_MAX_WORDS:
        return "chore", signals["chore"][:3]
    if s > c and s >= 1:  # nouns alone ("explain this function") don't make a coding task
        return "standard", signals["standard"][:3]
    return None, []


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
