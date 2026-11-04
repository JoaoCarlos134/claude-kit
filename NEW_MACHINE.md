# New machine: bootstrap prompt

Open a terminal Claude Code session in the parent folder that holds (or will hold) all projects, one folder
each, and paste the prompt below as the first message.

```text
Bootstrap this machine. This folder is my projects parent folder: each of my GitHub repos
(github.com/JoaoCarlos134) lives in its own subfolder here. Do the steps in order and report at the end.

0. Check tools: git, gh (run `gh auth status`; if not logged in, stop and tell me to run
   `! gh auth login`), and python on PATH.

1. claude-kit first. If ./claude-kit exists, fetch and fast-forward it; otherwise
   `gh repo clone JoaoCarlos134/claude-kit claude-kit`. Then, from it:
   a. ~/.claude/CLAUDE.md <- global/CLAUDE.md. If one already exists and differs (beyond line endings),
      show me the diff and merge rather than overwrite.
   b. ~/.claude/settings.json <- merge global/settings.json: back up the current file to
      settings.json.bak-<date> first, kit keys win, keys only on this machine are kept,
      `autoMode.environment` is replaced as a whole by the kit's list. Validate the JSON afterwards.
   c. Run `bash git/setup-identity.sh` so my own commits use the personal identity.
   d. Read ~/.claude/CLAUDE.md now and follow it for the rest of this session; it only loads
      automatically from the next session on.

2. All repos. List them with `gh repo list JoaoCarlos134 --limit 200 --json name,isArchived,sshUrl,url`
   (skip archived). For each one, match it to a local subfolder by its `origin` remote, not by folder name.
   - Found, clean, behind: `git pull --ff-only`.
   - Found but uncommitted changes, ahead, or diverged: do NOT pull, stash, reset or force anything -
     just report it.
   - Missing: clone it. Use these folder names so every machine matches:
     joaocarlos134.github.io -> git_profile, keyword-map -> Keyword_map, News_radio -> news_radio;
     all others keep the repo name.
   Also report local branches with no upstream that have commits not on main.

3. Report: one table (repo | folder | action taken | state now), anything you left alone and why, and
   then tell me what's left that I must do by hand: restart Claude Code so CLAUDE.md, settings and the
   joao-kit plugin load (if the plugin isn't active after the restart, run
   `/plugin install joao-kit@claude-kit`, user scope).
```

Notes

- `global/settings.json` already registers the claude-kit marketplace and enables `joao-kit`, which is why
  a restart is usually enough for the plugin.
- Folders outside GitHub (e.g. `app-idea`, `LowestPrice`) are not covered; copy them over yourself.
