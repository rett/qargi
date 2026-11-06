# Git-flow

A project that follows `gitflow` is driven by the lead with `qargi feature` and `qargi release`
(the `/qargi-flow` skill has the full process). Every merge is `--no-ff`, made in temporary
worktrees: your checkout is never touched, a branch moves only after every merge succeeded, and a
refusal changes nothing.

1. `qargi feature start NAME --purpose "..."` cuts `feature/NAME` from develop. A feature is a broad
   theme; `qargi feature list` shows the open ones and the files two of them both change.
2. Tasks run on `agent/<slug>` (`/qargi-task ... --base feature/NAME`) with targeted checks only.
   Per task: `qargi review check RUN/out` and `qargi review apply RUN` (puts the series on `agent/<slug>`; the author of each commit is reset to yours: the answer `git.author`, a string `Name <email>`, else the repository's `user.name` and `user.email`; `review.keep_author` `true` keeps the member's; the member's author is recorded in the ref journal and the audit log),
   `qargi feature merge NAME BRANCH`, `qargi local clean RUN`, then `qargi branch prune` to
   delete merged `agent/*` branches. Run `qargi local verify RUN` on every returned run before
   merging any of them; verify and clean accept and name qargi's own moves (`develop moved by qargi feature finish`, a fetch, the
   parking branch fast-forwarded to develop), so a run whose work is merged need not be cleaned before the next `feature finish`. A branch you make or push yourself
   while a run is out is accepted once you journal it with `qargi ref note BRANCH origin/BRANCH` (a ref that existed before the run still has to be explained), and the harness's own
   `worktree-bridge-*` branches are left out. `feature finish` is refused while a run of the feature is open (the message lists it and the way to close it); a run whose
   patches you applied by hand (`git am`) is closed with `qargi local close RUN --applied-by-am`. Keep `--scratch` on
   disk (prepare warns about a tmpfs, which a reboot empties); a passing verify also saves the run's output in `<state>/runs/`, and
   `qargi review apply --from-saved ID` applies it when the run directory is gone (`local list` shows such a run as directory gone). `qargi local list --scratch DIR` shows each run's role, slug, age and whether it is
   applied and merged; `qargi local clean --applied --scratch DIR` cleans those that are both and keeps the rest.
   `qargi local clean --stale DAYS --scratch DIR` lists the finished runs older than DAYS days, and `--yes` cleans them (a run whose work is not applied and merged is kept).
3. When the feature is complete: `qargi feature sync NAME` (merges develop in), `qargi feature verify
   NAME` (the one whole-suite run per feature), then `qargi feature finish NAME`, the only merge into
   develop. `qargi feature status NAME` shows commits ahead and whether the whole-suite run is
   current (when it is not, it says which merge or sync moved the head). `verify` warns when another suite may be running, and a
   failed one ends with the failing tests and the path of the log.
4. `qargi release start VERSION` cuts `release/VERSION` from develop (only from a head that passed the
   suite) and bumps `VERSION` and the changelog date. `qargi release push VERSION` opens the pull
   request into master so CI runs on the commit to be released; `qargi release finish VERSION`
   merges into master, tags, merges back into develop and pushes. `release status` and `release
   verify` work as for features. `release status` shows the checks of the pull request and, after the finish, what
   is left (tag on origin, GitHub release, assets, signatures); `release finish` lists the checks and refuses
   while one fails or is pending, unless `--ignore-checks "<your words>"`. To fix a failed check, `qargi release
   fix VERSION` makes a worktree on the release branch and `release fix VERSION --push` pushes the fix to the open
   pull request.
   Pushing the tag publishes the GitHub release through the workflow; for a tag that predates it,
   `qargi release publish TAG` creates the release from the changelog section (plan and token). The files to attach can be built
   from the tag without touching your checkout: `qargi release assets VERSION` runs the project's `release.assets_command` in a clean
   worktree of the tag, `release sign` signs there, and `release publish` attaches `release.assets` (globs), `--asset FILE` and
   `--asset-dir DIR` from it.
5. A hotfix is the same with `--hotfix`: `qargi release start VERSION --hotfix` (from master), then
   `release push` and `release finish --hotfix` (into the open release branch instead of develop,
   if there is one).

Merging into develop or master, pushing and tagging each print a plan and a token first; apply it
with `--plan TOKEN --approved "<your words>"`. A merge that conflicts changes nothing and exits 3,
naming a worktree with the merge in progress: resolve and commit there, then run the same command
with `--resolved`.

## Detached branches

A long-lived branch that must never meet the git-flow branches, such as a documentation site, is listed in the answers as
`repo.detached` (`qargi project set NAME repo.detached '["docs-site"]'`). qargi then refuses every merge between it and
develop, master, a release, a hotfix or a feature branch, in either direction (`feature merge`, `feature sync`, `feature finish`,
`release finish`), by name and by history: a branch cut from the detached branch cannot be merged into a feature, a branch cut from
develop cannot be merged into the detached branch. `feature start` and the other feature verbs refuse its name. Tasks are cut
from it as from any base (`local prepare --base docs-site`, `review apply`), and the finished `agent/<slug>` branch is merged
into it with `qargi feature merge docs-site agent/<slug>`: a plan and token, local only, nothing is pushed.

