---
name: dev-project
description: Initialise a project for dev-agent by asking the preliminary questions once (repository, long-lived branches, roles, per-role base branch, push policy, model and effort, packages, skills, budget, memory) and storing the answers outside the repository. Provisioning and dispatch read them.
argument-hint: init|show|list|validate NAME
---

# /dev-project

Run this before the first `/dev-provision` for a project. The answers live in
`$XDG_CONFIG_HOME/dev-agent/projects/<project>.json` (never in a repository) and
drive provisioning, the agent contracts and dispatch defaults.

## Ask first, then store

Ask the user these, in batches (AskUserQuestion), with the stated defaults
recommended; do not assume answers:

1. **Repository.** URL; local checkout path (optional); the long-lived branches
   no agent may ever touch (default `master`, `develop`).
2. **Roles.** Which of `dev`, `review`, `docs`, `test` this project uses.
3. **Per role, base branch.** `@dispatcher` (the dispatching session's branch)
   for dev; the docs branch (for example `gh-pages`) for docs.
4. **Per role, push policy** (the question that matters most):
   - `none` (the default for every role, always recommended): the agent returns
     patches; nothing is pushed unless the user asks.
   - `coordinator`: the agent returns patches; after review the coordinator
     pushes one branch matching a pattern such as `docs/<slug>`, with the
     user's go-ahead each time. Ask for the pattern.
   - `agent`: the agent itself may push branches matching the pattern with a
     credential. Only if the user insists; ask which credential (a vault id) and
     whether the repository's rulesets limit that credential to the pattern.
     Warn that the tool cannot enforce this server-side.
   Never offer merging, tagging or pushing long-lived branches. `coordinator` and
   `agent` are offered only when the user wants them. If a role already behaves
   that way (a docs agent that pushes `docs/<slug>`), keeping it is an explicit
   choice the user makes and you record, with its token file and vault ids; it is
   never assumed.
5. **Per role, model and effort**, extra apt packages, and Anthropic skills
   (`pdf`, `docx`, `pptx`, `xlsx`; the docs role defaults to `pdf`).
6. **Budget** per cloud session in cents (default 500, set on the deployment).
7. **Memory.** Create the project's stores or attach existing ones (ids).
8. **Profile.** Which profile file holds the repository's gates and review steps
   (kept under the config directory, per role if the gates differ).

Then write the answers file and store it:

```sh
dev-agent project template NAME > answers.json   # edit with the answers
dev-agent project validate answers.json
dev-agent project init NAME --answers answers.json
```

`validate` explains every problem (a push pattern that matches a long-lived
branch, a push by the agent without a credential, an unknown role or skill).
`dev-agent project show NAME` prints what was stored; change an answer by
editing and re-running `init --force`.
