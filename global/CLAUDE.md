# Personal instructions (all projects)

Copy or link to `~/.claude/CLAUDE.md`. Keep it short; project facts belong in each project's CLAUDE.md.

## Working with me

- I work with Claude in English. Some projects keep docs or code comments in Portuguese - the project's
  CLAUDE.md says which; follow it.
- Record *why*, not just what: decisions go into the project's CLAUDE.md with the reason and what was
  rejected.
- Verify before claiming: run the tests, reproduce the number, check GitHub before assuming local is current.
- After a work step, run the `work-reviewer` agent over the commits before building on them.

## Models and effort (save tokens)

- Sessions start on Sonnet 5.5 at medium effort (global settings). Route work to the cheapest model that
  does it well; the joao-kit router flags each prompt that doesn't fit the session's model or effort. A session can't change its own model, so delegate: bulky chores to
  `haiku-worker`, standard implementation from an Opus session to `sonnet-worker`, the hard step of deep
  work from a Sonnet or Haiku session to `opus-thinker`. They get CLAUDE.md, the project memory and a
  digest of the session. Do one- or two-edit things in place. When an `/effort` or `/model` change is the
  better move, tell me the exact command. Full rules: the `pick-model` skill.

## Git

- Personal repositories use only my personal identity (GitHub noreply address), never an employer's email.
  The joao-kit identity guard enforces this for Claude's commits; `git/setup-identity.sh` for everything else.
- Never commit `.env`, keys, tokens or private data. Never rewrite history or force-push without asking.
- Finish on main (my own repositories). A branch created or moved in a session is merged into main and
  pushed before the session ends: the project's tests pass (if it has none, that's no reason to wait),
  fast-forward or a merge commit (no squash, so git still sees it as merged), no force-push, then the
  branch is deleted on GitHub. If it can't be merged yet
  (conflicts, failing tests, waiting on me), say so in the closing message, naming the branch and why.
  The joao-kit branch guard reminds you at the end of a turn. Repos owned by others keep their own flow
  (pull requests).
- Before starting work, look at the unmerged branches the session-start check lists, so the same work
  isn't done twice.

## New projects

- Use the `new-project` skill: identity, CLAUDE.md with status line, tests from day one, CI, README.
