---
name: qargi-project
description: Initialise a project for qargi by asking the preliminary questions once (repository, long-lived branches, roles, per-role base branch, push policy, the runtime for each surface, model and effort, packages, skills, budget, memory) and storing the answers outside the repository, then link a work tree to its skills, agents and memory. Provisioning and dispatch read them.
argument-hint: init|new|attach|adopt|show|list|validate|set|link|unlink NAME
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
     whether the repository's rulesets limit it to the pattern. Warn that the
     tool cannot enforce this server-side.

   Never offer merging, tagging or pushing long-lived branches; offer `coordinator`
   and `agent` only when the user wants them. A role that already pushes its own
   branch keeps doing so only as an explicit choice the user makes and you record,
   with its token file and vault ids.
5. **Runtime, per surface.** Nothing is assumed: ask which runtime does the project's
   `local` work (agents on this machine) and which its `cloud` work, from `qargi provider
   list` (shipped: `claude-code` local, `claude-platform` cloud; a family name such as `claude`
   works when exactly one of its runtimes serves the surface). Leave a surface unset if the
   project never uses it. Store them with `qargi project set NAME models.provider.local X` and
   `models.provider.cloud Y`, or `--provider-local X --provider-cloud Y` on `project new` and
   `attach` (`--provider X` for one name). A runtime that does not serve the surface is refused;
   a verb that needs an unset surface exits 2 and says which, and `project validate` prints a
   `finding:` for it. A runtime with no read-only barrier cannot serve the review role until the
   person accepts that (`qargi provider accept`). For a runtime that is not shipped, see
   `/qargi-providers`.
6. **Per role, model and effort** (the tiers come from the runtime's catalog), extra apt
   packages, and Anthropic skills (`pdf`, `docx`, `pptx`, `xlsx`; the write role defaults to `pdf`).
7. **Budget** per cloud session in cents (default 500, set on the deployment).
8. **Memory.** Create the project's stores or attach existing ones (ids).
9. **Members, once.** The local workers are agents the user names: ask for their names and abilities, suggesting the two
   base members (`worker`, `reviewer`; the rest are profiles). `qargi agent add` is in `/qargi-instances`.
10. **Profile.** Which profile file holds the repository's gates and review steps
    (kept under the config directory, per role if the gates differ).

To link a work tree (`project link`, in each checkout or worktree) or start from a repository (`project new`, `attach`, `adopt`),
read `repository.md`. Or write the answers file and store it:

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
has a budget). `/qargi-provision` reads these answers; flags override them.

Teams (optional): `lead` (model, effort; it cannot be a role) and `teams.<name>` define the teams `/qargi-team` runs (its definition section lists the fields). Set them with `qargi project set`.

Push grant for the lead (`lead.push`, default none): `local` (this session may push `agent/*` and open pull requests), `cloud: branches` (a cloud or console lead may, with a token file and a vault, set up by `qargi credential setup lead-push PROJECT`), `branch_pattern` (`agent/...`), `merge` and `release` (`ask` or `never`; never automatic). Only the lead ever pushes.
