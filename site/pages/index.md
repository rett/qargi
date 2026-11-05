---
title: qargi documentation
description: How to run a project with qargi: install it, set one up, hand tasks to agents, check the patches they return and merge them. Every command is verified.
doctype: reference
---
qargi hands one-off development tasks to agents and takes the work back as patches you review. An agent works on one task in its own clone and never pushes. You, the lead, check what comes back, apply it and decide what is merged.

This site is the operational layer: what to type, in what order, and what is refused. The overview is in the [repository README](https://github.com/rett/qargi#readme) and the complete manual is `man qargi`.

## 1. Who it is for

You lead a software project and want agents to do bounded pieces of it. You keep control of the repository: nothing is merged, pushed or released without you. qargi gives you a way to describe a task, run it in isolation, and check the result before it touches a branch.

It also fits a member reading what is expected of it. The rules for a member are on [safety](/safety/).

## 2. The three-minute picture

1. You describe one task and an executable check that decides when it is done.
2. A member, an agent you named, works on it in its own clone of the repository. The clone has no remote and git runs through a wrapper without credentials.
3. The member returns numbered patches, one per commit, with a manifest and a report.
4. You verify the run, check the series, apply it to a branch and run the check yourself.
5. You merge it into a feature branch. When the feature is complete you run the whole test suite once and finish the feature into develop.

Local is the default: a member runs on your machine. A cloud agent is used only when your request for that task names it.

## 3. Where to start

- Not installed yet: [install and update](/install/).
- Installed, no project yet: [your first project](/first-project/).
- Working day to day: [the lead's loop](/lead-loop/), then [dispatch and verify](/dispatch-and-verify/) for the detail of one task.
- Wondering what an agent or a skill may do: [safety](/safety/).
- Looking for a command or an option: the [command reference](/reference/), for example [project init](/reference/set-up/#project-init). It is generated from the release it names.
- What changed in a version: the [releases](/releases/).

## 4. The commands you will use most

```bash
qargi project show
qargi agent for build
qargi local prepare --repo . --base develop --slug rename-verb --scratch ~/qargi-runs
qargi local verify RUN
qargi review check RUN/out
qargi review apply RUN
qargi feature merge NAME agent/rename-verb
```

Each line is explained where it is used. `qargi help` lists every command and `qargi help TOPIC` prints a topic such as `concepts`, `approvals` or `guard`.

## 5. See also

- [Install and update](/install/)
- [Your first project](/first-project/)
- [The lead's loop](/lead-loop/)
- [Dispatch and verify](/dispatch-and-verify/)
- [Safety](/safety/)
- [About these docs](/about/)
