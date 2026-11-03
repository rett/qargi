---
name: docs-site-member
description: Writing to a documentation branch that shares no history with the main branches: base your work on that branch and never merge it.
---
# A site branch

A site branch holds a documentation site and shares no history with the main branches.

- Work in a clone of the site branch, not of `develop`.
- Base your `agent/<slug>` branch on the site branch named in your task.
- Never merge the site branch into a long-lived branch, or a long-lived branch into it.
- Never cherry-pick code history into it.
- Your patches apply onto the site branch only; say so in the report, with its sha.
