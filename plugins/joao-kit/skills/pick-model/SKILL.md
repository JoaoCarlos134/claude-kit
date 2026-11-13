---
name: pick-model
description: Decide where a task should run so it costs the fewest tokens while still getting the quality it needs - same session at another effort, a model-pinned joao-kit agent (haiku-worker, sonnet-worker, opus-thinker) that keeps the project's memory, a new session, or a model switch - weighing the prompt-cache cost. Use when the user asks "which model", "pick model", "what effort", "is Haiku enough", "Opus or Sonnet", "should I switch/downgrade/upgrade", when the joao-kit router flags a mismatch, or before starting costly work (multi-file refactor, research, long mechanical edits). Judges and routes only - it does not do the task itself.
---

# Pick model

Live state of this session:

!`python "${CLAUDE_PLUGIN_ROOT}/hooks/model_state.py" "${CLAUDE_SESSION_ID}" "${CLAUDE_EFFORT}"`

If you see that command above rather than its output (on this Windows machine Claude Code can hand it
to you to run instead of rendering it), run it once exactly as written; it works in bash and PowerShell
and always exits 0. If it prints `state=missing`: in the desktop app read model and effort with
`get_session("self")`; otherwise use the status line or ask. Never guess the current model.

Note: this skill sets no `model` or `effort` in its frontmatter on purpose. A skill whose model differs
from the session's makes that turn a model switch, and the whole conversation is re-read uncached.

## The rule: route the work, don't move the session

Sessions start on Sonnet 5.5 at medium effort (global settings). Most work fits there. Opus comes in for
the hard step through `opus-thinker`, or for a whole session that will be deep all through (`/model
opus` at the start costs nothing extra).

A session can't change its own model. Hooks can't set it, and the desktop app refuses a session that
re-prices its own turns. What saves tokens is putting each piece of work on the cheapest setup that does
it well. From cheapest to costliest:

1. **Do it here at another effort**: `/effort low|medium|high`. On Opus 5.5, Sonnet 5.5, Haiku 5.5 and
   Fable 5.1+ (subscription or API key), Claude Code changes effort without losing the cache. Effort sets
   how much the model thinks and writes (output tokens), not how much it reads.
2. **Delegate to an agent pinned to a model.** Every tool call in a long session re-reads its whole
   context: at 150k tokens on Opus, that's about $0.03 per call before any output. An agent starts small
   (a live haiku-worker began at about 10k tokens) plus what it reads, on its own model, and the parent's
   cache isn't touched. The joao-kit
   context bridge gives each agent the project's CLAUDE.md files, the auto-memory index and a digest of
   this session (recent requests, files edited, git status). So it starts with the project's memory
   without the price of this session's full context.
   - `joao-kit:haiku-worker` (Haiku 5.5, low): chores
   - `joao-kit:sonnet-worker` (Sonnet 5.5, medium): standard implementation with its test
   - `joao-kit:opus-thinker` (Opus 5.5, high, read-only): diagnosis, plan, methodology or security check
     asked from a Sonnet or Haiku session
   - Broad read-only searches: the built-in `Explore` agent with `model: haiku`.

   Delegate when the work needs more than a couple of tool calls, reads many files, or produces long
   mechanical output, and you can brief it completely. Don't delegate one or two quick edits: the brief
   costs about as much as the work.
3. **A new session on the right model**, for a self-contained task of another tier. In the desktop app,
   `start_session` with `model`. It starts fresh, so none of this conversation gets re-cached.
4. **Switch this session**: `/model`, which only the user can run. It's worth it at the start (nothing is
   cached yet), after the cache has expired (resumed after more than the TTL; the state above says when),
   or when the rest of a long session is clearly another tier. Claude Code asks for confirmation while the
   cache is warm.

Agent-tool forks inherit the full conversation but always run on the parent's model, so they don't save
tokens on the model.

## Tiers

Check the project's CLAUDE.md for a "Model hints" line first; it overrides this table.

