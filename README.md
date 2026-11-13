# claude-kit

[![CI](https://github.com/JoaoCarlos134/claude-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/JoaoCarlos134/claude-kit/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

My personal base for Claude Code: what I learned on earlier projects, packaged so every machine and every new
project starts from it instead of from zero. It is a plugin marketplace with one plugin, `joao-kit`.

**Rule for adding things:** only what is true for a project I haven't started yet, and only after I have
explained it to Claude at least twice. Project-specific skills and rules stay in that project's repo.

## What's in it

| Piece | What it does |
|---|---|
| `agents/work-reviewer.md` | Independent, read-only reviewer: fact-checks claims, reruns checks, tries to break new code. Grown from the prosumer project. |
| `agents/haiku-worker.md`, `sonnet-worker.md`, `opus-thinker.md` | The same work on a cheaper (or deeper) model: chores on Haiku 5.5, standard implementation on Sonnet 5.5, read-only diagnosis and plans on Opus 5.5. A session can't change its own model, but it can hand work to these. |
| `skills/pick-model/` | Decides where a task runs - effort change, one of those agents, a new session, or a `/model` switch - from the live model, context size and cache, with what a switch would cost. |
| `skills/new-project/` | Sets up a project properly: personal identity, CLAUDE.md, tests from day one, CI, README with status. |
| `hooks/model_router.py`, `router_classifier.py` | On every prompt: labels it chore / standard / deep (a scorer over the user's own words in English and Portuguese, no model call; it labels only what it is fairly sure of) and, when the session's model or effort doesn't fit, tells Claude which agent to hand it to and tells you once which `/effort` or `/model` would do. Silent when the fit is fine. |
| `hooks/context_bridge.py` | When one of the three agents starts, gives it the project's auto-memory index and a digest of the session (recent requests, files edited, git status), so a cheap model works with the project's memory without paying for the session's whole context. |
| `hooks/branch_guard.py` | "Finish on main", in my own repos: at the end of a turn, if a branch this session worked on (its tip is in this worktree's HEAD reflog since the session started) still has commits not on main, asks Claude once to merge and push main or say why not; later commits only notify you. Other sessions' worktree branches never count. `CLAUDE_KIT_BRANCH_RULE=all` applies it to every repo. |
| `hooks/identity_guard.py` | Blocks Claude's `git commit` / `git push` in my repos unless the identity is my personal one. Allowlist-based (GitHub noreply + `CLAUDE_KIT_PERSONAL_EMAILS`), so it names no employer and survives a job change. Repos owned by anyone else are left alone. |
| `hooks/freshness_check.py` | At session start, fetches and warns (Claude and you) when the repo - or each repo in a folder of repos - is behind, ahead, diverged or unlinked from GitHub, and lists branches whose work is not on main yet, so it isn't done twice. Read-only; silent when all is in sync and merged. |
| `tests/router_corpus/` | 652 labeled prompts and `router_eval.py`, which scores the classifier (`python tests/router_corpus/router_eval.py --errors`). `blind*.jsonl` were written by other models that never saw the classifier. |
| `templates/CLAUDE.md` | Starting CLAUDE.md for a project. |
| `global/CLAUDE.md` | My instructions for all projects -> `~/.claude/CLAUDE.md`. |
| `global/settings.json` | My Claude Code settings (default Sonnet 5.5 at medium effort - Opus comes in through the router and `opus-thinker` - auto mode and its environment rules, this marketplace and plugin) -> merge into `~/.claude/settings.json`. Machine-specific entries (paths to one work repo) are left out on purpose. |
| `git/setup-identity.sh` | Git config so *my own* commits (not only Claude's) use the personal identity in every repo of my account. |

## Install on a new machine

Quickest: paste the prompt in [NEW_MACHINE.md](NEW_MACHINE.md) into a Claude Code session opened in the
projects parent folder; it does the steps below and clones/pulls every repo. By hand:

1. Git identity (once per machine):

   ```bash
   bash git/setup-identity.sh
   ```

2. Plugin, in a terminal Claude Code session (not the desktop app's Code tab):

   ```
   /plugin install joao-kit --marketplace JoaoCarlos134/claude-kit
   ```

   Answer `y` to add the marketplace, then pick the user scope. Update later with `/plugin update`.

3. Global instructions: copy `global/CLAUDE.md` to `~/.claude/CLAUDE.md` (merge if one exists).

4. Settings: merge `global/settings.json` into `~/.claude/settings.json` - keys from the kit win, keys only
   on the machine are kept. It also registers the marketplace and enables `joao-kit`, so step 2 can be
   skipped if this is done first and Claude Code is restarted.

The hooks need `python` 3.11 or newer on PATH (CI tests 3.11 and 3.12) and git. Optional env vars: `CLAUDE_KIT_GITHUB_USERS` (accounts treated as
mine, comma separated) and `CLAUDE_KIT_PERSONAL_EMAILS` (extra allowed addresses).

## Tests

```bash
python -m pytest tests -q
```

## Using it yourself

It is built around one person's setup (`JoaoCarlos134` is the default account in `setup-identity.sh` and the
guard), but every piece takes its own inputs: pass your account, name and noreply address to
`setup-identity.sh`, set `CLAUDE_KIT_GITHUB_USERS` and `CLAUDE_KIT_PERSONAL_EMAILS` for the guard, and fork
the repo to make the marketplace yours.

## License

[MIT](LICENSE)