A documentation site kept on such a branch is regenerated when a release ships. With `site.enabled` set to `true` (and
`site.branch`, which defaults to `gh-pages` when `repo.detached` lists it, and `site.config`, default `site/site.json` with the
hand pages in `site/pages/`), `release finish` ends with `next: qargi release site VERSION`. That verb builds the site of the
tag with `lib/site.py` to check it and commits the release it built on the site branch (`site.json`; the build's `_site/` is not
committed, because a Pages build needs it empty), behind a plan and token; it never pushes and prints the push command. `release status VERSION` says whether the site of that version is built and pushed.

Two optional fields of `site.json` add a line to the footer of every page, the 404 page included. `copyright` is one line of plain text (at most 200
characters, no `<` or `>`, shown escaped), for example `"(c) 2026 Example Author. MIT licensed."`; the forbidden words of `site.json` apply to it.
`license_url` is an `https://` address (no query or fragment) that the words "MIT licensed" in `copyright` link to; without those words it is not
shown and `lib/site.py check` warns. With `copyright` unset the pages are unchanged. The fields of `site.json` are listed in the header of `lib/site.py`.

## Feature branches on origin

Two answers decide what the flow does with a feature branch on origin. `branches.push_features` is `never` (the default),
`when-shared` or `always`: `feature start`, `feature merge` and `feature sync` push the branch (a plain push, never forced) only
under `always`, or under `when-shared` when origin already has it. Setting it is the standing approval for those pushes; develop,
master and release branches keep their plans and tokens. `branches.delete_merged` is `local` (the default) or `local+remote`: with
`local+remote`, `feature finish` also deletes the branch on origin when origin has it and holds nothing the feature lacks; the plan
shows the deletion and its token covers origin's tip. `branches.push_develop` is `true` (the default) or `false`: `feature finish`
pushes develop to origin, when the repository has one, unless it is `false`. The first line of the finish plan says which ("will
push develop to origin", or "local only, will not push" and why), and the token covers it.

## Pruning merged branches

`qargi branch prune [--remote]` prints the merged `agent/*` and `feature/*` branches of the project (with `--remote`, the same
branches on origin, asked live) and the worktrees qargi made for them, with a token; apply it with `--plan TOKEN --approved
"<your words>"`. A branch is merged when it was merged with `--no-ff` into develop, or, for an agent branch, into an open
feature; a branch that only sits at the tip of develop or of a feature was never merged and is kept. It never deletes master,
develop, the branches of `repo.long_lived` or `repo.detached`, the parking branch, an unmerged branch, or a branch checked out in a
worktree qargi did not make (the main checkout, the runtime's own worktrees) or in a dirty one; each kept branch is listed with
the reason. A remote branch is deleted as a lease on the tip the plan showed.

## Following an upstream repository

A project that is a fork keeps its own changes, the overlay, on top of an upstream repository. The answers name the remote
(`upstream.remote`), the branch it follows (`upstream.branch`) and the local branch that carries the upstream line and nothing
else (`upstream.into`, default `upstream`; put it in `repo.long_lived`); `upstream.overlay_check`, optional, is a command array
that checks the overlay still applies or builds. `qargi upstream status` fetches that one branch of that remote and says how
far the branch is behind and ahead; `qargi upstream review [--limit N]` lists the upstream commits not yet in it with the files
each touches and marks the ones that touch a file develop changed since it parted from the upstream line; `qargi upstream sync`
fast-forwards the branch to the fetched tip from a plan and a token, refuses a branch with commits of its own, pushes nothing and
never merges into develop: the upstream line meets develop only through a feature (`qargi feature start upstream-X`, then
`qargi feature merge upstream-X upstream`), where the overlay is fixed and the feature lands as any other. With
`upstream.overlay_check` set, sync then runs it on a trial merge of the branch into develop in a temporary worktree.

## The worktree root

qargi makes the worktrees it creates under one root, `worktrees.root` in the answers (default `<state>/worktrees/PROJECT`), one
per branch at `ROOT/<branch>`. `qargi feature start NAME --worktree` creates `ROOT/feature/NAME` and prints the path. While a
clean worktree of a feature is under the root, `feature merge` and `feature sync` bring it up to date, and `feature finish`
detaches and removes it after the merge, when it deletes the branch; a dirty one stops each of them with its path. `feature list`
and `feature status` flag every other worktree of the project, with the `git worktree move` that fixes it. The main checkout, the
worktrees inside the main checkout (the agent runtime makes its own there, under `.claude/worktrees/` for Claude Code) and qargi's
temporary worktrees are not flagged.

## The parking branch

qargi moves develop and master without touching a working tree, so neither can be checked out in the project's main checkout
(`need_free` refuses and says so). The checkout rests on a parking branch instead: `repo.parking_branch` in the answers, `scratch` by
default. `git -C DIR switch -c scratch develop` makes it; `qargi feature park` refreshes it later: `checkout -B scratch develop` in the
main checkout, refused when the tree is dirty or when `scratch` has commits develop lacks (it lists them: re-implement them with an
agent task based on develop). After `feature finish`, `release finish` and `release finish --hotfix` moved develop, a clean main
checkout on the parking branch with no commits of its own is fast-forwarded to develop; otherwise one line says why not. The parking
branch is never pushed or merged.
