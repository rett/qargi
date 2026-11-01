---
name: qargi-project
description: Initialise a project for qargi by asking the preliminary questions once (repository, long-lived branches, roles, per-role base branch, push policy, model and effort, packages, skills, budget, memory) and storing the answers outside the repository. Provisioning and dispatch read them.
argument-hint: init|new|attach|adopt|show|list|validate NAME
---

# /qargi-project

Run this before the first `/qargi-provision` for a project. The answers live in
`~/.qargi/config/projects/<project>.json` (never in a repository) and
drive provisioning, the agent contracts and dispatch defaults.

## Ask first, then store

Ask the user these, in batches (AskUserQuestion), with the stated defaults
recommended; do not assume answers:

1. **Repository.** URL; local checkout path (optional); the long-lived branches
   no agent may ever touch (default `master`, `develop`). **Private repository?** If
   checking it out needs a credential, ask for a token file: a fine-grained, read-only
   token (contents: read), in a file only the user can read (chmod 600), outside every
   repository. Record its path as `repo.credential_file`, then run
   `qargi credential check NAME`: it proves the token can read and warns if it can
   also push. Public repositories need none. The token is never typed into a command, a
   log, the tracker or a repository.
2. **Roles.** Which of the abilities `build`, `write`, `review`, `test` this project uses.
3. **Per role, base branch.** `@dispatcher` (the dispatching session's branch)
   for build; the documentation branch (for example `gh-pages`) for write.
4. **Per role, push policy** (the question that matters most):
   - `none` (the default for every role, always recommended): the agent returns
     patches; nothing is pushed unless the user asks.
   - `coordinator`: the agent returns patches; after review the coordinator
     pushes one branch matching a pattern such as `agent/<slug>`, with the
     user's go-ahead each time. Ask for the pattern.
   - `agent`: the agent itself may push branches matching the pattern with a
     credential. Only if the user insists; ask which credential (a vault id) and
     whether the repository's rulesets limit that credential to the pattern.
     Warn that the tool cannot enforce this server-side.
   Never offer merging, tagging or pushing long-lived branches. `coordinator` and
   `agent` are offered only when the user wants them. If a role already behaves
   that way (an agent that pushes its own branch), keeping it is an explicit
   choice the user makes and you record, with its token file and vault ids; it is
   never assumed.
5. **Per role, model and effort**, extra apt packages, and Anthropic skills
   (`pdf`, `docx`, `pptx`, `xlsx`; the write role defaults to `pdf`).
6. **Budget** per cloud session in cents (default 500, set on the deployment).
7. **Memory.** Create the project's stores or attach existing ones (ids).
8. **Members, once.** The local workers are agents the user names. Ask for their
   names and abilities, suggesting the two base members (`worker` for build, write and
   test; `reviewer` for review); specializations such as the auditor are profiles, not
   members (`qargi agent models`). Create each with `qargi agent add NAME --abilities LIST` (`--project NAME` puts it in this
   repository's `.claude/agents`, hidden from git); skip names that `qargi agent list`
   already shows.
9. **Profile.** Which profile file holds the repository's gates and review steps
   (kept under the config directory, per role if the gates differ).

A project can also start from a repository instead of an answers file: `qargi project new NAME` creates a new one on the
methodology's branches, `qargi project attach [DIR]` reads an existing one (it shows the answers and the gaps and changes nothing in
the repository), and `qargi project adopt NAME` then creates the missing long-lived branches and methodology files on a branch to
review. See `qargi help project`.

Or write the answers file and store it:

```sh
qargi project template NAME > answers.json   # edit with the answers
qargi project validate answers.json
qargi project init NAME --answers answers.json
```

`validate` explains every problem (a push pattern that matches a long-lived
branch, a push by the agent without a credential, an unknown role or skill).
`qargi project show NAME` prints what was stored. Change one answer at any
time with `qargi project set NAME PATH VALUE` (for example `budget_cents 2500`
or `roles.write.effort high`); it is validated first and applies to the next
provision. A live deployment's ceiling changes with `qargi instances budget
NAME CENTS --asked "..."` (add `--session SID` for a running session that already
has a budget). `/qargi-provision` reads these answers for model, effort, packages,
skills, budget and stores; flags override them.

Teams (optional): `lead` (model, effort) and `teams.<name>` (`members`, `max_rounds`, `budget_cents`, `standards`, `scopes`, `done`) define the teams `/qargi-team` runs; `lead` cannot be a role. Set them with `qargi project set`.

Push grant for the lead (`lead.push`, default none): `local` (this session may push `agent/*` and open pull requests), `cloud: branches` (a cloud or console lead may, with a token file and a vault, set up by `qargi credential setup lead-push PROJECT`), `branch_pattern` (`agent/...`), `merge` and `release` (`ask` or `never`; never automatic). Only the lead ever pushes.
