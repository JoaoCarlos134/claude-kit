# claude-kit

My personal base for Claude Code: what I learned on earlier projects, packaged so every machine and every new
project starts from it instead of from zero. It is a plugin marketplace with one plugin, `joao-kit`.

**Rule for adding things:** only what is true for a project I haven't started yet, and only after I have
explained it to Claude at least twice. Project-specific skills and rules stay in that project's repo.

## What's in it

| Piece | What it does |
|---|---|
| `agents/work-reviewer.md` | Independent, read-only reviewer: fact-checks claims, reruns checks, tries to break new code. Grown from the prosumer project. |
| `skills/new-project/` | Sets up a project properly: personal identity, CLAUDE.md, tests from day one, CI, README with status. |
| `hooks/identity_guard.py` | Blocks Claude's `git commit` / `git push` in my repos unless the identity is my personal one. Allowlist-based (GitHub noreply + `CLAUDE_KIT_PERSONAL_EMAILS`), so it names no employer and survives a job change. Repos owned by anyone else are left alone. |
| `hooks/freshness_check.py` | At session start, fetches and warns (Claude and you) when the repo - or each repo in a folder of repos - is behind, ahead, diverged or unlinked from GitHub. Read-only; silent when all is in sync. |
| `templates/CLAUDE.md` | Starting CLAUDE.md for a project. |
| `global/CLAUDE.md` | My instructions for all projects -> `~/.claude/CLAUDE.md`. |
| `global/settings.json` | My Claude Code settings (model, effort, auto mode and its environment rules, this marketplace and plugin) -> merge into `~/.claude/settings.json`. Machine-specific entries (paths to one work repo) are left out on purpose. |
| `git/setup-identity.sh` | Git config so *my own* commits (not only Claude's) use the personal identity in every repo of my account. |

## Install on a new machine

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

The guard needs `python` on PATH and git. Optional env vars: `CLAUDE_KIT_GITHUB_USERS` (accounts treated as
mine, comma separated) and `CLAUDE_KIT_PERSONAL_EMAILS` (extra allowed addresses).

## Tests

```bash
python -m pytest tests -q
```
