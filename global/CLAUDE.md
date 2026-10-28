# Personal instructions (all projects)

Copy or link to `~/.claude/CLAUDE.md`. Keep it short; project facts belong in each project's CLAUDE.md.

## Working with me

- I work with Claude in English. Some projects keep docs or code comments in Portuguese - the project's
  CLAUDE.md says which; follow it.
- Record *why*, not just what: decisions go into the project's CLAUDE.md with the reason and what was
  rejected.
- Verify before claiming: run the tests, reproduce the number, check GitHub before assuming local is current.
- After a work step, run the `work-reviewer` agent over the commits before building on them.

## Git

- Personal repositories use only my personal identity (GitHub noreply address), never an employer's email.
  The joao-kit identity guard enforces this for Claude's commits; `git/setup-identity.sh` for everything else.
- Never commit `.env`, keys, tokens or private data. Never rewrite history or force-push without asking.

## New projects

- Use the `new-project` skill: identity, CLAUDE.md with status line, tests from day one, CI, README.
