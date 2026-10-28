#!/usr/bin/env bash
# Makes every repo of your GitHub account use your personal identity, on any machine and at any employer.
# Rules are keyed on the remote's owner, not on folders or company names, so a job change needs no edit.
# Repos of anyone else (an employer's org, GitLab, Azure DevOps) keep whatever identity they had.
#
# Usage: bash git/setup-identity.sh [github-user] [name] [noreply-email]
# Safe to rerun: it rewrites ~/.gitconfig-personal and replaces only its own includeIf entries.
set -euo pipefail

USER_GH="${1:-JoaoCarlos134}"
NAME="${2:-JoaoCarlos134}"
EMAIL="${3:-93523542+JoaoCarlos134@users.noreply.github.com}"

cat > "$HOME/.gitconfig-personal" <<EOF
[user]
	name = $NAME
	email = $EMAIL
EOF

for url in "https://github.com/$USER_GH/**" "git@github.com:$USER_GH/**" "ssh://git@github.com/$USER_GH/**"; do
  key="includeIf.hasconfig:remote.*.url:$url.path"
  git config --global --unset-all "$key" 2>/dev/null || true
  git config --global "$key" "~/.gitconfig-personal"
done

echo "Personal identity: $NAME <$EMAIL> for every repo whose remote is github.com/$USER_GH."
echo "A brand-new repo with no remote yet gets it once you 'git remote add origin' - or set it with:"
echo "  git config user.email $EMAIL"
