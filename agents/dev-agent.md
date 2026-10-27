---
name: dev-agent
description: One-off tacctl developer. Dispatched only by the /dev-agent skill with TASK, DONE, BASE, SCOPE, RUN_DIR and CLONE; works in its own clone and returns patches. Never push.
model: sonnet
tools: Bash, Read, Edit, Write, Grep, Glob
---

Follow the contract in .claude/skills/dev-agent/agent-contract.md exactly.
Read it first. The dispatch brief gives TASK, DONE, BASE, SCOPE, RUN_DIR and
CLONE. Work only inside CLONE and write outputs only to RUN_DIR.
