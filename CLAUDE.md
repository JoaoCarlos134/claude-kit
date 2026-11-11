# CLAUDE.md — claude-kit

My personal base for Claude Code: a plugin marketplace with one plugin, `joao-kit` (agents, skills, hooks),
plus the global CLAUDE.md and settings every machine gets. README.md has the piece-by-piece table.

**Status (2026-11-11): active.** joao-kit 0.2.0 adds token-saving model routing and the finish-on-main rule.

## Commands

```bash
python -m pytest tests -q        # all hooks, against real throwaway git repos and transcripts
# live check of the plugin from this folder, on Haiku (cents): run in a throwaway git repo
claude -p "<prompt>" --plugin-dir plugins/joao-kit --model haiku --output-format json
```

Live-checked 2026-11-11 with `--plugin-dir`: haiku-worker ran on claude-haiku-5-5 and received the bridge
context and CLAUDE.md; the router's note reached Claude on a second prompt; the Stop hook's reminder led
Claude to fast-forward a new branch into main. `/joao-kit:pick-model` got the live state line, but not at
load: on this machine Claude Code handed the `!` command to Claude to run, and the first try failed on
a bash-only `||` in PowerShell 5.1 (since removed).

Changes reach a machine only after they are pushed and the plugin is updated there
(`/plugin update joao-kit@claude-kit` in a terminal session, then restart). `global/CLAUDE.md` is copied
to `~/.claude/CLAUDE.md` by hand or by the NEW_MACHINE.md prompt.

## Rules

- Hooks: Python standard library only, `python` on PATH, must work on Windows and Linux (CI runs both).
  A hook never breaks the session: unexpected input or errors -> exit 0 and say nothing. Read stdin as
  UTF-8 bytes (Portuguese prompts break the Windows default code page); print JSON with `json.dumps`
  defaults (ASCII-escaped).
- Tests use real temporary git repos and fake transcripts, never the user's own `~/.claude`.
- Only things true for a project I haven't started yet go here (README "Rule for adding things").
- Model names, prices and cache facts must change together in: `PRICES` / `LONG_INPUT` in
  `hooks/model_state.py`, `effort_keeps_cache` in `hooks/model_router.py`, the Costs and effort sections of
  `skills/pick-model/SKILL.md`, the agent descriptions, and README's table.
- Hooks need Python 3.11+ (CI runs 3.11 and 3.12 on Linux and Windows).

## Decisions (newest first)

- **2026-11-11 — Default model Sonnet 5.5 at medium effort (was Opus at high), in `global/settings.json`
  and on this machine.** Why: the session itself keeps the full context and memory, at half Opus 5.5's
  price per token; the router plus `opus-thinker` bring Opus in only for the hard step, and `/model opus`
  at the start of a session that will be deep all through costs nothing extra. Bulky chores in a big
  Sonnet session still go to `haiku-worker` (Haiku 5.5 is about 20x cheaper). Rejected: keeping Opus as
  the default and only delegating down, because then every turn of every session pays Opus prices for
  reading the context. Revisit if Sonnet's answers on everyday work in prosumer or Loom turn out
  noticeably worse.

- **2026-11-11 — Model routing delegates to model-pinned agents instead of switching models.** Why: no
  hook output can set the model or effort (hooks docs: PreModelSwitch can only allow, ask or block a
  switch the user started), and the desktop app refuses `set_session_model` on the session itself. A
  subagent runs on its own `model` and doesn't touch the parent's prompt cache. In a long session every
  tool call re-reads the whole context (about $0.03 a call at 150k tokens on Opus 5.5), so moving
  multi-step chores out of it is where the saving is. Rejected: installing digital-stoic-org's
  `pick-model` with `npx skillfish` (third-party code; its model table predates Opus 5.5 and Sonnet 5.5;
  its `model: sonnet` frontmatter makes the skill itself a cache-breaking model switch per Claude Code's
  prompt-caching docs; its `pick-model-state` script isn't on this machine); a Haiku API call inside the
  hook (needs a key, adds latency and cost to every prompt; keyword heuristics are free and good enough
  for a hint Claude can overrule); Agent-tool forks (full context, but they always run on the parent's
  model).
- **2026-11-11 — Cheap agents keep the project's memory through a SubagentStart hook (`context_bridge.py`).**
  Why: subagents load the CLAUDE.md files but not the auto memory or anything from the session, and the
  user asked for cheaper models "while still having the memory and context of the project". The bridge
  adds the MEMORY.md index plus a digest (recent requests, files edited, git status): a couple of
  thousand tokens at the agent's price. `work-reviewer` is excluded on purpose (fresh eyes).
- **2026-11-11 — The router tells Claude on every mismatched prompt, tells the user once per hint per
  session (again after 15 prompts).** Why: delegation only happens if Claude sees the hint each time; the
  user needs it once. Standard work on Opus is flagged only at xhigh or max, and delegation is suggested
  only above 40k tokens of context, because Opus 5.5 is just 2x Sonnet 5.5 and small sessions save little.
  Questions ("what is", "why", "o que e", "explain") get no label: a 43-prompt probe by the reviewer
  showed them being sent toward Haiku or sonnet-worker when only the main session can answer them.
- **2026-11-11 — The router never guesses the model from settings files.** It uses the newer of the last
  response's model (transcript) and the model SessionStart or PostModelSwitch reported, else
  `ANTHROPIC_MODEL`, else stays silent. Why: in a live `claude -p --model haiku` run, SessionStart carried
  no `model` and UserPromptSubmit no `effort`, and the settings file said `opus`, so the router gave a
  wrong "fits" verdict. A wrong hint is worse than none; from the second prompt on, the transcript knows.
- **2026-11-11 — `pick-model` sets no `model`/`effort` frontmatter.** Why: a skill whose model differs from
  the session's turns that turn into a model switch (full uncached re-read).
- **2026-11-11 — Finish on main: a CLAUDE.md rule for my own repos, enforced by a Stop hook.** Why:
  parallel desktop sessions left work on unmerged branches and it got redone (Loom's two lines diverged
  at 7ae5dde and had to be ported back together). A branch counts as this session's only if its tip
  moved since the SessionStart snapshot AND that tip is in this worktree's own HEAD reflog since the
  session started. The first version used "tip moved + not checked out in another worktree", and the
  work-reviewer showed it blamed this session for another session's branch once that worktree was
  removed or switched branch. A repo missing from the snapshot is judged by its checked-out branch only.
  Only the first reminder per branch makes Claude continue (each continuation is a full-context call);
  later commits only notify the user. Scoped to personal repos like identity_guard, because employer
  repos merge through pull requests (`CLAUDE_KIT_BRANCH_RULE=all` overrides). Rejected: SessionEnd (it
  can't make Claude act), blocking every Stop (forces a merge after each turn), squash merges (git can't
  see the branch as merged, so the session-start report would list it forever). Known limit: two
  sessions in the same checkout (no worktrees) share one HEAD reflog, so each can be reminded about the
  other's branch.

## Where to continue

- After pushing: update the plugin on each machine and restart, then watch a few sessions. Check that the
  router's hints are right (false positives -> adjust the keyword tables in `model_router.py`) and that the
  agents' reports are good enough to save tokens overall.
- Consider adding "Model hints" lines to the CLAUDE.md of prosumer and Loom (the projects with the clearest
  deep-vs-chore split).
