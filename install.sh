#!/usr/bin/env bash
# Install dev-agent into a project: symlink the skill and the local subagent
# definition under the project's .claude directory.
# Usage: install.sh /path/to/project
set -eu
proj=${1:?usage: install.sh /path/to/project}
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$proj/.claude/skills" "$proj/.claude/agents"
ln -sfn "$here/skill" "$proj/.claude/skills/dev-agent"
ln -sfn "$here/agents/dev-agent.md" "$proj/.claude/agents/dev-agent.md"
echo "installed into $proj/.claude (skill and agent are symlinks to $here)"
