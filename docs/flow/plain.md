# The plain methodology

`plain` is the methodology for a project whose output is documents: a note, a report, a handbook, a set of pages. Nothing is released, so there are no
release branches, no tags, no version file and no changelog. It keeps what qargi does for every project (a task is a run in its own clone, its result
comes back as patches, the lead checks them, applies them on a branch of its own and merges them) and drops the git-flow shape around it.

| | `gitflow` | `plain` |
|---|---|---|
| long-lived branches | `master`, `develop` | `main` |
| work branches | `feature/NAME`, `agent/SLUG`, `release/VERSION`, `hotfix/VERSION` | `agent/SLUG` |
| tags, `VERSION`, `CHANGELOG.md`, CI workflow | yes | none |
| `qargi feature`, `release` (hotfixes too), `branch prune`, `upstream`, `changelog renumber` | the flow | refused (`methodology-no-flow`) |
| `qargi local`, `review`, `backlog` | yes | yes, with `--base main` |

## Start a project

```sh
qargi project new notes --methodology plain --url https://github.com/me/notes
qargi project new notes --methodology plain --url https://github.com/me/notes --plan TOKEN --approved "..."
```

The plan lists the branch `main` and five files: `README.md`, `CONTRIBUTING.md`, `AGENTS.md` (with its Development environment section),
`artifacts/.gitkeep` and `BACKLOG.md`. The documents go under `artifacts/`. With `--url` the answers are stored too: the methodology `plain`,
`main` as the only long-lived branch and `BACKLOG.md` as the backlog file. `--json` prints the plan and its token as one object, and that token
approves the same plan. `qargi project template NAME --methodology plain` prints answers with `main` in place of `master` and `develop`.

`qargi project validate` refuses a `methodology` answer that `qargi methodology check` does not pass, and says why.

## Work on a document

A task is a run cut from `main`. The check that says it is done is set with the task and is mechanical: the file exists, its format parses, its
length and headings are right, its links resolve. The `--scope` is a hard limit: a series that changes a path outside it fails `review check` and is
not applied.

```sh
qargi local prepare --repo DIR --base main --slug first-note --scratch DIR2 \
  --task-file task.txt --done 'test -s artifacts/a.md' --scope artifacts/
qargi local verify RUN
qargi review check RUN/out
qargi review apply RUN            # agent/first-note, cut at main
```

A read-only review run on the applied branch (`qargi local prepare --role review --base agent/first-note`) returns a report with findings and a
verdict, and `qargi review check` reads it as it reads any review. The lead merges the reviewed branch into `main` with `--no-ff` and then
`qargi local clean RUN`: after a passing verify, `local verify` and `local clean` accept a fast-forward or a merge of `main`, the one long-lived
branch of a plain project, as they accept one of `develop` and `master` in a git-flow project, and nothing else that the ref journal does not name.

## The methodology file

A methodology says `"flow": "plain"` in its `methodology.json` (without `flow` it is `gitflow`). `qargi methodology check` then requires exactly one
long-lived branch and a `task` pattern with `{slug}`, and refuses `branches.feature`, `release`, `hotfix` and `tag`, `after_release`, `release`
and `versioning`, each with its reason. The shipped `plain` is under `methodologies/plain/`; yours can live beside it under
`~/.qargi/config/methodologies/NAME/`.
