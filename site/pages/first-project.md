---
title: Your first project
description: Store a project's answers once, choose the runtime, name your first members and check that qargi can dispatch to them, using a project called myproject.
doctype: tutorial
---
This page sets up a project called `myproject`, adds two members and checks that qargi can dispatch to them. Every name is an example; use your own. You need qargi [installed](/install/).

The answers you give are stored under `~/.qargi`, outside the repository. Nothing qargi related is added to the project's committed files.

## 1. Pick the starting point

You either have a repository already or you want a new one.

For an existing repository, run this from inside it. It reads the repository and changes nothing; it prints the answers it would store, the gaps against the git-flow model and a plan token.

```bash
cd ~/src/myproject
qargi project attach --name myproject --provider-local claude-code
```

For a new project, `project new` prints a plan for the directory, the branches and the generic files:

```bash
qargi project new myproject --param test_command='make test' --provider-local claude-code
```

`qargi provider list` shows the runtimes you can name. The project names one for the local surface and, if you use cloud agents, one for the cloud surface. qargi never guesses either.

## 2. Apply the plan

Read the plan. If it is what you want, run the same command again with the token it printed and your go-ahead in your own words. The words are written to the audit log.

```bash
qargi project attach --name myproject --provider-local claude-code --plan TOKEN --approved "store the answers for myproject"
```

If the plan changes between the two runs, the token no longer matches and nothing happens. `qargi help approvals` has the rules.

## 3. Close the gaps

An attached repository may lack the long-lived branches or the methodology files. `qargi project adopt` creates the missing branches locally and puts the missing files on a branch for you to review. It is a plan and a token as well, and it never pushes.

```bash
qargi project adopt myproject
```

## 4. Look at what was stored

```bash
qargi project show myproject
qargi project list
```

The answers hold the repository, its branches, the roles and each role's base branch, model and effort, the memory stores and the push policy. To change one, use `qargi project set myproject PATH VALUE`, for example `roles.write.effort high`.

## 5. Add members

A member is a local agent you name. It serves one or more roles: build changes code, write writes documentation, review reads a change and changes no file, test writes and runs tests. Names are yours.

```bash
qargi agent add forge --roles build,test --project myproject
qargi agent add scribe --roles write --project myproject
qargi agent add reader --roles review --project myproject
qargi agent list --project myproject
```

`agent add` refuses when the project has no local runtime, and it prints where it wrote the definition. In a Claude Code session a new member is available once you start a new session.

## 6. Check dispatch

`agent for` prints what dispatch would use for a role: the member, the model alias and the effort.

```bash
qargi agent for build --project myproject
qargi agent for review --project myproject
```

If no member serves a role, add one. If `agent list` shows `STALE` or `DRIFT`, the definition changed since the member was written or was edited by hand; `qargi agent refresh NAME` writes it again.

## 7. Run a first task

Start with a task that is small and has a check you can run: rename a function, add a test. The loop is in [the lead's loop](/lead-loop/) and one task in detail is in [dispatch and verify](/dispatch-and-verify/). In short:

1. `qargi feature start first-task --purpose "learn the loop"` cuts a feature branch from develop.
2. Prepare a run on that base, give the task and its check to the member `agent for` printed.
3. When it reports, `qargi local verify RUN`, `qargi review check RUN/out`, `qargi review apply RUN`, run the check yourself, then merge.

## 8. See also

- [Install and update](/install/)
- [The lead's loop](/lead-loop/)
- [Dispatch and verify](/dispatch-and-verify/)
- [Safety](/safety/)
- [project](/reference/set-up/#project) and [agent](/reference/set-up/#agent) in the reference