| Tier | Runs best on | Typical in my projects |
|---|---|---|
| Chore | Haiku 5.5 low (`haiku-worker`) | rename across files, PT<->EN translation of docs, reformat tables, bump versions or dates, extract fields from JSON/CSV/PDF text, regex, list or summarise files, update a status line in CLAUDE.md or ROADMAP |
| Standard | Sonnet 5.5 medium (`sonnet-worker` from Opus) | single-module bug fix with its test (academic-search CLI, a news_radio stage), Streamlit page (Keyword_map), React component (git_profile), scripts, docs, review of a small diff |
| Deep | Opus 5.5 high (`opus-thinker` from Sonnet) | forecasting methodology and leakage checks (prosumer), benchmark design, thesis/TCC argument, reconciling diverged lines (Loom), architecture, security, 3+ file refactors, intermittent bugs |
| Boulder | Fable 5.2 high, for the whole session | multi-day work with a large live context and sustained ambiguity, e.g. a full release build; or Opus high already failed at it once |

Go up one tier (one at most) when the task touches money, secrets or personal data, is hard to undo
(migrations, deletes, publishing), has no tests to catch mistakes, already failed once, or feeds a number
or claim that will be published. Go down when the spec is exact, tests cover it, and it's repetitive.

Effort per model:
- Haiku 5.5: low, or medium for longer chains.
- Sonnet 5.5: low for lookups and chat, medium for agentic coding, high for tricky work. Don't push Sonnet
  to xhigh or max; past high, Opus 5.5 at twice the price gives more for each token.
- Opus 5.5: medium for routine work, high for real reasoning, xhigh for long hard agentic coding, max rarely.
- Fable 5.2: start at high; use xhigh only where it has shown a gain.

## Costs

List prices per million tokens, input / output / cache read (claude-api skill, cached 2026-11-03). All
four models have a 1M-token context.

| Model | In | Out | Cache read |
|---|---|---|---|
| Haiku 5.5 | $0.10 | $0.50 | ~$0.01 (prompts up to 100K; $0.50 / $2.50 beyond) |
| Sonnet 5.5 | $2 | $10 | $0.10 |
| Opus 5.5 | $4 | $20 | $0.20 |
| Fable 5.2 | $8 | $40 | $0.20 |

Cache writes cost 1.25x input on the 5-minute TTL, or 2x on the 1-hour TTL (a subscription's main
conversation). On a subscription these are usage-limit units, not dollars, but the ratios hold.

- Switch penalty ≈ context × new input price × write multiple (the state block above computes it).
- Switch gain ≈ (old − new output price) × output still to come, plus (old − new cache-read price) ×
  context × tool calls still to come.
- Switch only when the gain clearly beats the penalty. Otherwise change the effort or delegate.

## Verdict

```
Verdict: Stay | Effort -> X | Delegate -> agent | New session (model) | Switch -> model
Now: Opus 5.5 · xhigh · 165k context · cache 96%
Fit: <tier> - <one line on why>
Cost: <"effort change keeps the cache" | "agent: own small cache, parent untouched" | "switch re-caches ~$X">
Plan: <e.g. "haiku-worker renames across 14 files; I review the diff here">
```

Then act on it in the same turn when it's yours to do: delegate, or carry on here. A `/model` or `/effort`
change is the user's to make, so give them the exact command.

## Briefing an agent

The agent knows the project (CLAUDE.md, memory, session digest), but not your reasoning. Give it:
- the goal in one line, and the files involved;
- the exact change, or the question (for opus-thinker);
- constraints already decided in this conversation that aren't in CLAUDE.md;
- how to check it's done: the test command, a grep that must come back empty.

Verify the agent's report before you claim the work is done: read the diff, re-run the check.

## Anti-patterns

- Opus at high or xhigh as the default for chores.
- Switching models late in a long session for a small gain: the re-cache costs more than it saves.
- Delegating a one-line edit.
- Treating effort as an input cost. It's output spend; in a loop, a higher effort can finish in fewer turns.
- A `model:` field on a skill that runs in the main conversation (it causes a cache-breaking switch).
- Trusting the router blindly. It scores words: on prompts it wasn't tuned on it misses 44% of deep and
  36% of chore prompts (mostly by staying silent, sometimes with the wrong label); overrule it when the
  task says otherwise.
