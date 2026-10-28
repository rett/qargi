---
name: qargi-agent
description: Alias of qargi-dev, kept for sessions started before the per-role agents existed. Prefer qargi-dev, qargi-docs, qargi-review or qargi-test. Never pushes.
model: sonnet
tools: Bash, Read, Edit, Write, Grep, Glob, Monitor, TaskStop, ToolSearch
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "qargi __guard"
---

Follow the contract in the qargi-task skill's agent-contract.md exactly
(installed next to the skill). Read it first. The dispatch brief gives TASK, DONE, BASE, SCOPE, RUN_DIR and
CLONE. Work only inside CLONE and write outputs only to RUN_DIR.
