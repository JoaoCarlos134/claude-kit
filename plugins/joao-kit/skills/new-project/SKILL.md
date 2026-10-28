---
name: new-project
description: Set up a new project, or bring an existing one without the basics up to standard - personal git identity, CLAUDE.md, tests from day one, CI, README with a status line, .gitignore for secrets. Use when the user starts a new repo or project, says "set up", "bootstrap", "start a project", or asks to add tests/CI/CLAUDE.md to a project that lacks them.
---

# New project setup

The goal: from the first commit, Claude can verify its own work in this project, and the next session (or
the next machine) can continue without re-explaining anything. Lessons come from earlier projects: the ones
that went well had tests + CI + a CLAUDE.md that records *why*, from early on; the ones that drifted had none.

Work through the steps in order. Ask the user only for what you cannot infer (purpose, audience, public or
private, language of docs). Skip a step that already exists, but check it is actually right.

## 1. Repository and identity

- `git init` if needed; default branch `main`.
- Confirm `git config user.email` is the personal GitHub noreply address before the first commit. If it is
  anything else, stop and fix it (`git config user.email <noreply>` or the global rule from
  `claude-kit/git/setup-identity.sh`). Never commit a personal project with an employer's address.
- `.gitignore` for the stack, always including `.env`, `.venv/`, `node_modules/`, caches, large data and
  model files. Add `.env.example` with every key empty.

## 2. CLAUDE.md (start from `templates/CLAUDE.md` in claude-kit)

Fill in, short and factual:
- **What it is** in two lines, and who it is for.
- **Status** line (active / paused because X / complete), dated.
- **Commands**: install, run, test, lint - exactly as typed, using the project environment.
- **Rules**: privacy and data constraints, languages for code/docs/comments, budget limits.
- **Decisions**: a dated log, each with the reason and what was rejected. This is the most valuable section
  later - "decided by ear after comparing six variants" saves a whole session of re-litigating.

## 3. Tests from day one

- Pick the standard runner (pytest, vitest...) and add one real test of the first real behaviour, not a
  placeholder. Write it before or with the code, and see it fail once.
- External things (network, paid APIs, GPU, TTS, LLMs) are injected as parameters so tests run offline, with
  no keys, in seconds. This is what lets a stranger - or CI - run the suite.
- For anything that produces numbers or AI output: keep a small frozen input set and the checks that define
  "good" (an eval), so model or prompt changes are measured, not judged by eye.

## 4. CI

- A GitHub Actions workflow that runs lint + tests on push and PR, with the same commands as CLAUDE.md.
- Keep it green; a red CI is fixed before new work.

## 5. README

- One-line hook, status line, quick start that works from a clean clone, how to run tests.
- For public repos: licence (ask the user - never pick one for them), attribution for data sources and APIs.

## 6. First commit and handover

- Commit with a message that says what and why. Run the `work-reviewer` agent over the first commits.
- Tell the user what was set up, what was skipped and why, and what they must do by hand (create the GitHub
  repo, add secrets to the CI, choose a licence).
